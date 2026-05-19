# lockfile.py

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple


# ── PyPI helpers ─────────────────────────────────────────────────────────────

def _pypi_info(package: str) -> Optional[Dict]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        logging.debug("PyPI fetch failed for %s: %s", package, exc)
        return None


def _latest_version(package: str) -> Optional[str]:
    data = _pypi_info(package)
    return data.get("info", {}).get("version") if data else None


def _requires_dist(package: str, version: str) -> List[str]:
    data = _pypi_info(package)
    if not data:
        return []
    requires = data.get("info", {}).get("requires_dist") or []
    # Filter extras-only and conditional-marker lines
    return [
        r for r in requires
        if "; extra ==" not in r
        and not re.search(r'extra\s*==', r, re.IGNORECASE)
    ]


def _parse_req_name(req: str) -> str:
    """Canonical (hyphenated, lowercased) package name from a requirement string."""
    name = re.split(r"[><=!~\[;, ]", req.strip())[0]
    return re.sub(r"[-_.]+", "-", name).lower()


# ── Recursive resolver ────────────────────────────────────────────────────────

def resolve_lockfile(
    direct_packages: Set[str],
    installed_packages: Dict[str, str],
    *,
    depth_limit: int = 6,
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """
    Recursively resolve *direct_packages* into a fully-pinned dict.

    Returns:
        pinned   — {package_canonical: "x.y.z"}
        sources  — {package_canonical: ["direct" | "transitive via <parent>"]}
    """
    pinned:  Dict[str, str]       = {}
    sources: Dict[str, List[str]] = {}
    queue:   List[Tuple[str, str, int]] = []

    for pkg in direct_packages:
        queue.append((_parse_req_name(pkg), "direct", 0))

    visited: Set[str] = set()

    while queue:
        pkg, via, depth = queue.pop(0)
        if pkg in visited or depth > depth_limit:
            continue
        visited.add(pkg)

        ver = installed_packages.get(pkg)
        if not ver:
            logging.info("Fetching latest version of %s from PyPI…", pkg)
            ver = _latest_version(pkg)
        if not ver:
            logging.warning("Could not resolve version for %s — skipping", pkg)
            continue

        pinned[pkg] = ver
        sources.setdefault(pkg, []).append(via)

        if depth < depth_limit:
            for req in _requires_dist(pkg, ver):
                child = _parse_req_name(req)
                if child and child not in visited:
                    queue.append((child, f"transitive via {pkg}", depth + 1))

    return pinned, sources


# ── Lock file writer ──────────────────────────────────────────────────────────

def write_lockfile(
    pinned: Dict[str, str],
    sources: Dict[str, List[str]],
    output_path,
    *,
    direct_names: Optional[Set[str]] = None,
) -> bool:
    """
    Write a ``requirements.lock`` file with UTF-8 encoding and ASCII-safe header.

    Header format:
        # reqget lockfile - <timestamp>   (plain hyphen, always ASCII)
        # python: 3.x.y  platform: linux
        # hash: sha256:<body_hash>
    """
    from pathlib import Path

    direct_names_canon = {
        re.sub(r"[-_.]+", "-", n).lower()
        for n in (direct_names or set())
    }

    direct_lines:     List[str] = []
    transitive_lines: List[str] = []

    for pkg in sorted(pinned):
        ver  = pinned[pkg]
        via  = sources.get(pkg, ["?"])
        line = f"{pkg}=={ver}"
        if pkg in direct_names_canon or "direct" in via:
            direct_lines.append(line)
        else:
            parent = next(
                (v.replace("transitive via ", "") for v in via
                 if v.startswith("transitive via")),
                "?"
            )
            transitive_lines.append(f"{line}  # via {parent}")

    body_lines = (
        ["# [direct]"] + direct_lines +
        ["", "# [transitive]"] + transitive_lines
    )
    body = "\n".join(body_lines)
    sha  = hashlib.sha256(body.encode("utf-8")).hexdigest()

    # Use plain ASCII hyphen in the timestamp line — avoids Windows cp1252 issues
    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    py  = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    header = (
        f"# reqget lockfile - {ts}\n"          # plain hyphen, not em-dash
        f"# python: {py}  platform: {sys.platform}\n"
        f"# hash: sha256:{sha}\n"
    )

    try:
        # Always write as UTF-8 explicitly — prevents Windows from using cp1252
        Path(output_path).write_text(header + "\n" + body + "\n", encoding="utf-8")
        logging.info("Wrote lockfile %s (%d packages)", output_path, len(pinned))
        return True
    except OSError as exc:
        logging.error("Could not write lockfile %s: %s", output_path, exc)
        return False


def verify_lockfile(lockfile_path) -> Tuple[bool, str]:
    """Re-compute the body hash and compare it to the stored one."""
    from pathlib import Path
    try:
        # Read as UTF-8; fall back to latin-1 for files written on Windows pre-fix
        for enc in ("utf-8", "latin-1"):
            try:
                text = Path(lockfile_path).read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            return False, "Could not decode lockfile (tried utf-8 and latin-1)."

        lines  = text.splitlines()
        stored = next(
            (l.split("sha256:")[1].strip() for l in lines if "hash: sha256:" in l),
            None,
        )
        if not stored:
            return False, "No hash found in lockfile header."

        body   = "\n".join(lines[4:])
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if actual == stored:
            return True, "Lockfile hash verified OK."
        return False, f"Hash mismatch — stored={stored[:16]}… actual={actual[:16]}…"
    except Exception as exc:
        return False, f"Could not verify lockfile: {exc}"
