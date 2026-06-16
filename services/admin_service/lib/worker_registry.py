"""Worker alias → Python module mapping (strict allowlist for subprocess execution)."""

from __future__ import annotations

from fastapi import HTTPException, status

# Hardcoded allowlist — user-supplied names must match exactly (no dynamic import).
WORKER_ALLOWLIST: dict[str, str] = {
    "macro-ingestion": "workers.macro_ingestion_worker",
    "macro-regime": "workers.macro_regime_worker",
    "massive-ingest": "workers.massive_ingestion_worker",
    "intraday-ingest": "workers.intraday_ingestion_worker",
    "daily-pipeline": "workers.daily_pipeline_runner",
    "indicator-compute": "workers.indicator_compute_worker",
    "theeye-indicator": "workers.theeyebeta_indicator_worker",
    "sector-aggregation": "workers.sector_aggregation_worker",
    "market-cap-fetch": "workers.market_cap_fetch_worker",
    "market-cap-threshold": "workers.market_cap_threshold_worker",
    "gap-sentinel": "workers.gap_sentinel_worker",
    "supabase-sync": "workers.supabase_sync_worker",
}

# Legacy aliases accepted at the API layer (mapped to allowlist keys).
WORKER_ALIASES: dict[str, str] = {
    "macro-ingest": "macro-ingestion",
    "indicator-validate": "theeye-indicator",
    "sector": "sector-aggregation",
}

WORKER_CLASS_NAMES: dict[str, str] = {
    "macro-ingestion": "MacroIngestionWorker",
    "macro-regime": "MacroRegimeWorker",
    "massive-ingest": "MassiveDailyIngestionWorker",
    "intraday-ingest": "IntradayIngestionWorker",
    "indicator-compute": "IndicatorComputeWorker",
    "theeye-indicator": "TheeyebetaIndicatorWorker",
    "daily-pipeline": "daily_pipeline",
    "gap-sentinel": "GapSentinelWorker",
    "sector-aggregation": "SectorAggregationWorker",
    "market-cap-fetch": "MarketCapFetchWorker",
    "market-cap-threshold": "MarketCapThresholdWorker",
    "supabase-sync": "SupabaseSyncV2",
}

# Backward-compatible export used by list endpoints.
WORKER_MODULES: dict[str, str] = WORKER_ALLOWLIST

WORKER_HEARTBEAT_INTERVALS: dict[str, int] = {
    "IntradayIngestionWorker": 900,
    "GapSentinelWorker": 86400,
    "MacroIngestionWorker": 86400,
    "MacroRegimeWorker": 86400,
    "MassiveDailyIngestionWorker": 86400,
    "IndicatorComputeWorker": 86400,
    "TheeyebetaIndicatorWorker": 86400,
    "SectorAggregationWorker": 86400,
    "MarketCapFetchWorker": 86400,
    "MarketCapThresholdWorker": 86400,
    "daily_pipeline": 86400,
    "SupabaseSyncV2": 86400,
}

DEFAULT_HEARTBEAT_INTERVAL = 86400


def resolve_worker_module(name: str) -> tuple[str, str, str]:
    """Map API worker name to allowlist key, module path, and DB class name."""
    canonical = WORKER_ALIASES.get(name, name)
    if canonical not in WORKER_ALLOWLIST:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown worker: {name}",
        )
    module = WORKER_ALLOWLIST[canonical]
    class_name = WORKER_CLASS_NAMES[canonical]
    return canonical, module, class_name
