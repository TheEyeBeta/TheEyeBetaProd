"""Compliance control gaps and default rule schema."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_RULES: dict[str, object] = {
    "no_hk_dual_class": False,
    "blocked_markets": [],
    "max_day_trades_5d": 3,
    "aml_small_trade_usd": 10_000.0,
    "aml_small_trade_count": 3,
}

RULE_CATALOG: list[dict[str, str]] = [
    {"rule_id": "restricted_list", "title": "Restricted list", "group": "sanctions"},
    {"rule_id": "mandate_constraints", "title": "Mandate constraints", "group": "mandate"},
    {"rule_id": "wash_sale", "title": "Wash sale", "group": "tax"},
    {"rule_id": "pdt_rule", "title": "Pattern day trader", "group": "regulatory"},
    {"rule_id": "aml_structuring", "title": "AML structuring", "group": "aml"},
]


@dataclass(frozen=True, slots=True)
class ComplianceControlGap:
    action: str
    reason: str


RULE_EDIT_GAP = ComplianceControlGap(
    action="edit_rules",
    reason=(
        "Rule patches persist in admin_compliance_rules only; "
        "compliance_service engine still reads portfolios.mandate until wired."
    ),
)

RESTRICTED_LIST_GAP = ComplianceControlGap(
    action="edit_restricted_list",
    reason="Restricted symbols are loaded from zinc_schemas/restricted.yaml at service start; no admin editor.",
)

LEGAL_HOLD_ENFORCEMENT_GAP = ComplianceControlGap(
    action="legal_hold_enforcement",
    reason=(
        "Legal holds are recorded in admin_legal_holds; "
        "compliance_service and order flow do not enforce holds yet."
    ),
)

OVERRIDE_ENFORCEMENT_GAP = ComplianceControlGap(
    action="override_enforcement",
    reason=(
        "Compliance overrides persist in admin_compliance_overrides; "
        "compliance_service CheckOrder does not consult overrides yet."
    ),
)
