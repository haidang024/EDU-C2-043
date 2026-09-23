# tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py
#
# PB-7: HITL interrupt propagation — EDU-C2-043
#
# CONDITIONAL: Active because config/config.yaml sets hitl.enabled: true
#
# Two test cases (PB-7, HITL interrupt propagation):
#   test_pb7_hitl_interrupt_propagates()
#       GraphInterrupt propagates through __call__() — NOT caught by the application.
#   test_pb7_hitl_allowed_false_skips_interrupt()
#       hitl_allowed=False guard prevents interrupt() — no deadlock.

from __future__ import annotations

import pathlib
import warnings

import pytest

from src.schemas.state import to_json

# ---------------------------------------------------------------------------
# Conditional skip — only runs when config/agent.yaml has hitl.enabled: true
# ---------------------------------------------------------------------------

_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _hitl_enabled() -> bool:
    if not _CONFIG_PATH.exists():
        warnings.warn(f"{_CONFIG_PATH} not found — PB-7 applicability is unknown", stacklevel=2)
        return False
    try:
        import yaml

        data = yaml.safe_load(_CONFIG_PATH.read_text())
    except Exception as exc:
        warnings.warn(f"{_CONFIG_PATH} could not be parsed ({exc})", stacklevel=2)
        return False
    hitl = (data or {}).get("hitl", {}) if isinstance(data, dict) else None
    if not isinstance(hitl, dict):
        warnings.warn(f"{_CONFIG_PATH} has no valid hitl mapping", stacklevel=2)
        return False
    return bool(hitl.get("enabled", False))


pytestmark = pytest.mark.skipif(
    not _hitl_enabled(),
    reason="config/config.yaml does not set hitl.enabled: true — PB-7 not applicable",
)

# ---------------------------------------------------------------------------
# Helper — minimal state for CounselorHandoffNode tests
# ---------------------------------------------------------------------------


