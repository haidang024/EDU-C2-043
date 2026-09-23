"""EscalationGuidanceNode — maps documented case indicators to configured escalation references."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json

# Reference mapping: event_type → institutional escalation guidance entry
# These are static references only — the agent does NOT autonomously escalate.
_ESCALATION_REFERENCE_MAP: dict[str, dict] = {
    "academic_concern": {
        "guidance_ref": "EDU-ESC-001",
        "title": "Academic Support Escalation Pathway",
        "description": "Refer to academic support coordinator per institutional policy §4.2",
        "policy_source": "Student Support Policy §4.2",
    },
    "welfare_concern": {
        "guidance_ref": "EDU-ESC-002",
        "title": "Wellbeing and Welfare Referral",
        "description": "Contact student wellbeing team; counselor decision on referral urgency",
        "policy_source": "Student Welfare Framework §7.1",
    },
    "attendance_concern": {
        "guidance_ref": "EDU-ESC-003",
        "title": "Attendance Monitoring Protocol",
        "description": "Escalate to head of year per attendance threshold policy §2.4",
        "policy_source": "Attendance Policy §2.4",
    },
    "disability_support": {
        "guidance_ref": "EDU-ESC-004",
        "title": "Disability and Access Support Referral",
        "description": "Refer to disability support services; counselor confirms need",
        "policy_source": "Disability Support Guidelines §3.1",
    },
    "mental_health_concern": {
        "guidance_ref": "EDU-ESC-005",
        "title": "Mental Health Support Referral",
        "description": "Contact student mental health team; counselor determines referral pathway",
        "policy_source": "Mental Health Support Policy §5.3",
    },
}

_GAP_ENTRY = {
    "guidance_ref": "[no institutional reference]",
    "title": "No Approved Guidance Available",
    "description": "No configured escalation reference for this indicator — counselor judgment required",
    "policy_source": "[none]",
}


class EscalationGuidanceNode(FunctionNode):
    """Inner node: maps documented case indicators to configured institutional escalation references.

    Presents references as counselor decision support only.
    Does NOT autonomously escalate, contact parties, or determine urgency/eligibility.
    Marks gaps explicitly when approved guidance is unavailable for an indicator.
    """

    # Inner DomainWorkflowGraph nodes must be ANONYMOUS (trust-trap anti-pattern prevention)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Map case history themes to institutional escalation guidance references."""
        themes = from_json(state.get("support_themes_json"), default=[])
        coverage = state.get("retrieval_coverage", "empty")

        if not isinstance(themes, list):
            themes = []

        guidance_entries: list[dict] = []
        matched_refs: list[str] = []
        gap_themes: list[str] = []

        for theme_entry in themes:
            theme_key = theme_entry.get("theme", "")
            if not theme_key or theme_key.startswith("["):
                continue  # skip placeholder entries

            if theme_key in _ESCALATION_REFERENCE_MAP:
                ref = dict(_ESCALATION_REFERENCE_MAP[theme_key])
                ref["matched_theme"] = theme_key
                ref["occurrence_count"] = theme_entry.get("occurrence_count", 0)
                ref["note"] = (
                    "Decision support reference only — counselor determines whether " "to act on this guidance."
                )
                guidance_entries.append(ref)
                matched_refs.append(ref["guidance_ref"])
            else:
                gap_entry = dict(_GAP_ENTRY)
                gap_entry["matched_theme"] = theme_key
                gap_entry["occurrence_count"] = theme_entry.get("occurrence_count", 0)
                guidance_entries.append(gap_entry)
                gap_themes.append(theme_key)

        if not guidance_entries:
            guidance_entries = [
                {
                    "guidance_ref": "[none]",
                    "title": "No Indicators Found",
                    "description": "No case indicators identified — no escalation references applicable",
                    "policy_source": "[none]",
                    "matched_theme": "[none]",
                    "occurrence_count": 0,
                    "note": "Insufficient history for guidance mapping.",
                }
            ]

        emit_trace_event(
            "EscalationGuidanceNode_guidance_assembled",
            {
                "total_entries": len(guidance_entries),
                "matched_ref_count": len(matched_refs),
                "gap_theme_count": len(gap_themes),
                "coverage": coverage,
            },
            state,
        )

        return {
            "escalation_guidance_json": to_json(guidance_entries),
            "status": AgentStatus.SUCCESS.value,
        }
