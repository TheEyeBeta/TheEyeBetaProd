"""fund_tracker.py — TheEyeBeta multi-account fund report worker.

Covers ZINC INVESTMENTS (fund), NYSE, and NASDAQ paper sub-accounts.

Run modes:
  python scripts/zinc_fund_tracker.py           — snapshot all 3 accounts, no email
  python scripts/zinc_fund_tracker.py --eod     — EOD report, all accounts
  python scripts/zinc_fund_tracker.py --eow     — End-of-Week report (fire on Fridays)
  python scripts/zinc_fund_tracker.py --eom     — End-of-Month (checks if last trading day)
  python scripts/zinc_fund_tracker.py --eoq     — End-of-Quarter (checks if last trading day)
  python scripts/zinc_fund_tracker.py --eoy     — End-of-Year (checks if last trading day)
  python scripts/zinc_fund_tracker.py --seed    — import open Alpaca orders into DB (zinc)
"""

from __future__ import annotations

import json
import os
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import psycopg

# ── Account registry ───────────────────────────────────────────────────────────

ACCOUNTS: dict[str, dict[str, str]] = {
    "zinc": {
        "key":          os.environ.get("ALPACA_API_KEY_PAPER_ZINC", ""),
        "secret":       os.environ.get("ALPACA_API_SECRET_PAPER_ZINC", ""),
        "portfolio_id": "c40e8400-e29b-41d4-a716-446655440004",
        "display":      "ZINC INVESTMENTS",
        "subtitle":     "Market-cap weighted · 4× leveraged",
        "accent":       "#f59e0b",
    },
    "nyse": {
        "key":          os.environ.get("ALPACA_API_KEY_PAPER_NYSE", ""),
        "secret":       os.environ.get("ALPACA_API_SECRET_PAPER_NYSE", ""),
        "portfolio_id": "d40e8400-e29b-41d4-a716-446655440006",
        "display":      "NYSE",
        "subtitle":     "NYSE-listed individual stocks",
        "accent":       "#3b82f6",
    },
    "nasdaq": {
        "key":          os.environ.get("ALPACA_API_KEY_PAPER_NASDAQ", ""),
        "secret":       os.environ.get("ALPACA_API_SECRET_PAPER_NASDAQ", ""),
        "portfolio_id": "e40e8400-e29b-41d4-a716-446655440008",
        "display":      "NASDAQ",
        "subtitle":     "NASDAQ-listed individual stocks",
        "accent":       "#8b5cf6",
    },
}

INSTRUMENT_IDS: dict[str, int] = {
    "AAPL": 1, "MSFT": 2, "NVDA": 3, "GOOGL": 4,
    "AMD": 43, "AMZN": 50, "AVGO": 62, "META": 324,
    "MU": 346, "TSLA": 468,
}

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "").replace("+psycopg", "")

SMTP_HOST     = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER     = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_TO      = os.environ.get("ZINC_FUND_EMAIL_TO") or os.environ.get("TRASK_ALERT_EMAILS", "")

LITELLM_URL = os.environ.get("LITELLM_PROXY_URL", "http://127.0.0.1:4000")
LITELLM_KEY = os.environ.get("LITELLM_MASTER_KEY", "")
OPENAI_KEY  = os.environ.get("OPENAI_API_KEY", "")

ALPACA_BASE = "https://paper-api.alpaca.markets/v2"

PERIOD_LABELS = {
    "eod": "End of Day",
    "eow": "End of Week",
    "eom": "End of Month",
    "eoq": "End of Quarter",
    "eoy": "End of Year",
}
PERIOD_TRUNC = {
    "eod": "day", "eow": "week", "eom": "month", "eoq": "quarter", "eoy": "year",
}

# ── Alpaca helpers ─────────────────────────────────────────────────────────────

