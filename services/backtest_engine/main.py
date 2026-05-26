"""Backtest engine entrypoint — FastAPI on 127.0.0.1:7100."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    """Run uvicorn when executed as a module."""
    import uvicorn

    from backtest_engine.app import create_app
    from backtest_engine.settings import Settings

    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
