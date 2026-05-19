# scanner.py

import ast
import logging
from pathlib import Path
from typing import Dict, Set

# Directories that are never worth scanning
_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "venv", ".venv", "env", ".env",
    "node_modules",
    "dist", "build", ".eggs",
    "site-packages",
}


def extract_imports(file_path: Path) -> Set[str]:
    """
    Extract top-level imported module names from a Python file using AST.
    Falls back to latin-1 if the file isn't valid UTF-8.
    """
    imports: Set[str] = set()
    source = None
    for encoding in ("utf-8", "latin-1"):
        try:
            source = file_path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            logging.error("Cannot read %s: %s", file_path, exc)
            return imports

    if source is None:
        return imports

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as exc:
        logging.warning("Syntax error in %s (skipping): %s", file_path, exc)
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 → relative import; skip
            if node.module and node.level == 0:
                imports.add(node.module.split(".")[0])

    logging.debug("Imports from %s: %s", file_path, imports)
    return imports


def scan_directory_for_imports(
    directory: Path,
    blacklist: Set[str],
) -> Dict[str, Set[Path]]:
    """
    Recursively scan *directory* for Python files and return a mapping of
    {module_name: {source_files}} for every third-party import found.

    Skips:
    * stdlib / blacklisted modules
    * local modules (a .py file or package with the same name exists nearby)
    * common non-project directories (venv, .git, __pycache__, …)

    Returns a dict rather than a plain set so callers can show provenance.
    """
    blacklist_lower = {m.lower() for m in blacklist}

    # Collect all relevant .py files first
    py_files: list[Path] = []
    for path in directory.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        py_files.append(path)

    # Build local module/package names visible anywhere in the tree
    local_names: Set[str] = set()
    for py_file in py_files:
        local_names.add(py_file.stem)
        local_names.add(py_file.parent.name)

    result: Dict[str, Set[Path]] = {}
    for file_path in py_files:
        logging.info("Scanning %s", file_path)
        for module in extract_imports(file_path):
            if module.lower() in blacklist_lower:
                logging.debug("Skipping stdlib/blacklisted: %s", module)
                continue
            if module in local_names:
                logging.debug("Skipping local module: %s", module)
                continue
            result.setdefault(module, set()).add(file_path)

    return result
