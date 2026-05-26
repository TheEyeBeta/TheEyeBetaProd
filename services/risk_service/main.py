"""Risk-service entrypoint — gRPC on 7060 and HTTP bridge on 8007."""

from __future__ import annotations

from dotenv import load_dotenv

from risk_service.app import main

load_dotenv()

if __name__ == "__main__":
    main()
