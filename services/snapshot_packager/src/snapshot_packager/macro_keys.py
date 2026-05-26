"""Map FRED ``series_code`` values to packaged snapshot macro keys."""

from __future__ import annotations

# Locked v1 macro key names (region.metric).
MACRO_KEY_BY_SERIES_CODE: dict[str, str] = {
    "CPIAUCSL": "us.cpi_yoy",
    "DGS10": "us.dgs10",
    "GDP": "us.gdp",
    "DEXJPUS": "us.dexjpus",
    "DTWEXBGS": "us.dtwexbgs",
    "DCOILWTICO": "us.dcoilwtico",
    "CHNCPIALLMINMEI": "cn.cpi_yoy",
    "CHNGDPNQDSMEI": "cn.gdp",
}


def macro_key_for_series(series_code: str) -> str:
    """Return the packaged macro dict key for a DB series code."""
    mapped = MACRO_KEY_BY_SERIES_CODE.get(series_code)
    if mapped is not None:
        return mapped
    return series_code.lower().replace("_", ".")
