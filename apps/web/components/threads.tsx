"use client";

import { FileCode2, GitBranch, ShieldAlert, TestTube2, Wrench } from "lucide-react";
import Link from "next/link";
import type { Thread } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RiskBadge } from "./common";
import { AgentAvatar, Elapsed, GateProgress, LifecycleStepper, LiveDot, ago } from "./forge";

type Tone = "agent" | "warning" | "success" | "danger" | "muted" | "primary";

/** What is this thread doing / waiting for, in one phrase. */
export function threadState(t: Thread): { label: React.ReactNode; tone: Tone; live: boolean; key: string } {
  if (t.execution?.status === "RUNNING") return { label: <>Working <Elapsed since={t.execution.started_at} /></>, tone: "agent", live: true, key: "working" };
  if (t.status === "MERGED") return { label: `Merged ${ago(t.gate?.merged_at ?? t.updated_at)} ago`, tone: "success", live: false, key: "merged" };
  if (t.status === "FAILED") return { label: "Run failed", tone: "danger", live: false, key: "failed" };
  if (t.status === "ABANDONED") return { label: "Abandoned", tone: "muted", live: false, key: "abandoned" };
  if (t.gate?.status === "CONFLICT") return { label: "Conflict", tone: "danger", live: false, key: "conflict" };
  if (t.gate?.status === "BLOCKED") return { label: "Blocked", tone: "danger", live: false, key: "blocked" };
  if (t.pending_approvals > 0) return { label: `Needs approval · ${t.pending_approvals}`, tone: "warning", live: false, key: "approval" };
  if (t.gate?.status === "READY") return { label: "Ready to merge", tone: "success", live: false, key: "ready" };
  if (t.status === "REVIEW") return { label: "In review", tone: "primary", live: false, key: "review" };
  if (t.status === "CHECKPOINTED") return { label: "Checkpointed", tone: "muted", live: false, key: "checkpointed" };
  return { label: "Idle", tone: "muted", live: false, key: "idle" };
}

const TONE: Record<Tone, string> = {
  agent: "border-agent/30 bg-agent/10 text-agent",
  warning: "border-warning/35 bg-warning/10 text-warning",
  success: "border-success/30 bg-success/10 text-success",
  danger: "border-destructive/35 bg-destructive/10 text-destructive",
  primary: "border-primary/30 bg-primary/10 text-primary",
  muted: "border-border bg-muted text-muted-foreground",
};

export function ThreadState({ t }: { t: Thread }) {
  const s = threadState(t);
  return (
    <span data-thread-state={s.key} className={cn("inline-flex h-[22px] items-center gap-1.5 whitespace-nowrap rounded-full border px-2 text-2xs font-medium", TONE[s.tone])}>
      {s.live && <LiveDot />}{s.label}
    </span>
  );
}

const TOOL_VERB: Record<string, string> = { write_file: "wrote", read_file: "read", delete_file: "deleted", run_command: "ran", list_files: "listed" };

export function ThreadCard({ t }: { t: Thread }) {
  const s = threadState(t);
  const ex = t.execution;
  return (
    <Link href={`/workspaces/${t.workspace_id}`} data-testid="thread-card" data-thread-state={s.key}
      className={cn("group flex flex-col gap-3 rounded-lg border bg-panel p-3.5 transition-colors hover:border-input hover:bg-elevated",
        s.live && "border-agent/30")}>
      <div className="flex items-center gap-2">
        {t.agent ? <AgentAvatar name={t.agent.name} size={22} /> : <span className="size-[22px] rounded-[5px] bg-muted" />}
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12.5px] font-medium">{t.agent?.name ?? "unassigned"}</div>
          <div className="truncate font-mono text-2xs text-muted-foreground">{ex?.model ?? t.agent?.model ?? "—"}</div>
        </div>
        <ThreadState t={t} />
      </div>
      <div>
        <div className="line-clamp-2 text-[13.5px] font-medium leading-snug group-hover:text-foreground">{t.task.title}</div>
        <div className="mt-1.5 flex items-center gap-1.5 text-2xs text-muted-foreground">
          <GitBranch className="size-3" /><span className="truncate font-mono">{t.branch.replace("forgeflow/ws/", "")}</span>
        </div>
      </div>
      <LifecycleStepper status={t.status} compact />
      {s.live && ex?.last_tool ? (
        <div className="truncate rounded-md bg-agent/[0.07] px-2 py-1.5 font-mono text-2xs text-agent">
          {TOOL_VERB[ex.last_tool.tool] ?? ex.last_tool.tool} {ex.last_tool.target}
        </div>
      ) : t.last_event ? (
        <div className="truncate text-2xs text-muted-foreground" title={t.last_event.message}>
          {t.last_event.message} · {ago(t.last_event.created_at)}
        </div>
      ) : null}
      <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-border/60 pt-2.5 text-2xs text-muted-foreground">
        {ex && <span className="flex items-center gap-1" title="tool calls"><Wrench className="size-3" />{ex.tool_calls}</span>}
        {ex && <span className="flex items-center gap-1" title="files changed"><FileCode2 className="size-3" />{ex.files}</span>}
        {ex?.denied ? <span className="flex items-center gap-1 text-destructive" title="denied tool calls"><ShieldAlert className="size-3" />{ex.denied}</span> : null}
        {ex?.tests && (
          <span className={cn("flex items-center gap-1", ex.tests.failed + ex.tests.errors ? "text-destructive" : "text-success")} title="tests">
            <TestTube2 className="size-3" />{ex.tests.passed}{ex.tests.failed + ex.tests.errors ? `/${ex.tests.failed + ex.tests.errors}✗` : ""}
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {t.gate && <GateProgress {...t.gate} />}
          {t.risk && <RiskBadge score={t.risk.score} severity={t.risk.severity} />}
        </span>
      </div>
    </Link>
  );
}

export function ThreadRow({ t, active }: { t: Thread; active?: boolean }) {
  return (
    <Link href={`/workspaces/${t.workspace_id}`} className="row" data-active={active} data-testid="thread-row">
      {t.agent ? <AgentAvatar name={t.agent.name} size={18} /> : <span className="size-[18px]" />}
      <span className="w-32 shrink-0 truncate text-muted-foreground">{t.agent?.name ?? "—"}</span>
      <span className="min-w-0 flex-1 truncate font-medium">{t.task.title}</span>
      <span className="hidden w-40 shrink-0 truncate font-mono text-2xs text-muted-foreground xl:block">{t.branch.replace("forgeflow/ws/", "")}</span>
      <span className="hidden w-28 shrink-0 lg:block"><LifecycleStepper status={t.status} compact /></span>
      <span className="hidden w-[118px] shrink-0 md:block">{t.gate ? <GateProgress {...t.gate} /> : <span className="text-2xs text-muted-foreground">no merge</span>}</span>
      <span className="w-[132px] shrink-0 text-right"><ThreadState t={t} /></span>
      <span className="w-10 shrink-0 text-right text-2xs text-muted-foreground tabular-nums">{ago(t.updated_at)}</span>
    </Link>
  );
}
