"""conftest.py — framework stubs and shared fixtures for EDU-C2-043 tests."""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types

import pytest


def _framework_installed() -> bool:
    try:
        return importlib.util.find_spec("framework") is not None
    except (ImportError, ValueError):
        return False


_USE_FRAMEWORK_STUBS = not _framework_installed()


def _make_stub_module(name: str, **attrs) -> types.ModuleType:
    if not _USE_FRAMEWORK_STUBS:
        return importlib.import_module(name)
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ── Framework stubs ────────────────────────────────────────────────────────────
# These stubs allow tests to import src.* without requiring the full AgentCore
# framework package. Each stub provides the minimal interface used by production code.


class _TrustLevel:
    ANONYMOUS = type("TrustLevel", (), {"value": "anonymous"})()
    VERIFIED_EXTERNAL = type("TrustLevel", (), {"value": "verified_external"})()
    INTERNAL = type("TrustLevel", (), {"value": "internal"})()

    @classmethod
    def from_value(cls, value: str):
        mapping = {
            "anonymous": cls.ANONYMOUS,
            "verified_external": cls.VERIFIED_EXTERNAL,
            "internal": cls.INTERNAL,
        }
        return mapping.get(value, cls.ANONYMOUS)


class _AgentStatus:
    SUCCESS = type("AgentStatus", (), {"value": "success"})()
    ERROR = type("AgentStatus", (), {"value": "error"})()
    PENDING = type("AgentStatus", (), {"value": "pending"})()


class _AgentState(dict):
    """Minimal AgentState stub — a plain dict for checkpoint safety tests."""

    pass


class _SecurityViolationError(Exception):
    pass


class _ConfigError(Exception):
    pass


# Stub secrets
class _SecretsProvider:
    def __init__(self, values: dict | None = None, **kwargs) -> None:
        self._values = values or {}

    def require(self, key: str) -> str:
        return self._values.get(key, f"FAKE_{key}_FOR_TEST")  # noqa: S106

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _InMemoryProvider(_SecretsProvider):
    pass


class _InvocationContext:
    def __init__(
        self,
        session_id="test",
        caller_trust_level=None,
        caller_id="",
        input_context=None,
        hitl_allowed=True,
        **kwargs,
    ):
        self.session_id = session_id
        self.caller_trust_level = caller_trust_level or _TrustLevel.ANONYMOUS
        self.caller_id = caller_id
        self.input_context = input_context or {}
        self.hitl_allowed = hitl_allowed
        self.secrets = _SecretsProvider()

    @classmethod
    def from_state(cls, state: dict) -> "_InvocationContext":
        tl_val = state.get("caller_trust_level", "anonymous")
        if hasattr(tl_val, "value"):
            tl_val = tl_val.value
        return cls(
            session_id=state.get("session_id", "test"),
            caller_trust_level=_TrustLevel.from_value(str(tl_val)),
            caller_id=state.get("caller_id", ""),
        )


# Stub emit_trace_event
_trace_events: list[dict] = []


def _emit_trace_event(event_name: str, payload: dict, state: dict) -> None:
    _trace_events.append({"event": event_name, "payload": payload})


# Stub FunctionNode
class _NodePipelineStub:
    required_trust_level = _TrustLevel.ANONYMOUS

    def __init__(self, *args, **kwargs) -> None:
        pass

    def __call__(self, state: dict) -> dict:
        tl = state.get("caller_trust_level")
        tl_val = tl.value if hasattr(tl, "value") else str(tl)
        required = self.required_trust_level.value

        trust_order = {"anonymous": 0, "verified_external": 1, "internal": 2}
        if trust_order.get(tl_val, -1) < trust_order.get(required, 0):
            return {
                "status": _AgentStatus.ERROR.value,
                "error": f"insufficient trust level: need {required}, got {tl_val}",
            }

        import framework.nodes.base_node as _bnmod

        _bnmod.emit_trace_event("node_start", {}, state)
        state = self._security_gate_input(state)
        result = self.execute(state)
        result = self._security_gate_output(result)
        _bnmod.emit_trace_event("node_complete", {}, state)
        return result

    def _security_gate_input(self, state: dict) -> dict:
        return self._extra_security_gate_input(state)

    def _security_gate_output(self, result: dict) -> dict:
        return self._extra_security_gate_output(result)

    def _extra_security_gate_input(self, state: dict) -> dict:
        return state

    def _extra_security_gate_output(self, result: dict) -> dict:
        return result

    def execute(self, state: dict) -> dict:  # pragma: no cover
        raise NotImplementedError


class _BaseNode(_NodePipelineStub):
    pass


class _FunctionNode(_BaseNode):
    """Fallback FunctionNode that enforces the framework's final-gate contract."""

    def __init_subclass__(cls, **kwargs) -> None:
        for gate in ("_security_gate_input", "_security_gate_output"):
            if gate in cls.__dict__:
                raise TypeError(f"Overriding {gate!r} is forbidden in FunctionNode subclasses")
        super().__init_subclass__(**kwargs)


