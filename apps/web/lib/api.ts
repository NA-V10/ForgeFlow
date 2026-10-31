// Typed client for the ForgeFlow REST API (proxied through Next.js at /api/v1).

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface AgentRef { id: string; name: string; model: string }
export interface TaskRef { id: string; title: string; status: string }
export interface WorkspaceRef { id: string; status: string; branch: string }

export interface Repository {
  id: string; name: string; description: string; default_branch: string; source_url: string | null;
  engine: string; settings: Record<string, unknown>; created_at: string; head: string | null;
}
export interface Agent {
  id: string; name: string; description: string; kind: string; model: string; model_version: string | null;
  provider: string | null; capabilities: string[]; status: string; repository_id: string | null; created_at: string;
}
export interface Task {
  id: string; repository_id: string; title: string; description: string; status: string; priority: string;
  base_commit: string; labels: string[]; agent: AgentRef | null; created_by: string | null; created_at: string;
  started_at: string | null; completed_at: string | null;
}
export interface Workspace {
  id: string; repository_id: string; task: TaskRef; agent: AgentRef | null; status: string; branch: string;
  base_commit: string; current_commit: string; permissions: Record<string, unknown>; created_at: string;
  updated_at: string; path: string | null;
}
export interface TestSummary { framework: string; passed: number; failed: number; errors: number; skipped: number; total: number; command?: string }
export interface Execution {
  id: string; repository_id: string; workspace_id: string; task: TaskRef; agent: AgentRef; status: string;
  model: string; model_version: string | null; base_commit: string; result_commit: string | null;
  environment: Record<string, any>; summary: { tests?: TestSummary | null; commands?: string[]; files?: string[];
    tool_calls?: number; denied?: number; duration_ms?: number; [k: string]: unknown };
  error: string | null; started_at: string; finished_at: string | null;
}
export interface ToolCall {
  id: string; sequence: number; tool: string; command: string | null; input: Record<string, any>;
  output: Record<string, any>; files_affected: string[]; status: string; exit_code: number | null;
  duration_ms: number; policy: Record<string, any>; created_at: string;
}
export interface Artifact { id: string; execution_id: string | null; name: string; kind: string; content_type: string; size: number; sha256: string; created_at: string }
export interface Change {
  id: string; repository_id: string; task: TaskRef; agent: AgentRef | null; workspace_id: string;
  execution_id: string | null; checkpoint_id: string | null; commit_sha: string; parent_commit: string; path: string;
  change_type: string; additions: number; deletions: number; semantic: SemanticChange[]; created_at: string;
}
export interface ForgeEvent {
  seq: number; id: string; type: string; message: string; payload: Record<string, any>; repository_id: string | null;
  task_id: string | null; workspace_id: string | null; execution_id: string | null; agent_id: string | null;
  subject_type: string | null; subject_id: string | null; actor_type: string; actor_id: string; created_at: string;
  hash: string; prev_hash: string;
}
export interface ExecutionDetail extends Execution { tool_calls: ToolCall[]; artifacts: Artifact[]; changes: Change[]; events: ForgeEvent[] }
export interface Checkpoint {
  id: string; workspace_id: string; task: TaskRef; execution_id: string | null; commit_sha: string; parent_commit: string;
  tree_id: string; message: string; task_state: Record<string, any>; filesystem: Record<string, any>;
  created_by: string | null; created_at: string;
}
export interface SemanticChange {
  kind: string; category: string; path: string; description: string; symbol: string | null; symbol_kind: string | null;
  line: number | null; domains: string[]; details: Record<string, any>; symbol_id: string | null;
}
export interface SemanticDiff {
  files: { path: string; status: string; language: string | null; analyzed: boolean; note: string | null; changes: SemanticChange[] }[];
  groups: Record<string, SemanticChange[]>; domains: Record<string, string[]>; stats: Record<string, number>;
}
export interface Diff {
  base: string; head: string; files: { path: string; status: string; additions: number; deletions: number; binary: boolean }[];
  additions: number; deletions: number; patch: string; semantic: SemanticDiff | null; summary: string | null;
  includes_uncommitted: boolean;
}
export interface RiskAssessment {
  id: string; workspace_id: string; task: TaskRef; head_commit: string; score: number; severity: Severity;
  reasons: string[]; signals: { name: string; points: number; reason: string }[]; created_at: string;
}
export interface Review {
  id: string; workspace_id: string; task: TaskRef; status: string; base_commit: string; head_commit: string;
  diff_stats: Record<string, number>; semantic_diff: SemanticDiff; policy: Record<string, any>;
  submitted_by: string | null; created_at: string;
}
export interface Approval {
  id: string; workspace: WorkspaceRef; task: TaskRef; review_id: string | null; merge_id: string | null; action: string;
  requirement_key: string; kind: string; reason: string; status: string; head_commit: string;
  details: Record<string, any>; decided_by: string | null; comment: string | null; created_at: string;
  decided_at: string | null;
}
export interface ApprovalDetail extends Approval {
  context: {
    agent: AgentRef | null; task: TaskRef & { priority: string }; workspace: Record<string, string>; action: string;
    files: { path: string; status: string; additions: number; deletions: number }[]; diff: string;
    diff_truncated: boolean; semantic: SemanticDiff | null;
    risk: { score: number; severity: Severity; reasons: string[]; signals: { name: string; points: number; reason: string }[] } | null;
    policy_reason: string; requirement: string; tests: TestSummary | null;
    evidence: { executions: { id: string; status: string; model: string; model_version: string | null; commands: string[];
      tool_calls: number; denied: number; sandbox: string }[]; checkpoints: { id: string; commit: string; message: string }[] };
  };
}
export interface GateCheck { step: number; name: string; status: "pass" | "fail" | "warn" | "skip"; summary: string; details: Record<string, any> }
export interface SemanticConflict { conflict_type: string; severity: Severity; affected_symbols: string[]; affected_files: string[]; explanation: string; with?: string }
export interface Merge {
  id: string; repository_id: string; workspace: WorkspaceRef; task: TaskRef; status: string; target_branch: string;
  head_commit: string; merge_commit: string | null; target_head_before: string | null; revert_commit: string | null;
  requested_by: string | null; created_at: string; evaluated_at: string | null; merged_at: string | null;
  position: number | null;
  evaluation: {
    decision?: string; reasons?: string[]; checks?: GateCheck[]; risk?: { score: number; severity: Severity; reasons: string[] } | null;
    semantic_conflicts?: SemanticConflict[]; advisory_conflicts?: SemanticConflict[]; textual_conflicts?: string[];
    tests?: TestSummary | null; requirements?: { key: string; kind: string; reason: string }[];
  };
}
export interface Policy { id: string; scope: string; version: number; document: string; active: boolean; created_by: string | null; created_at: string }
export interface Dashboard {
  counts: { repositories: number; agents: number; tasks: Record<string, number>; workspaces: Record<string, number>; executions: Record<string, number> };
  active_agents: Agent[]; running_tasks: Task[]; pending_approvals: Approval[]; merge_queue: Merge[];
  recent_checkpoints: Checkpoint[]; risk_distribution: Record<Severity, number>; recent_executions: Execution[];
}
export interface TaskDetail extends Task {
  workspaces: Workspace[]; executions: Execution[]; checkpoints: Checkpoint[]; changes: Change[]; reviews: Review[];
  approvals: Approval[]; risk: RiskAssessment | null; merges: Merge[];
}
export interface GraphData { nodes: { id: string; type: string; label: string; data: Record<string, any> }[]; edges: { id: string; source: string; target: string; label: string }[] }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: Record<string, any> = {}) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, params?: Record<string, string | number | boolean | undefined | null>): Promise<T> {
  const qs = params
    ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => [k, String(v)])).toString()
    : "";
  const res = await fetch(`/api/v1${path}${qs}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    let data: any = {};
    try { data = await res.json(); } catch { /* not json */ }
    throw new ApiError(res.status, data.error ?? "http_error", data.message ?? (typeof data.detail === "string" ? data.detail : res.statusText), data.details ?? {});
  }
  return res.headers.get("content-type")?.includes("application/json") ? res.json() : ((await res.text()) as T);
}

export const api = {
  get: <T,>(path: string, params?: Record<string, string | number | boolean | undefined | null>) => request<T>("GET", path, undefined, params),
  post: <T,>(path: string, body: unknown = {}, params?: Record<string, string | number | boolean | undefined | null>) => request<T>("POST", path, body, params),
  put: <T,>(path: string, body: unknown) => request<T>("PUT", path, body),
  patch: <T,>(path: string, body: unknown) => request<T>("PATCH", path, body),
};

export function wsUrl(): string {
  const explicit = process.env.NEXT_PUBLIC_FORGEFLOW_WS_URL;
  if (explicit) return explicit;
  const api = process.env.NEXT_PUBLIC_FORGEFLOW_API_URL || "http://localhost:8000";
  return api.replace(/^http/, "ws") + "/api/v1/ws/events";
}

export interface InboxItem {
  id: string; kind: "approval" | "merge" | "execution" | "task"; priority: "P0" | "P1" | "P2"; title: string; reason: string;
  needs: "approve" | "merge" | "resolve" | "investigate"; href: string; created_at: string; agent: AgentRef | null;
  workspace_id: string | null; task_id: string | null; branch: string | null; risk: { score: number; severity: Severity } | null;
  approval_id?: string; approval_kind?: string; merge_id?: string; merge_status?: string;
}

export interface Thread {
  workspace_id: string; status: string; branch: string; repository_id: string;
  task: { id: string; title: string; status: string; priority: string };
  agent: (AgentRef & { kind: string }) | null;
  execution: {
    id: string; status: string; model: string; started_at: string; finished_at: string | null; tool_calls: number;
    files: number; denied: number; last_tool: { tool: string; target: string | null; status: string } | null;
    tests: TestSummary | null;
  } | null;
  gate: { passed: number; total: number; status: string; merge_id: string; merged_at: string | null } | null;
  risk: { score: number; severity: Severity } | null;
  pending_approvals: number;
  last_event: { type: string; message: string; created_at: string } | null;
  updated_at: string;
}
