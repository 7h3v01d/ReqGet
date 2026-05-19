# resolver.py

from __future__ import annotations

import importlib.metadata
import json
import logging
import re
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

# ── Module-name → PyPI package-name mapping ──────────────────────────────────
MODULE_TO_PACKAGE: Dict[str, str] = {
    # web / scraping
    "bs4":              "beautifulsoup4",
    "cv2":              "opencv-python",
    "PIL":              "Pillow",
    "yaml":             "PyYAML",
    "dotenv":           "python-dotenv",
    "dateutil":         "python-dateutil",
    "Crypto":           "pycryptodome",
    "serial":           "pyserial",
    "usb":              "pyusb",
    "wx":               "wxPython",
    "gi":               "PyGObject",
    "gi.repository":    "PyGObject",
    "pkg_resources":    "setuptools",
    "attr":             "attrs",
    "jwt":              "PyJWT",
    "magic":            "python-magic",
    "fitz":             "PyMuPDF",
    "docx":             "python-docx",
    "pptx":             "python-pptx",
    "xlrd":             "xlrd",
    "xlwt":             "xlwt",
    "openpyxl":         "openpyxl",
    "MySQLdb":          "mysqlclient",
    "psycopg2":         "psycopg2-binary",
    "pymongo":          "pymongo",
    "redis":            "redis",
    "celery":           "celery",
    "boto3":            "boto3",
    "botocore":         "botocore",
    "tensorflow":       "tensorflow",
    "torch":            "torch",
    "transformers":     "transformers",
    "huggingface_hub":  "huggingface-hub",
    "anthropic":        "anthropic",
    "openai":           "openai",
    "sklearn":          "scikit-learn",
    # audio / ML common packages
    "faster_whisper":   "faster-whisper",
    "kokoro_onnx":      "kokoro-onnx",
    "sounddevice":      "sounddevice",
    "soundfile":        "soundfile",
    # search / duck
    "duckduckgo_search":"duckduckgo-search",
    # other common underscore→hyphen cases
    "azure":            "azure",
    "google":           "google",
}

# Canonical hyphenated name for packages that appear with underscores in the wild
_NORMALIZE = re.compile(r"[-_.]+")

def _canonical(name: str) -> str:
    """Lowercase and collapse [-_.] runs to a single hyphen (PEP 503)."""
    return _NORMALIZE.sub("-", name).lower()


# ── Extras / marker filtering ─────────────────────────────────────────────────

# Matches lines that are only relevant for an optional extra, e.g.:
#   somepackage; extra == "dev"
#   somepackage>=1.0; (os_name == "nt") and extra == "test"
_EXTRAS_RE = re.compile(r'extra\s*==', re.IGNORECASE)

# Matches platform/env markers that don't apply universally (we drop these from
# the simple requirements.txt; the lockfile keeps them annotated).
_COND_MARKERS = re.compile(
    r';\s*(os_name|sys_platform|platform_machine|platform_python_implementation'
    r'|implementation_name|python_version|platform_system)',
    re.IGNORECASE,
)

def _is_extras_only(req: str) -> bool:
    """True if the requirement only applies when a specific extra is requested."""
    return bool(_EXTRAS_RE.search(req))

def _strip_marker(req: str) -> str:
    """Remove environment markers from a requirement string, keeping the name+version."""
    return req.split(";")[0].strip()

def _req_name(req: str) -> str:
    """Extract the bare, canonical package name from a requirement string."""
    name = re.split(r"[><=!~\[;, ]", req.strip())[0]
    return _canonical(name)

def _req_lower_bound(req: str) -> Optional[str]:
    """Return the version string if the req is a simple lower-bound (>=x.y.z)."""
    m = re.match(r"[^><=!~]+>=([^\s,;]+)", req)
    return m.group(1) if m else None


# ── Deduplication ─────────────────────────────────────────────────────────────

