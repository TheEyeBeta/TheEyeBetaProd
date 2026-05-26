"""Compliance-service package."""

from compliance_service.models import ComplianceOutcome

__all__ = ["ComplianceEngine", "ComplianceOutcome"]


def __getattr__(name: str) -> object:
    if name == "ComplianceEngine":
        from compliance_service.engine import ComplianceEngine

        return ComplianceEngine
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
