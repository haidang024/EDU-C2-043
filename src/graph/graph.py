"""Graph — outer AgentBaseGraph for EDU-C2-043 Student Support Case History Briefing Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, cast

from langgraph.checkpoint.memory import MemorySaver

from framework.graph.agent_base_graph import AgentBaseGraph
from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.nodes.post_process_node import PostProcessNode
from src.nodes.pre_process_node import PreProcessNode
from src.schemas.state import State
from src.services.error_presenter import classify

if TYPE_CHECKING:
    from src.graph.domain_workflow_graph import DomainWorkflowGraph


class CaseHistoryBriefingGraphNode(GraphNode):
    """GraphNode wrapper for the inner DomainWorkflowGraph; assigned to the 'main' slot.

    Wraps the multi-step support-case briefing pipeline (scope_validation →
    history_retrieval → timeline_synthesis → escalation_guidance → counselor_handoff).

    propagate_hitl=True surfaces the HITL interrupt() from the inner
    counselor_handoff node to the outer graph caller so that the human reviewer
    can resume through the outer API.
    """

    # "handle" (not "propagate"): a propagated SubgraphError aborts the run
    # before merge_output(), so post_process never executes and the Marketplace
    # runner returns a bare RuntimeError with no reason. on_subgraph_error()
    # converts the failure into a domain field instead.
    error_strategy: ClassVar[str] = "handle"
    # Surface HITL interrupt to the outer graph so the API caller can resume
    propagate_hitl: ClassVar[bool] = True
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm: object | None = None, config: dict | None = None) -> None:
        super().__init__()
        self._llm = llm
        self._config: dict = dict(config or {})
        self._config["llm"] = llm
        self._subgraph: DomainWorkflowGraph | None = None

    def get_subgraph(self) -> "DomainWorkflowGraph":
        """Instantiate and return the inner domain workflow graph."""
        from src.graph.domain_workflow_graph import DomainWorkflowGraph

        if self._subgraph is None:
            self._subgraph = DomainWorkflowGraph(config=self._parent_config())
            hitl_enabled = self._config.get("hitl", {}).get("enabled", False)
            needs_checkpointer = self._config.get("memory_enabled") or hitl_enabled
            self._subgraph.compile(checkpointer=MemorySaver() if needs_checkpointer else None)
        return self._subgraph

    def extract_input(self, state: AgentState) -> str:
        """Return the validated case scope input for the inner graph."""
        return str(state.get("validated_input", state.get("user_input", "")))

    def execute(self, state: AgentState) -> dict[str, Any]:
        if state.get("input_error_message"):
            return {"status": AgentStatus.SUCCESS.value}
        return cast(dict[str, Any], super().execute(state))

    def on_subgraph_error(self, state: AgentState, error: Exception) -> dict[str, Any]:
        """Carry an inner failure as a domain field so the pipeline keeps running.

        Returning status=error here would route straight to finalize, skipping the
        post-process node; the Marketplace runner then drops `output` and the caller
        sees only "invocation did not succeed". post_process renders
        workflow_error_message into an actionable message instead.
        """
        error_log = getattr(error, "error_log", None) or []
        records = [str(e) for e in error_log if str(e).strip()]
        # Classify here; never carry the raw record forward. error_log entries
        # embed a traceback with absolute paths, source lines, and secret names,
        # and workflow_error_message is rendered to the caller by post_process.
        # The full record stays in error_log for operator/S-4 audit use.
        return {
            "status": AgentStatus.SUCCESS.value,
            "workflow_error_message": classify(records[-1] if records else str(error)),
        }

    def merge_output(self, state: AgentState, sub_result: dict) -> dict:
        """Map inner graph sub_result fields back into the outer state.

        Designed together with DomainWorkflowGraph.get_output().
        Returns only the keys this node changes.
        """
        return {
            "result": sub_result.get("output", ""),
            "status": sub_result.get("status", ""),
            "review_outcome": sub_result.get("review_outcome", ""),
            "review_notes": sub_result.get("review_notes", ""),
            "citations_json": sub_result.get("citations_json", ""),
            "retrieval_coverage": sub_result.get("retrieval_coverage", "empty"),
            "history_source": sub_result.get("history_source"),
            "timeline_json": sub_result.get("timeline_json", ""),
            "support_themes_json": sub_result.get("support_themes_json", ""),
            "escalation_guidance_json": sub_result.get("escalation_guidance_json", ""),
            "hitl_draft_json": sub_result.get("output", ""),
        }

    def _parent_config(self) -> dict:
        """Forward runtime configuration, including the optional LLM client."""
        return dict(self._config)


class Graph(AgentBaseGraph):
    """Outer Cat 2 AgentBaseGraph for EDU-C2-043 Student Support Case History Briefing Agent.

    Pipeline: initialize → pre_process → main (CaseHistoryBriefingGraphNode)
              → post_process → finalize

    pre_process validates operator-authorized scope at VERIFIED_EXTERNAL trust.
    main wraps the inner DomainWorkflowGraph (scope → retrieval → synthesis → guidance → HITL).
    post_process formats the final human-reviewed counselor handoff briefing.
    """

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict | None = None) -> None:
        # MUST set self._config before super().__init__() because super calls register_nodes()
        self._config: dict = config or {}
        super().__init__(config=self._config)

    @property
    def name(self) -> str:
        return "EDU-C2-043"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        """Register outer backbone nodes.

        super().register_nodes() injects InitializeNode and FinalizeNode.
        FunctionNode subclasses (PreProcessNode, PostProcessNode) take no constructor args.
        GraphNode subclass (CaseHistoryBriefingGraphNode) accepts config=.
        """
        super().register_nodes()
        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = CaseHistoryBriefingGraphNode(
            llm=self.config.get("llm"),
            config=self.config,
        )
        self._nodes["post_process"] = PostProcessNode(config=self.config)

    def get_output(self, state: AgentState) -> dict[str, Any]:
        output = cast(dict[str, Any], super().get_output(state))
        output["generation_mode"] = state.get("generation_mode")
        output["provider_error_message"] = state.get("provider_error_message")
        # Operator-facing: "live" or "fixture". The rendered briefing is
        # identical either way, so this is the only signal distinguishing them.
        output["history_source"] = state.get("history_source")
        _set_marketplace_guidance(output, state, "Case history briefing request")
        return output

    # add_edges() is NOT overridden — backbone wiring belongs to the framework


def _set_marketplace_guidance(output: dict[str, Any], state: AgentState, subject: str) -> None:
    context = state.get("input_context")
    message = state.get("input_error_message")
    if not (isinstance(context, dict) and "conversation_history" in context and message):
        return
    lines = [f"{subject} could not be processed.", "", f"Reason: {message}"]
    guidance = state.get("input_error_guidance")
    if isinstance(guidance, list) and guidance:
        lines.extend(["", "How to continue:"])
        lines.extend(f"- {item}" for item in guidance)
    output["output"] = "\n".join(lines)
