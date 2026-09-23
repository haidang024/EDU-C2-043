"""PB-3: External service boundary tests — EDU-C2-043.

Proves controlled fake-adapter mapping and provenance across the L1-to-service boundary.
All tests use deterministic fakes — no live student/case data or credentials.
"""

from __future__ import annotations

import pytest

from src.schemas.state import from_json, to_json
from src.services.case_history_service import FakeCaseHistoryService


class TestCaseHistoryServiceBoundary:
    """PB-3: L1 → case-history source boundary via FakeCaseHistoryService."""

    def test_pb3_fake_returns_configured_events(self):
        """PB-3: FakeAdapter returns pre-configured events for approved source."""
        fake_events = [
            {
                "date": "2024-04-01",
                "event_type": "academic_concern",
                "summary": "Missed deadline",
                "source_id": "SRC-FAKE",
                "citation_ref": "CIT-SRC-FAKE-000",
            }
        ]
        svc = FakeCaseHistoryService(events_by_source={"SRC-FAKE": fake_events})
        result = svc.fetch_events(
            source_id="SRC-FAKE",
            student_ref="STU-PB3",
            date_from="2024-01-01",
            date_to="2024-12-31",
        )

        assert result["events"] == fake_events
        assert len(result["citations"]) == 1
        assert result["citations"][0]["source_id"] == "SRC-FAKE"

    def test_pb3_error_source_raises_runtime_error(self):
        """PB-3: Error source raises RuntimeError, not a silent failure."""
        svc = FakeCaseHistoryService(error_sources={"SRC-ERROR"})
        with pytest.raises(RuntimeError, match="SRC-ERROR"):
            svc.fetch_events(
                source_id="SRC-ERROR",
                student_ref="STU-PB3",
                date_from="2024-01-01",
                date_to="2024-12-31",
            )

    def test_pb3_unknown_source_returns_empty_events(self):
        """PB-3: Unknown source (not configured) returns empty events list."""
        svc = FakeCaseHistoryService(events_by_source={})
        result = svc.fetch_events(
            source_id="SRC-UNKNOWN",
            student_ref="STU-PB3",
            date_from="2024-01-01",
            date_to="2024-12-31",
        )
        assert result["events"] == []
        assert result["citations"] == []

    def test_pb3_citations_carry_provenance(self):
        """PB-3: Citations include source_id and citation_ref for provenance tracing."""
        fake_events = [
            {
                "date": "2024-02-01",
                "event_type": "welfare_concern",
                "summary": "Y",
                "source_id": "SRC-A",
                "citation_ref": "CIT-A-001",
            },
            {
                "date": "2024-03-01",
                "event_type": "attendance_concern",
                "summary": "Z",
                "source_id": "SRC-A",
                "citation_ref": "CIT-A-002",
            },
        ]
        svc = FakeCaseHistoryService(events_by_source={"SRC-A": fake_events})
        result = svc.fetch_events(
            source_id="SRC-A",
            student_ref="STU-PB3",
            date_from="2024-01-01",
            date_to="2024-12-31",
        )

        assert len(result["citations"]) == 2
        for cit in result["citations"]:
            assert "citation_ref" in cit
            assert cit["source_id"] == "SRC-A"

    def test_pb3_service_never_makes_eligibility_decision(self):
        """PB-3: Service adapter returns raw events only — no decision-making fields."""
        fake_events = [
            {
                "date": "2024-01-01",
                "event_type": "welfare_concern",
                "summary": "X",
                "source_id": "SRC-A",
                "citation_ref": "C1",
            }
        ]
        svc = FakeCaseHistoryService(events_by_source={"SRC-A": fake_events})
        result = svc.fetch_events("SRC-A", "STU-001", "2024-01-01", "2024-12-31")

        for event in result["events"]:
            assert "eligibility" not in str(event).lower()
            assert "decision" not in str(event).lower()
            assert "escalate_now" not in event


class TestHistoryRetrievalNodeWithFake:
    """Integration: HistoryRetrievalNode uses FakeCaseHistoryService end-to-end."""

    def test_pb3_node_uses_service_adapter(self, monkeypatch):
        """PB-3: HistoryRetrievalNode retrieves and stores normalized events via adapter."""
        from src.services.case_history_service import FakeCaseHistoryService
        import src.nodes.history_retrieval_node as hrm

        fake_events = [
            {
                "date": "2024-05-01",
                "event_type": "disability_support",
                "summary": "Accommodation requested",
                "source_id": "SRC-001",
                "citation_ref": "CIT-001-000",
            },
        ]
        fake = FakeCaseHistoryService(events_by_source={"SRC-001": fake_events})
        monkeypatch.setattr(hrm, "CaseHistoryService", lambda credential: fake)

        from src.nodes.history_retrieval_node import HistoryRetrievalNode
        from framework.schemas.trust_level import TrustLevel
        from framework.schemas.agent_status import AgentStatus

        node = HistoryRetrievalNode()
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "correlation_id": "pb3-int-test",
            "session_id": "pb3-session",
            "thread_id": "pb3-thread",
            "trace_id": "pb3-trace",
            "caller_id": "pb3-caller",
            "node_history": [],
            "error_log": [],
            "execution_time": {},
            "status": "success",
            "hitl_allowed": False,
            "case_scope_json": to_json(
                {
                    "student_ref": "STU-PB3",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            "approved_sources_json": to_json(["SRC-001"]),
        }

        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        events = from_json(result["case_history_json"])
        assert len(events) == 1
        assert events[0]["event_type"] == "disability_support"
        citations = from_json(result["citations_json"])
        assert len(citations) == 1
        assert result["retrieval_coverage"] == "complete"

    def test_pb3_raw_credentials_not_in_state(self, monkeypatch):
        """PB-3: No credential values appear in node state output."""
        from src.services.case_history_service import FakeCaseHistoryService
        import src.nodes.history_retrieval_node as hrm

        fake = FakeCaseHistoryService(events_by_source={})
        monkeypatch.setattr(hrm, "CaseHistoryService", lambda credential: fake)

        from src.nodes.history_retrieval_node import HistoryRetrievalNode
        from framework.schemas.trust_level import TrustLevel

        node = HistoryRetrievalNode()
        state = {
            "caller_trust_level": TrustLevel.ANONYMOUS.value,
            "correlation_id": "pb3-cred-test",
            "session_id": "pb3-session",
            "thread_id": "pb3-thread",
            "trace_id": "pb3-trace",
            "caller_id": "pb3-caller",
            "node_history": [],
            "error_log": [],
            "execution_time": {},
            "status": "success",
            "hitl_allowed": False,
            "case_scope_json": to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            "approved_sources_json": to_json(["SRC-001"]),
        }

        result = node(state)

        # Credential values must not appear in any state field
        result_str = str(result)
        assert "FAKE_CASE_HISTORY_SERVICE_TOKEN" not in result_str
        assert "FAKE_" not in result_str or "FAKE_CREDENTIAL_TEST_ONLY" not in result_str