def _dedup_requirements(reqs: Set[str]) -> Set[str]:
    """
    Collapse duplicate/redundant requirement lines for the same package.

    Strategy per package:
    * Drop extras-only lines entirely.
    * Drop conditional-marker lines (platform-specific).
    * If multiple lower-bounds remain (>=x, >=y), keep only the highest.
    * If a pinned version (==) exists alongside bounds, keep the pin.
    * Normalise typing_extensions → typing-extensions etc.
    """
    # Group by canonical name
    by_name: Dict[str, List[str]] = {}
    for req in reqs:
        req = req.strip()
        if not req or req.startswith("#"):
            continue
        if _is_extras_only(req):
            continue
        if _COND_MARKERS.search(req):
            # conditional on platform — drop from the universal file
            continue
        clean = _strip_marker(req)
        name  = _req_name(clean)
        by_name.setdefault(name, []).append(clean)

    result: Set[str] = set()
    for name, entries in by_name.items():
        # If there's a pin, use it
        pinned = [e for e in entries if "==" in e]
        if pinned:
            # Use the most recent pin (last wins, they should be identical)
            result.add(pinned[-1])
            continue

        # Multiple lower bounds — keep the highest
        bounds = [e for e in entries if ">=" in e]
        if bounds:
            def _ver_tuple(s: str) -> tuple:
                raw = re.search(r">=([^\s,;]+)", s)
                if not raw:
                    return (0,)
                try:
                    return tuple(int(x) for x in raw.group(1).split("."))
                except ValueError:
                    return (0,)
            best = max(bounds, key=_ver_tuple)
            result.add(best)
            continue

        # Anything else (bare name, compat ~=, upper bounds) — just take the first
        result.add(entries[0])

    return result


# ── PyPI helpers ──────────────────────────────────────────────────────────────

def get_installed_packages() -> Dict[str, str]:
    """Return {canonical_package_name: version} for every installed distribution."""
    packages: Dict[str, str] = {}
    try:
        for dist in importlib.metadata.distributions():
            name = dist.metadata.get("Name")
            if name:
                packages[_canonical(name)] = dist.version
    except Exception as exc:
        logging.error("Failed to enumerate installed packages: %s", exc)
    return packages


def resolve_package(module: str, installed_packages: Dict[str, str]) -> str:
    """
    Translate an import-level module name to its canonical PyPI distribution name.

    Priority:
    1. Known MODULE_TO_PACKAGE mapping
    2. Exact match in installed packages (after normalisation)
    3. Return canonical form of the module name as a best guess
    """
    # 1. Explicit map (try original case, then lowered)
    if module in MODULE_TO_PACKAGE:
        return MODULE_TO_PACKAGE[module]
    if module.lower() in MODULE_TO_PACKAGE:
        return MODULE_TO_PACKAGE[module.lower()]

    # 2. Installed match
    canon = _canonical(module)
    if canon in installed_packages:
        return canon

    # 3. Fallback — at least normalise underscores to hyphens
    return canon


def fetch_pypi_requires(package: str) -> List[str]:
    """
    Ask PyPI for the run-time requirements of *package*.
    Returns [] on any failure (network, not found, etc.).
    Extras-only requirements are filtered out here.
    """
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
        requires = data.get("info", {}).get("requires_dist") or []
        return [r for r in requires if not _is_extras_only(r)]
    except Exception as exc:
        logging.debug("PyPI lookup failed for %s: %s", package, exc)
        return []


def get_dependencies_from_packages(
    packages: Set[str],
    installed_packages: Dict[str, str],
    *,
    fetch_transitive: bool = True,
) -> Tuple[Set[str], Dict[str, List[str]]]:
    """
    Given a set of PyPI package names, return:

    * ``direct_deps``   – deduplicated, pinned/unpinned requirement strings
    * ``transitive_map``– {package: [transitive_req_strings]}
    """
    direct_deps: Set[str] = set()
    transitive_map: Dict[str, List[str]] = {}

    for package in packages:
        canon   = _canonical(package)
        version = installed_packages.get(canon)
        direct_deps.add(f"{canon}=={version}" if version else canon)

        if fetch_transitive:
            raw = fetch_pypi_requires(package)
            if raw:
                # Deduplicate transitive reqs for this package
                deduped = _dedup_requirements(set(raw))
                transitive_map[package] = sorted(deduped)
                logging.debug("Transitive deps for %s: %s", package, deduped)

    return direct_deps, transitive_map


def check_conflicts(
    dependencies: Set[str],
    conflict_data: Dict,
) -> List[Dict]:
    """
    Check for known conflicts.  Returns a list of triggered conflict records.
    """
    conflict_table = conflict_data.get("conflict_table", [])
    detected = {_req_name(dep) for dep in dependencies}

    triggered = []
    for conflict in conflict_table:
        conflict_pkgs = {_canonical(p) for p in conflict.get("packages", [])}
        if conflict_pkgs.issubset(detected):
            triggered.append(conflict)
            logging.warning(
                "Conflict detected between %s: %s  →  %s",
                conflict.get("packages"),
                ", ".join(conflict.get("symptoms", [])),
                conflict.get("resolution", {}).get("suggest", ""),
            )
    return triggered
