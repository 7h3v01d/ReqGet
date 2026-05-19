# tests/test_reqget.py

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reqget import resolver, scanner
from reqget.config import Config, init_config, load_config, merge_with_args
from reqget.freezecheck import compare, format_report, FreezeReport
from reqget.lockfile import verify_lockfile, write_lockfile

MOCK_FILE_CONTENT = """\
import os
import requests
from bs4 import BeautifulSoup
from aiohttp import ClientSession
import typing
import my_local_module
"""

MOCK_INSTALLED = {
    "requests":          "2.31.0",
    "beautifulsoup4":    "4.12.2",
    "aiohttp":           "3.9.1",
    "typing-extensions": "4.14.0",
    "lxml":              "5.1.0",
}


# ── scanner ───────────────────────────────────────────────────────────────────

class TestScanner(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.py_file = self.tmp / "main.py"
        self.py_file.write_text(MOCK_FILE_CONTENT)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_extract_imports_finds_third_party(self):
        imports = scanner.extract_imports(self.py_file)
        self.assertIn("requests", imports)
        self.assertIn("bs4", imports)
        self.assertIn("aiohttp", imports)

    def test_extract_imports_bad_syntax(self):
        bad = self.tmp / "bad.py"
        bad.write_text("def foo(:\n    pass\n")
        result = scanner.extract_imports(bad)
        self.assertIsInstance(result, set)

    def test_scan_filters_stdlib_and_local(self):
        (self.tmp / "my_local_module.py").touch()
        result = scanner.scan_directory_for_imports(self.tmp, {"os", "typing"})
        self.assertIn("requests", result)
        self.assertIn("bs4", result)
        self.assertNotIn("os", result)
        self.assertNotIn("my_local_module", result)
        self.assertIsInstance(result["requests"], set)

    def test_scan_skips_venv(self):
        venv = self.tmp / "venv"; venv.mkdir()
        (venv / "evil.py").write_text("import evil_package\n")
        result = scanner.scan_directory_for_imports(self.tmp, set())
        self.assertNotIn("evil_package", result)


# ── resolver ──────────────────────────────────────────────────────────────────

class TestResolver(unittest.TestCase):
    @patch("reqget.resolver.importlib.metadata.distributions")
    def test_get_installed_packages(self, mock_dists):
        d1 = MagicMock(); d1.metadata = {"Name": "requests"};       d1.version = "2.31.0"
        d2 = MagicMock(); d2.metadata = {"Name": "beautifulsoup4"}; d2.version = "4.12.2"
        mock_dists.return_value = [d1, d2]
        pkgs = resolver.get_installed_packages()
        self.assertEqual(pkgs["requests"], "2.31.0")

    def test_resolve_package_known_mapping(self):
        self.assertEqual(resolver.resolve_package("bs4",    MOCK_INSTALLED), "beautifulsoup4")
        self.assertEqual(resolver.resolve_package("PIL",    MOCK_INSTALLED), "Pillow")
        self.assertEqual(resolver.resolve_package("yaml",   MOCK_INSTALLED), "PyYAML")
        self.assertEqual(resolver.resolve_package("cv2",    MOCK_INSTALLED), "opencv-python")
        self.assertEqual(resolver.resolve_package("sklearn",MOCK_INSTALLED), "scikit-learn")

    def test_resolve_package_fallback(self):
        # Fallback normalises underscores to hyphens (PEP 503 canonical form)
        self.assertEqual(resolver.resolve_package("unknown_pkg", {}), "unknown-pkg")

    def test_get_dependencies_returns_tuple(self):
        direct, trans = resolver.get_dependencies_from_packages(
            {"requests", "beautifulsoup4"}, MOCK_INSTALLED, fetch_transitive=False
        )
        self.assertIn("requests==2.31.0", direct)
        self.assertIn("beautifulsoup4==4.12.2", direct)
        self.assertEqual(trans, {})

    def test_check_conflicts_detects(self):
        triggered = resolver.check_conflicts(
            {"requests==2.31.0", "urllib3==1.26.10"},
            {"conflict_table": [{"packages": ["requests", "urllib3"],
                                  "symptoms": ["RuntimeError"],
                                  "resolution": {"suggest": "Upgrade urllib3"}}]},
        )
        self.assertEqual(len(triggered), 1)

    def test_check_conflicts_no_false_positive(self):
        triggered = resolver.check_conflicts(
            {"flask==3.0.0"},
            {"conflict_table": [{"packages": ["requests", "urllib3"],
                                  "symptoms": [], "resolution": {"suggest": ""}}]},
        )
        self.assertEqual(triggered, [])


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults(self):
        cfg = load_config()
        self.assertEqual(cfg.output, "requirements.txt")
        self.assertFalse(cfg.no_transitive)
        self.assertFalse(cfg.lock)

    def test_load_from_file(self):
        rc = self.tmp / ".reqgetrc"
        rc.write_text(json.dumps({"no_transitive": True, "output": "deps.txt"}))
        cfg = load_config(explicit_path=rc)
        self.assertTrue(cfg.no_transitive)
        self.assertEqual(cfg.output, "deps.txt")

    def test_unknown_keys_ignored(self):
        rc = self.tmp / ".reqgetrc"
        rc.write_text(json.dumps({"totally_fake_key": 42, "no_comments": True}))
        cfg = load_config(explicit_path=rc)  # should not raise
        self.assertTrue(cfg.no_comments)

    def test_invalid_json_uses_defaults(self):
        rc = self.tmp / ".reqgetrc"
        rc.write_text("{ this is not json }")
        cfg = load_config(explicit_path=rc)
        self.assertEqual(cfg.output, "requirements.txt")

    def test_init_config_creates_file(self):
        path = init_config(self.tmp)
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertIn("output", data)

    def test_init_config_raises_if_exists(self):
        init_config(self.tmp)
        with self.assertRaises(FileExistsError):
            init_config(self.tmp)

    def test_init_config_force(self):
        init_config(self.tmp)
        path = init_config(self.tmp, force=True)  # should not raise
        self.assertTrue(path.exists())

    def test_merge_with_args_overrides(self):
        cfg = Config(no_transitive=False, output="requirements.txt")
        args = MagicMock()
        args.no_transitive = True
        args.no_comments   = False
        args.lock          = False
        args.freeze_check  = False
        args.ignore_extra  = False
        args.output        = "custom.txt"
        args.lock_output   = None
        cfg = merge_with_args(cfg, args)
        self.assertTrue(cfg.no_transitive)
        self.assertEqual(cfg.output, "custom.txt")

    def test_project_dir_discovery(self):
        rc = self.tmp / ".reqgetrc"
        rc.write_text(json.dumps({"no_comments": True}))
        cfg = load_config(project_dir=self.tmp)
        self.assertTrue(cfg.no_comments)


# ── freezecheck ───────────────────────────────────────────────────────────────

class TestFreezeCheck(unittest.TestCase):
    FREEZE = {
        "requests":       "2.31.0",
        "certifi":        "2024.2.2",
        "extra-tool":     "1.0.0",
    }

    def test_missing(self):
        report = compare({"requests==2.31.0", "flask==3.0.0"}, self.FREEZE)
        names = [m[0] for m in report.missing]
        self.assertIn("flask", names)
        self.assertNotIn("requests", names)

    def test_ok(self):
        report = compare({"requests==2.31.0"}, self.FREEZE)
        names = [o[0] for o in report.ok]
        self.assertIn("requests", names)

    def test_version_mismatch(self):
        report = compare({"requests==2.28.0"}, self.FREEZE)
        names = [v[0] for v in report.version_mismatch]
        self.assertIn("requests", names)

    def test_extra(self):
        report = compare({"requests==2.31.0"}, self.FREEZE, ignore_extra=False)
        extra_names = [e[0] for e in report.extra]
        self.assertIn("extra-tool", extra_names)

    def test_ignore_extra(self):
        report = compare({"requests==2.31.0"}, self.FREEZE, ignore_extra=True)
        self.assertEqual(report.extra, [])

    def test_has_issues_false_when_clean(self):
        report = compare({"requests==2.31.0"}, {"requests": "2.31.0"})
        self.assertFalse(report.has_issues)

    def test_format_report_no_crash(self):
        report = FreezeReport(
            missing=[("flask", "3.0.0")],
            version_mismatch=[("requests", "2.28.0", "2.31.0")],
        )
        out = format_report(report, color=False)
        self.assertIn("flask", out)
        self.assertIn("requests", out)


# ── lockfile ──────────────────────────────────────────────────────────────────

class TestLockfile(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_write_and_verify(self):
        pinned  = {"requests": "2.31.0", "certifi": "2024.2.2"}
        sources = {"requests": ["direct"], "certifi": ["transitive via requests"]}
        out = self.tmp / "requirements.lock"
        ok = write_lockfile(pinned, sources, out, direct_names={"requests"})
        self.assertTrue(ok)
        self.assertTrue(out.exists())
        content = out.read_text()
        self.assertIn("requests==2.31.0", content)
        self.assertIn("certifi==2024.2.2", content)
        valid, msg = verify_lockfile(out)
        self.assertTrue(valid, msg)

    def test_tampered_lockfile_fails_verify(self):
        pinned  = {"requests": "2.31.0"}
        sources = {"requests": ["direct"]}
        out = self.tmp / "requirements.lock"
        write_lockfile(pinned, sources, out)
        # tamper
        out.write_text(out.read_text().replace("2.31.0", "9.99.9"))
        valid, _ = verify_lockfile(out)
        self.assertFalse(valid)

    def test_write_lockfile_header_fields(self):
        out = self.tmp / "requirements.lock"
        write_lockfile({"flask": "3.0.0"}, {"flask": ["direct"]}, out)
        text = out.read_text()
        self.assertIn("reqget lockfile", text)
        self.assertIn("python:", text)
        self.assertIn("hash: sha256:", text)

    def test_missing_hash_fails_verify(self):
        out = self.tmp / "bad.lock"
        out.write_text("flask==3.0.0\n")
        valid, msg = verify_lockfile(out)
        self.assertFalse(valid)
        self.assertIn("No hash", msg)


if __name__ == "__main__":
    unittest.main()


# ── resolver bug fixes ────────────────────────────────────────────────────────

class TestResolverFixes(unittest.TestCase):

    def test_stdlib_not_in_module_to_package(self):
        """__future__ and dataclasses must never resolve to a PyPI package."""
        from reqget.resolver import resolve_package, MODULE_TO_PACKAGE
        self.assertNotIn("__future__", MODULE_TO_PACKAGE)
        self.assertNotIn("dataclasses", MODULE_TO_PACKAGE)

    def test_underscore_modules_resolve_to_hyphen(self):
        from reqget.resolver import resolve_package
        self.assertEqual(resolve_package("faster_whisper",    {}), "faster-whisper")
        self.assertEqual(resolve_package("kokoro_onnx",       {}), "kokoro-onnx")
        self.assertEqual(resolve_package("duckduckgo_search", {}), "duckduckgo-search")

    def test_canonical_normalises_underscores(self):
        from reqget.resolver import _canonical
        self.assertEqual(_canonical("typing_extensions"), "typing-extensions")
        self.assertEqual(_canonical("python_dotenv"),     "python-dotenv")
        self.assertEqual(_canonical("some__weird___pkg"), "some-weird-pkg")

    def test_dedup_removes_extras_only(self):
        from reqget.resolver import _dedup_requirements
        reqs = {
            'brotli; platform_python_implementation == "CPython" and extra == "brotli"',
            'pywin32; (os_name == "nt") and extra == "dev"',
            'requests>=2.28.0',
        }
        result = _dedup_requirements(reqs)
        names = {r.split(">=")[0].split("==")[0].strip().lower() for r in result}
        self.assertIn("requests", names)
        self.assertNotIn("brotli", names)
        self.assertNotIn("pywin32", names)

    def test_dedup_keeps_highest_lower_bound(self):
        from reqget.resolver import _dedup_requirements
        reqs = {
            "click>=7.0",
            "click>=8.1.7",
            "click>=8.1.8",
        }
        result = _dedup_requirements(reqs)
        self.assertEqual(len(result), 1)
        self.assertIn("click>=8.1.8", result)

    def test_dedup_pins_win_over_bounds(self):
        from reqget.resolver import _dedup_requirements
        reqs = {"requests>=2.28.0", "requests==2.31.0"}
        result = _dedup_requirements(reqs)
        self.assertEqual(len(result), 1)
        self.assertIn("requests==2.31.0", result)

    def test_dedup_drops_conditional_markers(self):
        from reqget.resolver import _dedup_requirements
        reqs = {
            'colorama>=0.4; sys_platform == "win32"',
            'uvloop>=0.15.1; sys_platform != "win32"',
        }
        result = _dedup_requirements(reqs)
        # Both have platform markers — should be dropped from universal output
        self.assertEqual(len(result), 0)

    def test_dedup_normalises_typing_extensions(self):
        from reqget.resolver import _dedup_requirements
        reqs = {
            "typing_extensions>=4.0",
            "typing-extensions>=4.8.0",
            "typing-extensions>=4.14.1",
        }
        result = _dedup_requirements(reqs)
        self.assertEqual(len(result), 1)
        r = list(result)[0]
        self.assertIn("4.14.1", r)

    def test_is_extras_only(self):
        from reqget.resolver import _is_extras_only
        self.assertTrue(_is_extras_only('brotli; extra == "brotli"'))
        self.assertTrue(_is_extras_only('pywin32; (os_name == "nt") and extra == "dev"'))
        self.assertFalse(_is_extras_only('requests>=2.28.0'))
        self.assertFalse(_is_extras_only('colorama; sys_platform == "win32"'))


# ── blacklist completeness ─────────────────────────────────────────────────────

class TestBlacklist(unittest.TestCase):
    def _load(self, ver: str) -> set:
        import json
        from pathlib import Path
        data = json.loads((Path(__file__).parent.parent / "src/reqget/blacklist.json").read_text())
        return set(data.get(ver, {}).get("non_pip_modules", []))

    def test_future_blacklisted_all_versions(self):
        for ver in ("3.8", "3.9", "3.10", "3.11", "3.12"):
            with self.subTest(ver=ver):
                self.assertIn("__future__", self._load(ver))

    def test_dataclasses_blacklisted_311(self):
        self.assertIn("dataclasses", self._load("3.11"))

    def test_main_blacklisted_all_versions(self):
        for ver in ("3.8", "3.9", "3.10", "3.11", "3.12"):
            with self.subTest(ver=ver):
                self.assertIn("__main__", self._load(ver))


# ── lockfile encoding fix ─────────────────────────────────────────────────────

class TestLockfileEncoding(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_header_uses_plain_hyphen_not_emdash(self):
        out = self.tmp / "requirements.lock"
        write_lockfile({"requests": "2.31.0"}, {"requests": ["direct"]}, out)
        raw = out.read_bytes()
        self.assertNotIn(b'\x97', raw,   "em-dash (cp1252 0x97) found in lockfile")
        self.assertNotIn(b'\xe2\x80\x94', raw, "UTF-8 em-dash found in lockfile")

    def test_written_as_utf8(self):
        out = self.tmp / "requirements.lock"
        write_lockfile({"requests": "2.31.0"}, {"requests": ["direct"]}, out)
        # Should be readable as strict UTF-8
        text = out.read_text(encoding="utf-8")
        self.assertIn("reqget lockfile", text)

    def test_verify_works_on_fresh_lockfile(self):
        out = self.tmp / "requirements.lock"
        write_lockfile({"flask": "3.0.0"}, {"flask": ["direct"]}, out)
        ok, msg = verify_lockfile(out)
        self.assertTrue(ok, msg)
