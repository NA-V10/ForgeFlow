"""Client SDK for agents running under ForgeFlow.

Agents authenticate with the token issued at registration and act exclusively
through mediated tools; they never see host paths::

    client = ForgeFlowClient("http://localhost:8000", token=os.environ["FORGEFLOW_AGENT_TOKEN"])
    with client.execution(workspace_id, model="claude-opus-5-5") as run:
        src = run.read_file("app/auth.py")
        run.write_file("app/auth.py", src.replace("TODO", "done"))
        result = run.run_command(["pytest", "-q"])
        run.checkpoint_on_finish("Implement OAuth")
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx


class ForgeFlowError(RuntimeError):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None) -> None:
        super().__init__(f"[{status} {code}] {message}")
        self.status, self.code, self.message, self.details = status, code, message, details or {}


class PolicyDeniedError(ForgeFlowError):
    pass


def _raise_for(resp: httpx.Response) -> None:
    if resp.is_success:
        return
    try:
        body = resp.json()
    except ValueError:
        body = {"error": "http_error", "message": resp.text}
    if isinstance(body.get("detail"), (str, list)):
        body = {"error": "http_error", "message": str(body["detail"])}
    cls = PolicyDeniedError if body.get("error") == "policy_denied" else ForgeFlowError
    raise cls(resp.status_code, body.get("error", "error"), body.get("message", resp.text), body.get("details"))


class ForgeFlowClient:
    def __init__(self, base_url: str = "http://localhost:8000", token: str | None = None,
                 client: httpx.Client | None = None, timeout: float = 900.0) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if client is not None:
            self.http = client
            self._headers = headers
        else:
            self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
            self._headers = headers
        self.prefix = "/api/v1"

    # ------------------------------------------------------------------ http
    def request(self, method: str, path: str, /, **kw: Any) -> Any:
        headers = {**self._headers, **kw.pop("headers", {})}
        resp = self.http.request(method, self.prefix + path, headers=headers, **kw)
        _raise_for(resp)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.content

    def get(self, path: str, /, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})

    def post(self, path: str, json: Any = None, /, **params: Any) -> Any:
        return self.request("POST", path, json=json if json is not None else {},
                            params={k: v for k, v in params.items() if v is not None})

    # ---------------------------------------------------------------- agents
    def me(self) -> dict:
        return self.get("/agents/me")

    def create_workspace(self, task_id: str, permissions: dict | None = None) -> dict:
        return self.post("/workspaces", {"task_id": task_id, "permissions": permissions})

    def start_execution(self, workspace_id: str, model: str | None = None, model_version: str | None = None,
                        environment: dict | None = None) -> "Execution":
        data = self.post("/executions", {"workspace_id": workspace_id, "model": model,
                                         "model_version": model_version, "environment": environment or {}})
        return Execution(self, data)

    @contextmanager
    def execution(self, workspace_id: str, **kw: Any) -> Iterator["Execution"]:
        run = self.start_execution(workspace_id, **kw)
        try:
            yield run
        except BaseException as exc:
            if not run.finished:
                run.finish("FAILED", error=f"{type(exc).__name__}: {exc}")
            raise
        else:
            if not run.finished:
                run.finish("SUCCESS")

    def submit_review(self, workspace_id: str) -> dict:
        return self.post(f"/workspaces/{workspace_id}/review")

    def request_merge(self, workspace_id: str, execute: bool = False) -> dict:
        return self.post("/merges", {"workspace_id": workspace_id, "execute": execute})


class Execution:
    def __init__(self, client: ForgeFlowClient, data: dict) -> None:
        self.client = client
        self.data = data
        self.id: str = data["id"]
        self.finished = False
        self._message: str | None = None

    def tool(self, name: str, **args: Any) -> dict:
        return self.client.post(f"/executions/{self.id}/tools/{name}", {"args": args})

    def read_file(self, path: str) -> str:
        return self.tool("read_file", path=path)["content"]

    def write_file(self, path: str, content: str) -> dict:
        return self.tool("write_file", path=path, content=content)

    def delete_file(self, path: str) -> dict:
        return self.tool("delete_file", path=path)

    def list_files(self, prefix: str = "") -> list[str]:
        return self.tool("list_files", prefix=prefix)["files"]

    def run_command(self, argv: list[str] | str, timeout: float | None = None) -> dict:
        key = "argv" if isinstance(argv, list) else "command"
        return self.tool("run_command", **{key: argv, "timeout": timeout})

    def checkpoint_on_finish(self, message: str) -> None:
        self._message = message

    def finish(self, status: str = "SUCCESS", summary: dict | None = None, error: str | None = None,
               checkpoint: bool = True, message: str | None = None) -> dict:
        data = self.client.post(f"/executions/{self.id}/finish", {
            "status": status, "summary": summary or {}, "error": error, "checkpoint": checkpoint,
            "message": message or self._message,
        })
        self.finished = True
        self.data = data
        return data


__all__ = ["Execution", "ForgeFlowClient", "ForgeFlowError", "PolicyDeniedError"]
