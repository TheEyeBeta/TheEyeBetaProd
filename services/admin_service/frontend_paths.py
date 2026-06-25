"""Resolve TheEyeBetaAdminFrontend paths for templates, static, and frontend_ia."""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_DIR = Path(__file__).resolve().parent
_MONOREPO_ROOT = _SERVICE_DIR.parents[2]
_DEFAULT_FRONTEND_ROOT = _MONOREPO_ROOT / "TheEyeBetaAdminFrontend"


def resolve_frontend_root(explicit: str | Path | None = None) -> Path:
    """Return the admin frontend repo root (sibling of TheEyeProd)."""
    if explicit:
        path = Path(explicit).expanduser().resolve()
    else:
        path = _DEFAULT_FRONTEND_ROOT.resolve()
    if not path.is_dir():
        msg = f"Admin frontend root not found: {path}"
        raise FileNotFoundError(msg)
    return path


def ensure_frontend_on_path(frontend_root: Path | None = None) -> Path:
    """Add frontend repo to ``sys.path`` so ``import frontend_ia`` works."""
    root = frontend_root or resolve_frontend_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def templates_dir(frontend_root: Path) -> Path:
    return frontend_root / "templates"


def static_dir(frontend_root: Path) -> Path:
    return frontend_root / "static"


def terminal_dir(frontend_root: Path) -> Path:
    """Built Terminal Echo SPA (Vite output)."""
    return frontend_root / "static" / "terminal"
