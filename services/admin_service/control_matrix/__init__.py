"""MASTER_ADMIN control matrix — backend/frontend/edge parity registry."""

from control_matrix.registry import build_control_matrix, summarize_categories
from control_matrix.validation import collect_drift_alerts, validate_matrix_invariants

__all__ = [
    "build_control_matrix",
    "collect_drift_alerts",
    "summarize_categories",
    "validate_matrix_invariants",
]
