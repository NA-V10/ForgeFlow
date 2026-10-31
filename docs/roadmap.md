# Roadmap: replacing Git with a native content-addressed version engine

Git is the storage engine for the MVP because it is correct, universal and fast enough.
ForgeFlow already treats it as an implementation detail: every read and write goes through
the `VersionEngine` protocol (`packages/version-engine/src/ff_version/engine.py`), and nothing
outside that package invokes `git`. Replacing Git means providing a second implementation of
that protocol, then migrating.

## Why replace it

| Limitation of Git for agent workloads | What a native engine can do |
|---|---|
| Provenance lives in commit trailers and has to be joined back to the database | Provenance is a first-class field of every object (who/which execution/which model produced this blob) |
| History granularity is the commit; agent operations happen per tool call | Every tool call can produce an immutable snapshot, so "replay to step 17" becomes cheap |
| Worktrees are full checkouts; 100 agents mean 100 copies on disk | Copy-on-write, lazily materialized workspaces (overlay or FUSE) |
| Merges are line-based; semantic structure is recomputed on every diff | Store parsed symbol trees alongside blobs; diffs and conflict checks read precomputed ASTs |
| Single-machine ref locking | Refs as compare-and-swap rows in PostgreSQL; objects in S3; horizontally scalable |
| Blame is recomputed on demand | Line-level provenance maintained incrementally at write time |

## Design sketch

* **Objects:** `blob`, `tree`, `snapshot` (a tree plus provenance: execution, agent, model, tool call), and `change` (a snapshot with parents). All are addressed by BLAKE3 hashes and stored in object storage under the `objects/` prefix of the existing artifact bucket. The blob store the API already uses for agent writes (`blobs/sha256/…`) is a first step.
* **Refs:** a `refs` table `(repository_id, name, target, version)` updated with optimistic CAS, which is the same contract `GitEngine.merge(expected_head=…)` already enforces with `update-ref <new> <old>`.
* **Workspaces:** materialized on demand from a snapshot into a sandbox volume; writes go through the tool API, which already sees every byte, so the engine records snapshots without scanning the filesystem.
* **Semantic layer:** `ff_semantic` symbol tables cached per blob hash (the extractor is already a pure function of `(path, bytes)` and memoized), making dependency graphs incremental.
* **Interop:** a Git bridge exports snapshots as commits (with today's trailers) so external tools, CI and GitHub keep working, and imports Git history as snapshots without provenance.

## Migration plan

1. **Dual-write (shadow) phase.** Implement `NativeEngine` with the `VersionEngine` protocol. A `ShadowEngine` delegates to Git and mirrors every write into the native store, comparing tree hashes after each operation (`tree_id` is already part of the protocol). Mismatches are logged, not served.
2. **Conformance suite.** Run `packages/version-engine/tests` parametrized over both engines, plus the merge-engine and API integration tests. The protocol is the contract.
3. **Read cut-over per repository.** `Repository.engine` already exists (`"git"` today); flip it per repository to `"native"` with the Git bridge exporting for compatibility.
4. **Native-only features.** Per-tool-call snapshots, exact replay to any step, AST-aware three-way merge, copy-on-write workspaces.
5. **Retire the Git backend** for repositories that no longer need external Git access; keep the bridge for those that do.

## Other roadmap items

* **Authentication:** OIDC/SSO for humans, scoped and expiring agent tokens, per-repository roles, multi-party approvals (`approvals: 2` is already parsed by the policy engine but approvals are single-decision today).
* **Sandbox:** gVisor/Firecracker runtimes, egress allowlists (`NetworkPolicy.allowed_hosts` is modelled but only `none`/`full` are enforced), per-task resource budgets.
* **Semantic diff:** more languages (Go, Java, Rust via Tree-sitter grammars), rename detection, type-aware call resolution, OpenAPI/GraphQL schema diffs.
* **Merge queue:** speculative batching (test N queued merges together), automatic rebase of non-conflicting workspaces.
* **Scale:** worker pool for test runs and merge evaluation (today they run in the API request), Postgres row-level security per tenant, event stream retention to object storage.
