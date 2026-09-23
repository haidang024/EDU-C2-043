"""Unit tests for EDU-C2-043 nodes — BL and TC tests."""

from __future__ import annotations

import json

import pytest

from src.schemas.state import from_json, to_json


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _vext_state(**overrides) -> dict:
    """Minimal state for VERIFIED_EXTERNAL outer nodes."""
    from framework.schemas.trust_level import TrustLevel

    state = {
        "caller_trust_level": TrustLevel.VERIFIED_EXTERNAL.value,
        "correlation_id": "test-unit",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "caller_id": "test-caller",
        "node_history": [],
        "error_log": [],
        "execution_time": {},
        "status": "success",
        "hitl_allowed": True,
        "hitl_count": 0,
    }
    state.update(overrides)
    return state


def _anon_state(**overrides) -> dict:
    """Minimal state for ANONYMOUS inner nodes."""
    from framework.schemas.trust_level import TrustLevel

    state = {
        "caller_trust_level": TrustLevel.ANONYMOUS.value,
        "correlation_id": "test-unit",
        "session_id": "test-session",
        "thread_id": "test-thread",
        "trace_id": "test-trace",
        "caller_id": "test-caller",
        "node_history": [],
        "error_log": [],
        "execution_time": {},
        "status": "success",
        "hitl_allowed": True,
        "hitl_count": 0,
    }
    state.update(overrides)
    return state


def _valid_scope_input() -> str:
    return json.dumps(
        {
            "student_ref": "STU-HASHED-001",
            "date_from": "2024-01-01",
            "date_to": "2024-12-31",
            "support_category": "academic_concern",
            "approved_sources": ["SRC-001", "SRC-002"],
        }
    )


# ── BL-01: PreProcessNode scope validation ────────────────────────────────────


