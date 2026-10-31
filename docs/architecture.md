# ForgeFlow Architecture

ForgeFlow is a control plane for repositories where many AI coding agents work at
once. Git stays the storage engine for the MVP. ForgeFlow adds the layer Git does not
have: who (which agent, model, task) produced a change, under what evidence, at what
risk, under which policy, and who approved it.

```
                ┌──────────────────────────────────────────────────────────────┐
                │                         Clients                              │
                │   forge CLI (Typer)     Web dashboard (Next.js)    Agents    │
                └───────┬───────────────────────┬─────────────────────┬────────┘
                        │ REST /api/v1          │ REST + WebSocket    │ agent-sdk (REST)
                ┌───────▼───────────────────────▼─────────────────────▼────────┐
                │                    apps/api  (FastAPI)                        │
                │  routers ─► services ─► domain packages                      │
                │  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐    │
                │  │ tasks /  │ │ execution │ │ review / │ │ merge queue  │    │
                │  │workspaces│ │ + tools   │ │ approvals│ │              │    │
                │  └────┬─────┘ └─────┬─────┘ └────┬─────┘ └──────┬───────┘    │
                │       │   EventLog (hash-chained, append-only) + EventBus    │
                └───────┼─────────────┼────────────┼──────────────┼────────────┘
                        │             │            │              │
   ┌────────────────────▼──┐ ┌────────▼───────┐ ┌──▼──────────┐ ┌─▼─────────────┐
   │ packages/version-engine│ │packages/sandbox│ │policy-engine│ │ merge-engine  │
   │ VersionEngine protocol │ │ CommandPolicy  │ │ risk-engine │ │ semantic-diff │
   │ └ GitEngine (git CLI)  │ │ Docker / Local │ │ provenance  │ │ (tree-sitter) │
   └──────────┬─────────────┘ └───────┬────────┘ └─────────────┘ └───────────────┘
              │                       │
   bare repos + git worktrees    isolated workspace dirs        PostgreSQL · Redis · MinIO
```

## Principles → mechanisms

| Principle | Mechanism |
|---|---|
| Git is the source of truth | Managed **bare** repositories; every workspace is a `git worktree` on its own branch `forgeflow/ws/<id>`; checkpoints and merges are ordinary commits. |
| Replaceable version engine | All Git access goes through the `VersionEngine` protocol (`packages/version-engine`). Nothing else shells out to `git`. |
| Deterministic over LLM | Diffs, semantic diffs (Tree-sitter ASTs), conflict detection, risk scores and policy decisions are pure functions of repository state + config. No model is consulted. |
| Every agent action auditable | Agents never touch the filesystem directly: file reads/writes and commands are **tool calls mediated by the API**, recorded as `ToolCall` rows and `Event`s before and after execution. |
| Explicit security boundaries | Path confinement (no `..`, absolute paths or symlink escapes), command allow/deny lists, network policy, Docker sandbox, approval gates enforced server-side. |
| Concurrency | Each agent gets its own worktree; merges use `git merge-tree --write-tree` + `update-ref` compare-and-swap under a per-repository lock, so two merges can never silently overwrite each other. |

## Packages

| Package | Python module | Responsibility |
|---|---|---|
| `packages/version-engine` | `ff_version` | `VersionEngine` protocol and `GitEngine`: init/import repos, worktrees, commits with provenance trailers, diffs, blame, merge-tree conflict checks, CAS merges, reverts. |
| `packages/semantic-diff` | `ff_semantic` | Tree-sitter symbol extraction (Python, JS, TS), symbol-level diffs, route/import/dependency/config diffs, domain grouping, dependency graph and semantic conflict detection. |
| `packages/risk-engine` | `ff_risk` | Weighted deterministic signals → 0-100 score, severity and reasons. |
| `packages/policy-engine` | `ff_policy` | YAML policies; `deny > require_approval > require_review > allow` precedence. |
| `packages/provenance` | `ff_provenance` | Commit trailer format, provenance records, line → commit → execution → agent → task → model tracing. |
| `packages/sandbox` | `ff_sandbox` | Path confinement, `CommandPolicy`, `NetworkPolicy`, `DockerSandbox` and `LocalSandbox` runners. |
| `packages/merge-engine` | `ff_merge` | The 7-step merge gate producing `READY / BLOCKED / REQUIRES_APPROVAL / CONFLICT`. |
| `packages/agent-sdk` | `ff_agent_sdk` | HTTP client agents use to open executions and call tools. |
| `apps/api` | `forgeflow_api` | FastAPI control plane: persistence, services, REST, WebSocket, event log. |
| `apps/cli` | `forgeflow_cli` | `forge` command-line client (REST). |
| `apps/agent-runtime` | `forgeflow_runtime` | Agent workflow on a state graph with LangGraph's construction API (setup → act → validate → fix → finish → submit); playbook (simulated) and Claude planners. |
| `apps/web` | — | Next.js dashboard. |

