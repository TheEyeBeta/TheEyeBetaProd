# STATUS: scaffolded, not deployed. Pending: deploy unit + gRPC infra.
"""Guard-service entrypoint — gRPC on 7040 and HTTP bridge on 8005."""

from __future__ import annotations

from dotenv import load_dotenv

from guard_service.app import main

load_dotenv()

if __name__ == "__main__":
    main()
