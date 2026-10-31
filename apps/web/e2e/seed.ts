// Seeds real data through the ForgeFlow API (the same calls an agent makes), so the UI tests
// exercise genuine diffs, risk scores, approvals and merges, not fixtures.
import type { APIRequestContext } from "@playwright/test";

export const API = `http://localhost:${process.env.FORGEFLOW_API_PORT ?? 8000}/api/v1`;

async function call<T>(req: APIRequestContext, method: "get" | "post", path: string, body?: unknown, token?: string): Promise<T> {
  const res = await req[method](`${API}${path}`, {
    data: body, headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok()) throw new Error(`${method.toUpperCase()} ${path} → ${res.status()} ${await res.text()}`);
  return res.json();
}

export const uid = () => Math.random().toString(36).slice(2, 8);

export async function seedRepo(req: APIRequestContext) {
  return call<{ id: string; name: string }>(req, "post", "/repositories", {
    name: `e2e-${uid()}`,
    initial_files: {
      "app/__init__.py": "",
      "app/auth.py": "def login(user, password):\n    return user == 'admin'\n",
      "app/util.py": "def add(a, b):\n    return a + b\n",
      "conftest.py": "",
      "tests/test_util.py": "from app.util import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n",
    },
    settings: { test_command: "pytest -q -p no:cacheprovider" },
  });
}

/** Register an agent, create a task + workspace, and run one execution that edits `path`. */
export async function seedWork(req: APIRequestContext, repoId: string, opts: { title: string; path: string; content: string; submit?: boolean }) {
  const agent = await call<{ id: string; name: string; token: string }>(req, "post", "/agents", { name: `bot_${uid()}`, model: "scripted-playbook", kind: "scripted" });
  const task = await call<{ id: string }>(req, "post", "/tasks", { repository_id: repoId, title: opts.title, agent_id: agent.id });
  const ws = await call<{ id: string }>(req, "post", "/workspaces", { task_id: task.id });
  const ex = await call<{ id: string }>(req, "post", "/executions", { workspace_id: ws.id }, agent.token);
  await call(req, "post", `/executions/${ex.id}/tools/write_file`, { args: { path: opts.path, content: opts.content } }, agent.token);
  await call(req, "post", `/executions/${ex.id}/tools/run_command`, { args: { argv: ["pytest", "-q", "-p", "no:cacheprovider"] } }, agent.token);
  await call(req, "post", `/executions/${ex.id}/finish`, { status: "SUCCESS", message: opts.title }, agent.token);
  if (opts.submit) await call(req, "post", `/workspaces/${ws.id}/review`, {});
  return { agent, task, workspace: ws, execution: ex };
}
