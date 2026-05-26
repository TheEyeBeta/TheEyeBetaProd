#!/usr/bin/env python3
"""Provision LiteLLM virtual keys and print sops-ready secret lines.

Usage (llm-gateway healthy on port 7020)::

    export LITELLM_MASTER_KEY=sk-...
    python services/llm_gateway/scripts/provision_virtual_keys.py

Paste the printed ``LITELLM_KEY_*`` lines into ``secrets/prod.enc.yaml`` (via sops).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:7020"

KEY_SPECS: list[dict[str, Any]] = [
    {
        "key_alias": "agent-runtime-executors",
        "secret_env": "LITELLM_KEY_AGENT_RUNTIME_EXECUTORS",
        "max_budget": 50.0,
        "budget_duration": "1d",
        "models": ["claude-sonnet-4-6", "claude-haiku-4-5", "gpt-5"],
    },
    {
        "key_alias": "rnd-agent",
        "secret_env": "LITELLM_KEY_RND_AGENT",
        "max_budget": 5.0,
        "budget_duration": "1d",
        "models": ["gpt-5"],
    },
    {
        "key_alias": "guard-service-classifier",
        "secret_env": "LITELLM_KEY_GUARD_SERVICE_CLASSIFIER",
        "max_budget": 5.0,
        "budget_duration": "1d",
        "models": ["claude-haiku-4-5"],
    },
    {
        "key_alias": "embeddings",
        "secret_env": "LITELLM_KEY_EMBEDDINGS",
        "max_budget": 2.0,
        "budget_duration": "1d",
        "models": ["text-embedding-3-large"],
    },
]


def _base_url() -> str:
    return os.environ.get("LITELLM_PROXY_URL", DEFAULT_BASE_URL).rstrip("/")


def _master_key() -> str:
    key = os.environ.get("LITELLM_MASTER_KEY", "")
    if not key.startswith("sk-"):
        msg = "LITELLM_MASTER_KEY must be set and start with sk-"
        raise SystemExit(msg)
    return key


def _generate_key(client: httpx.Client, spec: dict[str, Any]) -> str:
    payload = {
        "key_alias": spec["key_alias"],
        "max_budget": spec["max_budget"],
        "budget_duration": spec["budget_duration"],
        "models": spec["models"],
        "metadata": {"service": spec["key_alias"], "provisioned_by": "provision_virtual_keys.py"},
    }
    response = client.post("/key/generate", json=payload)
    response.raise_for_status()
    body = response.json()
    token = body.get("key") or body.get("token")
    if not token:
        msg = f"No key returned for {spec['key_alias']}: {json.dumps(body)}"
        raise RuntimeError(msg)
    return str(token)


def main() -> int:
    """Generate all virtual keys and print secret assignments."""
    master = _master_key()
    headers = {"Authorization": f"Bearer {master}", "Content-Type": "application/json"}

    print(f"# LiteLLM proxy: {_base_url()}")
    print("# Add these to secrets/prod.enc.yaml (encrypt with sops):\n")

    with httpx.Client(base_url=_base_url(), headers=headers, timeout=60.0) as client:
        health = client.get("/health/liveliness")
        if health.status_code != 200:
            health = client.get("/health")
        health.raise_for_status()

        for spec in KEY_SPECS:
            token = _generate_key(client, spec)
            print(f"{spec['secret_env']}={token}")

    print("\n# Verify keys in UI: http://127.0.0.1:7020/ui")
    return 0


if __name__ == "__main__":
    sys.exit(main())