class TestPreProcessNode:
    def test_bl01_valid_scope_input(self):
        """BL-01: Valid scope input is parsed and normalized."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        state = _vext_state(user_input=_valid_scope_input())
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["validated_input"]
        scope = from_json(result["case_scope_json"])
        assert scope["student_ref"] == "STU-HASHED-001"
        assert scope["date_from"] == "2024-01-01"
        sources = from_json(result["approved_sources_json"])
        assert sources == ["SRC-001", "SRC-002"]

    def test_bl02_missing_required_scope_fields(self):
        """BL-02: Missing required fields produce readable guidance."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        bad_input = json.dumps({"student_ref": "STU-001", "approved_sources": ["SRC-001"]})
        state = _vext_state(user_input=bad_input)
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "input_error_message" in result

    def test_bl03_empty_approved_sources(self):
        """BL-03: Empty approved_sources produces readable guidance."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        bad_input = json.dumps(
            {
                "student_ref": "STU-001",
                "date_from": "2024-01-01",
                "date_to": "2024-12-31",
                "approved_sources": [],
            }
        )
        state = _vext_state(user_input=bad_input)
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "approved_sources" in result["input_error_message"]

    def test_bl04_non_json_input(self):
        """BL-04: Non-JSON input produces readable guidance."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        state = _vext_state(user_input="not json at all")
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert "not valid JSON" in result["input_error_message"]

    def test_bl05_trust_level_enforced(self):
        """BL-05: ANONYMOUS caller cannot invoke VERIFIED_EXTERNAL pre_process."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        state = _anon_state(user_input=_valid_scope_input())
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value


# ── BL-06: ScopeValidationNode ────────────────────────────────────────────────


class TestScopeValidationNode:
    def test_bl06_valid_scope_passes(self):
        """BL-06: Valid scope and sources pass validation."""
        from src.nodes.scope_validation_node import ScopeValidationNode
        from framework.schemas.agent_status import AgentStatus

        node = ScopeValidationNode()
        state = _anon_state(
            case_scope_json=to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            approved_sources_json=to_json(["SRC-001"]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_bl07_invalid_date_range(self):
        """BL-07: date_from > date_to produces ERROR."""
        from src.nodes.scope_validation_node import ScopeValidationNode
        from framework.schemas.agent_status import AgentStatus

        node = ScopeValidationNode()
        state = _anon_state(
            case_scope_json=to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2025-01-01",
                    "date_to": "2024-01-01",
                    "support_category": "general",
                }
            ),
            approved_sources_json=to_json(["SRC-001"]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value

    def test_bl08_no_sources(self):
        """BL-08: Empty sources list produces ERROR."""
        from src.nodes.scope_validation_node import ScopeValidationNode
        from framework.schemas.agent_status import AgentStatus

        node = ScopeValidationNode()
        state = _anon_state(
            case_scope_json=to_json({"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
            approved_sources_json=to_json([]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value

    def test_subgraph_entry_reconstructs_validated_scope(self):
        """The first inner node reconstructs fields from GraphNode user_input."""
        from framework.schemas.agent_status import AgentStatus
        from src.nodes.scope_validation_node import ScopeValidationNode

        result = ScopeValidationNode()(_anon_state(user_input=_valid_scope_input()))

        assert result["status"] == AgentStatus.SUCCESS.value
        assert from_json(result["approved_sources_json"]) == ["SRC-001", "SRC-002"]


# ── BL-09: HistoryRetrievalNode ───────────────────────────────────────────────


class TestHistoryRetrievalNode:
    def _patched_node(self, monkeypatch, fake_service):
        """Return HistoryRetrievalNode with service patched to use fake."""
        from src.nodes import history_retrieval_node as hrm

        monkeypatch.setattr(hrm, "CaseHistoryService", lambda credential: fake_service)
        from src.nodes.history_retrieval_node import HistoryRetrievalNode

        return HistoryRetrievalNode()

    def test_bl09_retrieves_events_from_approved_sources(self, monkeypatch):
        """BL-09: Events are retrieved and normalized from approved sources."""
        from src.services.case_history_service import FakeCaseHistoryService
        from framework.schemas.agent_status import AgentStatus

        fake_events = [
            {
                "date": "2024-03-01",
                "event_type": "academic_concern",
                "summary": "Missed exam",
                "source_id": "SRC-001",
                "citation_ref": "CIT-001",
            }
        ]
        fake = FakeCaseHistoryService(events_by_source={"SRC-001": fake_events})
        node = self._patched_node(monkeypatch, fake)

        state = _anon_state(
            case_scope_json=to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            approved_sources_json=to_json(["SRC-001"]),
        )
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        events = from_json(result["case_history_json"])
        assert len(events) == 1
        assert result["retrieval_coverage"] == "complete"

    def test_bl10_partial_source_failure(self, monkeypatch):
        """BL-10: Partial source failure results in 'partial' coverage, not ERROR."""
        from src.services.case_history_service import FakeCaseHistoryService
        from framework.schemas.agent_status import AgentStatus

        fake_events = [
            {
                "date": "2024-03-01",
                "event_type": "welfare_concern",
                "summary": "Support request",
                "source_id": "SRC-001",
                "citation_ref": "CIT-001",
            }
        ]
        fake = FakeCaseHistoryService(
            events_by_source={"SRC-001": fake_events},
            error_sources={"SRC-002"},
        )
        node = self._patched_node(monkeypatch, fake)

        state = _anon_state(
            case_scope_json=to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            approved_sources_json=to_json(["SRC-001", "SRC-002"]),
        )
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["retrieval_coverage"] == "partial"

    def test_bl11_no_events_returns_empty_coverage(self, monkeypatch):
        """BL-11: No events returned yields 'empty' coverage."""
        from src.services.case_history_service import FakeCaseHistoryService

        fake = FakeCaseHistoryService(events_by_source={})
        node = self._patched_node(monkeypatch, fake)

        state = _anon_state(
            case_scope_json=to_json(
                {
                    "student_ref": "STU-001",
                    "date_from": "2024-01-01",
                    "date_to": "2024-12-31",
                    "support_category": "general",
                }
            ),
            approved_sources_json=to_json(["SRC-001"]),
        )
        result = node(state)
        assert result["retrieval_coverage"] == "empty"


# ── BL-12: TimelineSynthesisNode ──────────────────────────────────────────────


class TestTimelineSynthesisNode:
    def test_bl12_timeline_is_chronological(self):
        """BL-12: Timeline entries are sorted chronologically."""
        from src.nodes.timeline_synthesis_node import TimelineSynthesisNode
        from framework.schemas.agent_status import AgentStatus

        events = [
            {
                "date": "2024-06-01",
                "event_type": "welfare_concern",
                "summary": "Check-in",
                "source_id": "SRC-001",
                "citation_ref": "CIT-002",
            },
            {
                "date": "2024-03-01",
                "event_type": "academic_concern",
                "summary": "Missed exam",
                "source_id": "SRC-001",
                "citation_ref": "CIT-001",
            },
        ]
        node = TimelineSynthesisNode()
        state = _anon_state(case_history_json=to_json(events), retrieval_coverage="complete")
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        timeline = from_json(result["timeline_json"])
        assert timeline[0]["date"] == "2024-03-01"
        assert timeline[1]["date"] == "2024-06-01"

    def test_bl13_themes_counted_by_event_type(self):
        """BL-13: Support themes reflect factual occurrence counts."""
        from src.nodes.timeline_synthesis_node import TimelineSynthesisNode

        events = [
            {
                "date": "2024-01-01",
                "event_type": "academic_concern",
                "summary": "A",
                "source_id": "SRC",
                "citation_ref": "C1",
            },
            {
                "date": "2024-02-01",
                "event_type": "academic_concern",
                "summary": "B",
                "source_id": "SRC",
                "citation_ref": "C2",
            },
            {
                "date": "2024-03-01",
                "event_type": "welfare_concern",
                "summary": "C",
                "source_id": "SRC",
                "citation_ref": "C3",
            },
        ]
        node = TimelineSynthesisNode()
        state = _anon_state(case_history_json=to_json(events), retrieval_coverage="complete")
        result = node(state)

        themes = from_json(result["support_themes_json"])
        theme_map = {t["theme"]: t["occurrence_count"] for t in themes}
        assert theme_map.get("academic_concern") == 2
        assert theme_map.get("welfare_concern") == 1

    def test_bl14_no_diagnosis_or_welfare_judgment(self):
        """BL-14: Timeline synthesis does not produce eligibility/welfare decisions."""
        from src.nodes.timeline_synthesis_node import TimelineSynthesisNode

        events = [
            {
                "date": "2024-01-01",
                "event_type": "mental_health_concern",
                "summary": "X",
                "source_id": "SRC",
                "citation_ref": "C1",
            }
        ]
        node = TimelineSynthesisNode()
        state = _anon_state(case_history_json=to_json(events), retrieval_coverage="complete")
        result = node(state)

        # Should not contain welfare decision language
        for key in ("timeline_json", "support_themes_json"):
            content = result.get(key, "")
            assert "is eligible" not in content.lower()
            assert "must be" not in content.lower()


# ── BL-15: EscalationGuidanceNode ────────────────────────────────────────────


class TestEscalationGuidanceNode:
    def test_bl15_maps_known_theme_to_reference(self):
        """BL-15: Known indicator theme maps to institutional reference."""
        from src.nodes.escalation_guidance_node import EscalationGuidanceNode
        from framework.schemas.agent_status import AgentStatus

        themes = [{"theme": "academic_concern", "occurrence_count": 2, "note": ""}]
        node = EscalationGuidanceNode()
        state = _anon_state(support_themes_json=to_json(themes), retrieval_coverage="complete")
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        guidance = from_json(result["escalation_guidance_json"])
        refs = [e["guidance_ref"] for e in guidance]
        assert "EDU-ESC-001" in refs

    def test_bl16_unknown_theme_produces_gap_entry(self):
        """BL-16: Unknown indicator produces a gap entry, not an error."""
        from src.nodes.escalation_guidance_node import EscalationGuidanceNode
        from framework.schemas.agent_status import AgentStatus

        themes = [{"theme": "unknown_custom_theme", "occurrence_count": 1, "note": ""}]
        node = EscalationGuidanceNode()
        state = _anon_state(support_themes_json=to_json(themes), retrieval_coverage="complete")
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        guidance = from_json(result["escalation_guidance_json"])
        assert any(e["guidance_ref"] == "[no institutional reference]" for e in guidance)

    def test_bl17_no_autonomous_escalation(self):
        """BL-17: Escalation guidance output contains no autonomous escalation language."""
        from src.nodes.escalation_guidance_node import EscalationGuidanceNode

        themes = [{"theme": "welfare_concern", "occurrence_count": 1, "note": ""}]
        node = EscalationGuidanceNode()
        state = _anon_state(support_themes_json=to_json(themes), retrieval_coverage="complete")
        result = node(state)

        guidance_json = result.get("escalation_guidance_json", "")
        # Guidance must not autonomously escalate or contact parties
        assert "we have escalated" not in guidance_json.lower()
        assert "student has been contacted" not in guidance_json.lower()


# ── BL-18: CounselorHandoffNode (HITL) ───────────────────────────────────────


class TestCounselorHandoffNode:
    def _base_state(self, **overrides) -> dict:
        state = _anon_state(
            case_scope_json=to_json({"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
            timeline_json=to_json(
                [
                    {
                        "date": "2024-03-01",
                        "event_type": "academic_concern",
                        "summary": "X",
                        "source_id": "SRC",
                        "citation_ref": "C1",
                    }
                ]
            ),
            support_themes_json=to_json([{"theme": "academic_concern", "occurrence_count": 1, "note": ""}]),
            escalation_guidance_json=to_json(
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
            citations_json=to_json([{"citation_ref": "C1", "source_id": "SRC", "description": "Test citation"}]),
            retrieval_coverage="complete",
            hitl_draft_json="",
            review_outcome="",
            review_notes="",
        )
        state.update(overrides)
        return state

    def test_bl18_hitl_interrupt_raised(self, monkeypatch):
        """BL-18: interrupt() is raised when hitl_allowed=True and no existing draft."""
        import src.nodes.counselor_handoff_node as handoff_module
        from langgraph.errors import GraphInterrupt
        from langgraph.types import Interrupt

        def raise_graph_interrupt(_payload):
            raise GraphInterrupt((Interrupt(value={"type": "unit"}, id="unit"),))

        monkeypatch.setattr(handoff_module, "interrupt", raise_graph_interrupt)

        node = handoff_module.CounselorHandoffNode()
        state = self._base_state(hitl_allowed=True)

        with pytest.raises(GraphInterrupt):
            node(state)

    def test_bl19_hitl_skipped_when_not_allowed(self):
        """BL-19: No GraphInterrupt when hitl_allowed=False (non-blocking mode)."""
        from src.nodes.counselor_handoff_node import CounselorHandoffNode
        from framework.schemas.agent_status import AgentStatus

        node = CounselorHandoffNode()
        state = self._base_state(hitl_allowed=False)
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value

    def test_bl20_approved_resume(self):
        """BL-20: 'approved' resume outcome produces SUCCESS."""
        from src.nodes.counselor_handoff_node import CounselorHandoffNode
        from framework.schemas.agent_status import AgentStatus

        node = CounselorHandoffNode()
        draft = to_json({"doc": "test"})
        state = self._base_state(hitl_draft_json=draft, review_outcome="approved", review_notes="")
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["review_outcome"] == "approved"

    def test_bl21_corrected_resume(self):
        """BL-21: 'corrected' resume outcome produces SUCCESS with notes."""
        from src.nodes.counselor_handoff_node import CounselorHandoffNode
        from framework.schemas.agent_status import AgentStatus

        node = CounselorHandoffNode()
        draft = to_json({"doc": "test"})
        state = self._base_state(
            hitl_draft_json=draft, review_outcome="corrected", review_notes="Please add more context."
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["review_outcome"] == "corrected"
        assert result["review_notes"] == "Please add more context."

    def test_bl22_rejected_resume(self):
        """BL-22: 'rejected' resume outcome produces ERROR with notes."""
        from src.nodes.counselor_handoff_node import CounselorHandoffNode
        from framework.schemas.agent_status import AgentStatus

        node = CounselorHandoffNode()
        draft = to_json({"doc": "test"})
        state = self._base_state(
            hitl_draft_json=draft, review_outcome="rejected", review_notes="Insufficient coverage."
        )
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value
        assert result["review_outcome"] == "rejected"

    def test_bl23_no_welfare_decision(self):
        """BL-23: CounselorHandoffNode output does not contain welfare/emergency decisions."""
        from src.nodes.counselor_handoff_node import CounselorHandoffNode

        node = CounselorHandoffNode()
        draft = to_json({"doc": "briefing content"})
        state = self._base_state(hitl_draft_json=draft, review_outcome="approved", hitl_allowed=False)
        result = node(state)

        all_output = str(result)
        assert "is eligible" not in all_output.lower()
        assert "emergency action required" not in all_output.lower()


# ── BL-24: PostProcessNode ────────────────────────────────────────────────────


class TestPostProcessNode:
    def _base_state(self, **overrides) -> dict:
        draft = {
            "agent_id": "EDU-C2-043",
            "timeline": [
                {
                    "date": "2024-03-01",
                    "event_type": "academic_concern",
                    "summary": "X",
                    "source_id": "SRC",
                    "citation_ref": "C1",
                }
            ],
            "support_themes": [{"theme": "academic_concern", "occurrence_count": 1, "note": ""}],
            "escalation_references": [
                {
                    "guidance_ref": "EDU-ESC-001",
                    "title": "T",
                    "description": "D",
                    "policy_source": "P",
                    "matched_theme": "academic_concern",
                    "occurrence_count": 1,
                    "note": "",
                }
            ],
            "citations": [],
            "limitations": ["This briefing is human-reviewed support material only."],
            "scope": {},
            "retrieval_coverage": "complete",
            "review_required": True,
        }
        state = _vext_state(
            result="",
            hitl_draft_json=to_json(draft),
            review_outcome="approved",
            review_notes="",
            citations_json=to_json([]),
            retrieval_coverage="complete",
        )
        state.update(overrides)
        return state

    def test_bl24_formatted_output_present(self):
        """BL-24: formatted_output field is populated in PostProcessNode result."""
        from src.nodes.post_process_node import PostProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PostProcessNode()
        state = self._base_state()
        result = node(state)

        assert result["status"] == AgentStatus.SUCCESS.value
        assert result.get("formatted_output")
        assert "EDU-C2-043" in result["formatted_output"]

    def test_bl25_rejected_produces_error(self):
        """BL-25: Rejected review outcome yields ERROR status."""
        from src.nodes.post_process_node import PostProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PostProcessNode()
        state = self._base_state(review_outcome="rejected", review_notes="Not sufficient.")
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value
        assert "rejected" in result["formatted_output"].lower()

    def test_bl26_limitations_included_in_output(self):
        """BL-26: Formatted output includes limitations section."""
        from src.nodes.post_process_node import PostProcessNode

        node = PostProcessNode()
        state = self._base_state()
        result = node(state)
        assert "Limitations" in result["formatted_output"]
        assert "human-reviewed" in result["formatted_output"].lower()

    def test_bl27_no_raw_credentials_in_output(self):
        """BL-27: formatted_output does not contain credential-like strings."""
        from src.nodes.post_process_node import PostProcessNode

        node = PostProcessNode()
        state = self._base_state()
        result = node(state)

        output = result.get("formatted_output", "")
        assert "api_key" not in output.lower()
        assert "FAKE_CASE_HISTORY_SERVICE_TOKEN" not in output

    def test_unreviewed_draft_remains_pending(self):
        """An interrupt-suppressed draft must never be presented as approved."""
        from framework.schemas.agent_status import AgentStatus
        from src.nodes.post_process_node import PostProcessNode

        result = PostProcessNode()(self._base_state(review_outcome=""))

        assert result["status"] == AgentStatus.PENDING.value
        assert "pending authorized human review" in result["formatted_output"]


# ── TC-01: State contract ─────────────────────────────────────────────────────


class TestStateContract:
    def test_tc01_state_is_flat_typeddict(self):
        """TC-01: State schema is a flat TypedDict subclass, no Pydantic/dataclass."""
        from src.schemas.state import State
        import typing

        assert issubclass(State, dict)
        # Should not be a Pydantic model
        assert not hasattr(State, "model_fields")
        # Should have annotations (TypedDict)
        hints = typing.get_type_hints(State)
        assert "validated_input" in hints
        assert "case_history_json" in hints

    def test_tc01_to_json_from_json_helpers_exist(self):
        """TC-01: to_json/from_json helpers are present in state.py."""
        from src.schemas.state import to_json, from_json

        data = [{"key": "value"}]
        encoded = to_json(data)
        decoded = from_json(encoded)
        assert decoded == data

    def test_tc01_all_structured_fields_are_str(self):
        """TC-01: All structured (list/dict) fields are declared as str."""
        import typing
        from src.schemas.state import State

        hints = typing.get_type_hints(State)
        structured_fields = [
            "case_history_json",
            "citations_json",
            "timeline_json",
            "support_themes_json",
            "escalation_guidance_json",
            "hitl_draft_json",
            "approved_sources_json",
            "case_scope_json",
        ]
        for field in structured_fields:
            assert hints.get(field) is str, f"{field} must be str, not {hints.get(field)}"


# ── TC-08: required_trust_level enforced ─────────────────────────────────────


class TestTrustLevelEnforcement:
    def test_tc08_anon_caller_rejected_by_pre_process(self):
        """TC-08: ANONYMOUS caller cannot reach execute() in PreProcessNode."""
        from src.nodes.pre_process_node import PreProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PreProcessNode()
        state = _anon_state(user_input=_valid_scope_input())
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value

    def test_tc08_anon_caller_rejected_by_post_process(self):
        """TC-08: ANONYMOUS caller cannot reach execute() in PostProcessNode."""
        from src.nodes.post_process_node import PostProcessNode
        from framework.schemas.agent_status import AgentStatus

        node = PostProcessNode()
        state = _anon_state(result="", review_outcome="approved", hitl_draft_json="")
        result = node(state)
        assert result["status"] == AgentStatus.ERROR.value

    def test_tc08_inner_nodes_accept_anonymous(self):
        """TC-08: Inner DomainWorkflowGraph nodes accept ANONYMOUS callers."""
        from src.nodes.scope_validation_node import ScopeValidationNode
        from framework.schemas.agent_status import AgentStatus

        node = ScopeValidationNode()
        state = _anon_state(
            case_scope_json=to_json({"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
            approved_sources_json=to_json(["SRC-001"]),
        )
        result = node(state)
        assert result["status"] == AgentStatus.SUCCESS.value


# ── TC-11: emit_trace_event in every execute() ────────────────────────────────


class TestAuditEmission:
    def test_tc11_pre_process_emits_event(self, monkeypatch):
        """TC-11: PreProcessNode emits at least one domain trace event."""
        import src.nodes.pre_process_node as ppmod

        events: list[str] = []
        monkeypatch.setattr(ppmod, "emit_trace_event", lambda name, payload, state: events.append(name))

        from src.nodes.pre_process_node import PreProcessNode

        node = PreProcessNode()
        state = _vext_state(user_input=_valid_scope_input())
        node(state)

        assert any("PreProcessNode" in e for e in events)

    def test_tc11_scope_validation_emits_event(self, monkeypatch):
        """TC-11: ScopeValidationNode emits at least one domain trace event."""
        import src.nodes.scope_validation_node as svmod

        events: list[str] = []
        monkeypatch.setattr(svmod, "emit_trace_event", lambda name, payload, state: events.append(name))

        from src.nodes.scope_validation_node import ScopeValidationNode

        node = ScopeValidationNode()
        state = _anon_state(
            case_scope_json=to_json({"student_ref": "STU-001", "date_from": "2024-01-01", "date_to": "2024-12-31"}),
            approved_sources_json=to_json(["SRC-001"]),
        )
        node(state)

        assert any("ScopeValidationNode" in e for e in events)

    def test_tc11_post_process_emits_event(self, monkeypatch):
        """TC-11: PostProcessNode emits at least one domain trace event."""
        import src.nodes.post_process_node as ppmod

        events: list[str] = []
        monkeypatch.setattr(ppmod, "emit_trace_event", lambda name, payload, state: events.append(name))

        draft = to_json(
            {
                "timeline": [],
                "support_themes": [],
                "escalation_references": [],
                "citations": [],
                "limitations": [],
                "scope": {},
                "retrieval_coverage": "complete",
            }
        )

        from src.nodes.post_process_node import PostProcessNode

        node = PostProcessNode()
        state = _vext_state(
            result="",
            hitl_draft_json=draft,
            review_outcome="approved",
            review_notes="",
            citations_json=to_json([]),
            retrieval_coverage="complete",
        )
        node(state)

        assert any("PostProcessNode" in e for e in events)
