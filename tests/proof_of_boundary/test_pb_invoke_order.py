# PB-6: Invoke Execution Order Verification — EDU-C2-043
# Verifies BaseNode.__call__() enforces:
#   S-1 trust gate -> S-4 node_start -> S-2 _security_gate_input() ->
#   execute() -> S-3 _security_gate_output() -> S-4 node_complete
# Also verifies negative S-1 trust rejection (mandatory per IMPLEMENTATION.md §0).

import importlib
import inspect
import json
import pkgutil
from typing import ClassVar

import pytest
from framework.nodes.base_node import BaseNode
from framework.schemas.trust_level import TrustLevel

from src.schemas.state import to_json


class _PrivilegedTrustGateFixture(BaseNode):
    """Always-present privileged node used to prove the S-1 negative boundary."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _security_gate_input(self, state):
        return state

    def execute(self, state):
        return {"status": "success"}

    def _security_gate_output(self, result):
        return result


def _trust_predecessor(required: TrustLevel) -> TrustLevel:
    predecessors = {
        TrustLevel.VERIFIED_EXTERNAL: TrustLevel.ANONYMOUS,
        TrustLevel.INTERNAL: TrustLevel.VERIFIED_EXTERNAL,
    }
    try:
        return predecessors[required]
    except KeyError as exc:
        raise AssertionError(f"no lower trust level defined for {required!r}") from exc


def _make_node_state(node_cls) -> dict:
    """Build a minimal valid state for the given node class to exercise the invoke pipeline.

    Provides node-specific inputs so gates don't fire on structural validation
    errors — the goal is to verify the invoke order, not to trigger errors.
    """
    base = {
        "caller_trust_level": node_cls.required_trust_level.value,
        "correlation_id": "pb6-invoke-order-test",
        "session_id": "pb6-session",
        "thread_id": "pb6-thread",
        "trace_id": "pb6-trace",
        "caller_id": "pb6-caller",
        "node_history": [],
        "error_log": [],
        "execution_time": {},
        "status": "success",
        "hitl_allowed": False,  # Prevents CounselorHandoffNode GraphInterrupt
    }

    name = node_cls.__name__
    if name == "PreProcessNode":
        base["user_input"] = json.dumps(
            {
                "student_ref": "STU-PB6",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "approved_sources": ["SRC-001"],
            }
        )
    elif name == "ScopeValidationNode":
        base["case_scope_json"] = to_json(
            {"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}
        )
        base["approved_sources_json"] = to_json(["SRC-001"])
    elif name == "HistoryRetrievalNode":
        base["case_scope_json"] = to_json(
            {
                "student_ref": "STU-001",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "support_category": "general",
            }
        )
        base["approved_sources_json"] = to_json(["SRC-001"])
    elif name == "TimelineSynthesisNode":
        base["case_history_json"] = to_json([])
        base["retrieval_coverage"] = "empty"
    elif name == "EscalationGuidanceNode":
        base["support_themes_json"] = to_json([])
        base["retrieval_coverage"] = "empty"
    elif name == "CounselorHandoffNode":
        base["case_scope_json"] = to_json(
            {"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}
        )
        base["timeline_json"] = to_json([])
        base["support_themes_json"] = to_json([])
        base["escalation_guidance_json"] = to_json([])
        base["citations_json"] = to_json([])
        base["retrieval_coverage"] = "empty"
        base["hitl_draft_json"] = ""
        base["review_outcome"] = ""
        base["review_notes"] = ""
    elif name == "PostProcessNode":
        base["result"] = ""
        base["hitl_draft_json"] = to_json(
            {
                "timeline": [],
                "support_themes": [],
                "escalation_references": [],
                "citations": [],
                "limitations": [],
                "scope": {},
                "retrieval_coverage": "empty",
            }
        )
        base["review_outcome"] = "approved"
        base["review_notes"] = ""
        base["citations_json"] = to_json([])
        base["retrieval_coverage"] = "empty"

    return base


def _discover_node_classes() -> list[type]:
    """Import every module under src/nodes/ and collect concrete FunctionNode subclasses."""
    from framework.nodes.function_node import FunctionNode

    try:
        pkg = importlib.import_module("src.nodes")
    except ImportError:
        return []

    discovered = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, FunctionNode)
                and attr is not FunctionNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


class TestInvokeOrder:
    """PB-6: __call__ must run S-1 -> node_start -> S-2 -> execute() -> S-3 -> node_complete."""

    def test_s1_denial_refuses_execution_before_execute(self, monkeypatch):
        """TC-08: S-1 denial happens before execute or normal lifecycle events."""
        import framework.nodes.base_node as base_node_module

        events: list[str] = []
        execute_calls: list[object] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, _payload, _state: events.append(event_type),
        )
        original_execute = _PrivilegedTrustGateFixture.execute

        def spy_execute(self, state):
            execute_calls.append(state)
            return original_execute(self, state)

        monkeypatch.setattr(_PrivilegedTrustGateFixture, "execute", spy_execute)
        result = _PrivilegedTrustGateFixture()(
            {
                "caller_trust_level": _trust_predecessor(_PrivilegedTrustGateFixture.required_trust_level).value,
                "correlation_id": "tc08-s1-denial",
            }
        )

        assert result["status"] == "error"
        assert "S-1 trust gate denied" in result["error_log"][0]
        assert events == ["s1_denied"]
        assert not execute_calls

    def test_call_order_for_every_node(self, monkeypatch):
        node_classes = _discover_node_classes()
        if not node_classes:
            pytest.skip("no concrete FunctionNode subclasses found under src/nodes/")

        import framework.nodes.base_node as base_node_module

        failures: list[str] = []
        for node_cls in node_classes:
            order: list[str] = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _o=order: _o.append(f"event:{event_type}"),
            )

            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _o=order, _label=label, _orig=original):
                    _o.append(_label)
                    return _orig(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            instance = node_cls()
            state = _make_node_state(node_cls)
            instance(state)

            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(
                    f"{node_cls.__name__}: invoke order violation.\n" f"expected: {expected}\nactual:   {order}"
                )

        assert not failures, "\n\n".join(failures)
