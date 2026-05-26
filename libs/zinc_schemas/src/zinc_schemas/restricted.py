"""Load restricted-list YAML for compliance checks."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

ListType = Literal["blacklist", "grey_list", "watch_list"]


class RestrictedEntry(BaseModel):
    """One restricted symbol entry."""

    model_config = ConfigDict(extra="ignore")

    symbol: str
    list_type: ListType = "blacklist"
    reason: str = ""


class RestrictedListDocument(BaseModel):
    """Sanctions and insider restriction lists."""

    model_config = ConfigDict(extra="ignore")

    sanctions: list[RestrictedEntry] = Field(default_factory=list)
    insider_restricted: list[RestrictedEntry] = Field(default_factory=list)

    def all_entries(self) -> list[RestrictedEntry]:
        """Return combined sanctions and insider entries."""
        return [*self.sanctions, *self.insider_restricted]

    def lookup(self, symbol: str) -> RestrictedEntry | None:
        """Find an active entry for ``symbol`` (case-insensitive)."""
        key = symbol.upper()
        for entry in self.all_entries():
            if entry.symbol.upper() == key:
                return entry
        return None


@lru_cache(maxsize=4)
def load_restricted_list(path: str | None = None) -> RestrictedListDocument:
    """Load restricted-list YAML from disk or the bundled package file."""
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    else:
        try:
            raw = files("zinc_schemas").joinpath("restricted.yaml").read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError):
            raw = (
                Path(__file__)
                .resolve()
                .parents[2]
                .joinpath("restricted.yaml")
                .read_text(
                    encoding="utf-8",
                )
            )
    data = yaml.safe_load(raw) or {}
    return RestrictedListDocument.model_validate(data)