def _base_state(**overrides) -> dict:
    from framework.schemas.trust_level import TrustLevel

    state = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "pb7-test",
        "session_id": "pb7-session",
        "thread_id": "pb7-thread",
        "trace_id": "pb7-trace",
        "caller_id": "pb7-caller",
        "node_history": [],
        "error_log": [],
        "hitl_allowed": True,
        "hitl_count": 0,
        "case_scope_json": to_json({"student_ref": "STU-PB7", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
        "timeline_json": to_json(
            [
                {
                    "date": "2024-03-01",
                    "event_type": "academic_concern",
                    "summary": "PB-7 test event",
                    "source_id": "SRC-001",
                    "citation_ref": "CIT-001",
                }
            ]
        ),
        "support_themes_json": to_json([{"theme": "academic_concern", "occurrence_count": 1, "note": ""}]),
        "escalation_guidance_json": to_json(
            [
                {
                    "guidance_ref": "EDU-ESC-001",
                    "title": "T",
                    "description": "D",
                    "policy_source": "P",
                    "matched_theme": "academic_concern",
                    "occurrence_count": 1,
                }
            ]
        ),
        "citations_json": to_json(
            [{"citation_ref": "CIT-001", "source_id": "SRC-001", "description": "PB-7 test citation"}]
        ),
        "retrieval_coverage": "complete",
        "hitl_draft_json": "",
        "review_outcome": "",
        "review_notes": "",
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# PB-7-A: interrupt() raises GraphInterrupt and propagates
# ---------------------------------------------------------------------------


def test_pb7_hitl_interrupt_propagates(monkeypatch) -> None:
    """PB-7: interrupt() raises GraphInterrupt and propagates (not caught by app boundary).

    Covers PB-7 (first assertion):
      GraphInterrupt reaches LangGraph engine; status is NOT set to error.
    """
    import src.nodes.counselor_handoff_node as handoff_module
    from langgraph.errors import GraphInterrupt
    from langgraph.types import Interrupt

    def raise_graph_interrupt(_payload):
        raise GraphInterrupt((Interrupt(value={"type": "pb7"}, id="pb7"),))

    monkeypatch.setattr(handoff_module, "interrupt", raise_graph_interrupt)

    node = handoff_module.CounselorHandoffNode()
    state = _base_state(hitl_allowed=True)

    with pytest.raises(GraphInterrupt):
        node(state)


# ---------------------------------------------------------------------------
# PB-7-B: hitl_allowed=False guard prevents deadlock
# ---------------------------------------------------------------------------


def test_pb7_hitl_allowed_false_skips_interrupt() -> None:
    """PB-7 guard: hitl_allowed=False must NOT raise GraphInterrupt (no deadlock).

    Covers HITL compliance + review criterion #12.
    """
    from src.nodes.counselor_handoff_node import CounselorHandoffNode
    from framework.schemas.agent_status import AgentStatus

    node = CounselorHandoffNode()
    state = _base_state(hitl_allowed=False)

    result = node(state)  # must NOT raise GraphInterrupt
    assert result.get("status") == AgentStatus.SUCCESS.value
    assert result.get("hitl_draft_json") or result.get("status") == AgentStatus.SUCCESS.value


def test_inner_graph_first_invoke_awaits_human_review() -> None:
    """The compiled inner graph exposes an actual resumable HITL boundary."""
    import json

    from framework.schemas.agent_status import AgentStatus

    if not hasattr(AgentStatus, "AWAITING_HUMAN"):
        pytest.skip("fallback framework stub has no compiled HITL runtime")

    from framework.schemas.invocation_context import InvocationContext
    from framework.schemas.trust_level import TrustLevel
    from framework.secrets.context import bound_secrets
    from shared.secrets.inmemory_provider import InMemoryProvider
    from src.graph.graph import CaseHistoryBriefingGraphNode

    wrapper = CaseHistoryBriefingGraphNode(config={"memory_enabled": True, "hitl": {"enabled": True}})
    graph = wrapper.get_subgraph()
    provider = InMemoryProvider({"CASE_HISTORY_SERVICE_TOKEN": "stg-mock-case-history"})
    ctx = InvocationContext(
        session_id="pb7-session",
        thread_id="pb7-thread",
        caller_trust_level=TrustLevel.VERIFIED_EXTERNAL,
        caller_id="pb7-caller",
        hitl_allowed=True,
    )
    user_input = json.dumps(
        {
            "student_ref": "STU-HASHED-PB7",
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "support_category": "academic_concern",
            "approved_sources": ["SRC-PB7"],
        }
    )

    with bound_secrets(provider):
        result = graph.invoke(user_input, session_id=ctx.session_id, ctx=ctx)

    assert result["status"] == AgentStatus.AWAITING_HUMAN.value
    assert result["hitl_metadata"]["type"] == "counselor_review_required"

    with bound_secrets(provider):
        resumed = graph.resume(result["thread_id"], {"action": "approve"})

    assert resumed["status"] == AgentStatus.SUCCESS.value
    assert resumed["review_outcome"] == "approved"
    assert resumed["output"]


# ---------------------------------------------------------------------------
# PB-7-C: approved resume route
# ---------------------------------------------------------------------------


def test_pb7_approved_resume_produces_success() -> None:
    """PB-7: 'approved' resume outcome sets review_outcome and SUCCESS status."""
    from src.nodes.counselor_handoff_node import CounselorHandoffNode
    from framework.schemas.agent_status import AgentStatus

    node = CounselorHandoffNode()
    draft = to_json({"doc": "briefing"})
    state = _base_state(hitl_draft_json=draft, review_outcome="approved", review_notes="")
    result = node(state)

    assert result["status"] == AgentStatus.SUCCESS.value
    assert result["review_outcome"] == "approved"


# ---------------------------------------------------------------------------
# PB-7-D: corrected resume route
# ---------------------------------------------------------------------------


def test_pb7_corrected_resume_with_notes() -> None:
    """PB-7: 'corrected' resume includes counselor notes and SUCCESS status."""
    from src.nodes.counselor_handoff_node import CounselorHandoffNode
    from framework.schemas.agent_status import AgentStatus

    node = CounselorHandoffNode()
    draft = to_json({"doc": "briefing"})
    state = _base_state(hitl_draft_json=draft, review_outcome="corrected", review_notes="Please expand timeline.")
    result = node(state)

    assert result["status"] == AgentStatus.SUCCESS.value
    assert result["review_notes"] == "Please expand timeline."


# ---------------------------------------------------------------------------
# PB-7-E: rejected resume route
# ---------------------------------------------------------------------------


def test_pb7_rejected_resume_produces_error() -> None:
    """PB-7: 'rejected' resume sets ERROR status (no briefing issued)."""
    from src.nodes.counselor_handoff_node import CounselorHandoffNode
    from framework.schemas.agent_status import AgentStatus

    node = CounselorHandoffNode()
    draft = to_json({"doc": "briefing"})
    state = _base_state(hitl_draft_json=draft, review_outcome="rejected", review_notes="Coverage too low.")
    result = node(state)

    assert result["status"] == AgentStatus.ERROR.value
