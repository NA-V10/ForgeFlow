# ForgeFlow

**Agent-native version control and software delivery.** Git tracks *developer → change → commit*.
ForgeFlow tracks *agent → task → workspace → execution → tool calls → changes → evidence →
validation → review → merge*, for repositories where many AI coding agents work at the same time.

Git remains the storage engine. ForgeFlow is the control plane around it: isolated agent
workspaces, mediated and audited tool calls, AST-level semantic diffs, semantic conflict detection,
deterministic risk scoring, YAML policies, human approval gates, a merge queue, line-level
provenance and execution replay.

```
 forge CLI ─┐                       ┌─ version-engine (Git: bare repos + worktrees, CAS merges)
 dashboard ─┼─► FastAPI control ────┼─ semantic-diff  (Tree-sitter symbols, dependency graph, conflicts)
 agents ────┘   plane (REST + WS)   ├─ risk-engine    (deterministic 0-100 score + reasons)
   (agent-sdk)        │             ├─ policy-engine  (YAML: deny › require approval › review › allow)
                      │             ├─ merge-engine   (7-step gate → READY/BLOCKED/REQUIRES_APPROVAL/CONFLICT)
                      │             ├─ provenance     (line → commit → change → execution → agent → task → model)
                      ▼             └─ sandbox        (path confinement, command policy, Docker/local runners)
   PostgreSQL · Redis · MinIO       hash-chained, append-only audit log
```

## Why ForgeFlow (vs. GitHub, GitLab and similar)

GitHub was built for humans pushing commits and opening pull requests. ForgeFlow is built for many
AI agents changing the same repository concurrently. The unit of work is the agent, not the developer.

1. **Provenance down to the model and the tool call.** GitHub can tell you which commit added a line and
   who authored it. ForgeFlow traces line → change → execution (every file write and command) → agent →
   task → model and version. `forge trace app/auth.py:35` answers "why does this line exist?".
2. **Agents never touch the filesystem directly.** Elsewhere an agent typically gets a checkout and a
   shell, and you see the result afterwards. Here every file write and command goes through the API,
   which keeps the agent inside its own workspace, applies policy, and records the call (including
   denied ones). Agents never see host paths and can never approve their own work.
3. **Conflicts Git can't see.** Git only flags overlapping text. ForgeFlow parses the code and flags
   meaning-level conflicts: one agent changes `find_user`'s parameters while another agent's new code
   calls it, or one removes a function another still uses. The demo shows two changes that merge
   cleanly as text but are stopped for human sign-off. With many agents working in parallel, this is
   the failure mode that matters most.
4. **Deterministic, evidence-bound risk and approvals.** Every change gets a 0–100 risk score with
   listed reasons. YAML policies turn risk into approval requirements, and the merge gate re-checks
   everything, including tests on the combined code, before merging. Approvals are bound to the exact
   reviewed commit, so any later change makes them stale. No language model decides risk.
5. **Replayable, tamper-evident history.** `forge reproduce` replays a recorded run byte for byte and
   reports what matched and what couldn't be reproduced. The audit log is append-only and
   hash-chained, so tampering is detectable. That suits compliance needs around AI-written code.
6. **A supervision interface for agents.** The Inbox, thread cards and merge queue answer "what are my
   agents doing, and what needs me?" rather than "show me this pull request."

**Where GitHub and GitLab are far ahead:**

- **Maturity and scale:** ForgeFlow is an MVP that has only run locally on SQLite. The Postgres,
  Redis, MinIO and Docker stack is written but has not been run.
- **Ecosystem:** GitHub has Actions, Marketplace, issues, integrations, hosting and SSO. ForgeFlow has
  none of that.
- **Human code review:** GitHub's review threads, suggestions and comments are far richer.
- **Growing overlap:** GitHub already has branch protection, required reviews, CODEOWNERS and a merge
  queue, and its Copilot coding agent logs its sessions.
- **Semantic analysis is limited:** it covers only Python, JavaScript and TypeScript, matches code by
  name rather than by type, and can over-report conflicts.

**Positioning:** ForgeFlow works best as a control layer beside GitHub, not a replacement. Agents work
inside ForgeFlow (isolation, provenance, semantic conflict checks, risk, approvals), and merged results
can be pushed to GitHub for everything else; a Git bridge is on the [roadmap](docs/roadmap.md). It is most
compelling for teams running many agents on one codebase, especially regulated or security-sensitive
teams that need to prove what an AI changed, why, and who approved it.

## What works

