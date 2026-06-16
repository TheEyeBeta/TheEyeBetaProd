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


# ── HTML email builder ─────────────────────────────────────────────────────────

def _color(val: float, positive: str = "#22c55e", negative: str = "#ef4444") -> str:
    return positive if val >= 0 else negative


def _arrow(val: float) -> str:
    return "▲" if val >= 0 else "▼"


def _holding_rows_html(positions: list[dict]) -> str:
    rows = ""
    for i, p in enumerate(positions):
        bg = "#1a1f2e" if i % 2 == 0 else "#141824"
        day_col  = _color(p["day_pct"])
        tot_col  = _color(p["unrealized_pct"])
        rows += f"""
        <tr style="background:{bg};">
          <td style="padding:12px 16px;font-weight:700;font-size:15px;color:#e2e8f0;letter-spacing:0.5px;">{p['symbol']}</td>
          <td style="padding:12px 8px;font-size:13px;color:#94a3b8;text-align:right;">{p['qty']:.0f}</td>
          <td style="padding:12px 8px;font-size:14px;color:#e2e8f0;text-align:right;font-weight:600;">${p['market_value']:,.0f}</td>
          <td style="padding:12px 8px;font-size:13px;color:#64748b;text-align:right;">{p['weight_pct']:.1f}%</td>
          <td style="padding:12px 16px;font-size:14px;color:{day_col};text-align:right;font-weight:700;">{_arrow(p['day_pct'])} {abs(p['day_pct']):.2f}%</td>
          <td style="padding:12px 16px;font-size:13px;color:{tot_col};text-align:right;">{_arrow(p['unrealized_pct'])} {abs(p['unrealized_pct']):.2f}%</td>
        </tr>"""
    return rows


