"""Intelligence layer control gaps and catalogs."""

from __future__ import annotations

from dataclasses import dataclass

BRIEFING_GENERATION_GAP = "Briefings stored in admin_briefings; full PDF pipeline not wired."
BACKTEST_CANCEL_GAP = "Cancel updates DB status; backtest-engine has no cooperative cancel API."
BACKTEST_RETRY_GAP = "Retry re-enqueues via POST /backtest/run; prior run row retained."
AGENT_CONFIG_FILE_GAP = "Constitution rollback writes file under repo_root; runtime hot-reload not guaranteed."


@dataclass(frozen=True, slots=True)
class IntelligenceControlGap:
    action: str
    reason: str


CONFIG_PATCH_GAP = IntelligenceControlGap(
    action="patch_agent_config",
    reason="Only model_default and model_fallback are patchable via admin API.",
)

ROLLBACK_PROPOSAL_GAP = IntelligenceControlGap(
    action="rollback_proposal",
    reason="Rollback sets status to pending; applied git changes are not reverted automatically.",
)

REPORT_REGENERATE_GAP = IntelligenceControlGap(
    action="regenerate_report",
    reason="Regenerate marks briefing pending; external report renderer not in admin-service.",
)
