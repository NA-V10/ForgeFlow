"""A minimal state graph with LangGraph's construction API.

Agent workflows are declared with ``StateGraph`` / ``add_node`` / ``add_edge`` /
``add_conditional_edges`` / ``compile().invoke(state)``, the same construction
API as LangGraph, so workflow definitions can be ported to LangGraph (with a
typed state schema) without restructuring. This implementation has no
dependencies and adds a step limit to stop runaway loops.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

START = "__start__"
END = "__end__"

State = dict[str, Any]
Node = Callable[[State], State | None]


class CompiledGraph:
    def __init__(self, nodes: dict[str, Node], edges: dict[str, str],
                 conditional: dict[str, tuple[Callable[[State], str], dict[str, str] | None]],
                 max_steps: int) -> None:
        self.nodes, self.edges, self.conditional, self.max_steps = nodes, edges, conditional, max_steps

    def _next(self, current: str, state: State) -> str:
        if current in self.conditional:
            router, mapping = self.conditional[current]
            key = router(state)
            return mapping[key] if mapping else key
        if current in self.edges:
            return self.edges[current]
        raise RuntimeError(f"node '{current}' has no outgoing edge")

    def invoke(self, state: State) -> State:
        """Run to END. ``state`` is updated in place so callers can inspect it after a failure."""
        current = self._next(START, state)
        steps = 0
        while current != END:
            steps += 1
            if steps > self.max_steps:
                raise RuntimeError(f"graph exceeded {self.max_steps} steps (possible loop)")
            update = self.nodes[current](state)
            if update:
                state.update(update)
            state.setdefault("trace", []).append(current)
            current = self._next(current, state)
        return state


class StateGraph:
    def __init__(self, state_schema: Any = dict, max_steps: int = 100) -> None:
        self.state_schema = state_schema
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, str] = {}
        self.conditional: dict[str, tuple[Callable[[State], str], dict[str, str] | None]] = {}
        self.max_steps = max_steps

    def add_node(self, name: str, fn: Node) -> "StateGraph":
        if name in self.nodes or name in (START, END):
            raise ValueError(f"invalid or duplicate node name '{name}'")
        self.nodes[name] = fn
        return self

    def add_edge(self, source: str, target: str) -> "StateGraph":
        self.edges[source] = target
        return self

    def add_conditional_edges(self, source: str, router: Callable[[State], str],
                              mapping: dict[str, str] | None = None) -> "StateGraph":
        self.conditional[source] = (router, mapping)
        return self

    def set_entry_point(self, name: str) -> "StateGraph":
        return self.add_edge(START, name)

    def compile(self) -> CompiledGraph:
        targets = set(self.edges.values()) | {t for _, m in self.conditional.values() if m for t in m.values()}
        unknown = {t for t in targets if t not in self.nodes and t != END}
        if unknown:
            raise ValueError(f"edges point to unknown nodes: {sorted(unknown)}")
        if START not in self.edges and START not in self.conditional:
            raise ValueError("graph has no entry point")
        return CompiledGraph(self.nodes, self.edges, self.conditional, self.max_steps)

