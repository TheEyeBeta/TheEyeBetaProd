"""Data API service-client bridge for admin-service."""

from dataapi_control.client import DataApiBridge, fetch_dataapi_health

__all__ = ["DataApiBridge", "fetch_dataapi_health"]
