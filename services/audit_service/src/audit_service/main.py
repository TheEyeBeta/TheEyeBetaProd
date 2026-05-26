"""Entry point for the audit-service HTTP process."""

from __future__ import annotations

import uvicorn

from audit_service.app import create_app
from audit_service.settings import Settings


def main() -> None:
    """Run uvicorn bound to loopback on the configured audit port."""
    settings = Settings()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
