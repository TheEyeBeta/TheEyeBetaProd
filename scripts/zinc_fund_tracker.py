"""zinc_fund_tracker.py — ZINC INVESTMENTS 15-minute fund valuation worker.

Run modes:
  python scripts/zinc_fund_tracker.py          — take one snapshot
  python scripts/zinc_fund_tracker.py --eod    — take snapshot + send detailed EOD email
  python scripts/zinc_fund_tracker.py --seed   — insert open Alpaca orders into DB
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg

# ── Config ─────────────────────────────────────────────────────────────────────

ZINC_KEY    = os.environ["ALPACA_API_KEY_PAPER_ZINC"]
ZINC_SECRET = os.environ["ALPACA_API_SECRET_PAPER_ZINC"]
DATABASE_URL = os.environ["DATABASE_URL"].replace("+asyncpg", "").replace("+psycopg", "")

PORTFOLIO_ID = "c40e8400-e29b-41d4-a716-446655440004"

SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO      = os.environ.get("ZINC_FUND_EMAIL_TO") or os.environ.get("TRASK_ALERT_EMAILS", "")

LITELLM_URL = os.environ.get("LITELLM_PROXY_URL", "http://127.0.0.1:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")

ALPACA_BASE = "https://paper-api.alpaca.markets/v2"

INSTRUMENT_IDS: dict[str, int] = {
    "AAPL": 1, "MSFT": 2, "NVDA": 3, "GOOGL": 4,
    "AMD": 43, "AMZN": 50, "AVGO": 62, "META": 324,
    "MU": 346, "TSLA": 468,
}

# ── Alpaca helpers ─────────────────────────────────────────────────────────────

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


# ── Snapshot ───────────────────────────────────────────────────────────────────

def take_snapshot() -> dict:
    account   = _alpaca("/account")
    positions = _alpaca("/positions")

    equity      = float(account["equity"])
    last_equity = float(account["last_equity"])
    cash        = float(account["cash"])

    market_value    = sum(float(p["market_value"]) for p in positions)
    unrealized_pnl  = sum(float(p["unrealized_pl"]) for p in positions)
    day_pnl         = equity - last_equity
    day_pct         = (day_pnl / last_equity * 100) if last_equity else 0.0
    leverage        = (market_value / equity) if equity else 0.0

    pos_data = [
        {
            "symbol":           p["symbol"],
            "qty":              float(p["qty"]),
            "market_value":     float(p["market_value"]),
            "avg_entry":        float(p["avg_entry_price"]),
            "current_price":    float(p["current_price"]),
            "unrealized_pnl":   float(p["unrealized_pl"]),
            "unrealized_pct":   float(p["unrealized_plpc"]) * 100,
            "day_pnl":          float(p.get("unrealized_intraday_pl") or 0),
            "day_pct":          float(p.get("unrealized_intraday_plpc") or 0) * 100,
            "weight_pct":       (float(p["market_value"]) / market_value * 100) if market_value else 0,
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
              SET market_value    = EXCLUDED.market_value,
                  total_value     = EXCLUDED.total_value,
                  unrealized_pnl  = EXCLUDED.unrealized_pnl,
                  positions_count = EXCLUDED.positions_count,
                  positions       = EXCLUDED.positions
            """,
            (PORTFOLIO_ID, cash, market_value, equity, unrealized_pnl,
             len(positions), json.dumps(pos_data)),
        )
        conn.commit()

    snap = {
        "equity": equity, "last_equity": last_equity, "cash": cash,
        "market_value": market_value, "unrealized_pnl": unrealized_pnl,
        "day_pnl": day_pnl, "day_pct": day_pct, "leverage": leverage,
        "positions": pos_data,
    }

    print(
        f"[{datetime.now(timezone.utc).isoformat()}] "
        f"NAV=${equity:,.2f}  day={day_pnl:+,.2f} ({day_pct:+.2f}%)  "
        f"leverage={leverage:.1f}x  positions={len(positions)}"
    )
    return snap


# ── AI analyst brief ───────────────────────────────────────────────────────────

