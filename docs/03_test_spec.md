# Test Specification — EDU-C2-043 Student Support Case History Briefing Agent

## Test Strategy
- Coverage target: 90%
- Test types: Unit / Integration / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | File | Result |
|-------|------|----------------|------|--------|
| TC-01 | State contract: flat TypedDict with `to_json`/`from_json` helpers; all structured fields typed as `str` | Type check pass; no Pydantic/dataclass; helpers present and functional | `tests/unit/test_nodes.py::TestStateContract` | Pass |
| TC-02 | `SecurityViolationError` fires on oversized or structurally invalid input | Error raised in `_extra_security_gate_input()` | `tests/unit/test_nodes.py::TestPreProcessNode::test_bl04_non_json_input` | Pass |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement moved to CI) | `tests/proof_of_boundary/test_state_safety.py` | Pass |
| TC-04 | `InvocationContext` not stored in State | State schema contains no `InvocationContext` annotation | `tests/proof_of_boundary/test_state_safety.py` | Pass |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from all `execute()` bodies | Code review + grep | Pass |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py` | Pass |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden | `tests/unit/test_framework_compliance_tc06_tc07.py` | Pass |
| TC-08 | `required_trust_level` enforced: ANONYMOUS caller rejected by VERIFIED_EXTERNAL nodes | S-1 gate returns ERROR; `execute()` never reached | `tests/unit/test_nodes.py::TestTrustLevelEnforcement` | Pass |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial — validates input size and JSON structure | Domain-specific input checks execute correctly | `tests/unit/test_nodes.py::TestPreProcessNode::test_bl02_missing_required_scope_fields` | Pass |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial — rejects prohibited decision-framing | Domain-specific output check rejects welfare/eligibility language | `PostProcessNode._extra_security_gate_output` | Pass |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path | `tests/unit/test_nodes.py::TestAuditEmission` | Pass |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | File | Result |
|-------|----------|------|----------------|------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on every node invocation path | No silent failures | `tests/unit/test_nodes.py::TestAuditEmission` | Pass |
| PB-2 | State serialization | Post-invoke State contains only primitives (no Pydantic/dataclass/JWT) | State safety scan: 0 violations | `tests/proof_of_boundary/test_state_safety.py` | Pass |
| PB-3 | L1 → External service | `FakeCaseHistoryService` returns configured events with provenance; error sources raise `RuntimeError`; no raw credentials in output | Fake adapter mapping correct; provenance intact | `tests/integration/test_external_service_pb3.py` | Pass |
| PB-4 | Import isolation | No Level 0 (`agenticstar`) imports in `src/` | AST scan: 0 violations | `tests/proof_of_boundary/test_import_isolation.py` | Pass |
| PB-5 | Checkpoint safety | Static state scan always runs; raw-ingress persistence assertion runs when the installed framework exposes the required ingress hooks | No credential fields; conditional framework capability gate is explicit | `tests/proof_of_boundary/test_state_safety.py` | Conditional |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → `node_complete`; negative: ANONYMOUS rejected by VERIFIED_EXTERNAL node | Order verified; S-1 rejection confirmed | `tests/proof_of_boundary/test_pb_invoke_order.py` | Pass |
| PB-7 | HITL interrupt propagation | `GraphInterrupt` propagates from `CounselorHandoffNode` when `hitl_allowed=True`; `hitl_allowed=False` suppresses interrupt; all three resume outcomes (approve/correct/reject) handled correctly | Propagation confirmed; no deadlock; correct outcome routing | `tests/proof_of_boundary/test_pb7_hitl_interrupt_propagation.py` | Pass |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | File |
|-------|------|-------|----------------|------|
| BL-01 | Valid scope input parsed and normalized | JSON with student_ref, date_from, date_to, approved_sources | `case_scope_json` and `approved_sources_json` populated; SUCCESS | `test_nodes.py::test_bl01_valid_scope_input` |
| BL-02 | Missing required scope fields → ERROR | JSON missing `date_to` | STATUS=ERROR, error_log populated | `test_nodes.py::test_bl02_missing_required_scope_fields` |
| BL-03 | Empty approved_sources → ERROR | JSON with `approved_sources: []` | STATUS=ERROR | `test_nodes.py::test_bl03_empty_approved_sources` |
| BL-04 | Non-JSON input → ERROR | Plain string, not JSON | STATUS=ERROR | `test_nodes.py::test_bl04_non_json_input` |
| BL-05 | ANONYMOUS caller rejected by PreProcessNode | ANONYMOUS trust + valid input | STATUS=ERROR (S-1 gate) | `test_nodes.py::test_bl05_trust_level_enforced` |
| BL-06 | Valid scope passes ScopeValidationNode | Valid scope + non-empty sources | SUCCESS | `test_nodes.py::test_bl06_valid_scope_passes` |
| BL-07 | Invalid date range (from > to) → ERROR | date_from > date_to | STATUS=ERROR | `test_nodes.py::test_bl07_invalid_date_range` |
| BL-08 | Empty sources in ScopeValidationNode → ERROR | Empty sources list | STATUS=ERROR | `test_nodes.py::test_bl08_no_sources` |
| BL-09 | Events retrieved from approved sources | FakeService with 1 event for SRC-001 | events in state; coverage=complete | `test_nodes.py::test_bl09_retrieves_events_from_approved_sources` |
| BL-10 | Partial source failure → partial coverage | SRC-001 ok, SRC-002 error | coverage=partial; SUCCESS (not ERROR) | `test_nodes.py::test_bl10_partial_source_failure` |
| BL-11 | No events → empty coverage | FakeService no events | coverage=empty | `test_nodes.py::test_bl11_no_events_returns_empty_coverage` |
| BL-12 | Timeline is chronological | 2 events, out of order | timeline[0].date < timeline[1].date | `test_nodes.py::test_bl12_timeline_is_chronological` |
| BL-13 | Themes counted by event_type | 2 academic_concern, 1 welfare_concern events | academic_concern count=2, welfare_concern count=1 | `test_nodes.py::test_bl13_themes_counted_by_event_type` |
| BL-14 | No diagnosis or welfare judgment in synthesis | Events with mental_health_concern | No "is eligible" / "must be" in output | `test_nodes.py::test_bl14_no_diagnosis_or_welfare_judgment` |
| BL-15 | Known theme maps to institutional reference | academic_concern theme | guidance_ref=EDU-ESC-001 in output | `test_nodes.py::test_bl15_maps_known_theme_to_reference` |
| BL-16 | Unknown theme produces gap entry | Custom unknown theme | `[no institutional reference]` gap entry present | `test_nodes.py::test_bl16_unknown_theme_produces_gap_entry` |
| BL-17 | No autonomous escalation in guidance output | welfare_concern theme | No "we have escalated" / "student contacted" in output | `test_nodes.py::test_bl17_no_autonomous_escalation` |
| BL-18 | `interrupt()` raised when hitl_allowed=True | hitl_allowed=True + no existing draft | `GraphInterrupt` raised | `test_nodes.py::test_bl18_hitl_interrupt_raised` |
| BL-19 | No interrupt when hitl_allowed=False | hitl_allowed=False | No `GraphInterrupt`; SUCCESS | `test_nodes.py::test_bl19_hitl_skipped_when_not_allowed` |
| BL-20 | Approved resume → SUCCESS | review_outcome=approved + existing draft | SUCCESS; review_outcome=approved | `test_nodes.py::test_bl20_approved_resume` |
| BL-21 | Corrected resume → SUCCESS with notes | review_outcome=corrected + notes | SUCCESS; review_notes preserved | `test_nodes.py::test_bl21_corrected_resume` |
| BL-22 | Rejected resume → ERROR | review_outcome=rejected + reason | STATUS=ERROR | `test_nodes.py::test_bl22_rejected_resume` |
| BL-23 | No welfare/emergency decision in handoff output | Any valid state | No welfare decision language in output | `test_nodes.py::test_bl23_no_welfare_decision` |
| BL-24 | `formatted_output` present in PostProcessNode result | Approved draft | formatted_output populated; includes EDU-C2-043 header | `test_nodes.py::test_bl24_formatted_output_present` |
| BL-25 | Rejected review yields ERROR status in PostProcessNode | review_outcome=rejected | STATUS=ERROR; rejection message in formatted_output | `test_nodes.py::test_bl25_rejected_produces_error` |
| BL-26 | Limitations section included in output | Any approved draft | "Limitations" section present; "human-reviewed" in text | `test_nodes.py::test_bl26_limitations_included_in_output` |
| BL-27 | No raw credentials in formatted_output | Any invocation | No credential strings in output | `test_nodes.py::test_bl27_no_raw_credentials_in_output` |

## Test Execution Summary
- Execution date: 2026-08-18 (local CI)
- Full suite: 64 collected — 63 passed, 0 failed, 1 skipped
- Proof-of-boundary subset: 17 collected — 16 passed, 0 failed, 1 skipped
- Static gates: Ruff formatting/lint and mypy passed
- Stage 5 provisional invoke: HTTP 200, `awaiting_human`, overall `PASS`
- Coverage: not collected by `check-local.sh`

PB-5 is the single skip because AgentCore 1.0.0 does not expose the newer
`BaseGraph` checkpoint-ingress protection hooks. The template-pinned
`agenticstar-agentcore[anthropic]==1.0.1` was unavailable from the configured
package index, so the complete local CI path was exercised against the
already-installed AgentCore 1.0.0 compatibility environment. The CI-required
version remains unchanged at 1.0.1.
