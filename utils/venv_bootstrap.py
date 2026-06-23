"""
utils/venv_bootstrap.py — transparently re-exec under the repo's own venv.

install.sh installs all dependencies into ``$FCC_MAS_HOME/.venv`` (a real
virtualenv) instead of the system / --user site-packages. This avoids:
  • PEP 668 "externally-managed-environment" on Debian/Ubuntu/WSL pythons
  • the odfpy source build failing under Debian-patched setuptools
    (``AttributeError: install_layout``) when build isolation is off
  • clobbering the user's global package versions (e.g. pandas).

The skills, however, are documented to run our CLIs with a plain
``python3`` (via ``"${FCC_MAS_PY:-python3}"``). When that fallback to a
bare ``python3`` happens — or a developer just runs
``python3 scripts/build_docx_cli.py`` directly — this shim re-execs the
process under the venv interpreter so the imports resolve.

Pure stdlib (os, sys, pathlib) so it imports fine under *any* interpreter,
including one that has none of the project deps installed yet. Best-effort:
any failure leaves the current interpreter untouched.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def activate(repo_root: str | os.PathLike) -> None:
    """Re-exec the current process under ``<repo_root>/.venv`` if present.

    No-op when:
      • the venv doesn't exist (e.g. legacy --user install) — run in place;
      • we're already running under it — avoids an exec loop;
      • FCC_MAS_NO_VENV is set — escape hatch for debugging.
    """
    if os.environ.get("FCC_MAS_NO_VENV"):
        return
    try:
        venv_dir = Path(repo_root) / ".venv"
        bindir = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        venv_py = venv_dir / bindir / exe

        if not venv_py.exists():
            return  # no venv — legacy/in-place install, nothing to do
        # Already inside this venv? sys.prefix points at the venv root.
        if Path(sys.prefix).resolve() == venv_dir.resolve():
            return

        os.execv(str(venv_py), [str(venv_py), *sys.argv])
    except Exception:
        # Never let the bootstrap break an otherwise-working interpreter.
        return
