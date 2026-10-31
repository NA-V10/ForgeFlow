# Development plan and status

The build followed the vertical slice first, then broadened:
**repository → task → workspace → agent execution → changes → semantic diff → risk → approval → merge.**

| Phase | Scope | Status |
|---|---|---|
| 0. Design | Architecture, schema, API surface, repository layout | Done: `docs/architecture.md`, `docs/database.md`, `docs/api.md` |
| 1. Version engine | `VersionEngine` protocol; Git implementation with bare repos, worktrees, trailers, temp-index worktree diffs, blame, `merge-tree` conflict checks, CAS merges, reverts | Done, 11 tests |
| 2. Semantic diff | Tree-sitter symbol extraction (Python/JS/TS), normalized token hashes, routes, imports, dependency manifests, config keys, domain grouping | Done |
| 3. Conflicts | Dependency graph (imports, same-file, unique-name resolution, class aggregation), conflict taxonomy with severities and explanations | Done, 13 tests for semantic diff + conflicts |
| 4. Risk & policy | Deterministic signals and severity bands; YAML policies with validation and precedence | Done, 24 tests |
| 5. Sandbox & provenance | Path confinement, command/network policy, local + Docker runners, test parsers; trailer format and line tracing | Done, 31 tests |
| 6. Merge gate | Seven-step evaluation, approvals by stable requirement keys, advisory conflicts with open workspaces | Done, 8 tests |
| 7. Control plane | Models + Alembic migration, hash-chained events, mediated tool calls, checkpoints, reviews, approvals, merge queue, rollback, reproduction, provenance, dashboard, graph, WebSocket | Done, 11 integration tests |
| 8. Agent runtime & CLI | State-graph workflow (setup → act → validate → fix → finish → submit), playbook and Claude planners; `forge` CLI | Done, 6 tests |
| 9. Demo | Shop app, three playbooks, concurrent run, intentional semantic conflict, `--check` mode | Done, e2e test |
| 10. Dashboard | All navigation sections, diff viewer, repository graph, approvals, merge queue, executions timeline, live activity | Done, Playwright suite |

## Process

After each component the relevant suite was run and failures fixed before moving on. Several
defects were found this way and fixed at the root:

* host workspace paths leaking to agents through ORM serialization (fixed: explicit redaction, test added);
* a broken audit hash chain under concurrent agents on SQLite (fixed: take the write lock before reading the chain head);
* false-positive semantic conflicts from local variables shadowing global symbol names (fixed: local bindings excluded from references, test added);
* the default `security-code` policy missing `auth.py`-style modules.

## Next

See [roadmap.md](roadmap.md).
