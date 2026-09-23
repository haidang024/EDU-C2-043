"""PostProcessNode — formats final traceable counselor handoff briefing for EDU-C2-043."""

from __future__ import annotations

import re
from typing import ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event
from src.services.error_presenter import present
from src.services.llm_runtime import provider_metadata, request_advisory

from src.schemas.state import from_json

# Prohibited decision framing patterns — the briefing must not contain these
_DECISION_PATTERNS = [
    re.compile(r"\b(is eligible|is not eligible|must be disciplined|requires emergency)\b", re.I),
    re.compile(r"\b(we recommend disciplinary|student must|student should be)\b", re.I),
]


def _format_briefing(
    draft: dict,
    review_outcome: str,
    review_notes: str,
    citations: list[dict],
    coverage: str,
) -> str:
    """Format the reviewed draft into a structured counselor handoff briefing string.

    Includes timeline summary, themes, escalation references, review disposition,
    provenance citations, limitations, and partial-result messaging.
    """
    lines: list[str] = []
    lines.append("# EDU-C2-043 — Counselor Handoff Briefing")
    lines.append("")
    lines.append(
        "**NOTICE: This document is human-reviewed decision support only. "
        "It is NOT an eligibility, welfare, emergency, or disciplinary decision.**"
    )
    lines.append("")

    # Review disposition
    lines.append(f"## Review Disposition: {review_outcome.upper() or 'N/A'}")
    if review_notes:
        lines.append(f"**Counselor Notes:** {review_notes}")
    lines.append("")

    # Coverage notice
    if coverage != "complete":
        lines.append(
            f"**Coverage Notice:** Retrieval coverage is '{coverage}'. "
            "Some case history may not be reflected in this briefing."
        )
        lines.append("")

    # Timeline
    timeline = draft.get("timeline", [])
    lines.append("## Case History Timeline")
    if timeline:
        for entry in timeline:
            lines.append(
                f"- **{entry.get('date', '[date unknown]')}** | "
                f"{entry.get('event_type', 'event')} | "
                f"{entry.get('summary', '[no summary]')} "
                f"[Source: {entry.get('source_id', 'unknown')}]"
            )
    else:
        lines.append("*No timeline events available.*")
    lines.append("")

    # Support themes
    themes = draft.get("support_themes", [])
    lines.append("## Recurring Support Themes")
    if themes:
        for theme_entry in themes:
            if not theme_entry.get("theme", "").startswith("["):
                lines.append(f"- {theme_entry['theme']} " f"(occurrences: {theme_entry.get('occurrence_count', 0)})")
    else:
        lines.append("*No themes identified.*")
    lines.append("")

    # Escalation references
    guidance_entries = draft.get("escalation_references", [])
    lines.append("## Escalation Guidance References (Decision Support Only)")
    for entry in guidance_entries:
        if not entry.get("guidance_ref", "").startswith("[none"):
            lines.append(
                f"- [{entry.get('guidance_ref')}] {entry.get('title')} — "
                f"{entry.get('description')} (Policy: {entry.get('policy_source', '[unknown]')})"
            )
    lines.append("")

    # Citations / provenance
    lines.append("## Provenance Citations")
    if citations:
        for cit in citations:
            lines.append(
                f"- {cit.get('citation_ref', '[ref]')}: "
                f"{cit.get('source_id', '[source]')} — {cit.get('description', '')}"
            )
    else:
        lines.append("*No citations available.*")
    lines.append("")

    # Limitations
    lines.append("## Limitations")
    for limitation in draft.get("limitations", []):
        lines.append(f"- {limitation}")
    lines.append("")

    return "\n".join(lines)


class PostProcessNode(FunctionNode):
    """Outer post-process node: formats final handoff briefing with full provenance.

    Preserves operator-verifiable citations and does not expose raw restricted records.
    Applies domain output validation via _extra_security_gate_output().
    """

    # Outer post-process must be VERIFIED_EXTERNAL (Cat 2 boundary rule)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict | None = None) -> None:
        super().__init__()
        self._config: dict = config or {}
        self._llm: object | None = self._config.get("llm")

    def _extra_security_gate_output(self, result: dict) -> dict:
        """S-3 domain extension: verify formatted_output contains no prohibited decision framing."""
        output = result.get("formatted_output", "")
        for pattern in _DECISION_PATTERNS:
            if pattern.search(output):
                raise SecurityViolationError("PostProcessNode: formatted_output contains prohibited decision framing")
        return result

    def execute(self, state: dict) -> dict:
        if state.get("input_error_message"):
            message = str(state["input_error_message"])
            return {
                "status": AgentStatus.SUCCESS.value,
                "result": message,
                "formatted_output": message,
            }

        # Inner workflow failed (e.g. an unavailable credential or connector).
        # Report it on a SUCCESS envelope: the Marketplace runner only forwards
        # `output` when status == "success", so status=error would leave the
        # caller with no reason at all.
        if state.get("workflow_error_message"):
            # present() re-classifies defensively: workflow_error_message is
            # already classified by on_subgraph_error(), but any other writer of
            # this field must not be able to route a raw traceback to the caller.
            message = present(
                str(state["workflow_error_message"]),
                correlation_id=str(state.get("correlation_id", "")),
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "result": message,
                "formatted_output": message,
            }

        request_advisory(
            state,
            "Review the EDU-C2-043 workflow result for completeness.",
            self._llm,
            timeout_s=float(self._config.get("timeout_s", 30.0)),
            max_retry=int(self._config.get("max_retry", 3)),
        )
        metadata = provider_metadata(state)
        """Produce final counselor handoff briefing from reviewed draft."""
        review_outcome = state.get("review_outcome", "")
        review_notes = state.get("review_notes", "")
        citations = from_json(state.get("citations_json"), default=[])
        coverage = state.get("retrieval_coverage", "empty")

        draft = from_json(state.get("hitl_draft_json"), default={})

        # Handle rejection path
        if review_outcome == "rejected":
            rejection_msg = (
                "Counselor handoff briefing rejected during human review. "
                f"Reason: {review_notes or 'not specified'}. "
                "No briefing has been issued. Please re-initiate if needed."
            )
            emit_trace_event(
                "PostProcessNode_briefing_rejected",
                {"review_outcome": "rejected", "has_notes": bool(review_notes)},
                state,
            )
            return {
                "formatted_output": rejection_msg,
                "status": AgentStatus.ERROR.value,
                **metadata,
            }

        if review_outcome not in {"approved", "corrected"}:
            emit_trace_event(
                "PostProcessNode_review_pending",
                {"review_outcome": review_outcome or "pending"},
                state,
            )
            return {
                "formatted_output": (
                    "Counselor handoff briefing is pending authorized human review. "
                    "No reviewed briefing has been issued."
                ),
                "status": AgentStatus.PENDING.value,
                **metadata,
            }

        # Format briefing only after an approved or corrected review outcome.
        formatted = _format_briefing(
            draft=draft,
            review_outcome=review_outcome,
            review_notes=review_notes,
            citations=citations,
            coverage=coverage,
        )

        emit_trace_event(
            "PostProcessNode_briefing_formatted",
            {
                "review_outcome": review_outcome,
                "coverage": coverage,
                "has_citations": bool(citations),
                "output_length": len(formatted),
            },
            state,
        )

        return {
            "formatted_output": formatted,
            "status": AgentStatus.SUCCESS.value,
            **metadata,
        }
