"""
utils/spec_io.py — shared spec loading + safe path components for the
build_*_cli scripts.

The build scripts take a JSON spec from an untrusted-ish boundary (Claude
writes it, but a spec could carry a malicious `filename`/`subdir`). These
helpers keep output strictly inside `output/<bucket>/` — no path traversal.
"""
import json
import os
import sys
from pathlib import Path

# The only output buckets the toolkit writes to.
VALID_SUBDIRS = ("adhoc", "daily", "weekly")


def load_spec(arg: str) -> dict:
    """Load a JSON spec from a file path, or from stdin when arg == '-'."""
    if arg == "-":
        return json.load(sys.stdin)
    return json.loads(Path(arg).read_text(encoding="utf-8"))


def safe_subdir(subdir, default: str = "adhoc") -> str:
    """Restrict subdir to the known output buckets (prevents traversal)."""
    s = str(subdir or default).strip()
    return s if s in VALID_SUBDIRS else default


def safe_filename(name: str) -> str:
    """Strip any directory components from a spec-provided filename."""
    return os.path.basename(str(name)).strip() or "untitled"
