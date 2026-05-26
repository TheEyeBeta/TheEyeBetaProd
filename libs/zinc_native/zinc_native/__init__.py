"""Native C++ extensions for theeyebeta (zinc compute kernels)."""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["bt", "oms", "opt", "risk", "ta"]


def __getattr__(name: str) -> Any:
    """Lazy-load extension submodules so optional kernels stay importable."""
    if name in __all__:
        return importlib.import_module(f".{name}", __name__)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
