"""Validation helpers for the Snapshot contract."""

from __future__ import annotations

from pydantic import ValidationError

from zinc_schemas.snapshot import Snapshot


class SnapshotValidationError(Exception):
    """Raised when a dict fails Snapshot validation.

    Wraps :class:`pydantic.ValidationError` with a single string message
    so callers don't need to import pydantic directly.
    """


def validate_snapshot(d: dict) -> Snapshot:
    """Validate a raw dict against the Snapshot Pydantic model.

    Args:
        d: Parsed JSON dictionary to validate.

    Returns:
        A fully-validated :class:`Snapshot` instance.

    Raises:
        SnapshotValidationError: If any field fails validation.
    """
    try:
        return Snapshot.model_validate(d)
    except ValidationError as exc:
        raise SnapshotValidationError(str(exc)) from exc
