"""Read cloudflared and TRUSTED_HOSTS config without exposing secrets."""

from __future__ import annotations

import re
from pathlib import Path

_HOSTNAME_LINE = re.compile(r"^\s*-\s*hostname:\s*(\S+)\s*$")
_SERVICE_LINE = re.compile(r"^\s*service:\s*(\S+)\s*$")
_TUNNEL_ID = re.compile(r"^tunnel:\s*(\S+)\s*$", re.MULTILINE)


def read_text_if_exists(path: Path) -> tuple[str | None, str]:
    """Return (content, status) where status is readable | missing | unreadable."""
    if not path.exists():
        return None, "missing"
    try:
        return path.read_text(encoding="utf-8"), "readable"
    except OSError:
        return None, "unreadable"


def parse_cloudflared_ingress(content: str) -> dict[str, str]:
    """Parse hostname -> service URL from a cloudflared config ingress section."""
    routes: dict[str, str] = {}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        host_match = _HOSTNAME_LINE.match(lines[i])
        if host_match:
            hostname = host_match.group(1)
            j = i + 1
            while j < len(lines) and not _HOSTNAME_LINE.match(lines[j]):
                svc_match = _SERVICE_LINE.match(lines[j])
                if svc_match:
                    routes[hostname] = svc_match.group(1)
                    break
                j += 1
        i += 1
    return routes


def parse_tunnel_id(content: str) -> str | None:
    """Extract tunnel UUID from cloudflared config."""
    match = _TUNNEL_ID.search(content)
    return match.group(1) if match else None


def parse_trusted_hosts_from_env(content: str) -> list[str]:
    """Extract TRUSTED_HOSTS hostnames only — never return other env keys."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("TRUSTED_HOSTS="):
            raw = stripped.split("=", 1)[1].strip().strip('"').strip("'")
            return [h.strip() for h in raw.split(",") if h.strip()]
    return []


def parse_service_url_target(service_url: str) -> tuple[str | None, int | None]:
    """Parse ``http://127.0.0.1:7000`` into host and port."""
    if not service_url:
        return None, None
    match = re.match(r"^https?://([^:/]+):(\d+)\s*$", service_url.strip())
    if not match:
        return None, None
    return match.group(1), int(match.group(2))
