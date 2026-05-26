"""JSON Schema validation for packaged snapshot v1."""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from importlib import resources
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zinc_schemas.snapshot import Snapshot

from jsonschema import Draft202012Validator

SCHEMA_RESOURCE = "snapshot_schema_v1.json"


class SnapshotValidationError(Exception):
    """Raised when a dict fails packaged snapshot v1 validation.

    Attributes:
        path: JSON-pointer-style path segments (e.g. ``('prices', 'AAPL', 'open')``).
    """

    def __init__(self, message: str, *, path: Sequence[str | int] = ()) -> None:
        super().__init__(message)
        self.path: tuple[str | int, ...] = tuple(path)


def _format_path(path: Sequence[str | int]) -> str:
    if not path:
        return "$"
    return "$" + "".join(f"[{p!r}]" if isinstance(p, int) else f".{p}" for p in path)


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    """Load the bundled v1 JSON Schema (cached)."""
    raw = resources.files(__package__).joinpath(SCHEMA_RESOURCE).read_text(encoding="utf-8")
    return json.loads(raw)


def validate_snapshot(d: dict[str, Any]) -> dict[str, Any]:
    """Validate a raw dict against ``snapshot_schema_v1.json``.

    Args:
        d: Parsed JSON dictionary to validate.

    Returns:
        The input dict unchanged when valid.

    Raises:
        SnapshotValidationError: If any field fails validation, with a precise path.
    """
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(d), key=lambda err: list(err.absolute_path))
    if not errors:
        return d

    first = errors[0]
    path = tuple(first.absolute_path)
    location = _format_path(path)
    raise SnapshotValidationError(f"{location}: {first.message}", path=path) from None


def validate_legacy_snapshot(d: dict[str, Any]) -> Snapshot:
    """Validate against the legacy MIC-level :class:`~zinc_schemas.snapshot.Snapshot` model.

    Kept for older on-disk snapshots; prefer :func:`validate_snapshot` for packaged v1.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from zinc_schemas.snapshot import Snapshot  # noqa: PLC0415

    try:
        validated: Snapshot = Snapshot.model_validate(d)
        return validated
    except ValidationError as exc:
        raise SnapshotValidationError(str(exc)) from exc
