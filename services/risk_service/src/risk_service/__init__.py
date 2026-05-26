"""Risk-service package."""

from risk_service.models import RiskOutcome

__all__ = ["OrderRiskValidator", "RiskOutcome"]


def __getattr__(name: str) -> object:
    """Lazy import validator (requires zinc_native extension)."""
    if name == "OrderRiskValidator":
        from risk_service.validator import OrderRiskValidator

        return OrderRiskValidator
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
