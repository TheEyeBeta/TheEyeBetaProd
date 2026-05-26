"""Load recorded VCR cassette payloads for httpx-based adapter tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def load_cassette(name: str) -> dict[str, Any]:
    """Parse a VCR YAML cassette from ``tests/cassettes/``."""
    path = CASSETTE_DIR / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def cassette_response(name: str, *, interaction: int = 0) -> tuple[int, str]:
    """Return HTTP status code and body string for a cassette interaction."""
    data = load_cassette(name)
    response = data["interactions"][interaction]["response"]
    status = int(response["status"]["code"])
    body = response["body"]["string"]
    if isinstance(body, dict):
        return status, json.dumps(body)
    return status, str(body).strip()
