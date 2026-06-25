"""Bounded, sanitized journal/log handling."""

from __future__ import annotations

import re

MAX_LOG_LINES = 100
MAX_LINE_LENGTH = 4000

_SECRET_PATTERN = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|authorization|bearer)\s*[:=]\s*\S+",
)
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def sanitize_log_line(line: str) -> str:
    """Redact secrets and trim overly long journal lines."""
    cleaned = _ANSI_PATTERN.sub("", line).strip()
    cleaned = _SECRET_PATTERN.sub(r"\1=***", cleaned)
    if len(cleaned) > MAX_LINE_LENGTH:
        return cleaned[: MAX_LINE_LENGTH - 3] + "..."
    return cleaned


def sanitize_log_lines(lines: list[str], *, limit: int = MAX_LOG_LINES) -> list[str]:
    """Return bounded sanitized log lines."""
    capped = lines[:limit]
    return [sanitize_log_line(line) for line in capped if line.strip()]