| Capability | How |
|---|---|
| Repository registration | New bare Git repos, or imports of existing repositories by path/URL |
| Agent identities | Per-agent bearer tokens (hashed at rest); every action attributed |
| Isolated workspaces | One `git worktree` per task on `forgeflow/ws/<id>`; host paths never shown to agents |
| Mediated execution | Agents read/write files and run commands only through the API, which confines paths, applies command allow/deny lists and policies, and records every call |
| Provenance | Commit trailers + `Change` rows; `forge trace app/auth.py:35` walks line → commit → change → execution → agent → task → model |
| Diffs | Unified, split and semantic (functions, classes, imports, API routes, dependencies, configuration) for Python, JavaScript, TypeScript |
| Semantic conflicts | Same-symbol edits, signature changes vs. new callers, removed symbols still referenced, route collisions, dependency/config clashes |
| Checkpoints | Commits with provenance; list and restore |
| Risk | 0-100 + LOW/MEDIUM/HIGH/CRITICAL from explainable signals (auth, authz, public API, dependencies, migrations, sensitive paths, failing tests, conflicts) |
| Policies & approvals | Versioned YAML; approvals bound to the reviewed commit; only humans decide; nothing merges past a pending or rejected approval |
| Merge gate & queue | Base check → textual conflicts → semantic conflicts → policy → risk → tests on the merged tree → approvals; CAS ref update; queue re-validated after every merge; rollback by revert |
| Reproducibility | `forge reproduce` replays recorded writes byte-for-byte and re-runs commands, then compares trees and reports what could not be reproduced |
| Real time | WebSocket event stream drives the dashboard; Redis pub/sub in production |
| Audit | Immutable, hash-chained events (ORM guard + DB triggers) with `/events/verify` |

## Quick start

Requirements: Python 3.12+, Git 2.40+, Node 20+. Docker is optional (production sandbox).

```bash
./scripts/setup.sh                # or scripts\setup.ps1 on Windows
source .venv/bin/activate         # Windows: .venv\Scripts\activate
./scripts/dev.sh                  # API on :8000 (SQLite + local sandbox), dashboard on :3000
```

Or run the two processes yourself:

```bash
FORGEFLOW_DATA_DIR=.forgeflow uvicorn forgeflow_api.main:create_app --factory --port 8000
cd apps/web && npm run build && npm start        # http://localhost:3000
```

OpenAPI docs: http://localhost:8000/docs.

### Production-shaped stack

```bash
export FORGEFLOW_ADMIN_TOKEN=$(openssl rand -hex 24)
docker compose -f infrastructure/docker/docker-compose.yml up --build
```

PostgreSQL holds metadata, Redis fans out events, MinIO stores artifacts, and agent commands
run in `forgeflow/sandbox` containers (`--network none`, read-only root, non-root, capped
CPU/memory/pids, all capabilities dropped).

## Demo

