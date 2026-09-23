"""CounselorHandoffNode — assembles counselor handoff draft and requires authorized human review."""

from __future__ import annotations

from typing import ClassVar

from langgraph.types import interrupt

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json

# Valid resume outcomes from human reviewer
_VALID_OUTCOMES = {"approved", "corrected", "rejected"}


def _assemble_draft(
    case_scope: dict,
    timeline: list[dict],
    themes: list[dict],
    escalation_guidance: list[dict],
    citations: list[dict],
    coverage: str,
) -> dict:
    """Assemble the counselor handoff draft from synthesized data.

    The draft is factual support material only — it is not a welfare, emergency,
    eligibility, or disciplinary decision. All decisions remain with the human counselor.
    """
    return {
        "agent_id": "EDU-C2-043",
        "document_type": "counselor_handoff_briefing_draft",
        "scope": case_scope,
        "retrieval_coverage": coverage,
        "timeline": timeline,
        "support_themes": themes,
        "escalation_references": escalation_guidance,
        "citations": citations,
        "limitations": [
            "This briefing is human-reviewed support material only.",
            "The agent does not make eligibility, welfare, emergency, or disciplinary decisions.",
            "The agent does not contact students or third parties.",
            "Partial retrieval may mean not all case history is reflected.",
            "Escalation references are decision support — the counselor determines action.",
        ],
        "review_required": True,
    }


class CounselorHandoffNode(FunctionNode):
    """Inner node: assembles counselor handoff briefing and requires authorized human review (HITL).

    Uses LangGraph interrupt() to pause for counselor review before finalizing output.
    Handles approved, corrected, and rejected resume outcomes idempotently.
    The interrupt() call is guarded by state.get('hitl_allowed', True) to prevent
    deadlock in multi-agent pipelines.

    Frames the result as human-reviewed handoff support, never a welfare/emergency/
    disciplinary decision.
    """

    # Inner DomainWorkflowGraph nodes must be ANONYMOUS (trust-trap anti-pattern prevention)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Assemble handoff draft and require human review via HITL interrupt."""
        case_scope = from_json(state.get("case_scope_json"), default={})
        timeline = from_json(state.get("timeline_json"), default=[])
        themes = from_json(state.get("support_themes_json"), default=[])
        escalation_guidance = from_json(state.get("escalation_guidance_json"), default=[])
        citations = from_json(state.get("citations_json"), default=[])
        coverage = state.get("retrieval_coverage", "empty")

        # Check if we are resuming after a human review (hitl_draft already set)
        existing_draft_json = state.get("hitl_draft_json", "")
        review_outcome = state.get("review_outcome", "")

        if existing_draft_json and review_outcome in _VALID_OUTCOMES:
            # Resume path — human review has been completed; process the outcome
            return self._handle_resume(state, review_outcome)

        # First pass — assemble the draft and trigger human review
        draft = _assemble_draft(
            case_scope=case_scope,
            timeline=timeline,
            themes=themes,
            escalation_guidance=escalation_guidance,
            citations=citations,
            coverage=coverage,
        )

        emit_trace_event(
            "CounselorHandoffNode_draft_assembled",
            {
                "timeline_entries": len(timeline),
                "theme_count": len(themes),
                "guidance_count": len(escalation_guidance),
                "citation_count": len(citations),
                "coverage": coverage,
                "review_required": True,
            },
            state,
        )

        # Persist draft before HITL interrupt so resume can access it
        # This dict is written to state before interrupt() suspends execution
        draft_result = {
            "hitl_draft_json": to_json(draft),
            "review_outcome": "",
            "review_notes": "",
            "status": AgentStatus.SUCCESS.value,
        }

        # D6 HITL pattern: guard interrupt() with hitl_allowed to prevent deadlock
        # in multi-agent or automated pipeline contexts
        if state.get("hitl_allowed", True):
            feedback = interrupt(
                {
                    "type": "counselor_review_required",
                    "message": (
                        "Counselor handoff briefing draft assembled. "
                        "Please review and resume with action: "
                        "'approve', 'correct' (include review_notes), or 'reject'."
                    ),
                    "draft": draft_result["hitl_draft_json"],
                    "draft_summary": {
                        "timeline_entries": len(timeline),
                        "themes": [t.get("theme") for t in themes[:5]],
                        "coverage": coverage,
                    },
                }
            )
            action = feedback.get("action", "") if isinstance(feedback, dict) else feedback
            outcome = {
                "approve": "approved",
                "correct": "corrected",
                "reject": "rejected",
            }.get(str(action), "")
            resumed_state = {
                **state,
                **draft_result,
                "review_outcome": outcome,
                "review_notes": (str(feedback.get("review_notes", "")) if isinstance(feedback, dict) else ""),
            }
            return self._handle_resume(resumed_state, outcome)

        # hitl_allowed=False path: return draft without interrupting
        # (non-blocking mode for automated pipelines)
        emit_trace_event(
            "CounselorHandoffNode_hitl_skipped",
            {"hitl_allowed": False, "coverage": coverage},
            state,
        )
        return draft_result

    def _handle_resume(self, state: dict, review_outcome: str) -> dict:
        """Handle post-review resume: approved, corrected, or rejected."""
        review_notes = state.get("review_notes", "")

        if review_outcome == "approved":
            emit_trace_event(
                "CounselorHandoffNode_review_approved",
                {"review_outcome": "approved"},
                state,
            )
            return {
                "hitl_draft_json": state.get("hitl_draft_json", ""),
                "review_outcome": "approved",
                "review_notes": review_notes,
                "status": AgentStatus.SUCCESS.value,
            }

        if review_outcome == "corrected":
            emit_trace_event(
                "CounselorHandoffNode_review_corrected",
                {"review_outcome": "corrected", "has_notes": bool(review_notes)},
                state,
            )
            return {
                "hitl_draft_json": state.get("hitl_draft_json", ""),
                "review_outcome": "corrected",
                "review_notes": review_notes,
                "status": AgentStatus.SUCCESS.value,
            }

        if review_outcome == "rejected":
            emit_trace_event(
                "CounselorHandoffNode_review_rejected",
                {"review_outcome": "rejected", "has_notes": bool(review_notes)},
                state,
            )
            return {
                "hitl_draft_json": state.get("hitl_draft_json", ""),
                "review_outcome": "rejected",
                "review_notes": review_notes,
                "status": AgentStatus.ERROR.value,
                "error_log": [f"CounselorHandoffNode: briefing rejected by counselor. Notes: {review_notes}"],
            }

        # Unknown outcome — treat as error
        emit_trace_event(
            "CounselorHandoffNode_invalid_outcome",
            {"review_outcome": review_outcome},
            state,
        )
        return {
            "status": AgentStatus.ERROR.value,
            "error_log": [f"CounselorHandoffNode: unknown review outcome: {review_outcome!r}"],
        }
