"""HistoryRetrievalNode — retrieves approved case-history events from configured sources."""

from __future__ import annotations

from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json
from src.services.case_history_service import FIXTURE_CREDENTIAL, CaseHistoryService


class HistoryRetrievalNode(FunctionNode):
    """Inner node: retrieves permitted case-history events from approved sources.

    Uses the CaseHistoryService adapter to query only operator-approved source
    systems within the bounded scope. Preserves event provenance (citations)
    and handles no-result and partial-failure states safely.

    Does NOT copy raw provider responses into state — events are normalized
    to the State schema before storage. Does NOT make any student-support or
    escalation decisions.
    """

    # Inner DomainWorkflowGraph nodes must be ANONYMOUS (trust-trap anti-pattern prevention)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Retrieve case-history events from approved sources within bounded scope."""
        ctx = InvocationContext.from_state(state)
        case_scope = from_json(state.get("case_scope_json"), default={})
        approved_sources = from_json(state.get("approved_sources_json"), default=[])

        if not approved_sources or not case_scope:
            emit_trace_event(
                "HistoryRetrievalNode_precondition_failed",
                {"error": "missing_scope_or_sources"},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["HistoryRetrievalNode: missing case scope or approved sources"],
            }

        # Agent secret for case-history service authentication.
        # Declared in config/agent.yaml under requires.secrets. When it is not
        # provisioned the node falls back to the bundled fixture history rather
        # than failing the run, so a deployment without the connector still
        # produces a complete briefing. `history_source` records which path ran
        # so an operator can tell fixture-backed briefings from live ones.
        try:
            service_credential = ctx.secrets.require("CASE_HISTORY_SERVICE_TOKEN")
            history_source = "live"
        except Exception:
            emit_trace_event(
                "HistoryRetrievalNode_credential_missing",
                {"history_source": "fixture"},
                state,
            )
            service_credential = FIXTURE_CREDENTIAL
            history_source = "fixture"

        service = CaseHistoryService(credential=service_credential)

        all_events: list[dict] = []
        all_citations: list[dict] = []
        failed_sources: list[str] = []

        for source_id in approved_sources:
            try:
                result = service.fetch_events(
                    source_id=source_id,
                    student_ref=case_scope.get("student_ref", ""),
                    date_from=case_scope.get("date_from", ""),
                    date_to=case_scope.get("date_to", ""),
                    support_category=case_scope.get("support_category", "general"),
                )
                all_events.extend(result.get("events", []))
                all_citations.extend(result.get("citations", []))
            except Exception as exc:  # noqa: BLE001
                failed_sources.append(source_id)
                emit_trace_event(
                    "HistoryRetrievalNode_source_error",
                    {"source_id": source_id, "error_type": type(exc).__name__},
                    state,
                )

        # Determine retrieval coverage
        if not approved_sources:
            coverage = "empty"
        elif failed_sources and not all_events:
            coverage = "error"
        elif failed_sources:
            coverage = "partial"
        elif not all_events:
            coverage = "empty"
        else:
            coverage = "complete"

        emit_trace_event(
            "HistoryRetrievalNode_retrieval_complete",
            {
                "event_count": len(all_events),
                "citation_count": len(all_citations),
                "coverage": coverage,
                "failed_source_count": len(failed_sources),
                "total_sources": len(approved_sources),
                "history_source": history_source,
            },
            state,
        )

        # Partial failures are non-fatal — document in error_log for transparency
        result_dict: dict = {
            "case_history_json": to_json(all_events),
            "citations_json": to_json(all_citations),
            "retrieval_coverage": coverage,
            # Operator-facing: "live" or "fixture". The rendered briefing is
            # identical either way, so this is the only signal distinguishing
            # a fixture-backed briefing from a live one.
            "history_source": history_source,
            "status": AgentStatus.SUCCESS.value,
        }

        if failed_sources:
            result_dict["error_log"] = [
                f"HistoryRetrievalNode: {len(failed_sources)} source(s) unavailable — partial result"
            ]

        return result_dict
