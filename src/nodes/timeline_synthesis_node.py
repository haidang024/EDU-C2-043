"""TimelineSynthesisNode — synthesizes normalized history into a factual timeline and support themes."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json


def _build_timeline(events: list[dict]) -> list[dict]:
    """Build a chronological timeline from normalized case-history events.

    Returns each event as a timeline entry with source citation.
    Does NOT diagnose, classify a student, infer protected attributes,
    or invent missing facts.
    """
    sorted_events = sorted(events, key=lambda e: e.get("date", ""))
    timeline = []
    for event in sorted_events:
        entry = {
            "date": event.get("date", "[date unknown]"),
            "event_type": event.get("event_type", "unspecified"),
            "summary": event.get("summary", "[no summary available]"),
            "source_id": event.get("source_id", "[source unknown]"),
            "citation_ref": event.get("citation_ref", ""),
        }
        timeline.append(entry)
    return timeline


def _extract_themes(events: list[dict]) -> list[dict]:
    """Identify recurring support themes from case-history events.

    Counts event_type frequency to surface recurring patterns.
    Returns only factual counts — no diagnosis or welfare judgment.
    Missing evidence is marked explicitly rather than inferred.
    """
    theme_counts: dict[str, int] = {}
    for event in events:
        event_type = event.get("event_type", "unspecified")
        theme_counts[event_type] = theme_counts.get(event_type, 0) + 1

    themes = [
        {
            "theme": event_type,
            "occurrence_count": count,
            "note": "Factual occurrence count only — no welfare or diagnostic inference",
        }
        for event_type, count in sorted(theme_counts.items(), key=lambda x: -x[1])
    ]

    if not themes:
        themes = [
            {
                "theme": "[no recurring themes identified]",
                "occurrence_count": 0,
                "note": "Insufficient history to identify themes — marked as missing evidence",
            }
        ]

    return themes


class TimelineSynthesisNode(FunctionNode):
    """Inner node: synthesizes normalized history into a factual timeline and recurring support themes.

    Retains event/source citations and clearly marks missing evidence.
    Does NOT diagnose, classify a student, infer protected attributes, or invent missing facts.
    Produces traceable serializable results and safe partial output.
    """

    # Inner DomainWorkflowGraph nodes must be ANONYMOUS (trust-trap anti-pattern prevention)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Synthesize case history into timeline and support themes."""
        events = from_json(state.get("case_history_json"), default=[])
        coverage = state.get("retrieval_coverage", "empty")

        if coverage == "error" or not isinstance(events, list):
            emit_trace_event(
                "TimelineSynthesisNode_no_history",
                {"coverage": coverage, "event_count": 0},
                state,
            )
            return {
                "timeline_json": to_json([]),
                "support_themes_json": to_json(
                    [{"theme": "[no history available — retrieval failed]", "occurrence_count": 0, "note": ""}]
                ),
                "status": AgentStatus.SUCCESS.value,
            }

        timeline = _build_timeline(events)
        themes = _extract_themes(events)

        emit_trace_event(
            "TimelineSynthesisNode_synthesis_complete",
            {
                "event_count": len(events),
                "timeline_entry_count": len(timeline),
                "theme_count": len(themes),
                "coverage": coverage,
            },
            state,
        )

        return {
            "timeline_json": to_json(timeline),
            "support_themes_json": to_json(themes),
            "status": AgentStatus.SUCCESS.value,
        }