Domain packages do not import FastAPI, SQLAlchemy or each other's internals (the merge
engine depends on the *interfaces* of semantic-diff, risk and policy). Each has its own
tests under `packages/*/tests`.

## Lifecycle of a change

1. `forge task create` → `Task(PENDING)` with the repository's current head as base commit.
2. `forge workspace create` → `git worktree add` at the base commit on `forgeflow/ws/<id>` → `Workspace(CREATED)`.
3. An agent opens an `Execution` (model, model version, environment) → workspace `RUNNING`, task `RUNNING`.
4. The agent calls tools (`read_file`, `write_file`, `delete_file`, `list_files`, `run_command`) through the API. Each call is checked against path confinement + command policy + policy engine, executed, and recorded with input, output, files affected and exit code.
5. `checkpoint` commits the worktree with provenance trailers (`ForgeFlow-Execution`, `-Agent`, `-Task`, `-Model`) → `Checkpoint` + `Change` rows (one per file, with line stats).
6. Execution finishes → test results summarised → workspace `CHECKPOINTED`.
7. `forge review` submits the workspace: semantic diff, risk assessment and policy evaluation are computed and stored; approvals are created when policy or risk demands → workspace/task `REVIEW`.
8. `forge merge` runs the merge gate; on `READY` the merge is committed with CAS on the target ref → workspace `MERGED`, task `COMPLETED`; other open workspaces in the queue are re-evaluated.

## Concurrency

* Every agent works in its own worktree; there is no shared mutable checkout.
* Worktree creation and merges take a per-repository file lock; the final `update-ref <new> <old>`
  is a compare-and-swap, so a merge computed against a stale head fails and is re-evaluated.
* After a merge, every other open merge in the repository is re-evaluated (without tests), so
  textual and semantic conflicts introduced by the merge surface immediately in the queue.
* The audit chain head is locked before it is read. On PostgreSQL this is `SELECT … FOR UPDATE`;
  on SQLite a no-op `UPDATE` takes the database write lock first, because SQLite ignores `FOR UPDATE`.

## Event log

`events` is append-only. Each row stores `prev_hash` and `hash = sha256(prev_hash ‖ canonical_json(event))`
per repository, so tampering with history is detectable (`GET /api/v1/events/verify`).
The ORM refuses UPDATE/DELETE on events. Every event is also published on the
`EventBus` (Redis pub/sub in production, in-process fan-out in dev/tests) and streamed
to dashboards over `/api/v1/ws/events`.

## Storage adapters

| Concern | Production | Development / tests |
|---|---|---|
| Metadata | PostgreSQL (`FORGEFLOW_DATABASE_URL=postgresql+psycopg://…`) | SQLite file |
| Event fan-out | Redis pub/sub (`FORGEFLOW_REDIS_URL`) | in-process bus |
| Artifacts | S3 / MinIO (`FORGEFLOW_S3_*`) | local directory |
| Sandbox | Docker (`FORGEFLOW_SANDBOX=docker`) | local subprocess with policy (weaker isolation; flagged) |

## Security model

Agent code and commands are untrusted.

* **Filesystem**: the API resolves every agent-supplied path against the workspace root and rejects absolute paths, `..` traversal, symlink escapes and writes into `.git`. The host path of a workspace is never returned to agents (the agent SDK only sees workspace IDs).
* **Commands**: `CommandPolicy` checks the executable against an allow list and the full command line against deny patterns (e.g. `rm -rf /`, `curl`, `sudo`, `git push`). Commands are passed as argv lists, never through a shell.
* **Network**: `NetworkPolicy` (`none` by default). In the Docker sandbox it maps to `--network none`. The local sandbox cannot enforce it and says so in the execution's environment metadata.
* **Docker sandbox**: non-root user, read-only root filesystem, only the worktree mounted at `/workspace`, CPU/memory/pid limits, `--cap-drop ALL`, `no-new-privileges`.
* **Approval gates**: `merge` re-evaluates policy and risk at merge time and refuses unless every required approval is `APPROVED`. Approvals are decided only by human principals (`actor_type=human`). Agents' API tokens cannot call approve/reject.
* **Web UI**: it can trigger only control-plane operations (approve, reject, review, merge, checkpoint). It cannot run arbitrary commands.
* **Audit**: every state transition writes an immutable, hash-chained event.
