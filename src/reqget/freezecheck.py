# freezecheck.py
"""
pip freeze compare — diff what reqget found against what's actually installed.

Three categories:
  MISSING   — reqget found it in your code, but it's not installed in this env
  EXTRA     — it's installed in this env, but reqget didn't find an import for it
  VERSION   — it's installed but at a different version than what reqget pinned
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, Set, Tuple


@dataclass
class FreezeReport:
    missing: list[Tuple[str, str]] = field(default_factory=list)   # (name, pinned_ver)
    extra:   list[Tuple[str, str]] = field(default_factory=list)   # (name, installed_ver)
    version_mismatch: list[Tuple[str, str, str]] = field(default_factory=list)  # (name, pinned, installed)
    ok:      list[Tuple[str, str]] = field(default_factory=list)   # (name, ver)

    @property
    def has_issues(self) -> bool:
        return bool(self.missing or self.extra or self.version_mismatch)


def get_freeze_dict() -> Dict[str, str]:
    """Return {package_lower: version} from `pip freeze` in the current env."""
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "pip", "freeze", "--all"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return {}
    result: Dict[str, str] = {}
    for line in out.splitlines():
        line = line.strip()
        if "==" in line and not line.startswith("#") and not line.startswith("-"):
            name, _, ver = line.partition("==")
            result[name.strip().lower()] = ver.strip()
    return result


def compare(
    reqget_deps: Set[str],
    freeze_dict: Dict[str, str],
    *,
    ignore_extra: bool = False,
) -> FreezeReport:
    """
    Compare *reqget_deps* (set of "name==ver" or bare "name" strings) against
    *freeze_dict* (output of get_freeze_dict).

    ignore_extra: don't flag packages that are installed but not in reqget output
                  (useful when the env has dev tools, linters, etc.)
    """
    report = FreezeReport()

    # Parse reqget deps into {name_lower: pinned_ver_or_None}
    reqget: Dict[str, str | None] = {}
    for dep in reqget_deps:
        if "==" in dep:
            name, _, ver = dep.partition("==")
            reqget[name.strip().lower()] = ver.strip()
        else:
            reqget[dep.strip().lower()] = None

    for name, pinned_ver in reqget.items():
        installed_ver = freeze_dict.get(name)
        if installed_ver is None:
            report.missing.append((name, pinned_ver or "?"))
        elif pinned_ver and installed_ver != pinned_ver:
            report.version_mismatch.append((name, pinned_ver, installed_ver))
        else:
            report.ok.append((name, installed_ver))

    if not ignore_extra:
        reqget_names = set(reqget.keys())
        for name, ver in freeze_dict.items():
            if name not in reqget_names:
                report.extra.append((name, ver))

    return report


def format_report(report: FreezeReport, *, color: bool = True) -> str:
    """Return a human-readable diff string."""
    RED    = "\033[91m" if color else ""
    YELLOW = "\033[93m" if color else ""
    GREEN  = "\033[92m" if color else ""
    DIM    = "\033[2m"  if color else ""
    RESET  = "\033[0m"  if color else ""

    lines: list[str] = []

    if report.missing:
        lines.append(f"{RED}MISSING  (in code, not installed):{RESET}")
        for name, ver in sorted(report.missing):
            lines.append(f"  {RED}✗{RESET}  {name}=={ver}")

    if report.version_mismatch:
        lines.append(f"\n{YELLOW}VERSION MISMATCH:{RESET}")
        for name, pinned, installed in sorted(report.version_mismatch):
            lines.append(f"  {YELLOW}≠{RESET}  {name}  pinned={pinned}  installed={installed}")

    if report.extra:
        lines.append(f"\n{DIM}EXTRA  (installed, not in reqget output):{RESET}")
        for name, ver in sorted(report.extra):
            lines.append(f"  {DIM}+  {name}=={ver}{RESET}")

    if report.ok:
        lines.append(f"\n{GREEN}OK:{RESET}")
        for name, ver in sorted(report.ok):
            lines.append(f"  {GREEN}✓{RESET}  {name}=={ver}")

    if not report.has_issues:
        lines.append(f"{GREEN}Everything looks good — no issues found.{RESET}")

    return "\n".join(lines)
