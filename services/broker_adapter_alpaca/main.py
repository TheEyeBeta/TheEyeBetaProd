"""Broker-adapter entrypoint — FastAPI on 127.0.0.1:7090."""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    """Run uvicorn when executed as a module."""
    import uvicorn

    from broker_adapter_alpaca.app import create_app
    from broker_adapter_alpaca.live_gate import (
        LiveTradingNotApprovedError,
        assert_live_trading_allowed,
    )
    from broker_adapter_alpaca.settings import Settings

    settings = Settings()
    if settings.mode == "live":
        import asyncio

        asyncio.run(assert_live_trading_allowed(settings.pg_dsn()))

    try:
        uvicorn.run(
            create_app(settings),
            host=settings.host,
            port=settings.port,
            log_level="info",
        )
    except LiveTradingNotApprovedError:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
