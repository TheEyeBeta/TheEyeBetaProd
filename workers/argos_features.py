"""Full ARGOS feature JSON assembly (macro_context + sector_context)."""

from __future__ import annotations

from datetime import date

import asyncpg

from workers.macro_features import fetch_argos_macro_feature_block
from workers.sector_features import fetch_argos_sector_context


async def build_argos_feature_json(
    conn: asyncpg.Connection,
    *,
    trade_date: date,
    worker_name: str = "ArgosContextWorker",
) -> dict[str, object]:
    """Assemble the ARGOS feature payload from canonical theeyebeta data.

    Each block reports its own ``data_gaps``; the top-level ``data_gaps``
    aggregates them so a consumer can check one key. Missing data is named,
    never fabricated.
    """
    macro = await fetch_argos_macro_feature_block(
        conn,
        trade_date=trade_date,
        worker_name=worker_name,
    )
    sector = await fetch_argos_sector_context(
        conn,
        trade_date=trade_date,
        worker_name=worker_name,
    )
    data_gaps = sorted(
        {*macro.get("data_gaps", []), *sector.get("data_gaps", [])},
    )
    return {
        "as_of_date": trade_date.isoformat(),
        "macro_context": macro,
        "sector_context": sector,
        "data_gaps": data_gaps,
    }
