#!/usr/bin/env bash
# new_agent.sh — scaffold a new agent module inside agent-runtime
#
# Usage: bash scripts/new_agent.sh <agent-name>
# Example: bash scripts/new_agent.sh sentiment-agent
#
# Creates:
#   services/agent-runtime/src/agents/<name_snake>/
#   ├── __init__.py
#   ├── agent.py          (BaseAgent subclass)
#   ├── prompts/
#   │   └── v1_<name>.j2  (Jinja2 prompt template)
#   └── tests/
#       └── test_<name_snake>.py
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${REPO_ROOT}/services/agent-runtime"

# ── Validate ───────────────────────────────────────────────────────────────────
if [[ $# -lt 1 || -z "$1" ]]; then
  echo "Usage: bash scripts/new_agent.sh <agent-name>" >&2
  echo "  e.g. bash scripts/new_agent.sh sentiment-agent" >&2
  exit 1
fi

if [[ ! -d "$RUNTIME_DIR" ]]; then
  echo "✖ services/agent-runtime/ not found." >&2
  echo "  Create it first: bash scripts/new_service.sh agent-runtime" >&2
  exit 1
fi

AGENT_NAME="$1"
AGENT_SNAKE="${AGENT_NAME//-/_}"
AGENT_CLASS="$(echo "$AGENT_SNAKE" | sed 's/_\([a-z]\)/\U\1/g; s/^\([a-z]\)/\U\1/')"
AGENTS_DIR="${RUNTIME_DIR}/src/agents"
AGENT_DIR="${AGENTS_DIR}/${AGENT_SNAKE}"

if [[ -d "$AGENT_DIR" ]]; then
  echo "✖ Agent directory already exists: ${AGENT_DIR}" >&2
  exit 1
fi

echo "▶ Scaffolding agent: ${AGENT_NAME}"

mkdir -p "${AGENT_DIR}/prompts" "${RUNTIME_DIR}/tests"
touch "${AGENTS_DIR}/__init__.py"

# ── agent.py ───────────────────────────────────────────────────────────────────
cat > "${AGENT_DIR}/agent.py" << PY
"""${AGENT_NAME} — implements BaseAgent for [describe what this agent does]."""
from __future__ import annotations

import structlog
from pydantic import BaseModel

from agents.base import BaseAgent, AgentContext, AgentResult

log = structlog.get_logger(__name__)


class ${AGENT_CLASS}Input(BaseModel):
    """Input schema for ${AGENT_CLASS}."""
    # TODO: define input fields


class ${AGENT_CLASS}Output(BaseModel):
    """Output schema for ${AGENT_CLASS}."""
    # TODO: define output fields


class ${AGENT_CLASS}(BaseAgent[${AGENT_CLASS}Input, ${AGENT_CLASS}Output]):
    """${AGENT_CLASS} — [one-line description].

    Implements the BaseAgent interface. Called by agent-runtime on matching NATS subjects.
    """

    subject_pattern: str = "agent.${AGENT_NAME}.>"

    async def run(
        self,
        input_data: ${AGENT_CLASS}Input,
        ctx: AgentContext,
    ) -> AgentResult[${AGENT_CLASS}Output]:
        log.info("${AGENT_NAME}.run", input=input_data.model_dump())
        # TODO: implement agent logic
        raise NotImplementedError("${AGENT_CLASS}.run not yet implemented")
PY

# ── Jinja2 prompt template ─────────────────────────────────────────────────────
cat > "${AGENT_DIR}/prompts/v1_${AGENT_SNAKE}.j2" << 'J2'
{# v1_AGENT_NAME_PLACEHOLDER — prompt template version 1 #}
{# Context object fields are typed in agent.py AgentContext #}

You are a financial research agent. Analyse the provided data and respond in JSON.

## Task
{{ task_description }}

## Data
{{ data | tojson(indent=2) }}

## Instructions
- Be concise and precise.
- Return only valid JSON matching the output schema.
- Do not include explanations outside the JSON.

## Output schema
{{ output_schema | tojson(indent=2) }}
J2
sed -i "s/AGENT_NAME_PLACEHOLDER/${AGENT_NAME}/g" "${AGENT_DIR}/prompts/v1_${AGENT_SNAKE}.j2" 2>/dev/null || \
  sed -i '' "s/AGENT_NAME_PLACEHOLDER/${AGENT_NAME}/g" "${AGENT_DIR}/prompts/v1_${AGENT_SNAKE}.j2"

# ── __init__.py ────────────────────────────────────────────────────────────────
cat > "${AGENT_DIR}/__init__.py" << PY
from .agent import ${AGENT_CLASS}

__all__ = ["${AGENT_CLASS}"]
PY

# ── test stub ──────────────────────────────────────────────────────────────────
cat > "${RUNTIME_DIR}/tests/test_${AGENT_SNAKE}.py" << PY
"""Tests for ${AGENT_NAME}."""
from __future__ import annotations

import pytest

from agents.${AGENT_SNAKE}.agent import ${AGENT_CLASS}, ${AGENT_CLASS}Input


@pytest.mark.unit
class TestGiven${AGENT_CLASS}Agent:
    async def when_run_with_valid_input_then_returns_result(self) -> None:
        agent = ${AGENT_CLASS}()
        inp = ${AGENT_CLASS}Input()  # TODO: fill in required fields
        # TODO: mock llm-gateway + assert output shape
        pytest.skip("not yet implemented")
PY

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "✔ Scaffolded agent: services/agent-runtime/src/agents/${AGENT_SNAKE}/"
echo ""
echo "Next steps:"
echo "  1. Implement ${AGENT_CLASS}Input / ${AGENT_CLASS}Output fields in agent.py"
echo "  2. Implement ${AGENT_CLASS}.run() — call llm-gateway via httpx"
echo "  3. Update prompts/v1_${AGENT_SNAKE}.j2 with your actual prompt"
echo "  4. Register the agent in services/agent-runtime/src/agents/__init__.py"
echo "  5. Add integration test with mocked llm-gateway (respx fixture)"
echo "  6. Update docs/agents.md"
