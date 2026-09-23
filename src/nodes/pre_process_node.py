"""PreProcessNode — validates operator-authorized case scope and approved sources for EDU-C2-043."""

from __future__ import annotations

import json
from typing import ClassVar

from framework.errors import SecurityViolationError
from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from shared.utils.audit_logger import emit_trace_event

from src.schemas.state import to_json

# Maximum number of approved source IDs the operator may configure
_MAX_APPROVED_SOURCES = 20
# Minimum fields required in the case scope input
_REQUIRED_SCOPE_FIELDS = {"student_ref", "date_from", "date_to"}


class PreProcessNode(FunctionNode):
    """Outer boundary node: validates operator-authorized case scope and source configuration.

    Runs at VERIFIED_EXTERNAL trust (S-1 boundary). Normalizes bounded criteria,
    validates approved source identifiers, and prepares state for the inner
    DomainWorkflowGraph. Emits a domain audit event with no student/case content.
    """

    # S-1 boundary: outer pre-process must be VERIFIED_EXTERNAL (Cat 2 rule)
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _extra_security_gate_input(self, state: dict) -> dict:
        """S-2 domain extension: validate that user_input is a non-empty JSON scope payload.

        Enforces input size and structural constraints before execute() runs.
        Does NOT log student/case content — audit payload contains only structural facts.
        """
        raw = state.get("user_input", "")
        if not raw or not isinstance(raw, str):
            raise SecurityViolationError("PreProcessNode: user_input is absent or not a string")
        if len(raw) > 8192:
            raise SecurityViolationError("PreProcessNode: user_input exceeds maximum allowed size")
        return state

    def execute(self, state: dict) -> dict:
        """Validate and normalize operator-authorized case scope and source list."""
        raw = state.get("user_input", "")

        # Parse the operator-provided scope payload (JSON)
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            emit_trace_event(
                "PreProcessNode_scope_parse_error",
                {"error": "invalid_json", "input_length": len(raw)},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "The case history scope is not valid JSON.",
                "input_error_guidance": [
                    "Provide a JSON object with student_ref, date_from, date_to, and approved_sources.",
                    "approved_sources must be a non-empty list of source identifiers.",
                ],
            }

        if not isinstance(payload, dict):
            emit_trace_event(
                "PreProcessNode_scope_parse_error",
                {"error": "not_a_dict"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "The case history scope must be a JSON object.",
                "input_error_guidance": ["Provide student_ref, date_from, date_to, and approved_sources."],
            }

        # Validate required scope fields
        missing = _REQUIRED_SCOPE_FIELDS - set(payload.keys())
        if missing:
            emit_trace_event(
                "PreProcessNode_scope_validation_error",
                {"error": "missing_fields", "missing": sorted(missing)},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": f"Required case scope fields are missing: {sorted(missing)}.",
                "input_error_guidance": ["Provide student_ref, date_from, date_to, and approved_sources."],
            }

        # Validate and extract approved sources
        approved_sources = payload.get("approved_sources", [])
        if not isinstance(approved_sources, list) or not approved_sources:
            emit_trace_event(
                "PreProcessNode_sources_validation_error",
                {"error": "no_approved_sources"},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "approved_sources must be a non-empty list.",
                "input_error_guidance": ["Add one or more operator-approved source identifiers."],
            }

        if len(approved_sources) > _MAX_APPROVED_SOURCES:
            emit_trace_event(
                "PreProcessNode_sources_validation_error",
                {"error": "too_many_sources", "count": len(approved_sources)},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": f"approved_sources cannot contain more than {_MAX_APPROVED_SOURCES} entries.",
                "input_error_guidance": ["Reduce the source list to the approved sources needed for this case."],
            }

        # Validate each source ID is a non-empty string
        invalid_sources = [s for s in approved_sources if not isinstance(s, str) or not s.strip()]
        if invalid_sources:
            emit_trace_event(
                "PreProcessNode_sources_validation_error",
                {"error": "invalid_source_ids", "count": len(invalid_sources)},
                state,
            )
            return {
                "status": AgentStatus.SUCCESS.value,
                "input_error_message": "approved_sources contains an empty or invalid source identifier.",
                "input_error_guidance": ["Use non-empty strings for every approved source identifier."],
            }

        # Normalize bounded case scope (no raw student identifiers beyond what operator provides)
        case_scope = {
            "student_ref": str(payload["student_ref"]).strip(),
            "date_from": str(payload["date_from"]).strip(),
            "date_to": str(payload["date_to"]).strip(),
            "support_category": str(payload.get("support_category", "general")).strip(),
        }

        clean_sources = [s.strip() for s in approved_sources]

        emit_trace_event(
            "PreProcessNode_scope_validated",
            {
                "source_count": len(clean_sources),
                "scope_fields": list(case_scope.keys()),
                "support_category": case_scope["support_category"],
            },
            state,
        )

        return {
            "validated_input": raw.strip(),
            "case_scope_json": to_json(case_scope),
            "approved_sources_json": to_json(clean_sources),
            "status": AgentStatus.SUCCESS.value,
        }