def _build_html(snap: dict, ai_brief: str) -> str:
    date_str    = datetime.now(timezone.utc).strftime("%A, %b %d %Y")
    equity      = snap["equity"]
    last_equity = snap["last_equity"]
    day_pnl     = snap["day_pnl"]
    day_pct     = snap["day_pct"]
    leverage    = snap["leverage"]
    gross_exp   = snap["market_value"]
    cash        = snap["cash"]
    total_unreal = snap["unrealized_pnl"]
    positions   = sorted(snap["positions"], key=lambda x: x["market_value"], reverse=True)

    day_col   = _color(day_pnl)
    unreal_col = _color(total_unreal)
    day_sign  = "+" if day_pnl >= 0 else ""
    pnl_arrow = _arrow(day_pnl)

    holding_rows = _holding_rows_html(positions)

    no_pos_msg = ""
    if not positions:
        no_pos_msg = """
        <tr><td colspan="6" style="padding:20px;text-align:center;color:#64748b;font-size:13px;">
          Orders pending — positions will appear after market open
        </td></tr>"""

    ai_paragraphs = "".join(
        f'<p style="margin:0 0 10px;line-height:1.6;color:#cbd5e1;">{line}</p>'
        for line in ai_brief.split("\n") if line.strip()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZINC INVESTMENTS EOD</title></head>
<body style="margin:0;padding:0;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0b0f1a;">
<tr><td align="center" style="padding:20px 12px 32px;">
<table width="100%" style="max-width:600px;" cellpadding="0" cellspacing="0">

  <!-- HEADER -->
  <tr><td style="background:linear-gradient(135deg,#1e3a5f 0%,#0f2040 100%);border-radius:16px 16px 0 0;padding:28px 24px 22px;">
    <p style="margin:0 0 4px;font-size:11px;letter-spacing:3px;color:#64a0d4;text-transform:uppercase;font-weight:600;">End of Day Report</p>
    <h1 style="margin:0 0 6px;font-size:26px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">ZINC INVESTMENTS</h1>
    <p style="margin:0;font-size:13px;color:#8fb3d0;">{date_str} &nbsp;·&nbsp; Paper Trading &nbsp;·&nbsp; 4× Leveraged</p>
  </td></tr>

  <!-- NAV HERO -->
  <tr><td style="background:#111827;padding:24px 24px 20px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <p style="margin:0 0 6px;font-size:11px;letter-spacing:2px;color:#64748b;text-transform:uppercase;">Fund NAV</p>
    <p style="margin:0 0 8px;font-size:42px;font-weight:800;color:#f1f5f9;letter-spacing:-1px;">${equity:,.2f}</p>
    <p style="margin:0;font-size:18px;font-weight:700;color:{day_col};">
      {pnl_arrow} {day_sign}${abs(day_pnl):,.2f} &nbsp; ({day_sign}{day_pct:.2f}%) today
    </p>
  </td></tr>

  <!-- STATS ROW -->
  <tr><td style="background:#111827;padding:0 24px 24px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td width="33%" style="background:#0f172a;border-radius:12px;padding:16px;margin-right:8px;">
        <p style="margin:0 0 4px;font-size:10px;letter-spacing:2px;color:#64748b;text-transform:uppercase;">Leverage</p>
        <p style="margin:0;font-size:22px;font-weight:800;color:#f59e0b;">{leverage:.2f}×</p>
      </td>
      <td width="4%"></td>
      <td width="33%" style="background:#0f172a;border-radius:12px;padding:16px;">
        <p style="margin:0 0 4px;font-size:10px;letter-spacing:2px;color:#64748b;text-transform:uppercase;">Gross Exposure</p>
        <p style="margin:0;font-size:18px;font-weight:700;color:#e2e8f0;">${gross_exp:,.0f}</p>
      </td>
      <td width="4%"></td>
      <td width="33%" style="background:#0f172a;border-radius:12px;padding:16px;">
        <p style="margin:0 0 4px;font-size:10px;letter-spacing:2px;color:#64748b;text-transform:uppercase;">Total P&amp;L</p>
        <p style="margin:0;font-size:18px;font-weight:700;color:{unreal_col};">{_arrow(total_unreal)} ${abs(total_unreal):,.0f}</p>
      </td>
    </tr>
    </table>
  </td></tr>

  <!-- SECONDARY STATS -->
  <tr><td style="background:#111827;padding:0 24px 24px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-top:1px solid #1e293b;padding-top:16px;">
    <tr>
      <td style="padding:6px 0;font-size:13px;color:#94a3b8;">Yesterday Close</td>
      <td style="padding:6px 0;font-size:13px;color:#e2e8f0;text-align:right;font-weight:600;">${last_equity:,.2f}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;font-size:13px;color:#94a3b8;">Cash</td>
      <td style="padding:6px 0;font-size:13px;color:#e2e8f0;text-align:right;font-weight:600;">${cash:,.2f}</td>
    </tr>
    <tr>
      <td style="padding:6px 0;font-size:13px;color:#94a3b8;">Positions</td>
      <td style="padding:6px 0;font-size:13px;color:#e2e8f0;text-align:right;font-weight:600;">{len(positions)}</td>
    </tr>
    </table>
  </td></tr>

  <!-- HOLDINGS HEADER -->
  <tr><td style="background:#0f172a;padding:16px 24px 12px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <p style="margin:0;font-size:11px;letter-spacing:3px;color:#64748b;text-transform:uppercase;font-weight:600;">Holdings</p>
  </td></tr>

  <!-- HOLDINGS TABLE -->
  <tr><td style="border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr style="background:#0d1220;">
        <th style="padding:8px 16px;font-size:10px;letter-spacing:1px;color:#475569;text-align:left;font-weight:600;text-transform:uppercase;">Symbol</th>
        <th style="padding:8px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;font-weight:600;text-transform:uppercase;">Shares</th>
        <th style="padding:8px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;font-weight:600;text-transform:uppercase;">Value</th>
        <th style="padding:8px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;font-weight:600;text-transform:uppercase;">Wt</th>
        <th style="padding:8px 16px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;font-weight:600;text-transform:uppercase;">Today</th>
        <th style="padding:8px 16px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;font-weight:600;text-transform:uppercase;">Total</th>
      </tr>
      {holding_rows}{no_pos_msg}
    </table>
  </td></tr>

  <!-- AI BRIEF -->
  <tr><td style="background:#111827;padding:24px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <p style="margin:0 0 14px;font-size:11px;letter-spacing:3px;color:#64748b;text-transform:uppercase;font-weight:600;">AI Analyst Brief</p>
    <div style="background:#0f172a;border-left:3px solid #3b82f6;border-radius:0 8px 8px 0;padding:16px 18px;">
      {ai_paragraphs}
    </div>
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="background:#0a0e1a;border-radius:0 0 16px 16px;padding:20px 24px;border:1px solid #1e293b;border-top:none;text-align:center;">
    <p style="margin:0;font-size:11px;color:#334155;">TheEyeBeta &nbsp;·&nbsp; ZINC INVESTMENTS &nbsp;·&nbsp; Paper Trading Stack</p>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


# ── EOD email ──────────────────────────────────────────────────────────────────

def send_eod_email(snap: dict) -> None:
    date_str  = datetime.now(timezone.utc).strftime("%A, %b %d %Y")
    day_pnl   = snap["day_pnl"]
    day_pct   = snap["day_pct"]
    equity    = snap["equity"]
    day_sign  = "+" if day_pnl >= 0 else ""
    pnl_arrow = _arrow(day_pnl)

    ai_brief = generate_ai_brief(snap)
    html     = _build_html(snap, ai_brief)

    subject = f"ZINC  {pnl_arrow} {day_sign}{day_pct:.2f}%  ·  NAV ${equity:,.0f}  ·  {date_str}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html"))

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
