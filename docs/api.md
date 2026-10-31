# ForgeFlow REST API

Base URL: `http://localhost:8000`. All resource endpoints live under `/api/v1`.
Interactive documentation: `/docs` (Swagger UI) and `/redoc`; the machine-readable schema is
[`openapi.json`](openapi.json) (regenerate with `python scripts/gen_api_docs.py`).

## Authentication

Send `Authorization: Bearer <token>`.

| Principal | Token | May |
|---|---|---|
| Human | `FORGEFLOW_ADMIN_TOKEN` (or no token when `FORGEFLOW_AUTH_MODE=dev`) | everything except agent tool calls |
| Agent | `ffa_…` issued by `POST /api/v1/agents` (shown once; only its SHA-256 is stored) | start executions on its own workspaces, call tools, checkpoint, submit for review, request merges |

Approvals, policy changes, repository/agent registration and rollbacks require a human principal.
Tool calls require the agent that owns the execution. Humans cannot run agent tools.

## Errors

Errors are JSON: `{"error": "<code>", "message": "…", "details": {…}}`. Codes: `bad_request` (400),
`forbidden` (403), `policy_denied` (403), `not_found` (404), `invalid_state` (409), `version_engine` (409),
`immutable` (409).

Path parameters named `{ref}` accept a full UUID, a unique UUID prefix of at least 4 hex characters, or,
for repositories and agents, the name.

## Real-time events

`GET ws://localhost:8000/api/v1/ws/events?backfill=50[&token=…][&repository_id=…|task_id=…|workspace_id=…|execution_id=…|agent_id=…]`
streams every audit event as JSON after the transaction that produced it commits.

## Endpoints

### repositories

Git-backed repositories, history, files and line provenance

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/repositories` | List Repositories |
| POST | `/api/v1/repositories` | Register a repository |
| GET | `/api/v1/repositories/{ref}` | Get Repository |
| GET | `/api/v1/repositories/{ref}/blame` | Per-line provenance for a file |
| GET | `/api/v1/repositories/{ref}/branches` | Branches |
| GET | `/api/v1/repositories/{ref}/commits` | Commits |
| GET | `/api/v1/repositories/{ref}/file` | File Content |
| GET | `/api/v1/repositories/{ref}/files` | Files |
| GET | `/api/v1/repositories/{ref}/graph` | Repository → branches → tasks → agents → workspaces → changes → merges |
| GET | `/api/v1/repositories/{ref}/provenance` | Why does this line exist? |
| PATCH | `/api/v1/repositories/{ref}/settings` | Update Settings |

### agents

Agent identities and credentials

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/agents` | List Agents |
| POST | `/api/v1/agents` | Register an agent and issue its token |
| GET | `/api/v1/agents/me` | The agent authenticated by the bearer token |
| GET | `/api/v1/agents/{ref}` | Get Agent |
| POST | `/api/v1/agents/{ref}/rotate-token` | Rotate Token |

### tasks

Units of work assigned to agents

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/tasks` | List Tasks |
| POST | `/api/v1/tasks` | Create Task |
| GET | `/api/v1/tasks/{ref}` | Get Task |
| PATCH | `/api/v1/tasks/{ref}` | Update Task |

### workspaces

Isolated git worktrees, diffs and checkpoints

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/checkpoints` | List Checkpoints |
| GET | `/api/v1/checkpoints/{ref}` | Get Checkpoint |
| POST | `/api/v1/checkpoints/{ref}/restore` | Restore Checkpoint |
| GET | `/api/v1/workspaces` | List Workspaces |
| POST | `/api/v1/workspaces` | Create an isolated workspace |
| GET | `/api/v1/workspaces/{ref}` | Get Workspace |
| POST | `/api/v1/workspaces/{ref}/abandon` | Abandon |
| POST | `/api/v1/workspaces/{ref}/checkpoints` | Create Checkpoint |
| GET | `/api/v1/workspaces/{ref}/conflicts` | Semantic conflicts with other open workspaces |
| GET | `/api/v1/workspaces/{ref}/diff` | Standard and semantic diff |
| GET | `/api/v1/workspaces/{ref}/file` | Read a file from the live workspace |

