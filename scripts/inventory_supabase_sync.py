#!/usr/bin/env python3
"""D0: inventory legacy Supabase sync contract (read-only)."""

from __future__ import annotations

import os
import re

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = re.sub(r"\+\w+", "", os.environ.get("DATABASE_URL", ""), count=1)

CONTRACT = [
    ("latest_snapshot", "public.latest_snapshot + tickers", "REST upsert", "60s daemon", "IRIS / Supabase readers"),
    ("market_news", "public.market_news", "REST upsert", "60s news-sync", "IRIS news widgets"),
]


def main() -> None:
    print("| Supabase table | Source | Transform | Schedule | Consumer |")
    print("|---|---|---|---|---|")
    for row in CONTRACT:
        print(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} |")

    if not DATABASE_URL:
        return
    with psycopg.connect(DATABASE_URL) as conn:
        for table, *_ in CONTRACT:
            src = table if table != "latest_snapshot" else "latest_snapshot"
            try:
                n = conn.execute(f"SELECT COUNT(*) FROM public.{src}").fetchone()[0]
                print(f"\npublic.{src} rows: {n}")
            except psycopg.Error as exc:
                print(f"\npublic.{src}: {exc}")


if __name__ == "__main__":
    main()
