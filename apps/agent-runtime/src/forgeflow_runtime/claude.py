"""Claude-backed planner: a manual tool-use loop over ForgeFlow's mediated tools.

The model never touches the filesystem: each tool_use block becomes a ForgeFlow
tool call, so policy, path confinement and provenance apply exactly as for any
other agent. Policy denials are returned to the model as ``is_error`` results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ff_agent_sdk import Execution, ForgeFlowError

log = logging.getLogger("forgeflow.runtime.claude")

DEFAULT_MODEL = "claude-opus-5-5"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List files in the workspace, optionally under a directory prefix.",
        "input_schema": {"type": "object", "properties": {"prefix": {"type": "string"}},
                         "additionalProperties": False},
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 file from the workspace. Paths are relative to the repository root.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
                         "additionalProperties": False},
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a file with the complete new content.",
        "input_schema": {"type": "object",
                         "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                         "required": ["path", "content"], "additionalProperties": False},
    },
    {
        "name": "delete_file",
        "description": "Delete a file from the workspace.",
        "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
                         "additionalProperties": False},
    },
    {
        "name": "run_command",
        "description": "Run a command (argv list, no shell) in the workspace sandbox, e.g. [\"pytest\", \"-q\"]. "
                       "Network access and many executables are blocked by policy.",
        "input_schema": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
                         "required": ["argv"], "additionalProperties": False},
    },
]

SYSTEM = """You are a software engineering agent working inside a ForgeFlow workspace: an isolated Git worktree.
Use the tools to inspect the repository, make the change the task asks for, and run the tests.
Keep changes focused on the task. When the tests pass and the task is done, reply with a short summary of what \
you changed and why; ForgeFlow will checkpoint your work and route it to review. If a tool call is denied by \
policy, do not try to work around the policy - adapt your approach or explain the limitation."""


class ClaudePlanner:
    def __init__(self, model: str = DEFAULT_MODEL, max_turns: int = 40, effort: str = "high",
                 client: Any | None = None) -> None:
        self.model = model
        self.model_version = None
        self.max_turns = max_turns
        self.effort = effort
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic  # optional dependency: pip install "forgeflow-runtime[llm]"

            self._client = anthropic.Anthropic()
        return self._client

    def _execute(self, run: Execution, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        try:
            if name == "read_file":
                return run.read_file(args["path"]), False
            if name == "list_files":
                return "\n".join(run.list_files(args.get("prefix", ""))), False
            if name == "write_file":
                r = run.write_file(args["path"], args["content"])
                return f"wrote {r['path']} ({r['size']} bytes)", False
            if name == "delete_file":
                run.delete_file(args["path"])
                return f"deleted {args['path']}", False
            if name == "run_command":
                r = run.run_command(list(args["argv"]))
                out = f"exit code {r['exit_code']}\n--- stdout ---\n{r['stdout'][-8000:]}\n--- stderr ---\n" \
                      f"{r['stderr'][-4000:]}"
                return out, r["exit_code"] != 0
            return f"unknown tool {name}", True
        except ForgeFlowError as exc:
            return f"{exc.code}: {exc.message}", True
        except (KeyError, TypeError) as exc:
            return f"invalid input for {name}: {exc}", True

    def _converse(self, run: Execution, messages: list[dict[str, Any]]) -> str:
        for _ in range(self.max_turns):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if response.stop_reason == "refusal":
                raise RuntimeError(f"model declined the task: {getattr(response, 'stop_details', None)}")
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "max_tokens":
                raise RuntimeError("model response hit max_tokens before finishing")
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return "\n".join(b.text for b in response.content if b.type == "text")
            results = []
            for block in tool_uses:
                args = block.input if isinstance(block.input, dict) else json.loads(block.input)
                content, is_error = self._execute(run, block.name, args)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                "is_error": is_error})
            messages.append({"role": "user", "content": results})
        raise RuntimeError(f"agent did not finish within {self.max_turns} turns")

    def act(self, run: Execution, task: dict, state: dict) -> dict:
        prompt = f"Task: {task['title']}\n\n{task.get('description') or ''}".strip()
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
        summary = self._converse(run, messages)
        state["_claude_messages"] = messages
        return {"actions": [{"step": "claude", "summary": summary}], "message": summary.splitlines()[0][:200]
                if summary else None}

    def fix(self, run: Execution, task: dict, state: dict) -> bool:
        messages = state.get("_claude_messages")
        if not messages:
            return False
        messages.append({"role": "user", "content": "The validation command failed:\n\n"
                         f"{state.get('validation_output', '')}\n\nFix the problem and re-run the tests."})
        self._converse(run, messages)
        return True
