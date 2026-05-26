"""Market ↔ exchange MIC mapping (aligned with data_ingestion pipeline)."""

from __future__ import annotations

MARKET_EXCHANGE_CASE_SQL = """
CASE e.code
    WHEN 'XNAS' THEN 'US' WHEN 'XNYS' THEN 'US'
    WHEN 'XHKG' THEN 'HK' WHEN 'XTKS' THEN 'JP'
    WHEN 'XTAI' THEN 'TW' WHEN 'XSHG' THEN 'CN'
    WHEN 'XSHE' THEN 'CN' ELSE 'OTHER'
END
"""

VALID_MARKETS: frozenset[str] = frozenset({"US", "HK", "JP", "TW", "CN"})
