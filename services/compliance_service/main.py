"""Compliance-service entrypoint — gRPC on 7070 and HTTP bridge on 8008."""

from __future__ import annotations

from dotenv import load_dotenv

from compliance_service.app import main

load_dotenv()

if __name__ == "__main__":
    main()
