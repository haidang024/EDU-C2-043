"""State — flat TypedDict for EDU-C2-043 Student Support Case History Briefing Agent."""

from __future__ import annotations

import json
from typing import Any

from framework.schemas.agent_state import AgentState


# ─── msgpack-safety helpers (MANDATORY — must be present in every state.py) ───


def to_json(value: Any) -> str:
    """Encode structured value to JSON string before storing in State."""
    return json.dumps(value, ensure_ascii=False)


def from_json(value: str | None, default: Any = None) -> Any:
    """Decode JSON string from State back to structured value."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# ─── State schema ─────────────────────────────────────────────────────────────
# Rules:
#   - ALL fields must be primitives: str, int, float, bool, or None
#   - Structured data (dict, list) → JSON-encode with to_json(); declare field as str
#   - NEVER use: List[dict], dict, list, Optional[dict], Pydantic, dataclass
#   - NEVER store: JWT, API keys, InvocationContext, credentials
#
# Producer/Consumer ownership:
#   validated_input          → PreProcessNode (P) / inner nodes (C)
#   approved_sources_json    → PreProcessNode (P) / HistoryRetrievalNode (C)
#   case_scope_json          → PreProcessNode (P) / HistoryRetrievalNode (C)
#   case_history_json        → HistoryRetrievalNode (P) / TimelineSynthesisNode (C)
#   citations_json           → HistoryRetrievalNode (P) / PostProcessNode (C)
#   retrieval_coverage       → HistoryRetrievalNode (P) / PostProcessNode (C)
#   timeline_json            → TimelineSynthesisNode (P) / CounselorHandoffNode (C)
#   support_themes_json      → TimelineSynthesisNode (P) / CounselorHandoffNode (C)
#   escalation_guidance_json → EscalationGuidanceNode (P) / CounselorHandoffNode (C)
#   hitl_draft_json          → CounselorHandoffNode (P before interrupt) / PostProcessNode (C)
#   review_outcome           → CounselorHandoffNode (P after HITL resume) / PostProcessNode (C)
#   review_notes             → CounselorHandoffNode (P after HITL resume) / PostProcessNode (C)
#   formatted_output         → PostProcessNode outer (P) / API response
#   result                   → DomainWorkflowGraphNode.merge_output (P) / outer PostProcessNode (C)


class State(AgentState):
    """State for EDU-C2-043 Student Support Case History Briefing Agent.

    All structured fields are JSON-encoded strings for msgpack checkpoint safety.
    Shared fields (user_input, status, session_id, node_history, error_log,
    hitl_*, etc.) are inherited from AgentState.
    """

    input_error_message: str | None
    input_error_guidance: list[str]
    # Inner-workflow failure reason, carried as a domain field so the run
    # keeps a valid AgentStatus and still reaches the post-process node.
    workflow_error_message: str | None
    generation_mode: str | None
    provider_error_message: str | None

    # ── Input / Scope ──────────────────────────────────────────────────────────
    # Operator-specified normalized query after pre-process validation
    validated_input: str

    # JSON-encoded list[str] — approved source system IDs configured by operator
    approved_sources_json: str

    # JSON-encoded dict — bounded criteria: student_ref (hashed/anonymized),
    # date_from, date_to, support_category
    case_scope_json: str

    # ── Case History Retrieval ─────────────────────────────────────────────────
    # JSON-encoded list[dict] — normalized case-history events from approved sources
    case_history_json: str

    # JSON-encoded list[dict] — source/event provenance citations
    citations_json: str

    # "partial" | "complete" | "empty" | "error" — retrieval coverage flag
    retrieval_coverage: str
    # Which source answered: "live" when CASE_HISTORY_SERVICE_TOKEN is
    # provisioned, "fixture" when the bundled sample history was used.
    # Operator-facing only — the rendered briefing is identical either way.
    history_source: str | None

    # ── Synthesis ─────────────────────────────────────────────────────────────
    # JSON-encoded list[dict] — chronological timeline of case events with citations
    timeline_json: str

    # JSON-encoded list[dict] — recurring support themes identified from history
    support_themes_json: str

    # ── Escalation Guidance ───────────────────────────────────────────────────
    # JSON-encoded list[dict] — institutional escalation references mapped to
    # documented case indicators; presented as counselor decision support only
    escalation_guidance_json: str

    # ── Human Review (HITL) ───────────────────────────────────────────────────
    # JSON-encoded dict — counselor handoff draft assembled for human review
    hitl_draft_json: str

    # "approved" | "corrected" | "rejected" | "" — outcome from HITL resume
    review_outcome: str

    # Free-text counselor notes from HITL resume (corrections or rejection reason)
    review_notes: str

    # ── Output ────────────────────────────────────────────────────────────────
    # Final human-reviewed counselor handoff briefing content
    formatted_output: str

    # Mapped from inner graph get_output(); consumed by outer PostProcessNode
    result: str