def generate_ai_brief(snap: dict) -> str:
    pos_lines = "\n".join(
        f"  {p['symbol']}: weight {p['weight_pct']:.1f}%  "
        f"day {p['day_pct']:+.2f}%  total {p['unrealized_pct']:+.2f}%"
        for p in sorted(snap["positions"], key=lambda x: x["market_value"], reverse=True)
    )

    prompt = f"""You are a concise equity analyst. Write a 3-4 sentence end-of-day brief for a paper trading fund.

Fund: ZINC INVESTMENTS — Top 10 US tech by market cap, 4x leveraged paper portfolio
Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
NAV: ${snap['equity']:,.2f}  (yesterday: ${snap['last_equity']:,.2f})
Day P&L: ${snap['day_pnl']:+,.2f} ({snap['day_pct']:+.2f}%)
Leverage: {snap['leverage']:.2f}x
Gross exposure: ${snap['market_value']:,.2f}

Holdings performance today:
{pos_lines}

Write a brief analyst note covering: (1) overall fund performance, (2) notable movers, (3) one sentence on risk/leverage. Be direct, no fluff."""

    # Try LiteLLM proxy first, fall back to OpenAI direct
    for url, key, model in [
        (f"{LITELLM_URL}/v1/chat/completions", LITELLM_KEY, "gpt-4o-mini"),
        ("https://api.openai.com/v1/chat/completions", OPENAI_KEY, "gpt-4o-mini"),
    ]:
        if not key:
            continue
        try:
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0.4,
            }).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                resp = json.loads(r.read())
            return resp["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            print(f"AI brief failed ({url}): {exc}")
            continue

    return "(AI analyst unavailable)"


# ── EOD email ──────────────────────────────────────────────────────────────────

def send_eod_email(snap: dict) -> None:
    date_str    = datetime.now(timezone.utc).strftime("%A, %B %d %Y")
    equity      = snap["equity"]
    last_equity = snap["last_equity"]
    day_pnl     = snap["day_pnl"]
    day_pct     = snap["day_pct"]
    leverage    = snap["leverage"]
    gross_exp   = snap["market_value"]
    cash        = snap["cash"]
    total_unreal = snap["unrealized_pnl"]

    pnl_arrow = "▲" if day_pnl >= 0 else "▼"
    day_sign  = "+" if day_pnl >= 0 else ""

    ai_brief = generate_ai_brief(snap)

    # ── Holdings table ──
    positions = sorted(snap["positions"], key=lambda x: x["market_value"], reverse=True)
    hold_rows = ""
    for p in positions:
        day_arrow = "▲" if p["day_pct"] >= 0 else "▼"
        tot_arrow = "▲" if p["unrealized_pct"] >= 0 else "▼"
        hold_rows += (
            f"  {p['symbol']:<5}  {p['qty']:>5.0f} sh  "
            f"${p['market_value']:>10,.2f}  "
            f"{p['weight_pct']:>5.1f}%  "
            f"{day_arrow} {abs(p['day_pct']):>5.2f}%  "
            f"{tot_arrow} {abs(p['unrealized_pct']):>5.2f}%  "
            f"${p['day_pnl']:>+9,.2f}\n"
        )

    plain = f"""\
╔══════════════════════════════════════════════════════════════╗
  ZINC INVESTMENTS  |  EOD REPORT  |  {date_str}
╚══════════════════════════════════════════════════════════════╝

  FUND SUMMARY
  ─────────────────────────────────────────────────────────────
  NAV (Equity)        ${equity:>12,.2f}
  Yesterday Close     ${last_equity:>12,.2f}
  Today's P&L         ${day_pnl:>+12,.2f}   {pnl_arrow} {abs(day_pct):.2f}%

  Gross Exposure      ${gross_exp:>12,.2f}
  Cash                ${cash:>12,.2f}
  Leverage            {leverage:>11.2f}x
  Unrealized (total)  ${total_unreal:>+12,.2f}

  HOLDINGS  (sorted by position size)
  ─────────────────────────────────────────────────────────────
  {'Sym':<5}  {'Shares':>5}    {'Mkt Value':>11}  {'Wt%':>5}  {'Day%':>7}  {'Entry%':>7}  {'Day P&L':>10}
  {'─'*66}
{hold_rows}
  AI ANALYST BRIEF
  ─────────────────────────────────────────────────────────────
  {ai_brief.replace(chr(10), chr(10)+'  ')}

══════════════════════════════════════════════════════════════════
  TheEyeBeta · ZINC INVESTMENTS paper stack · 4× leveraged
══════════════════════════════════════════════════════════════════
"""

    subject = (
        f"ZINC INVESTMENTS EOD {date_str.split(',')[0]}  |  "
        f"NAV ${equity:,.0f}  {pnl_arrow} {day_sign}{day_pct:.2f}%"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(plain, "plain"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)

    print(f"EOD email sent → {EMAIL_TO}  |  {subject}")


# ── Order seeder ───────────────────────────────────────────────────────────────

def seed_orders() -> None:
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
                  gen_random_uuid(), %s, %s, %s, %s,
                  %s, 'market', %s, 'day', %s,
                  %s, %s, %s, now(), now()
                )
                ON CONFLICT (client_order_id) DO NOTHING
                """,
                (
                    o["client_order_id"], o["id"], PORTFOLIO_ID, instrument_id,
                    o["side"], float(o["qty"]), o["status"],
                    o.get("submitted_at"),
                    float(o.get("filled_qty") or 0),
                    float(o.get("filled_avg_price") or 0) or None,
                ),
            )
            inserted += 1
            print(f"  ✓ {sym:<6} {o['side']} {o['qty']} — {o['status']}")
        conn.commit()
    print(f"Seeded {inserted} orders into theeyebeta.orders")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])
    if "--seed" in args:
        seed_orders()
    else:
        snap = take_snapshot()
        if "--eod" in args:
            send_eod_email(snap)
