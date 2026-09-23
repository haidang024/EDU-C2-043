"""ScopeValidationNode — validates case scope bounds and source authorization inside DomainWorkflowGraph."""

from __future__ import annotations

import json
from typing import ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import from_json, to_json


class ScopeValidationNode(FunctionNode):
    """Inner node: validates normalized case scope and source authorization before retrieval.

    Trust is already verified at the outer PreProcessNode boundary.
    This node re-validates bounded criteria and source allowlist completeness
    without re-checking external caller trust.
    """

    # Inner DomainWorkflowGraph nodes must be ANONYMOUS (trust-trap anti-pattern prevention)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.ANONYMOUS

    def execute(self, state: dict) -> dict:
        """Validate case scope completeness and source allowlist before retrieval."""
        case_scope = from_json(state.get("case_scope_json"), default={})
        approved_sources = from_json(state.get("approved_sources_json"), default=[])

        # GraphNode invokes the inner graph with validated_input as its user_input;
        # outer state fields do not cross that subgraph boundary automatically.
        # Reconstruct the already-normalized scope at the first inner node, then
        # propagate it as JSON-safe state for downstream nodes.
        if not case_scope or not approved_sources:
            try:
                payload = json.loads(state.get("user_input", ""))
            except (TypeError, ValueError):
                payload = {}
            if isinstance(payload, dict):
                case_scope = {
                    "student_ref": str(payload.get("student_ref", "")).strip(),
                    "date_from": str(payload.get("date_from", "")).strip(),
                    "date_to": str(payload.get("date_to", "")).strip(),
                    "support_category": str(payload.get("support_category", "general")).strip(),
                }
                approved_sources = payload.get("approved_sources", [])

        errors: list[str] = []

        # Validate scope fields are present and non-empty
        for field in ("student_ref", "date_from", "date_to"):
            if not case_scope.get(field):
                errors.append(f"ScopeValidationNode: case_scope missing or empty: {field}")

        # Validate date ordering (lexicographic — ISO 8601 format expected)
        date_from = case_scope.get("date_from", "")
        date_to = case_scope.get("date_to", "")
        if date_from and date_to and date_from > date_to:
            errors.append("ScopeValidationNode: date_from must not be later than date_to")

        # Validate approved source list is populated
        if not approved_sources:
            errors.append("ScopeValidationNode: no approved sources configured")

        if errors:
            emit_trace_event(
                "ScopeValidationNode_validation_failed",
                {"error_count": len(errors), "fields_checked": ["student_ref", "date_from", "date_to", "sources"]},
                state,
            )
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": errors,
            }

        emit_trace_event(
            "ScopeValidationNode_scope_authorized",
            {
                "source_count": len(approved_sources),
                "support_category": case_scope.get("support_category", "general"),
                "has_date_range": bool(date_from and date_to),
            },
            state,
        )

        return {
            "case_scope_json": to_json(case_scope),
            "approved_sources_json": to_json(approved_sources),
            "status": AgentStatus.SUCCESS.value,
        }