Three simulated agents work on a small web shop at the same time: **A** implements token
authentication, **B** optimizes database queries (and changes `find_user`'s signature),
**C** adds tests.

```bash
python demo/run_demo.py                                  # embedded API, prints every step
python demo/run_demo.py --api http://localhost:8000      # against the running server: watch the dashboard
python demo/run_demo.py --api http://localhost:8000 --interactive   # approve in the UI yourself
```

The demo shows 3 agents, 3 tasks and 3 concurrent workspaces; semantic diffs grouped by domain;
risk scores; the cross-workspace conflict check; the merge queue; C and B merging cleanly;
then A blocked on approvals because B changed `find_user`'s signature underneath it
(`signature_change`, HIGH), approval and a successful merge; line provenance; and audit chain
verification. Nothing is precomputed: the playbooks only describe what each simulated agent
edits, and everything else comes from the API. `--check` asserts the expected outcomes and is run
by `tests/test_demo_e2e.py`.

Real LLM agents use the same path: `forge agent start <agent> --task <id> --claude` runs a
Claude tool-use loop (`claude-opus-5-5`, needs `pip install anthropic` and an API key) whose
tool calls go through the same mediated API.

## Tests

```bash
pytest                              # all Python suites: 106 tests across packages, API, runtime, CLI, demo
pytest packages/semantic-diff       # one package
cd apps/web && npm run build && npx playwright install chromium && npx playwright test   # UI e2e (starts API + web if not running)
PW_CHANNEL=chrome npx playwright test        # or use an installed Chrome/Edge instead of the downloaded Chromium
```

| Suite | Covers |
|---|---|
| `packages/*/tests` | Git operations, worktree isolation, CAS merges, reverts, blame; Tree-sitter extraction, semantic diff, dependency graph, conflict detection; risk scoring; policy parsing and precedence; path confinement, command policy, sandbox runners, test-output parsing; provenance tracing; the merge gate |
| `apps/api/tests` | Full vertical slice over HTTP (repository → task → workspace → execution → diff → review → approval → merge → provenance → rollback), reproduction, checkpoints, security boundaries, repository policies, immutable events, WebSocket streaming, concurrent agents with semantic and textual conflicts |
| `apps/agent-runtime/tests` | State graph, playbook agent with validate/fix loop, failure handling, Claude planner against a fake client (denied tool calls returned to the model) |
| `apps/cli/tests` | Every CLI command end to end, JSON and rich output |
| `tests/` | The demo scenario |
| `apps/web/e2e` | Command center + live events, agent thread cards, ⌘K palette, G-shortcuts, keyboard approval from the inbox, task creation, repository graph and provenance, diff viewer tabs, approval flow, merge flow |

## Dashboard

An original "forge" design (graphite surfaces, an ember accent for human actions, cyan reserved for
agent identity and live activity), keyboard-first:

* **Inbox**: everything waiting on a human (approvals, conflicts, blocked merges, failed runs),
  ranked P0–P2 deterministically by the API (`GET /api/v1/inbox`), with a preview pane and
  `⇧A` approve / `⇧R` reject / `⇧M` merge.
* **Command center**: agent threads (`GET /api/v1/threads`) showing live state ("Working 2m",
  "Needs approval", "Merged 1d ago"), lifecycle stepper, merge-gate progress (`Gate 5/7`), tool calls,
  files, tests and risk; plus the live event stream.
* **Thread view**: diff (unified / split / semantic), activity and checkpoints, with the merge gate,
  inline approval cards and risk breakdown alongside.
* `⌘K` / `/` command menu, `G` then a letter to navigate, `C` new task, `J`/`K` list navigation, `?` all shortcuts.

## Documentation

* [Architecture](docs/architecture.md): components, lifecycle, security model, storage adapters
* [Database schema](docs/database.md)
* [REST API](docs/api.md) ([OpenAPI](docs/openapi.json))
* [CLI](docs/cli.md)
* [Development plan & status](docs/development-plan.md)
* [Roadmap: native content-addressed version engine](docs/roadmap.md)

## Repository layout

```
apps/
  api/            FastAPI control plane (models, migrations, services, routers)
  web/            Next.js dashboard (App Router, Tailwind, shadcn-style UI, React Query, WebSockets, React Flow)
  agent-runtime/  LangGraph-style agent graph, playbook agents, Claude planner
  cli/            `forge` command line (Typer + Rich)
packages/
  version-engine/ semantic-diff/ merge-engine/ provenance/ policy-engine/ risk-engine/ sandbox/ agent-sdk/
infrastructure/   docker-compose, Dockerfiles (api, web, sandbox), postgres/redis/minio config
demo/             demo web shop + agent playbooks + run_demo.py
tests/            cross-component end-to-end tests
docs/
```

## Known limitations

* **Local sandbox is not a security boundary.** It confines the working directory, scrubs the environment and applies command policy, but cannot enforce network isolation or resource limits, and allowed interpreters (`python`, `node`) can still touch the filesystem. Each execution records which guarantees were actually enforced. Use `FORGEFLOW_SANDBOX=docker` for untrusted agents.
* **Network policy** supports `none` (Docker) and unrestricted; host allowlists are modelled but not enforced.
* **Semantic analysis** covers Python, JavaScript and TypeScript. Other files get file-level, dependency-manifest or config-key diffs. Reference resolution is name-based (imports, same file, unique global names), not type-aware; it can miss dynamic dispatch and over-report same-named symbols. Renames show as remove + add.
* **Tests and merge evaluation run inside the API request.** Long test suites need a worker queue (on the roadmap).
* **Approvals are single-decision;** `approvals: N` in policies is parsed but not yet enforced as N distinct approvers.
* **Reproduction** replays recorded actions; it does not re-query the model, and command side effects that depend on time, network or randomness can diverge (reported per step).
* **Auth** is token-based (admin token for humans, per-agent tokens). There is no SSO, RBAC or token expiry yet. `dev` auth mode treats anonymous requests as a human and is for local use only.
* **Single API process assumed for merges** on one repository: merges are serialized with a file lock plus a compare-and-swap on the ref, which is safe across processes on one host. Multi-host deployments need shared storage for repositories.
* SQLite is for development; concurrent load belongs on PostgreSQL.
