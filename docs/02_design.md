# Template Design Specification — EDU-C2-043 Student Support Case History Briefing Agent

## Position in AgentCore Architecture

- **Agent Class**: `Graph` (inherits `AgentBaseGraph`)
- **L1 Base**: AgentBaseGraph (Cat 2 — outer + inner BaseGraph)
- **Three-Layer Separation**:
  - State: flat TypedDict with `to_json`/`from_json` helpers (msgpack-safe)
  - Node: L1 FunctionNode inheritance; `execute(self, state: dict) -> dict` override only
  - Graph: composition via `register_nodes()`; no `add_edges()` override on outer graph

## Architecture Overview

### Node Configuration

| Node | Layer | Responsibility | Trust Level | Inherits |
|------|-------|----------------|-------------|---------|
| `initialize` | Outer | Framework default initialization | — | `InitializeNode` (framework) |
| `pre_process` (`PreProcessNode`) | Outer | Validates operator-authorized case scope JSON; normalizes bounded criteria; validates approved source IDs | `VERIFIED_EXTERNAL` | `FunctionNode` |
| `main` (`CaseHistoryBriefingGraphNode`) | Outer | Wraps inner DomainWorkflowGraph; receives runtime config and optional LLM client; propagates HITL interrupt | `VERIFIED_EXTERNAL` | `GraphNode` |
| `scope_validation` (`ScopeValidationNode`) | Inner | Re-validates scope completeness and source allowlist before retrieval | `ANONYMOUS` | `FunctionNode` |
| `history_retrieval` (`HistoryRetrievalNode`) | Inner | Retrieves normalized case-history events from approved sources via CaseHistoryService; preserves provenance; handles partial failures | `ANONYMOUS` | `FunctionNode` |
| `timeline_synthesis` (`TimelineSynthesisNode`) | Inner | Synthesizes events into chronological timeline and recurring support themes; retains citations; marks missing evidence | `ANONYMOUS` | `FunctionNode` |
| `escalation_guidance` (`EscalationGuidanceNode`) | Inner | Maps documented case indicators to configured institutional escalation references; marks gaps; presents as counselor decision support | `ANONYMOUS` | `FunctionNode` |
| `counselor_handoff` (`CounselorHandoffNode`) | Inner | Assembles counselor handoff draft; requires authorized human review via HITL interrupt(); handles approve/correct/reject resume outcomes | `ANONYMOUS` | `FunctionNode` |
| `post_process` (`PostProcessNode`) | Outer | Formats final briefing with timeline, themes, guidance refs, review disposition, provenance, limitations | `VERIFIED_EXTERNAL` | `FunctionNode` |
| `finalize` | Outer | Framework default finalization | — | `FinalizeNode` (framework) |

### Data Flow

```
START
  → initialize (framework)
  → pre_process          [S-1 VERIFIED_EXTERNAL boundary; S-2 scope JSON validation]
  → main (GraphNode)
      ↓ (inner DomainWorkflowGraph)
      scope_validation   [re-validates scope bounds + source allowlist]
      → history_retrieval  [CaseHistoryService adapter; normalized events + citations]
      → timeline_synthesis [chronological timeline + recurring themes; no diagnosis]
      → escalation_guidance [maps indicators → institutional refs; marks gaps]
      → counselor_handoff  [assembles draft; HITL interrupt() → human review]
                           ├─ approved  → review_outcome="approved"
                           ├─ corrected → review_outcome="corrected" + notes
                           └─ rejected  → review_outcome="rejected" + ERROR
      ↑ (merge_output back to outer state)
  → post_process         [formats final briefing; S-3 output gate]
  → finalize (framework)
END

Error routing: any ERROR status at scope_validation/history_retrieval/timeline_synthesis/
escalation_guidance → conditional_edges route to END (early exit)
```

### State Definition

