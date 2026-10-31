"""Agent workflow: setup → act → validate → (fix → validate)* → finish → submit.

Planners decide *what* to do; every action goes through the ForgeFlow tool API,
so the control plane records and polices it. Two planners ship:

* :class:`PlaybookPlanner`: deterministic, YAML-scripted edits (simulated agents
  for demos and tests).
* :class:`ClaudePlanner`: a Claude tool-use loop over the same mediated tools.
"""

from __future__ import annotations

import logging
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from ff_agent_sdk import Execution, ForgeFlowClient, ForgeFlowError, PolicyDeniedError

from .graph import END, StateGraph

log = logging.getLogger("forgeflow.runtime")


class Planner(Protocol):
    model: str
    model_version: str | None

    def act(self, run: Execution, task: dict, state: dict) -> dict: ...

    def fix(self, run: Execution, task: dict, state: dict) -> bool:
        """Try to repair failing validation. Return False if no fix is available."""
        ...


# --------------------------------------------------------------- playbooks
@dataclass
class Playbook:
    steps: list[dict[str, Any]]
    validate: list[str] | None = None
    fix_steps: list[dict[str, Any]] = field(default_factory=list)
    message: str | None = None
    model: str = "scripted-playbook"
    model_version: str | None = "v1"

    @classmethod
    def load(cls, path: str | Path) -> "Playbook":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(steps=data.get("steps", []), validate=data.get("validate"), fix_steps=data.get("fix_steps", []),
                   message=data.get("message"), model=data.get("model", "scripted-playbook"),
                   model_version=str(data.get("model_version", "v1")))


def apply_step(run: Execution, step: dict[str, Any]) -> dict[str, Any]:
    if "write" in step:
        s = step["write"]
        run.write_file(s["path"], s["content"])
        return {"step": "write", "path": s["path"]}
    if "replace" in step:
        s = step["replace"]
        src = run.read_file(s["path"])
        if s["old"] not in src:
            raise ValueError(f"replace: text not found in {s['path']}: {s['old'][:60]!r}")
        run.write_file(s["path"], src.replace(s["old"], s["new"], s.get("count", 1)))
        return {"step": "replace", "path": s["path"]}
    if "append" in step:
        s = step["append"]
        src = run.read_file(s["path"])
        run.write_file(s["path"], src.rstrip("\n") + "\n" + s["content"])
        return {"step": "append", "path": s["path"]}
    if "delete" in step:
        run.delete_file(step["delete"]["path"])
        return {"step": "delete", "path": step["delete"]["path"]}
    if "run" in step:
        r = run.run_command(step["run"])
        return {"step": "run", "command": step["run"], "exit_code": r["exit_code"]}
    raise ValueError(f"unknown playbook step: {sorted(step)}")


class PlaybookPlanner:
    def __init__(self, playbook: Playbook) -> None:
        self.playbook = playbook
        self.model = playbook.model
        self.model_version = playbook.model_version

    def act(self, run: Execution, task: dict, state: dict) -> dict:
        results = []
        for step in self.playbook.steps:
            try:
                results.append(apply_step(run, step))
            except PolicyDeniedError as exc:
                results.append({"step": "denied", "error": exc.message})
        return {"actions": results}

    def fix(self, run: Execution, task: dict, state: dict) -> bool:
        if not self.playbook.fix_steps or state.get("fixes", 0) > 0:
            return False
        for step in self.playbook.fix_steps:
            apply_step(run, step)
        return True


# ------------------------------------------------------------------ workflow
def build_workflow(client: ForgeFlowClient, planner: Planner, validate: list[str] | None, max_fixes: int = 2,
                   submit: bool = True):
    def setup(state: dict) -> dict:
        task = client.get(f"/tasks/{state['task_id']}")
        ws_id = state.get("workspace_id")
        if not ws_id:
            ws_id = client.create_workspace(task["id"])["id"]
        run = client.start_execution(ws_id, model=planner.model, model_version=planner.model_version,
                                     environment={"runtime": "forgeflow-runtime", "python": platform.python_version(),
                                                  "planner": type(planner).__name__})
        return {"task": task, "workspace_id": ws_id, "run": run, "execution_id": run.id, "fixes": 0}

    def act(state: dict) -> dict:
        return planner.act(state["run"], state["task"], state)

    def validate_node(state: dict) -> dict:
        if not validate:
            return {"tests_ok": True, "tests": None}
        r = state["run"].run_command(validate)
        return {"tests_ok": r["exit_code"] == 0, "tests": r.get("tests"), "validation_output": r["stdout"][-4000:]}

    def fix(state: dict) -> dict:
        fixed = planner.fix(state["run"], state["task"], state)
        return {"fixes": state["fixes"] + 1, "fix_available": fixed}

    def route_after_validate(state: dict) -> str:
        if state["tests_ok"] or state["fixes"] >= max_fixes or state.get("fix_available") is False:
            return "finish"
        return "fix"

    def route_after_fix(state: dict) -> str:
        return "validate" if state.get("fix_available") else "finish"

    def finish(state: dict) -> dict:
        run: Execution = state["run"]
        summary = {"actions": len(state.get("actions", [])), "fix_attempts": state["fixes"],
                   "validated": validate is not None, "tests_ok": state["tests_ok"]}
        data = run.finish("SUCCESS", summary=summary,
                          message=state.get("message") or f"{state['task']['title']}")
        return {"execution": data}

    def submit_node(state: dict) -> dict:
        if not submit or state["execution"].get("result_commit") == state["execution"].get("base_commit"):
            return {"review": None}
        try:
            return {"review": client.submit_review(state["workspace_id"])}
        except ForgeFlowError as exc:
            return {"review": None, "review_error": exc.message}

    g = StateGraph(dict)
    g.add_node("setup", setup)
    g.add_node("act", act)
    g.add_node("validate", validate_node)
    g.add_node("fix", fix)
    g.add_node("finish", finish)
    g.add_node("submit", submit_node)
    g.set_entry_point("setup")
    g.add_edge("setup", "act")
    g.add_edge("act", "validate")
    g.add_conditional_edges("validate", route_after_validate, {"fix": "fix", "finish": "finish"})
    g.add_conditional_edges("fix", route_after_fix, {"validate": "validate", "finish": "finish"})
    g.add_edge("finish", "submit")
    g.add_edge("submit", END)
    return g.compile()


def run_agent(client: ForgeFlowClient, task_id: str, planner: Planner, *, workspace_id: str | None = None,
              validate: list[str] | None = None, submit: bool = True, message: str | None = None) -> dict:
    """Run one agent on one task. Failures are recorded on the execution before re-raising."""
    workflow = build_workflow(client, planner, validate, submit=submit)
    state: dict[str, Any] = {"task_id": task_id, "workspace_id": workspace_id, "message": message}
    try:
        return workflow.invoke(state)
    except Exception as exc:
        run = state.get("run")
        if isinstance(run, Execution) and not run.finished:
            run.finish("FAILED", error=f"{type(exc).__name__}: {exc}", checkpoint=False)
        raise
