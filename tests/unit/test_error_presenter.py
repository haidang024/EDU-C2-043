"""EDU-C2-043 — Caller-facing error presentation must not leak diagnostics.

`BaseNode.__call__()` writes "[Node] <msg>\\n<traceback>" into error_log. These
tests pin the boundary that keeps the traceback half out of caller output.
"""

from __future__ import annotations

from framework.schemas.trust_level import TrustLevel

from src.services.error_presenter import classify, first_line, present

# A verbatim-shaped error_log entry: node tag, message, then a real traceback
# naming deployment paths, source lines, and the secret that was missing.
_RECORD = (
    "[HistoryRetrievalNode] Agent agent1000/EDU-C2-043: required secret "
    "'CASE_HISTORY_SERVICE_TOKEN' not found (checked: platform, "
    "namespaces/agent1000, agents/agent1000/EDU-C2-043)\n"
    "Traceback (most recent call last):\n"
    '  File "/usr/local/lib/python3.11/site-packages/framework/nodes/base_node.py", line 194, in __call__\n'
    "    result = self.execute(state)\n"
    '  File "/app/src/nodes/history_retrieval_node.py", line 51, in execute\n'
    '    service_credential = ctx.secrets.require("CASE_HISTORY_SERVICE_TOKEN")\n'
    "framework.secrets.base.MissingSecret: required secret 'CASE_HISTORY_SERVICE_TOKEN' not found\n"
)

# Substrings that must never reach a caller.
_FORBIDDEN = [
    "Traceback",
    'File "',
    "site-packages",
    "/app/",
    "CASE_HISTORY_SERVICE_TOKEN",
    "MissingSecret",
    "base_node.py",
    "history_retrieval_node.py",
    "framework.secrets",
    "namespaces/agent1000",
]


def _assert_clean(text: str) -> None:
    leaked = [token for token in _FORBIDDEN if token in text]
    assert not leaked, f"caller-facing text leaked diagnostics: {leaked}"


class TestFirstLine:
    def test_strips_node_tag_and_traceback(self):
        head = first_line(_RECORD)
        assert head.startswith("Agent agent1000/EDU-C2-043: required secret")
        assert "\n" not in head
        assert "Traceback" not in head

    def test_empty_record_yields_empty_string(self):
        assert first_line("") == ""


class TestClassify:
    def test_missing_secret_maps_to_configuration_reason(self):
        assert classify(_RECORD) == "The case history service is not fully configured in this environment."

    def test_scope_failure_maps_to_scope_reason(self):
        record = "[ScopeValidationNode] missing case scope or approved sources\nTraceback (most recent call last):\n"
        assert "case scope" in classify(record)

    def test_classified_reason_is_idempotent(self):
        # on_subgraph_error() classifies, then present() classifies again;
        # a second pass must not demote the reason to the generic one.
        once = classify(_RECORD)
        assert classify(once) == once

    def test_unrecognized_error_falls_back_to_generic(self):
        reason = classify("[SomeNode] object has no attribute 'foo'\nTraceback (most recent call last):\n")
        assert "temporary internal error" in reason

    def test_never_returns_input_derived_text(self):
        _assert_clean(classify(_RECORD))


class TestPresent:
    def test_output_is_clean_and_actionable(self):
        message = present(_RECORD, correlation_id="corr-1")
        _assert_clean(message)
        assert "could not be completed" in message
        assert "How to continue:" in message

    def test_correlation_id_is_included_for_operator_lookup(self):
        assert "Reference: corr-1" in present(_RECORD, correlation_id="corr-1")

    def test_correlation_id_omitted_when_absent(self):
        assert "Reference:" not in present(_RECORD)


class TestOnSubgraphErrorBoundary:
    """The regression that motivated this module: a node raising inside the
    inner graph surfaced a full traceback — deployment paths, source lines, and
    the case-history service credential — all the way to the counselor.
    """

    def _carry(self, record: str) -> dict:
        from src.graph.graph import CaseHistoryBriefingGraphNode

        error = RuntimeError("subgraph failed")
        error.error_log = [record]  # type: ignore[attr-defined]
        return CaseHistoryBriefingGraphNode.on_subgraph_error(
            CaseHistoryBriefingGraphNode.__new__(CaseHistoryBriefingGraphNode),
            {},
            error,
        )

    def _handle(self, record: str) -> str:
        """Drive the real path: on_subgraph_error() → PostProcessNode.execute().

        Both stages are exercised through their production entry points so that
        removing the guard in either one fails these tests.
        """
        from src.nodes.post_process_node import PostProcessNode

        state = {
            "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
            "correlation_id": "corr-abc",
            **self._carry(record),
        }
        return str(PostProcessNode(config={}).execute(state)["formatted_output"])

    def test_carried_field_is_already_sanitized(self):
        """Pin the first layer independently.

        post_process also sanitizes, so an end-to-end assertion still passes if
        this layer regresses. workflow_error_message lives in State, which is
        checkpointed — a raw traceback must not be written there in the first
        place, regardless of how it is later rendered.
        """
        _assert_clean(str(self._carry(_RECORD)["workflow_error_message"]))

    def test_traceback_never_reaches_the_rendered_message(self):
        _assert_clean(self._handle(_RECORD))

    def test_specific_reason_survives_the_two_classification_passes(self):
        message = self._handle(_RECORD)
        assert "not fully configured" in message
        assert "Reference: corr-abc" in message