| Field | Type | Purpose | Producer | Consumer |
|-------|------|---------|----------|---------|
| `user_input` | `str` | Raw operator case scope JSON payload | API | `PreProcessNode` |
| `validated_input` | `str` | Normalized validated scope JSON | `PreProcessNode` | `CaseHistoryBriefingGraphNode` |
| `case_scope_json` | `str` (JSON) | Bounded scope: student_ref (hashed), date_from, date_to, support_category | `PreProcessNode` | `ScopeValidationNode`, `HistoryRetrievalNode` |
| `approved_sources_json` | `str` (JSON) | Allowlisted source system IDs | `PreProcessNode` | `ScopeValidationNode`, `HistoryRetrievalNode` |
| `case_history_json` | `str` (JSON) | Normalized case-history events from approved sources | `HistoryRetrievalNode` | `TimelineSynthesisNode` |
| `citations_json` | `str` (JSON) | Source provenance citations for all retrieved events | `HistoryRetrievalNode` | `PostProcessNode` |
| `retrieval_coverage` | `str` | `complete` / `partial` / `empty` / `error` | `HistoryRetrievalNode` | `TimelineSynthesisNode`, `PostProcessNode` |
| `timeline_json` | `str` (JSON) | Chronological timeline of case events with source citations | `TimelineSynthesisNode` | `CounselorHandoffNode` |
| `support_themes_json` | `str` (JSON) | Recurring support themes (factual counts only) | `TimelineSynthesisNode` | `EscalationGuidanceNode`, `CounselorHandoffNode` |
| `escalation_guidance_json` | `str` (JSON) | Institutional escalation references mapped to case indicators | `EscalationGuidanceNode` | `CounselorHandoffNode` |
| `hitl_draft_json` | `str` (JSON) | Assembled counselor handoff draft pending human review | `CounselorHandoffNode` | `PostProcessNode` |
| `review_outcome` | `str` | `approved` / `corrected` / `rejected` / `""` | `CounselorHandoffNode` (post-resume) | `PostProcessNode` |
| `review_notes` | `str` | Counselor notes from HITL resume (corrections or rejection reason) | `CounselorHandoffNode` (post-resume) | `PostProcessNode` |
| `result` | `str` | Mapped from inner graph `get_output()`; consumed by outer `PostProcessNode` | `CaseHistoryBriefingGraphNode.merge_output()` | `PostProcessNode` |
| `formatted_output` | `str` | Final human-reviewed counselor handoff briefing | `PostProcessNode` | API response |

**State Constraints (mandatory):**
- Flat TypedDict only — no Pydantic, dataclass (msgpack incompatible)
- All structured fields JSON-encoded with `to_json()` — declared as `str`
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- `InvocationContext` via `config["configurable"]` only, never in State
- `to_json` / `from_json` helpers present and used consistently

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (`InvocationContext.from_state(state)` — in `HistoryRetrievalNode` for `ctx.secrets.require()`)
- [ ] ConnectionPolicy
- [x] SecurityViolationError (raised in `PreProcessNode._extra_security_gate_input()` and `PostProcessNode._extra_security_gate_output()`)
- [x] S-2: `_extra_security_gate_input()` — `PreProcessNode` validates input size and structural type before execute()
- [x] S-3: `_extra_security_gate_output()` — `PostProcessNode` validates formatted_output contains no prohibited decision-framing patterns
- [x] S-4: `emit_trace_event()` — at least one domain event inside each `execute()` across all nodes

### Composition Pattern

- **Pattern**: `GraphNode` (outer wraps inner `BaseGraph`)
- **Composition target**: `DomainWorkflowGraph` (inner 5-node pipeline)
- **Error propagation strategy**: `propagate` (inner errors raised as SubgraphError)
- **HITL propagation**: `propagate_hitl=True` — inner `CounselorHandoffNode.interrupt()` surfaced to outer API caller
- **Runtime config**: static registry metadata is in `config/agent.yaml`; `config/config.yaml` is passed to `Graph(config=...)` by the registry and standalone server
- **LLM injection contract**: the standalone adapter reads `ANTHROPIC_API_KEY` with `.get()`, stores the optional client in `config["llm"]`, and the outer graph constructs `CaseHistoryBriefingGraphNode(llm=self.config.get("llm"), config=self.config)`
- **Checkpointing**: `memory_enabled: true` and `hitl.enabled: true` cause the standalone adapter to compile with `MemorySaver`, matching registry behavior

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework.*`, `shared.*`, `langgraph.*`, own `src.*` only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | `AgentBaseGraph` | `AutonomousBaseGraph` | `AgentBaseGraph` | Fixed deterministic multi-step workflow; no autonomous think-act-observe loop needed |
| Inner graph parent | `BaseGraph` (custom topology) | `AgentBaseGraph` (standard slots) | `BaseGraph` | Domain nodes use custom names (scope_validation, history_retrieval, etc.) not pre_process/main/post_process |
| HITL position | Pre-synthesis gate | Post-assembly gate (counselor_handoff) | Post-assembly | Human reviewer needs complete briefing draft to make an informed review decision |
| Partial source failure | Abort (ERROR) | Continue with coverage flag | Continue (partial) | Partial history is better than no output; coverage flag ensures transparency |
| Escalation mapping | LLM-based inference | Static reference map | Static reference map | No inference needed — direct indicator-to-reference mapping avoids welfare decisions |
| propagate_hitl | `False` (HITL internal) | `True` (surface to outer caller) | `True` | Counselor must resume via the outer API; inner graph cannot complete the review loop alone |
| Generation mode | LLM | Deterministic | Deterministic | Timeline synthesis and escalation mapping are rule-based; optional LLM injection is retained only as the common scaffold construction contract |
