"use client";

import {
  AlertTriangle, Bot, CheckCircle2, CircleDashed, CircleSlash, Clock, FileCode2, GitBranch, GitMerge, Hammer,
  Loader2, Play, ShieldAlert, ShieldCheck, Sparkles, TestTube2, XCircle,
} from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import type { ForgeEvent, GateCheck, Severity, TestSummary } from "@/lib/api";
import { cn, short, timeAgo } from "@/lib/utils";
import { Badge, Skeleton } from "./ui/primitives";

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

const STATUS_TONE: Record<string, Tone> = {
  PENDING: "neutral", RUNNING: "info", BLOCKED: "danger", REVIEW: "primary", COMPLETED: "success", FAILED: "danger",
  CANCELLED: "neutral", CREATED: "neutral", CHECKPOINTED: "info", MERGED: "success", ABANDONED: "neutral",
  SUCCESS: "success", READY: "success", REQUIRES_APPROVAL: "warning", CONFLICT: "danger", QUEUED: "neutral",
  APPROVED: "success", REJECTED: "danger", STALE: "neutral", ROLLED_BACK: "warning", ACTIVE: "info", IDLE: "neutral",
  OPEN: "primary", SUPERSEDED: "neutral", OK: "success", ERROR: "danger", DENIED: "danger",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  return (
    <Badge tone={tone} className={className} data-status={status}>
      {status === "RUNNING" || status === "ACTIVE" ? <span className="size-1.5 animate-pulse rounded-full bg-current" /> : null}
      {status.replaceAll("_", " ")}
    </Badge>
  );
}

const SEV_TONE: Record<Severity, Tone> = { LOW: "success", MEDIUM: "warning", HIGH: "danger", CRITICAL: "danger" };
export const SEV_COLOR: Record<Severity, string> = {
  LOW: "bg-success", MEDIUM: "bg-warning", HIGH: "bg-orange-500", CRITICAL: "bg-destructive",
};

export function RiskBadge({ score, severity }: { score?: number | null; severity?: Severity | null }) {
  if (severity == null) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <Badge tone={SEV_TONE[severity]} className={cn(severity === "CRITICAL" && "font-semibold")}>
      {score != null && <span className="tabular-nums">{score}</span>} {severity}
    </Badge>
  );
}

export function RiskMeter({ score, severity }: { score: number; severity: Severity }) {
  return (
    <div className="flex items-center gap-3">
      <div className="text-3xl font-semibold tabular-nums">{score}<span className="text-base text-muted-foreground"> / 100</span></div>
      <div className="flex-1">
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <div className={cn("h-full rounded-full", SEV_COLOR[severity])} style={{ width: `${Math.max(3, score)}%` }} />
        </div>
        <div className="mt-1 text-xs font-medium">{severity}</div>
      </div>
    </div>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[12px] text-muted-foreground", className)}>{children}</span>;
}

export function Commit({ sha }: { sha: string | null | undefined }) {
  return <Mono className="rounded bg-muted px-1 py-0.5">{short(sha, 10)}</Mono>;
}

export function Tests({ tests }: { tests: TestSummary | null | undefined }) {
  if (!tests) return <span className="text-xs text-muted-foreground">no tests</span>;
  const bad = tests.failed + tests.errors;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs tabular-nums">
      <TestTube2 className="size-3.5 text-muted-foreground" />
      <span className="text-success">{tests.passed} passed</span>
      {bad > 0 && <span className="text-destructive">{bad} failing</span>}
    </span>
  );
}

/** Page title row. ``crumbs`` is accepted for compatibility; the top bar renders the breadcrumb. */
export function PageHeader({ title, description, actions }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; crumbs?: { href: string; label: string }[] }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="truncate text-[18px] font-semibold tracking-tight">{title}</h1>
        {description && <div className="mt-1 text-sm text-muted-foreground">{description}</div>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Empty({ icon: Icon = CircleDashed, title, hint }: { icon?: typeof CircleDashed; title: string; hint?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      <Icon className="size-6 text-muted-foreground/60" />
      <div className="text-sm font-medium">{title}</div>
      {hint && <div className="max-w-sm text-xs text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-7 w-full" />)}
    </div>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" />
      <span>{msg}</span>
    </div>
  );
}

// ----------------------------------------------------------------- events
const EVENT_ICON: Record<string, typeof Bot> = {
  agent: Bot, task: Hammer, workspace: GitBranch, file: FileCode2, tool: Play, test: TestTube2,
  checkpoint: CheckCircle2, conflict: AlertTriangle, approval: ShieldCheck, merge: GitMerge, review: Sparkles,
  risk: ShieldAlert, execution: Play, repository: GitBranch, policy: ShieldCheck, reproduce: Clock,
};

function eventTone(type: string): string {
  if (type.includes("denied") || type.includes("rejected") || type.startsWith("conflict")) return "text-destructive";
  if (type.includes("completed") || type.includes("granted") || type === "checkpoint.created") return "text-success";
  if (type.includes("requested") || type.includes("rolled_back")) return "text-warning";
  if (type.startsWith("agent")) return "text-info";
  return "text-muted-foreground";
}

export function EventRow({ e, compact }: { e: ForgeEvent; compact?: boolean }) {
  const kind = e.type.split(".")[0];
  const Icon = e.type === "tool.denied" ? CircleSlash : e.type.includes("failed") ? XCircle : EVENT_ICON[kind] ?? CircleDashed;
  return (
    <div className="group flex gap-3 px-4 py-2 text-sm hover:bg-accent/30" data-event-type={e.type}>
      <Icon className={cn("mt-0.5 size-4 shrink-0", eventTone(e.type))} />
      <div className="min-w-0 flex-1">
        <div className={cn("text-[13px] leading-snug", compact && "truncate")}>{e.message}</div>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
          <span className="font-mono">{e.type}</span>
          <span>·</span>
          <span>{timeAgo(e.created_at)}</span>
          <span>·</span>
          <span>{e.actor_type}</span>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------- gate checks
const CHECK_ICON = {
  pass: <CheckCircle2 className="size-4 text-success" />,
  fail: <XCircle className="size-4 text-destructive" />,
  warn: <AlertTriangle className="size-4 text-warning" />,
  skip: <CircleDashed className="size-4 text-muted-foreground" />,
};

export function GateChecks({ checks }: { checks: GateCheck[] | undefined }) {
  if (!checks?.length) return <div className="text-xs text-muted-foreground">Not evaluated yet.</div>;
  return (
    <ol className="space-y-1.5">
      {checks.map((c) => (
        <li key={c.step} className="flex items-start gap-2.5 text-sm" data-check={c.name} data-check-status={c.status}>
          <span className="mt-0.5">{CHECK_ICON[c.status]}</span>
          <span className="w-40 shrink-0 font-medium"><span className="text-muted-foreground">{c.step}.</span> {c.name}</span>
          <span className="text-muted-foreground">{c.summary}</span>
        </li>
      ))}
    </ol>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("size-4 animate-spin", className)} />;
}