def _alpaca(acct: str, path: str) -> Any:
    cfg = ACCOUNTS[acct]
    req = urllib.request.Request(
        f"{ALPACA_BASE}{path}",
        headers={
            "APCA-API-KEY-ID": cfg["key"],
            "APCA-API-SECRET-KEY": cfg["secret"],
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _is_last_trading_day_of(period: str) -> bool:
    """Return True when the next trading session is in a different period."""
    try:
        clock = _alpaca("zinc", "/clock")
        nxt = datetime.fromisoformat(clock["next_open"])
        now_et = datetime.now(nxt.tzinfo)
        if period == "eom":
            return nxt.month != now_et.month
        if period == "eoq":
            return (nxt.month - 1) // 3 != (now_et.month - 1) // 3
        if period == "eoy":
            return nxt.year != now_et.year
    except Exception:
        pass
    return True  # fire anyway on parse failure


# ── Snapshot ───────────────────────────────────────────────────────────────────

def _snap_account(acct: str) -> dict:
    account   = _alpaca(acct, "/account")
    positions = _alpaca(acct, "/positions")

    equity      = float(account["equity"])
    last_equity = float(account["last_equity"])
    cash        = float(account["cash"])
    market_value = sum(float(p["market_value"]) for p in positions)

    day_pnl  = equity - last_equity
    day_pct  = (day_pnl / last_equity * 100) if last_equity else 0.0
    leverage = (market_value / equity) if equity else 0.0

    pos_data = [
        {
            "symbol":         p["symbol"],
            "qty":            float(p["qty"]),
            "market_value":   float(p["market_value"]),
            "avg_entry":      float(p["avg_entry_price"]),
            "current_price":  float(p["current_price"]),
            "unrealized_pnl": float(p["unrealized_pl"]),
            "unrealized_pct": float(p["unrealized_plpc"]) * 100,
            "day_pnl":        float(p.get("unrealized_intraday_pl") or 0),
            "day_pct":        float(p.get("unrealized_intraday_plpc") or 0) * 100,
            "weight_pct":     (float(p["market_value"]) / market_value * 100) if market_value else 0,
        }
        for p in positions
    ]

    portfolio_id = ACCOUNTS[acct]["portfolio_id"]
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
            (portfolio_id, cash, market_value, equity,
             sum(p["unrealized_pnl"] for p in pos_data),
             len(pos_data), json.dumps(pos_data)),
        )
        conn.commit()

    return {
        "acct": acct,
        "equity": equity, "last_equity": last_equity, "cash": cash,
        "market_value": market_value, "day_pnl": day_pnl, "day_pct": day_pct,
        "leverage": leverage, "positions": pos_data,
        "unrealized_pnl": sum(p["unrealized_pnl"] for p in pos_data),
    }


def _get_period_start_nav(portfolio_id: str, period: str) -> float | None:
    trunc = PERIOD_TRUNC.get(period, "day")
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            cur = conn.execute(
                """
                SELECT total_value FROM theeyebeta.paper_fund_snapshots
                WHERE portfolio_id = %s
                  AND snapshotted_at >= date_trunc(%s, now() AT TIME ZONE 'America/New_York')
                                                    AT TIME ZONE 'America/New_York'
                ORDER BY snapshotted_at ASC LIMIT 1
                """,
                (portfolio_id, trunc),
            )
            row = cur.fetchone()
        return float(row[0]) if row else None
    except Exception:
        return None


def take_all_snapshots() -> list[dict]:
    snaps = []
    for acct in ACCOUNTS:
        try:
            s = _snap_account(acct)
            snaps.append(s)
            print(
                f"  [{acct:<6}] NAV=${s['equity']:,.2f}  "
                f"day={s['day_pnl']:+,.2f} ({s['day_pct']:+.2f}%)  "
                f"leverage={s['leverage']:.1f}×"
            )
        except Exception as exc:
            print(f"  [{acct:<6}] ERROR: {exc}")
    return snaps


# ── AI brief ──────────────────────────────────────────────────────────────────

def generate_ai_brief(snaps: list[dict], period: str) -> str:
    period_label = PERIOD_LABELS.get(period, period.upper())
    lines = []
    for s in snaps:
        cfg = ACCOUNTS[s["acct"]]
        lines.append(
            f"{cfg['display']}: NAV=${s['equity']:,.0f}  "
            f"day {s['day_pnl']:+,.0f} ({s['day_pct']:+.2f}%)  "
            f"leverage {s['leverage']:.2f}×"
        )
        for p in sorted(s["positions"], key=lambda x: abs(x["day_pct"]), reverse=True)[:3]:
            lines.append(f"  {p['symbol']}: day {p['day_pct']:+.2f}%  total {p['unrealized_pct']:+.2f}%")

    prompt = (
        f"You are a concise equity analyst. Write a 4-5 sentence {period_label} brief "
        f"for a paper trading portfolio covering three sub-accounts: ZINC INVESTMENTS "
        f"(top-10 US tech by market cap, 4× leveraged), NYSE (individual NYSE stocks), "
        f"and NASDAQ (individual NASDAQ stocks).\n\n"
        f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        f"Report type: {period_label}\n\n"
        f"Data:\n" + "\n".join(lines) + "\n\n"
        f"Cover: (1) overall combined performance, (2) notable movers, "
        f"(3) leverage and risk note. Be direct, no fluff, no bullet points."
    )

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
                "max_tokens": 250,
                "temperature": 0.4,
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            print(f"  AI brief error ({url}): {exc}")

    return "(AI analyst unavailable)"


# ── HTML builders ──────────────────────────────────────────────────────────────

def _c(val: float, pos: str = "#22c55e", neg: str = "#ef4444") -> str:
    return pos if val >= 0 else neg


def _arr(val: float) -> str:
    return "▲" if val >= 0 else "▼"


def _sign(val: float) -> str:
    return "+" if val >= 0 else ""


def _holdings_rows(positions: list[dict], period_key: str) -> str:
    if not positions:
        return (
            '<tr><td colspan="5" style="padding:18px;text-align:center;'
            'color:#475569;font-size:13px;">No positions — orders pending market open</td></tr>'
        )
    rows = ""
    for i, p in enumerate(sorted(positions, key=lambda x: x["market_value"], reverse=True)):
        bg = "#1a1f2e" if i % 2 == 0 else "#141824"
        dc = _c(p["day_pct"])
        tc = _c(p["unrealized_pct"])
        rows += f"""
        <tr style="background:{bg};">
          <td style="padding:11px 16px;font-weight:700;font-size:14px;color:#e2e8f0;">{p['symbol']}</td>
          <td style="padding:11px 8px;font-size:12px;color:#94a3b8;text-align:right;">{p['qty']:.0f} sh</td>
          <td style="padding:11px 8px;font-size:13px;color:#e2e8f0;text-align:right;font-weight:600;">${p['market_value']:,.0f}</td>
          <td style="padding:11px 8px;font-size:13px;color:{dc};text-align:right;font-weight:700;">{_arr(p['day_pct'])} {abs(p['day_pct']):.2f}%</td>
          <td style="padding:11px 16px;font-size:12px;color:{tc};text-align:right;">{_arr(p['unrealized_pct'])} {abs(p['unrealized_pct']):.2f}%</td>
        </tr>"""
    return rows


def _account_block(s: dict, period: str) -> str:
    cfg     = ACCOUNTS[s["acct"]]
    accent  = cfg["accent"]
    pnl_col = _c(s["day_pnl"])

    period_nav   = _get_period_start_nav(cfg["portfolio_id"], period)
    period_pnl   = (s["equity"] - period_nav) if period_nav else None
    period_pct   = ((period_pnl / period_nav) * 100) if (period_nav and period_nav) else None

    period_row = ""
    if period not in ("eod",) and period_pnl is not None:
        plabel = PERIOD_LABELS.get(period, period.upper()).replace("End of ", "")
        period_row = f"""
        <tr>
          <td style="padding:5px 0;font-size:12px;color:#64748b;">{plabel} P&amp;L</td>
          <td style="padding:5px 0;font-size:13px;font-weight:700;color:{_c(period_pnl)};text-align:right;">
            {_arr(period_pnl)} ${abs(period_pnl):,.0f} &nbsp;({_sign(period_pct)}{period_pct:.2f}%)
          </td>
        </tr>"""

    rows = _holdings_rows(s["positions"], period)

    return f"""
  <!-- {cfg['display']} BLOCK -->
  <tr><td style="padding:8px 24px 0;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#111827;border-radius:12px;overflow:hidden;border:1px solid #1e293b;">
      <!-- account header -->
      <tr><td style="background:{accent}20;border-left:4px solid {accent};padding:14px 18px;">
        <p style="margin:0 0 2px;font-size:16px;font-weight:800;color:#f1f5f9;">{cfg['display']}</p>
        <p style="margin:0;font-size:11px;color:#94a3b8;">{cfg['subtitle']}</p>
      </td></tr>
      <!-- NAV + day -->
      <tr><td style="padding:14px 18px 10px;">
        <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <p style="margin:0 0 3px;font-size:11px;color:#64748b;letter-spacing:1px;text-transform:uppercase;">NAV</p>
            <p style="margin:0;font-size:28px;font-weight:800;color:#f1f5f9;">${s['equity']:,.2f}</p>
          </td>
          <td style="text-align:right;">
            <p style="margin:0 0 3px;font-size:11px;color:#64748b;letter-spacing:1px;text-transform:uppercase;">Today</p>
            <p style="margin:0;font-size:22px;font-weight:700;color:{pnl_col};">
              {_arr(s['day_pnl'])} {_sign(s['day_pnl'])}${abs(s['day_pnl']):,.0f}
            </p>
            <p style="margin:2px 0 0;font-size:14px;font-weight:600;color:{pnl_col};">
              {_sign(s['day_pct'])}{s['day_pct']:.2f}%
            </p>
          </td>
        </tr>
        </table>
      </td></tr>
      <!-- stats -->
      <tr><td style="padding:0 18px 14px;">
        <table width="100%" cellpadding="0" cellspacing="0"
               style="border-top:1px solid #1e293b;padding-top:12px;">
          <tr>
            <td style="padding:4px 0;font-size:12px;color:#64748b;">Leverage</td>
            <td style="padding:4px 0;font-size:13px;color:{accent};text-align:right;font-weight:700;">{s['leverage']:.2f}×</td>
          </tr>
          <tr>
            <td style="padding:4px 0;font-size:12px;color:#64748b;">Gross Exposure</td>
            <td style="padding:4px 0;font-size:13px;color:#e2e8f0;text-align:right;font-weight:600;">${s['market_value']:,.0f}</td>
          </tr>
          <tr>
            <td style="padding:4px 0;font-size:12px;color:#64748b;">Unrealized P&amp;L</td>
            <td style="padding:4px 0;font-size:13px;color:{_c(s['unrealized_pnl'])};text-align:right;font-weight:600;">
              {_sign(s['unrealized_pnl'])}${abs(s['unrealized_pnl']):,.0f}
            </td>
          </tr>
          {period_row}
        </table>
      </td></tr>
      <!-- holdings -->
      <tr><td>
        <table width="100%" cellpadding="0" cellspacing="0">
          <tr style="background:#0d1220;">
            <th style="padding:7px 16px;font-size:10px;letter-spacing:1px;color:#475569;text-align:left;text-transform:uppercase;">Symbol</th>
            <th style="padding:7px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;text-transform:uppercase;">Shares</th>
            <th style="padding:7px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;text-transform:uppercase;">Value</th>
            <th style="padding:7px 8px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;text-transform:uppercase;">Day %</th>
            <th style="padding:7px 16px;font-size:10px;letter-spacing:1px;color:#475569;text-align:right;text-transform:uppercase;">Total %</th>
          </tr>
          {rows}
        </table>
      </td></tr>
    </table>
  </td></tr>"""


def build_html(snaps: list[dict], period: str, ai_brief: str) -> str:
    date_str     = datetime.now(timezone.utc).strftime("%A, %b %d %Y")
    period_label = PERIOD_LABELS.get(period, period.upper())

    total_nav  = sum(s["equity"] for s in snaps)
    total_day  = sum(s["day_pnl"] for s in snaps)
    total_base = sum(s["last_equity"] for s in snaps)
    total_pct  = (total_day / total_base * 100) if total_base else 0.0

    total_col = _c(total_day)

    account_blocks = "".join(_account_block(s, period) for s in snaps)

    ai_paras = "".join(
        f'<p style="margin:0 0 10px;line-height:1.65;color:#cbd5e1;font-size:14px;">{l}</p>'
        for l in ai_brief.split("\n") if l.strip()
    )

    snap_by_acct = {s["acct"]: s for s in snaps}

    def _tile(acct: str, label: str, color: str) -> str:
        s = snap_by_acct.get(acct)
        if s is None:
            return (
                f'<td width="32%" style="background:#0f172a;border-radius:10px;padding:14px 12px;">'
                f'<p style="margin:0 0 3px;font-size:10px;letter-spacing:1px;color:#64748b;text-transform:uppercase;">{label}</p>'
                f'<p style="margin:0;font-size:13px;color:#475569;">unavailable</p></td>'
            )
        return (
            f'<td width="32%" style="background:#0f172a;border-radius:10px;padding:14px 12px;">'
            f'<p style="margin:0 0 3px;font-size:10px;letter-spacing:1px;color:#64748b;text-transform:uppercase;">{label}</p>'
            f'<p style="margin:0;font-size:16px;font-weight:700;color:{color};">${s["equity"]:,.0f}</p>'
            f'<p style="margin:2px 0 0;font-size:12px;color:{_c(s["day_pct"])};">'
            f'{_sign(s["day_pct"])}{s["day_pct"]:.2f}%</p></td>'
        )

    summary_tiles = (
        _tile("zinc", "ZINC", "#f59e0b")
        + '<td width="2%"></td>'
        + _tile("nyse", "NYSE", "#3b82f6")
        + '<td width="2%"></td>'
        + _tile("nasdaq", "NASDAQ", "#8b5cf6")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TheEyeBeta Fund Report</title></head>
<body style="margin:0;padding:0;background:#0b0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0b0f1a;">
<tr><td align="center" style="padding:16px 10px 28px;">
<table width="100%" style="max-width:600px;" cellpadding="0" cellspacing="0">

  <!-- HEADER -->
  <tr><td style="background:linear-gradient(135deg,#1e3a5f,#0f2040);border-radius:16px 16px 0 0;padding:26px 24px 20px;">
    <p style="margin:0 0 3px;font-size:10px;letter-spacing:3px;color:#64a0d4;text-transform:uppercase;font-weight:700;">{period_label} &nbsp;·&nbsp; Paper Trading</p>
    <h1 style="margin:0 0 5px;font-size:24px;font-weight:800;color:#fff;letter-spacing:-0.5px;">TheEyeBeta Portfolio</h1>
    <p style="margin:0;font-size:12px;color:#8fb3d0;">{date_str}</p>
  </td></tr>

  <!-- COMBINED NAV HERO -->
  <tr><td style="background:#111827;padding:22px 24px 18px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <p style="margin:0 0 4px;font-size:10px;letter-spacing:2px;color:#64748b;text-transform:uppercase;">Combined NAV — All 3 Accounts</p>
    <p style="margin:0 0 8px;font-size:40px;font-weight:800;color:#f1f5f9;letter-spacing:-1px;">${total_nav:,.2f}</p>
    <p style="margin:0;font-size:17px;font-weight:700;color:{total_col};">
      {_arr(total_day)} {_sign(total_day)}${abs(total_day):,.2f} &nbsp;({_sign(total_pct)}{total_pct:.2f}%) today
    </p>
  </td></tr>
  <tr><td style="background:#111827;padding:0 24px 20px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;">
    <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      {summary_tiles}
    </tr>
    </table>
  </td></tr>

  <!-- SPACER -->
  <tr><td style="background:#0b0f1a;height:4px;border-left:1px solid #1e293b;border-right:1px solid #1e293b;"></td></tr>

  <!-- ACCOUNT BLOCKS -->
  {account_blocks}

  <!-- AI BRIEF -->
  <tr><td style="padding:8px 24px 0;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#111827;border-radius:12px;border:1px solid #1e293b;overflow:hidden;">
      <tr><td style="padding:16px 18px 4px;">
        <p style="margin:0;font-size:10px;letter-spacing:3px;color:#64748b;text-transform:uppercase;font-weight:700;">AI Analyst Brief</p>
      </td></tr>
      <tr><td style="padding:4px 18px 18px;">
        <div style="border-left:3px solid #3b82f6;padding:14px 16px;background:#0f172a;border-radius:0 8px 8px 0;">
          {ai_paras}
        </div>
      </td></tr>
    </table>
  </td></tr>

  <!-- FOOTER -->
  <tr><td style="padding:8px 24px 0 24px;">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="background:#0a0e1a;border-radius:12px;border:1px solid #1e293b;">
      <tr><td style="padding:16px 20px;text-align:center;">
        <p style="margin:0 0 3px;font-size:11px;color:#334155;">TheEyeBeta &nbsp;·&nbsp; {period_label} &nbsp;·&nbsp; All 3 paper sub-accounts</p>
        <p style="margin:0;font-size:10px;color:#1e293b;">ZINC INVESTMENTS &nbsp;·&nbsp; NYSE &nbsp;·&nbsp; NASDAQ</p>
      </td></tr>
    </table>
  </td></tr>
  <tr><td style="height:20px;"></td></tr>

</table>
</td></tr></table>
</body></html>"""


# ── Send ───────────────────────────────────────────────────────────────────────

def send_report(snaps: list[dict], period: str) -> None:
    period_label = PERIOD_LABELS.get(period, period.upper())
    total_nav  = sum(s["equity"] for s in snaps)
    total_day  = sum(s["day_pnl"] for s in snaps)
    total_base = sum(s["last_equity"] for s in snaps)
    total_pct  = (total_day / total_base * 100) if total_base else 0.0
    date_str   = datetime.now(timezone.utc).strftime("%b %d %Y")

    ai_brief = generate_ai_brief(snaps, period)
    html     = build_html(snaps, period, ai_brief)

    subject = (
        f"TheEyeBeta {period_label} · "
        f"{_arr(total_day)} {_sign(total_pct)}{total_pct:.2f}% · "
        f"${total_nav:,.0f} · {date_str}"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(msg)

    print(f"Report sent [{period.upper()}] → {EMAIL_TO} | {subject}")


# ── Order seeder (zinc only) ───────────────────────────────────────────────────

def seed_orders() -> None:
    orders = _alpaca("zinc", "/orders?status=all&limit=50")
    portfolio_id = ACCOUNTS["zinc"]["portfolio_id"]
    inserted = 0
    with psycopg.connect(DATABASE_URL) as conn:
        for o in orders:
            sym = o["symbol"]
            instrument_id = INSTRUMENT_IDS.get(sym)
            if instrument_id is None:
                continue
            conn.execute(
                """
                INSERT INTO theeyebeta.orders
                  (id, client_order_id, broker_order_id, portfolio_id, instrument_id,
                   side, order_type, qty, time_in_force, status,
                   submitted_at, filled_qty, avg_fill_price, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, 'market', %s, 'day', %s,
                        %s, %s, %s, now(), now())
                ON CONFLICT (client_order_id) DO NOTHING
                """,
                (
                    o["client_order_id"], o["id"], portfolio_id, instrument_id,
                    o["side"], float(o["qty"]), o["status"],
                    o.get("submitted_at"),
                    float(o.get("filled_qty") or 0),
                    float(o.get("filled_avg_price") or 0) or None,
                ),
            )
            inserted += 1
            print(f"  ✓ {sym:<6} {o['side']} {o['qty']} — {o['status']}")
        conn.commit()
    print(f"Seeded {inserted} orders")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = set(sys.argv[1:])

    if "--seed" in args:
        seed_orders()
        sys.exit(0)

    print(f"[{datetime.now(timezone.utc).isoformat()}] Taking snapshots…")
    snaps = take_all_snapshots()

    for period in ("eod", "eow", "eom", "eoq", "eoy"):
        if f"--{period}" not in args:
            continue
        # EOM/EOQ/EOY: only send if today is actually the last trading day
        if period in ("eom", "eoq", "eoy") and not _is_last_trading_day_of(period):
            print(f"  [{period.upper()}] Not last trading day of period — skipping")
            continue
        send_report(snaps, period)
