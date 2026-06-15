# STATUS: scaffolded, not deployed. Pending: deploy unit (live-trading-adjacent; approval req).
"""OMS entrypoint — FastAPI on 127.0.0.1:7080."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    """Run uvicorn when executed as a module."""
    import uvicorn

    from oms.app import create_app
    from oms.settings import Settings

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
