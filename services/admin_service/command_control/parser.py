"""Parse allowlisted command strings — rejects unknown verbs and parameters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from command_control.registry import (
    AGENT_ALIASES,
    COMMANDS_BY_ID,
    SERVICE_ALIASES,
    TIMER_ALIASES,
    WORKER_ALIASES,
    CommandDefinition,
)

_KV_PATTERN = re.compile(r"^([a-zA-Z_][\w-]*)=(.+)$")


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Result of parsing one command line."""

    definition: CommandDefinition
    raw: str
    params: dict[str, str]


def _normalize(raw: str) -> str:
    return " ".join(raw.strip().split())


def _resolve_worker(name: str) -> str:
    key = name.lower()
    if key not in WORKER_ALIASES:
        msg = f"Unknown worker {name!r}; not in allowlist"
        raise ValueError(msg)
    return WORKER_ALIASES[key]


def _parse_flags(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    positional: list[str] = []
    flags: dict[str, str] = {}
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token == "--date" and idx + 1 < len(tokens):
            flags["date"] = tokens[idx + 1]
            idx += 2
            continue
        if token.startswith("--"):
            msg = f"Unsupported flag {token}"
            raise ValueError(msg)
        positional.append(token)
        idx += 1
    return positional, flags


def _parse_kv_tail(tokens: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for token in tokens:
        match = _KV_PATTERN.match(token)
        if not match:
            msg = f"Expected key=value token, got {token!r}"
            raise ValueError(msg)
        params[match.group(1).lower()] = match.group(2)
    return params


def parse_command(raw: str) -> ParsedCommand:
    """Parse ``raw`` into a :class:`ParsedCommand` or raise :class:`ValueError`."""
    text = _normalize(raw)
    if not text:
        msg = "Command is empty"
        raise ValueError(msg)

    upper = text.upper()

    if upper == "EDGE ROUTES CHECK":
        return ParsedCommand(COMMANDS_BY_ID["edge.routes.check"], text, {})

    if upper == "CLOUDFLARE STATUS":
        return ParsedCommand(COMMANDS_BY_ID["cloudflare.status"], text, {})

    if upper == "DATAAPI HEALTH":
        return ParsedCommand(COMMANDS_BY_ID["dataapi.health"], text, {})

    if upper == "TRADING HALT":
        return ParsedCommand(COMMANDS_BY_ID["trading.halt"], text, {})

    if upper.startswith("AUDIT VERIFY"):
        tail = text[len("AUDIT VERIFY") :].strip()
        window = tail.upper() if tail else "24H"
        if not re.fullmatch(r"\d+H", window):
            msg = "AUDIT VERIFY expects window like 24H"
            raise ValueError(msg)
        return ParsedCommand(
            COMMANDS_BY_ID["audit.verify"],
            text,
            {"hours": window[:-1]},
        )

    if upper.startswith("RISK COMPUTE"):
        portfolio = text[len("RISK COMPUTE") :].strip() or "main"
        return ParsedCommand(
            COMMANDS_BY_ID["risk.compute"],
            text,
            {"portfolio_id": portfolio},
        )

    if upper.startswith("BROKER TEST"):
        broker = text[len("BROKER TEST") :].strip() or "alpaca"
        if broker.lower() != "alpaca":
            msg = f"Broker {broker!r} not allowlisted (only alpaca)"
            raise ValueError(msg)
        return ParsedCommand(COMMANDS_BY_ID["broker.test"], text, {"broker": broker.lower()})

    if upper.startswith("BACKTEST RUN"):
        tail = text[len("BACKTEST RUN") :].strip()
        if not tail:
            msg = "BACKTEST RUN requires strategy= and universe= parameters"
            raise ValueError(msg)
        params = _parse_kv_tail(tail.split())
        if "strategy" not in params:
            msg = "Missing strategy= parameter"
            raise ValueError(msg)
        if "universe" not in params:
            params["universe"] = "sp500"
        return ParsedCommand(COMMANDS_BY_ID["backtest.run"], text, params)

    if upper.startswith("AGENT RUN"):
        agent = text[len("AGENT RUN") :].strip()
        if not agent:
            msg = "AGENT RUN requires agent id"
            raise ValueError(msg)
        key = agent.lower()
        if key not in AGENT_ALIASES:
            msg = f"Agent {agent!r} not in allowlist"
            raise ValueError(msg)
        return ParsedCommand(
            COMMANDS_BY_ID["agent.run"],
            text,
            {"agent_id": AGENT_ALIASES[key], "alias": key},
        )

    if upper.startswith("WORKER RUN"):
        tail = text[len("WORKER RUN") :].strip()
        positional, flags = _parse_flags(tail.split())
        if not positional:
            msg = "WORKER RUN requires worker name"
            raise ValueError(msg)
        worker = _resolve_worker(positional[0])
        if flags.get("date", "").lower() == "today":
            flags["date"] = date.today().isoformat()
        return ParsedCommand(
            COMMANDS_BY_ID["worker.run"],
            text,
            {"worker": worker, **flags},
        )

    if upper.startswith("WORKER STOP"):
        name = text[len("WORKER STOP") :].strip()
        if not name:
            msg = "WORKER STOP requires worker name"
            raise ValueError(msg)
        return ParsedCommand(
            COMMANDS_BY_ID["worker.stop"],
            text,
            {"worker": _resolve_worker(name)},
        )

    if upper.startswith("TIMER DISABLE"):
        name = text[len("TIMER DISABLE") :].strip()
        if not name:
            msg = "TIMER DISABLE requires timer name"
            raise ValueError(msg)
        key = name.lower()
        if key not in TIMER_ALIASES:
            msg = f"Timer {name!r} not in allowlist"
            raise ValueError(msg)
        return ParsedCommand(
            COMMANDS_BY_ID["timer.disable"],
            text,
            {"timer": TIMER_ALIASES[key]},
        )

    if upper.startswith("SERVICE RESTART"):
        unit = text[len("SERVICE RESTART") :].strip()
        if not unit:
            msg = "SERVICE RESTART requires unit or service key"
            raise ValueError(msg)
        key = unit.lower()
        if key not in SERVICE_ALIASES:
            msg = f"Service {unit!r} not in allowlist"
            raise ValueError(msg)
        return ParsedCommand(
            COMMANDS_BY_ID["service.restart"],
            text,
            {"service": SERVICE_ALIASES[key]},
        )

    msg = f"Unknown command: {text!r}"
    raise ValueError(msg)


def default_backtest_dates() -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=90)
    return start, end
