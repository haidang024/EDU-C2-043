"""DomainWorkflowGraph — inner BaseGraph for EDU-C2-043 Student Support Case History Briefing."""

from __future__ import annotations

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from src.nodes.counselor_handoff_node import CounselorHandoffNode
from src.nodes.escalation_guidance_node import EscalationGuidanceNode
from src.nodes.history_retrieval_node import HistoryRetrievalNode
from src.nodes.scope_validation_node import ScopeValidationNode
from src.nodes.timeline_synthesis_node import TimelineSynthesisNode
from src.schemas.state import State


class DomainWorkflowGraph(BaseGraph):
    """Inner domain workflow graph for EDU-C2-043.

    Implements the multi-step support-case history briefing pipeline:
        START → scope_validation → history_retrieval → timeline_synthesis
              → escalation_guidance → counselor_handoff → END

    counselor_handoff uses HITL interrupt() to pause for authorized human review.
    The graph routes to END on error status after each step.

    Called by CaseHistoryBriefingGraphNode.get_subgraph() in graph.py.
    """

    @property
    def name(self) -> str:
        return "edu_c2_043_support_case_workflow"

    @property
    def state_schema(self) -> type:
        return State

    def _validate_config(self) -> None:
        """No mandatory inner-graph config keys for this pipeline."""
        pass

    def register_nodes(self) -> None:
        """Register all domain step nodes.

        No super() call — BaseGraph.register_nodes() is abstract.
        All inner nodes must use ANONYMOUS trust level (Cat 2 rule).
        """
        self._nodes["scope_validation"] = ScopeValidationNode()
        self._nodes["history_retrieval"] = HistoryRetrievalNode()
        self._nodes["timeline_synthesis"] = TimelineSynthesisNode()
        self._nodes["escalation_guidance"] = EscalationGuidanceNode()
        self._nodes["counselor_handoff"] = CounselorHandoffNode()

    def add_edges(self) -> None:
        """Wire the pipeline with conditional error-exit routing."""
        self._sg.add_edge(START, "scope_validation")
        self._sg.add_conditional_edges("scope_validation", self.route)
        self._sg.add_conditional_edges("history_retrieval", self.route)
        self._sg.add_conditional_edges("timeline_synthesis", self.route)
        self._sg.add_conditional_edges("escalation_guidance", self.route)
        self._sg.add_edge("counselor_handoff", END)

    def route(self, state: AgentState) -> str:
        """Route to next pipeline step or END on error status."""
        if state.get("status") == AgentStatus.ERROR.value:
            return str(END)

        # Advance through the pipeline in node_history order
        node_history = state.get("node_history", [])
        last_node = node_history[-1] if node_history else ""

        return {
            "ScopeValidationNode": "history_retrieval",
            "HistoryRetrievalNode": "timeline_synthesis",
            "TimelineSynthesisNode": "escalation_guidance",
            "EscalationGuidanceNode": "counselor_handoff",
        }.get(last_node, END)

    def get_output(self, state: AgentState) -> dict:
        """Shape the sub_result dict returned to CaseHistoryBriefingGraphNode.merge_output().

        Returns the handoff draft and enriched fields needed by the outer PostProcessNode.
        """
        return {
            "output": state.get("hitl_draft_json", ""),
            "status": state.get("status", AgentStatus.SUCCESS.value),
            "review_outcome": state.get("review_outcome", ""),
            "review_notes": state.get("review_notes", ""),
            "citations_json": state.get("citations_json", ""),
            "retrieval_coverage": state.get("retrieval_coverage", "empty"),
            "history_source": state.get("history_source"),
            "timeline_json": state.get("timeline_json", ""),
            "support_themes_json": state.get("support_themes_json", ""),
            "escalation_guidance_json": state.get("escalation_guidance_json", ""),
            # error_log must cross the subgraph boundary: GraphNode builds
            # SubgraphError from sub_result["error_log"], and an empty list
            # leaves the caller with a generic, unactionable reason.
            "error_log": state.get("error_log", []),
        }
