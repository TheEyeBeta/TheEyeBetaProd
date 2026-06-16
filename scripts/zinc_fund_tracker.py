"""zinc_fund_tracker.py — ZINC INVESTMENTS 15-minute fund valuation worker.

Run modes:
  python scripts/zinc_fund_tracker.py          — take one snapshot
  python scripts/zinc_fund_tracker.py --eod    — take snapshot + send EOD email
  python scripts/zinc_fund_tracker.py --seed   — insert open Alpaca orders into DB
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText

import psycopg

# ── Config ────────────────────────────────────────────────────────────────────

ZINC_KEY    = os.environ["ALPACA_API_KEY_PAPER_ZINC"]
ZINC_SECRET = os.environ["ALPACA_API_SECRET_PAPER_ZINC"]
DATABASE_URL = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")

PORTFOLIO_ID = "c40e8400-e29b-41d4-a716-446655440004"  # zinc-investments

SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO      = os.environ.get("ZINC_FUND_EMAIL_TO") or os.environ.get("TRASK_ALERT_EMAILS", "")

ALPACA_BASE = "https://paper-api.alpaca.markets/v2"

# instrument_id lookup for the 10 symbols
INSTRUMENT_IDS: dict[str, int] = {
    "AAPL": 1, "MSFT": 2, "NVDA": 3, "GOOGL": 4,
    "AMD": 43, "AMZN": 50, "AVGO": 62, "META": 324,
    "MU": 346, "TSLA": 468,
}

# ── Alpaca helpers ────────────────────────────────────────────────────────────

def _alpaca(path: str) -> object:
    req = urllib.request.Request(
        f"{ALPACA_BASE}{path}",
        headers={
            "APCA-API-KEY-ID": ZINC_KEY,
            "APCA-API-SECRET-KEY": ZINC_SECRET,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


# ── Snapshot ──────────────────────────────────────────────────────────────────

def take_snapshot() -> dict:
    account   = _alpaca("/account")
    positions = _alpaca("/positions")

    cash         = float(account["cash"])
    market_value = sum(float(p["market_value"]) for p in positions)
    total_value  = cash + market_value
    unreal_pnl   = sum(float(p["unrealized_pl"]) for p in positions)

    pos_data = [
        {
            "symbol":        p["symbol"],
            "qty":           float(p["qty"]),
            "market_value":  float(p["market_value"]),
            "unrealized_pnl": float(p["unrealized_pl"]),
            "avg_entry":     float(p["avg_entry_price"]),
            "current_price": float(p["current_price"]),
            "pct_change":    float(p["unrealized_plpc"]) * 100,
        }
        for p in positions
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO theeyebeta.paper_fund_snapshots
              (portfolio_id, snapshotted_at, cash, market_value,
               total_value, unrealized_pnl, positions_count, positions)
            VALUES (%s, now(), %s, %s, %s, %s, %s, %s)
            ON CONFLICT (portfolio_id, snapshotted_at) DO UPDATE
              SET market_value   = EXCLUDED.market_value,
                  total_value    = EXCLUDED.total_value,
                  unrealized_pnl = EXCLUDED.unrealized_pnl,
                  positions_count = EXCLUDED.positions_count,
                  positions      = EXCLUDED.positions
            """,
            (PORTFOLIO_ID, cash, market_value, total_value, unreal_pnl, len(positions), json.dumps(pos_data)),
        )
        conn.commit()

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"total=${total_value:,.2f}  pnl=${unreal_pnl:+,.2f}  positions={len(positions)}"
    )
    return {"cash": cash, "market_value": market_value, "total_value": total_value,
            "unrealized_pnl": unreal_pnl, "positions": pos_data}


# ── EOD email ─────────────────────────────────────────────────────────────────

def send_eod_email(snap: dict) -> None:
    tv  = snap["total_value"]
    pnl = snap["unrealized_pnl"]
    mv  = snap["market_value"]
    pos = sorted(snap["positions"], key=lambda x: x["market_value"], reverse=True)

    rows = "\n".join(
        f"  {p['symbol']:<6} {p['qty']:>5.0f} sh  "
        f"${p['market_value']:>11,.2f}  "
        f"${p['unrealized_pnl']:>+10,.2f}  "
        f"{p['pct_change']:>+7.2f}%"
        for p in pos
    )

    body = f"""\
ZINC INVESTMENTS — End of Day Report
{'='*60}
Date:             {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
Total Fund Value: ${tv:>12,.2f}
  Cash:           ${snap['cash']:>12,.2f}
  Equities:       ${mv:>12,.2f}
Unrealized P&L:   ${pnl:>+12,.2f}

Holdings:
  {'Symbol':<6} {'Shares':>5}     {'Market Value':>13}  {'Unreal P&L':>12}  {'Change':>8}
  {'-'*58}
{rows}
{'='*60}
Powered by TheEyeBeta / ZINC INVESTMENTS paper stack
"""

    msg = MIMEText(body)
    msg["Subject"] = f"ZINC INVESTMENTS EOD — ${tv:,.0f}"
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)

    print(f"EOD email sent → {EMAIL_TO}")


# ── Order seeder ──────────────────────────────────────────────────────────────

def seed_orders() -> None:
    """Pull open orders from Alpaca zinc account and insert into theeyebeta.orders."""
    orders = _alpaca("/orders?status=all&limit=50")

    inserted = 0
    with psycopg.connect(DATABASE_URL) as conn:
        for o in orders:
            sym = o["symbol"]
            instrument_id = INSTRUMENT_IDS.get(sym)
            if instrument_id is None:
                print(f"  skip {sym} — not in instrument map")
                continue

            conn.execute(
                """
                INSERT INTO theeyebeta.orders
                  (id, client_order_id, broker_order_id, portfolio_id, instrument_id,
                   side, order_type, qty, time_in_force, status,
                   submitted_at, filled_qty, avg_fill_price, created_at, updated_at)
                VALUES (
                  gen_random_uuid(),
                  %s, %s, %s, %s,
                  %s, 'market', %s, 'day', %s,
                  %s, %s, %s, now(), now()
                )
                ON CONFLICT (client_order_id) DO NOTHING
                """,
                (
                    o["client_order_id"],
                    o["id"],
                    PORTFOLIO_ID,
                    instrument_id,
                    o["side"],
                    float(o["qty"]),
                    o["status"],
                    o.get("submitted_at"),
                    float(o.get("filled_qty") or 0),
                    float(o.get("filled_avg_price") or 0) or None,
                ),
            )
            inserted += 1
            print(f"  ✓ {sym:<6} {o['side']} {o['qty']} — {o['status']}")

        conn.commit()

    print(f"Seeded {inserted} orders into theeyebeta.orders")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])

    if "--seed" in args:
        seed_orders()
    else:
        snap = take_snapshot()
        if "--eod" in args:
            send_eod_email(snap)
