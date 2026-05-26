"""Compliance rule registry."""

from __future__ import annotations

from compliance_service.rules.aml_structuring import AmlStructuringRule
from compliance_service.rules.base import ComplianceRule
from compliance_service.rules.mandate_constraints import MandateConstraintsRule
from compliance_service.rules.pdt_rule import PdtRule
from compliance_service.rules.restricted_list import RestrictedListRule
from compliance_service.rules.wash_sale import WashSaleRule

DEFAULT_RULES: list[ComplianceRule] = [
    RestrictedListRule(),
    MandateConstraintsRule(),
    WashSaleRule(),
    PdtRule(),
    AmlStructuringRule(),
]

__all__ = [
    "AmlStructuringRule",
    "DEFAULT_RULES",
    "MandateConstraintsRule",
    "PdtRule",
    "RestrictedListRule",
    "WashSaleRule",
]