### executions

Agent runs and mediated tool calls

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/executions` | List Executions |
| POST | `/api/v1/executions` | Start an execution (agent token required) |
| GET | `/api/v1/executions/{ref}` | Get Execution |
| POST | `/api/v1/executions/{ref}/finish` | Finish |
| POST | `/api/v1/executions/{ref}/reproduce` | Replay an execution and report what could and could not be reproduced |
| POST | `/api/v1/executions/{ref}/tools/{tool}` | Call a mediated tool (owning agent only) |

### reviews

Review submission, semantic diff and risk

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/reviews` | List Reviews |
| GET | `/api/v1/reviews/{ref}` | Get Review |
| GET | `/api/v1/risk-assessments` | List Risk |
| POST | `/api/v1/workspaces/{ref}/review` | Submit a workspace for review (semantic diff, risk, policy, approvals) |
| POST | `/api/v1/workspaces/{ref}/risk` | Compute a deterministic risk assessment |

### approvals

Human approval gates

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/approvals` | List Approvals |
| GET | `/api/v1/approvals/{ref}` | Approval with agent, task, action, files, diff, risk, policy reason, tests and evidence |
| POST | `/api/v1/approvals/{ref}/approve` | Approve |
| POST | `/api/v1/approvals/{ref}/reject` | Reject |

### policies

YAML policy documents and evaluation

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/policies` | List Policies |
| POST | `/api/v1/policies/check` | Evaluate an action against the effective policies |
| GET | `/api/v1/policies/effective` | The merged policy set that applies to a repository |
| PUT | `/api/v1/policies/{scope}` | Publish a new version of a policy document ('global' or a repository id/name) |

### merges

Merge queue and the 7-step merge gate

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/merges` | Merge queue (open merges have a position) |
| POST | `/api/v1/merges` | Queue a workspace for merge and run the merge gate |
| GET | `/api/v1/merges/{ref}` | Get Merge |
| POST | `/api/v1/merges/{ref}/evaluate` | Re-run the merge gate |
| POST | `/api/v1/merges/{ref}/execute` | Merge if (and only if) the gate returns READY |
| POST | `/api/v1/merges/{ref}/rollback` | Revert a completed merge on the target branch |

### observability

Events, real-time stream, dashboard and settings

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/artifacts` | List Artifacts |
| GET | `/api/v1/artifacts/{ref}/content` | Download artifact content |
| GET | `/api/v1/changes` | File-level changes with provenance |
| GET | `/api/v1/dashboard` | Dashboard |
| GET | `/api/v1/events` | Audit events (immutable, hash-chained) |
| GET | `/api/v1/events/verify` | Verify the integrity of the audit hash chain |
| GET | `/api/v1/inbox` | Everything waiting on a human, ranked P0-P2 deterministically |
| GET | `/api/v1/settings` | Runtime configuration (no secrets) |
| GET | `/api/v1/threads` | Per-workspace agent thread summaries for the command center |
| GET | `/health` | Health |

## Agent tool calls

`POST /api/v1/executions/{ref}/tools/{tool}` with body `{"args": {...}}`:

| Tool | Args | Policy action | Notes |
|---|---|---|---|
| `read_file` | `path` | `file.read` | content returned; only its hash is recorded |
| `write_file` | `path`, `content`, `encoding?` (`utf-8`/`base64`) | `file.write` | bytes stored content-addressed for replay |
| `delete_file` | `path` | `file.delete` | |
| `list_files` | `prefix?` | — | excludes `.git`, `node_modules` |
| `run_command` | `argv` (list) or `command` (string), `timeout?` | `command.run` | no shell; command allow/deny lists; test output parsed |

Paths are confined to the workspace (no absolute paths, `..`, symlink escapes or `.git`).
Every call, including denied ones, is stored as a `ToolCall` and emits audit events.
