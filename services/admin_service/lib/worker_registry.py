"""Worker alias → Python module mapping (mirrors ``tb workers list``)."""

from __future__ import annotations

WORKER_MODULES: dict[str, str] = {
    "macro-ingest": "workers.macro_ingestion_worker",
    "macro-regime": "workers.macro_regime_worker",
    "massive-ingest": "workers.massive_ingestion_worker",
    "intraday-ingest": "workers.intraday_ingestion_worker",
    "indicator-compute": "workers.indicator_compute_worker",
    "indicator-validate": "workers.theeyebeta_indicator_worker",
    "daily-pipeline": "workers.daily_pipeline_runner",
    "gap-sentinel": "workers.gap_sentinel_worker",
    "sector": "workers.sector_aggregation_worker",
    "market-cap-fetch": "workers.market_cap_fetch_worker",
    "market-cap-threshold": "workers.market_cap_threshold_worker",
    "supabase-sync": "workers.supabase_sync_worker",
}

WORKER_CLASS_NAMES: dict[str, str] = {
    "macro-ingest": "MacroIngestionWorker",
    "macro-regime": "MacroRegimeWorker",
    "massive-ingest": "MassiveDailyIngestionWorker",
    "intraday-ingest": "IntradayIngestionWorker",
    "indicator-compute": "IndicatorComputeWorker",
    "indicator-validate": "TheeyebetaIndicatorWorker",
    "daily-pipeline": "daily_pipeline",
    "gap-sentinel": "GapSentinelWorker",
    "sector": "SectorAggregationWorker",
    "market-cap-fetch": "MarketCapFetchWorker",
    "market-cap-threshold": "MarketCapThresholdWorker",
    "supabase-sync": "SupabaseSyncV2",
}

# Expected heartbeat interval seconds for staleness detection.
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
