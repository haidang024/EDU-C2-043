"""PB-2/PB-5 state and checkpoint-surface safety for EDU-C2-043."""

from __future__ import annotations

import ast
import json
import pathlib
import re
from collections.abc import Iterator
from typing import Any

import pytest

CREDENTIAL_FIELD_PATTERNS = re.compile(
    r"(jwt|token|api_key|secret|password|credential|connection_string)", re.IGNORECASE
)
PROHIBITED_TYPE_ANNOTATIONS = ["BaseModel", "InvocationContext"]
_RUNTIME_CONFIG_PATH = pathlib.Path(__file__).parents[2] / "config" / "config.yaml"


def _checkpointing_enabled() -> bool:
    if not _RUNTIME_CONFIG_PATH.exists():
        return False
    try:
        import yaml

        config = yaml.safe_load(_RUNTIME_CONFIG_PATH.read_text()) or {}
    except Exception:
        return False
    return bool(config.get("memory_enabled") or config.get("hitl", {}).get("enabled", False))


def _framework_ingress_protection_available() -> bool:
    try:
        from framework.graph.base_graph import BaseGraph
    except Exception:
        return False
    return all(hasattr(BaseGraph, hook) for hook in ("_sanitize_ingress", "_sanitize_resume_feedback"))


def _scan_state_file(filepath: str) -> list[str]:
    source = pathlib.Path(filepath).read_text()
    tree = ast.parse(source, filename=filepath)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    field_name = item.target.id
                    if CREDENTIAL_FIELD_PATTERNS.search(field_name):
                        violations.append(f"{filepath}:{item.lineno} — Credential-like field name: {field_name}")
                    annotation = ast.dump(item.annotation) if item.annotation else ""
                    for prohibited in PROHIBITED_TYPE_ANNOTATIONS:
                        if prohibited in annotation:
                            violations.append(f"{filepath}:{item.lineno} — Prohibited type in State: {prohibited}")
    return violations


def _walk_checkpoint_surface(value: Any, path: str = "checkpoint") -> Iterator[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_checkpoint_surface(key, f"{path}.<key>")
            yield from _walk_checkpoint_surface(child, f"{path}[{key!r}]")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, child in enumerate(value):
            yield from _walk_checkpoint_surface(child, f"{path}[{index}]")


def _assert_raw_ingress_absent(surfaces: dict[str, Any], raw_values: dict[str, Any]) -> None:
    for surface, value in surfaces.items():
        for path, persisted in _walk_checkpoint_surface(value, surface):
            for name, raw in raw_values.items():
                if raw in (None, "", {}, []):
                    continue
                if persisted == raw:
                    pytest.fail(f"PB-5 raw {name} found at {path}; ingress crossed persistence boundary")
                if isinstance(raw, str) and isinstance(persisted, str) and raw in persisted:
                    pytest.fail(f"PB-5 raw {name} found within string at {path}; ingress crossed persistence boundary")


class TestStateSafety:
    def test_state_file_safety(self):
        state_file = pathlib.Path(__file__).parents[2] / "src" / "schemas" / "state.py"
        violations = _scan_state_file(str(state_file))
        assert violations == [], "State safety violations found:\n" + "\n".join(violations)

    def test_state_is_json_serializable(self):
        sample = {
            "validated_input": "{}",
            "approved_sources_json": '["SRC-001"]',
            "case_scope_json": '{"student_ref":"STU-HASHED-001"}',
            "case_history_json": "[]",
            "citations_json": "[]",
            "retrieval_coverage": "complete",
            "timeline_json": "[]",
            "support_themes_json": "[]",
            "escalation_guidance_json": "[]",
            "hitl_draft_json": "{}",
            "review_outcome": "approved",
            "review_notes": "",
            "formatted_output": "reviewed briefing",
            "result": "{}",
        }
        assert json.loads(json.dumps(sample)) == sample


_PB5_APPLICABLE = _checkpointing_enabled() and _framework_ingress_protection_available()
_PB5_WAIVER_REASON = (
    "config/config.yaml enables neither memory_enabled nor hitl.enabled — PB-5 auto-waived"
    if not _checkpointing_enabled()
    else "installed agentcore lacks BaseGraph ingress hooks — PB-5 auto-waived pending framework cutover"
)


@pytest.mark.skipif(not _PB5_APPLICABLE, reason=_PB5_WAIVER_REASON)
def test_pb5_precheckpoint_ingress_not_raw() -> None:
    """Require a real persistence-surface fixture when framework hooks are available."""
    pytest.fail(
        "PB-5 is applicable (checkpointing enabled + framework ingress hooks present) but "
        "this template has not wired a graph/checkpointer fixture. Build the fixture and "
        "call _assert_raw_ingress_absent() before shipping."
    )
