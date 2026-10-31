"""Regenerate docs/openapi.json and docs/api.md from the running application's OpenAPI schema."""

import json
import tempfile
from pathlib import Path

from forgeflow_api.config import Settings
from forgeflow_api.main import TAGS, create_app

ROOT = Path(__file__).resolve().parents[1]

app = create_app(Settings(data_dir=Path(tempfile.mkdtemp())))
spec = app.openapi()
(ROOT / "docs" / "openapi.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

by_tag: dict[str, list[tuple[str, str, str]]] = {}
for path, ops in spec["paths"].items():
    for method, op in ops.items():
        tag = (op.get("tags") or ["other"])[0]
        summary = op.get("summary") or ""
        by_tag.setdefault(tag, []).append((method.upper(), path, summary))

lines = [
    "# ForgeFlow REST API",
    "",
    "Base URL: `http://localhost:8000`. All resource endpoints live under `/api/v1`.",
    "Interactive documentation: `/docs` (Swagger UI) and `/redoc`; the machine-readable schema is",
    "[`openapi.json`](openapi.json) (regenerate with `python scripts/gen_api_docs.py`).",
    "",
    "## Authentication",
    "",
    "Send `Authorization: Bearer <token>`.",
    "",
    "| Principal | Token | May |",
    "|---|---|---|",
    "| Human | `FORGEFLOW_ADMIN_TOKEN` (or no token when `FORGEFLOW_AUTH_MODE=dev`) | everything except agent tool calls |",
    "| Agent | `ffa_…` issued by `POST /api/v1/agents` (shown once; only its SHA-256 is stored) | start executions on its own workspaces, call tools, checkpoint, submit for review, request merges |",
    "",
    "Approvals, policy changes, repository/agent registration and rollbacks require a human principal.",
    "Tool calls require the agent that owns the execution. Humans cannot run agent tools.",
    "",
    "## Errors",
    "",
    "Errors are JSON: `{\"error\": \"<code>\", \"message\": \"…\", \"details\": {…}}`. Codes: `bad_request` (400),",
    "`forbidden` (403), `policy_denied` (403), `not_found` (404), `invalid_state` (409), `version_engine` (409),",
    "`immutable` (409).",
    "",
    "Path parameters named `{ref}` accept a full UUID, a unique UUID prefix of at least 4 hex characters, or,",
    "for repositories and agents, the name.",
    "",
    "## Real-time events",
    "",
    "`GET ws://localhost:8000/api/v1/ws/events?backfill=50[&token=…][&repository_id=…|task_id=…|workspace_id=…|execution_id=…|agent_id=…]`",
    "streams every audit event as JSON after the transaction that produced it commits.",
    "",
    "## Endpoints",
]
for tag in [t["name"] for t in TAGS]:
    rows = by_tag.get(tag)
    if not rows:
        continue
    desc = next(t["description"] for t in TAGS if t["name"] == tag)
    lines += ["", f"### {tag}", "", desc, "", "| Method | Path | Summary |", "|---|---|---|"]
    lines += [f"| {m} | `{p}` | {s} |" for m, p, s in sorted(rows, key=lambda r: (r[1], r[0]))]
lines += [
    "",
    "## Agent tool calls",
    "",
    "`POST /api/v1/executions/{ref}/tools/{tool}` with body `{\"args\": {...}}`:",
    "",
    "| Tool | Args | Policy action | Notes |",
    "|---|---|---|---|",
    "| `read_file` | `path` | `file.read` | content returned; only its hash is recorded |",
    "| `write_file` | `path`, `content`, `encoding?` (`utf-8`/`base64`) | `file.write` | bytes stored content-addressed for replay |",
    "| `delete_file` | `path` | `file.delete` | |",
    "| `list_files` | `prefix?` | — | excludes `.git`, `node_modules` |",
    "| `run_command` | `argv` (list) or `command` (string), `timeout?` | `command.run` | no shell; command allow/deny lists; test output parsed |",
    "",
    "Paths are confined to the workspace (no absolute paths, `..`, symlink escapes or `.git`).",
    "Every call, including denied ones, is stored as a `ToolCall` and emits audit events.",
    "",
]
(ROOT / "docs" / "api.md").write_text("\n".join(lines), encoding="utf-8")
print(f"wrote docs/api.md and docs/openapi.json ({len(spec['paths'])} paths)")
