# `forge` CLI

`forge` talks to the ForgeFlow API. Configuration comes from `~/.forgeflow/config.json`
(written by `forge init`), overridden by `FORGEFLOW_API_URL` and `FORGEFLOW_TOKEN`.
Every command accepts `--json`. Entity arguments accept a full UUID, a unique prefix of
at least 4 hex characters, or, for repositories and agents, the name.

Exit codes: `0` success, `1` API error (message on stderr), `2` API unreachable, `3` merge not completed.

## Setup

| Command | Description |
|---|---|
| `forge init [--api-url URL] [--token T]` | Save the API URL and human token, check connectivity, show the runtime configuration |

## Repositories, agents, tasks

| Command | Description |
|---|---|
| `forge repo create NAME [--from PATH_OR_URL] [--test-command CMD] [--require-tests]` | Register a new repository or import an existing Git repository |
| `forge repo list` | List repositories with head commit and test command |
| `forge agent create NAME [--model M] [--model-version V] [--kind scripted\|llm\|external]` | Register an agent; its token is saved to the CLI config (shown once) |
| `forge agent list` | Agents with kind, model and status |
| `forge agent start AGENT --task T (--playbook FILE \| --claude) [--model M] [--workspace W] [--validate CMD] [--no-submit]` | Run an agent on a task through the mediated tool API, validate, checkpoint and submit for review |
| `forge task create TITLE --repo R [--agent A] [--priority P] [--description D]` | Create a task (its base commit is the current head) |
| `forge task list [--repo R] [--status S]` | Tasks |
| `forge task show T` | Task with its provenance tree: workspaces → executions → checkpoints → merges, risk and approvals |

## Workspaces and changes

| Command | Description |
|---|---|
| `forge workspace create --task T [--agent A]` | Create an isolated Git worktree for a task |
| `forge workspace list [--repo R] [--status S]` | Workspaces |
| `forge workspace show W` | Branch, base/head commits, permissions and host path (humans only) |
| `forge diff W [--semantic] [--committed]` | Standard diff, or the AST-level semantic diff grouped by domain |
| `forge checkpoint create W [-m MSG]` | Commit the workspace with provenance trailers |
| `forge checkpoint list W` | Checkpoints of a workspace |
| `forge checkpoint restore CP` | Reset the workspace to a checkpoint |

## Review, risk, policy, approval

| Command | Description |
|---|---|
| `forge review W` | Submit for review: semantic diff, risk assessment, policy evaluation, approval requests |
| `forge risk W` | Deterministic 0-100 risk score, severity and reasons |
| `forge policy check ACTION [--path P ...] [--repo R] [--agent A] [--command C] [--risk-score N]` | Evaluate an action against the effective policies |
| `forge policy show [--repo R]` | Effective policy rules |
| `forge policy set FILE [--scope global\|REPO]` | Publish a new version of a YAML policy document |
| `forge approvals [--status S]` | Approval requests |
| `forge approve ID [-m COMMENT]` / `forge reject ID [-m COMMENT]` | Decide an approval (human principals only) |

## Merge and recovery

| Command | Description |
|---|---|
| `forge merge W [--dry-run]` | Run the 7-step merge gate; merge if READY (prints each check and the reasons) |
| `forge queue [--repo R]` | Merge queue with positions, statuses and risk |
| `forge rollback MERGE [-m REASON]` | Revert a merge on the target branch |
| `forge reproduce EXECUTION [--keep]` | Replay an execution and report what could and could not be reproduced |
| `forge trace PATH:LINE --repo R [--rev REV]` | Why does this line exist? line → commit → change → execution → agent → task → model |
| `forge events [--follow] [--type PREFIX] [--limit N]` | Audit log; `--follow` streams live over WebSocket |

## Example session

```console
$ forge init
$ forge repo create shop --from ./shop --test-command "pytest -q"
$ forge agent create agent_auth --model claude-opus-5-5 --kind llm
$ forge task create "Implement OAuth authentication" --repo shop --agent agent_auth
✓ task 3f2a9c1e Implement OAuth authentication (base 91ac72d0e1, agent agent_auth)
$ forge agent start agent_auth --task 3f2a --claude --validate "pytest -q"
$ forge diff 7b1e --semantic
Semantic changes:

Authentication
  - Added class `OAuthMiddleware` in auth/oauth.py
  - Added function `validate_jwt`(token) in auth/oauth.py
API
  - POST /login changed (handler `login` modified)
Dependencies
  - Added oauthlib ==3.2.2
$ forge risk 7b1e
╭─ risk ─────────────────────────────╮
│ 82 / 100                           │
│ HIGH                               │
│ Reasons:                           │
│ - authentication code changed      │
│ - public API modified (1 route)    │
│ - 1 dependency added               │
╰────────────────────────────────────╯
$ forge merge 7b1e
merge 5c0d21aa  REQUIRES_APPROVAL  Implement OAuth authentication → main
  ✓ 1. verify base commit    base 91ac72d0e1 is in main and is current
  ✓ 2. textual conflicts     merges cleanly
  ✓ 3. semantic conflicts    no conflicts with merged work
  ! 4. policies              2 approval requirement(s)
  ! 5. risk                  82/100 HIGH
  ✓ 6. tests                 43 passed on the merged tree
  ! 7. approvals             2 of 2 approval(s) pending
$ forge approvals
$ forge approve 1d9e -m "reviewed"
$ forge merge 7b1e
```

(The output above is illustrative; every number comes from the API at run time.)
