# STATUS: scaffolded, not deployed. Pending: deploy unit + LLM wiring.
"""Entry point for rnd-agent."""

from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

from rnd_agent.app import create_app
from rnd_agent.settings import Settings

load_dotenv()


def main() -> None:
    """Run uvicorn bound to loopback on port 7120."""
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