# Stub GraphNode
class _GraphNode:
    error_strategy = "propagate"
    propagate_hitl = False

    def __init__(self, llm=None, config: dict | None = None, **kwargs) -> None:
        self._llm = llm
        self._config = config or {}

    def get_subgraph(self):  # pragma: no cover
        raise NotImplementedError

    def extract_input(self, state):  # pragma: no cover
        return state.get("validated_input", "")

    def merge_output(self, state, sub_result):  # pragma: no cover
        return {}

    def _parent_config(self) -> dict:
        return {}


# Stub AgentBaseGraph
class _AgentBaseGraph:
    required_trust_level = _TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, config: dict | None = None, **kwargs) -> None:
        self.config = config or {}
        self._config = self.config
        self._nodes: dict = {}
        self._secrets_provider = None
        self.register_nodes()

    def register_nodes(self) -> None:
        pass

    @property
    def name(self) -> str:  # pragma: no cover
        return "stub"

    @property
    def state_schema(self):  # pragma: no cover
        return _AgentState

    def invoke(self, *args, **kwargs) -> dict:  # pragma: no cover
        return {}

    def compile(self, checkpointer=None) -> None:
        self.register_nodes()

    def provision_secrets(self, *args, **kwargs) -> None:
        if args:
            self._secrets_provider = args[0]


# Stub BaseGraph
class _BaseGraph:
    def __init__(self, config: dict | None = None, **kwargs) -> None:
        self._config = config or {}
        self._nodes: dict = {}
        self._sg = type(
            "SG",
            (),
            {
                "add_edge": lambda *a, **kw: None,
                "add_conditional_edges": lambda *a, **kw: None,
            },
        )()
        self.register_nodes()

    def register_nodes(self) -> None:  # pragma: no cover
        pass

    def add_edges(self) -> None:  # pragma: no cover
        pass

    def route(self, state):  # pragma: no cover
        return "end"

    def get_output(self, state):  # pragma: no cover
        return {}

    def _validate_config(self) -> None:
        pass

    @property
    def name(self) -> str:  # pragma: no cover
        return "stub_inner"

    @property
    def state_schema(self):  # pragma: no cover
        return _AgentState


# Stub langgraph
class _GraphInterrupt(Exception):
    def __init__(self, value=None):
        self.value = value
        super().__init__(value)


class _Interrupt:
    def __init__(self, value=None, id="placeholder-id", **kwargs):
        self.value = value
        self.id = id


def _interrupt(value=None):
    raise _GraphInterrupt(value)


# Register all stubs
_make_stub_module("framework")
_make_stub_module("framework.schemas")
_make_stub_module("framework.schemas.trust_level", TrustLevel=_TrustLevel)
_make_stub_module("framework.schemas.agent_status", AgentStatus=_AgentStatus)
_make_stub_module("framework.schemas.agent_state", AgentState=_AgentState)
_make_stub_module("framework.schemas.invocation_context", InvocationContext=_InvocationContext)
_make_stub_module("framework.nodes")
_make_stub_module("framework.nodes.function_node", FunctionNode=_FunctionNode)
_make_stub_module("framework.nodes.base_node", BaseNode=_BaseNode, emit_trace_event=_emit_trace_event)
_make_stub_module("framework.nodes.graph_node", GraphNode=_GraphNode)
_make_stub_module("framework.graph")
_make_stub_module("framework.graph.agent_base_graph", AgentBaseGraph=_AgentBaseGraph)
_make_stub_module("framework.graph.base_graph", BaseGraph=_BaseGraph)
_make_stub_module("framework.errors", SecurityViolationError=_SecurityViolationError, ConfigError=_ConfigError)
_make_stub_module("shared")
_make_stub_module("shared.utils")
_make_stub_module("shared.utils.audit_logger", emit_trace_event=_emit_trace_event)
_make_stub_module("shared.secrets", factory=lambda **kw: _InMemoryProvider())
_make_stub_module("shared.secrets.inmemory_provider", InMemoryProvider=_InMemoryProvider)
_make_stub_module("shared.services")
_make_stub_module("shared.services.llm")
_make_stub_module("langgraph")
_make_stub_module("langgraph.types", interrupt=_interrupt, Interrupt=_Interrupt)
_make_stub_module("langgraph.errors", GraphInterrupt=_GraphInterrupt)
_make_stub_module("langgraph.graph", START="__start__", END="__end__")
_make_stub_module("langgraph.checkpoint")


class _MemorySaver:
    pass


_make_stub_module("langgraph.checkpoint.memory", MemorySaver=_MemorySaver)
_make_stub_module("framework.secrets")
_make_stub_module("framework.secrets.context", bound_secrets=lambda *a, **kw: __import__("contextlib").nullcontext())
_make_stub_module("framework.utils")


def _load_config(path: str) -> dict:
    import yaml

    with open(path) as stream:
        return yaml.safe_load(stream) or {}


_make_stub_module("framework.utils.config_loader", load_config=_load_config)


if not _USE_FRAMEWORK_STUBS:
    from framework.secrets.context import bound_secrets as _real_bound_secrets
    from shared.secrets.inmemory_provider import InMemoryProvider as _RealInMemoryProvider

    @pytest.fixture(autouse=True)
    def _bind_synthetic_test_secrets():
        """Provide the synthetic service credential used by domain-node tests."""
        provider = _RealInMemoryProvider({"CASE_HISTORY_SERVICE_TOKEN": "mock-case-history-key-for-testing"})
        with _real_bound_secrets(provider):
            yield
