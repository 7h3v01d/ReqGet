# config.py
"""
.reqgetrc config file support.

reqget looks for a config file in this order:
  1. Path passed via --config <file>
  2. .reqgetrc  in the project directory being scanned
  3. .reqgetrc  in the user's home directory (~/.reqgetrc)

Format: JSON  (comments not supported — use a wrapper script if you need them)

Example .reqgetrc:
{
    "output":          "requirements.txt",
    "no_transitive":   false,
    "no_comments":     false,
    "lock":            false,
    "lock_output":     "requirements.lock",
    "ignore_extra":    false,
    "freeze_check":    false,
    "exclude_dirs":    ["docs", "scripts"],
    "extra_blacklist": ["mypy", "black", "isort", "pytest"]
}

CLI flags always override config file values.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import List, Optional


CONFIG_FILENAME = ".reqgetrc"

DEFAULTS: dict = {
    "output":          "requirements.txt",
    "no_transitive":   False,
    "no_comments":     False,
    "lock":            False,
    "lock_output":     "requirements.lock",
    "ignore_extra":    False,
    "freeze_check":    False,
    "exclude_dirs":    [],
    "extra_blacklist": [],
}


@dataclass
class Config:
    # Output
    output:          str       = "requirements.txt"
    no_transitive:   bool      = False
    no_comments:     bool      = False
    # Lockfile
    lock:            bool      = False
    lock_output:     str       = "requirements.lock"
    # Freeze check
    freeze_check:    bool      = False
    ignore_extra:    bool      = False
    # Scanner tweaks
    exclude_dirs:    List[str] = field(default_factory=list)
    extra_blacklist: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        logging.info("Saved config to %s", path)


def _find_config(project_dir: Optional[Path] = None) -> Optional[Path]:
    """Search for .reqgetrc in project dir then home dir."""
    candidates = []
    if project_dir:
        candidates.append(project_dir / CONFIG_FILENAME)
    candidates.append(Path.home() / CONFIG_FILENAME)
    for path in candidates:
        if path.is_file():
            logging.debug("Found config: %s", path)
            return path
    return None


def load_config(
    project_dir: Optional[Path] = None,
    explicit_path: Optional[Path] = None,
) -> Config:
    """
    Load and return a Config.  Falls back to all defaults if no file is found.
    Unknown keys in the file are silently ignored (forward-compat).
    """
    config_path = explicit_path or _find_config(project_dir)
    data: dict = {}

    if config_path:
        try:
            data = json.loads(config_path.read_text())
            logging.info("Loaded config from %s", config_path)
        except json.JSONDecodeError as exc:
            logging.error("Invalid JSON in %s: %s — using defaults", config_path, exc)
        except OSError as exc:
            logging.error("Cannot read %s: %s — using defaults", config_path, exc)

    # Merge with defaults; ignore unknown keys
    valid_keys = {f.name for f in fields(Config)}
    merged = {**DEFAULTS, **{k: v for k, v in data.items() if k in valid_keys}}
    return Config(**merged)


def merge_with_args(config: Config, args) -> Config:
    """
    Override config values with any CLI args that were explicitly set.
    argparse stores None for unset optional flags, False for unset store_true.
    We only override when the CLI arg is truthy or explicitly provided.
    """
    # Booleans: CLI wins when True (store_true flags default to False)
    bool_flags = ("no_transitive", "no_comments", "lock", "freeze_check", "ignore_extra")
    for flag in bool_flags:
        if getattr(args, flag, False):
            setattr(config, flag, True)

    # Strings: CLI wins when not None
    if getattr(args, "output", None):
        config.output = args.output
    if getattr(args, "lock_output", None):
        config.lock_output = args.lock_output

    return config


def init_config(project_dir: Path, *, force: bool = False) -> Path:
    """
    Write a default .reqgetrc into *project_dir*.
    Raises FileExistsError if one already exists and force=False.
    """
    dest = project_dir / CONFIG_FILENAME
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} already exists. Use --force to overwrite.")
    cfg = Config()
    cfg.save(dest)
    return dest
