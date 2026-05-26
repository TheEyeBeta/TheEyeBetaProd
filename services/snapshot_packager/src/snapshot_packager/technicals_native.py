"""zinc_native.ta wrapper with a clear import error when extensions are missing."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from zinc_native.ta import TechnicalsLast


def snapshot_technicals_last(ohlc_series: list[np.ndarray]) -> list[TechnicalsLast]:
    """Compute last-bar technicals for many instruments via ``zinc_native._zinc_ta``."""
    try:
        from zinc_native._zinc_ta import snapshot_technicals_last as _native_last
    except ImportError as exc:
        msg = (
            "zinc_native._zinc_ta is not built — run `make build-cpp` from the repo root "
            "before packaging snapshots"
        )
        raise ImportError(msg) from exc
    return _native_last(ohlc_series)
