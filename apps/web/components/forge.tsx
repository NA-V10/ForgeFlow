"use client";

// ForgeFlow-specific visual building blocks: identities, priority, lifecycle and gate progress.

import { Bot, User } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

// ------------------------------------------------------------ identities
function hue(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return h % 360;
}

function initials(name: string): string {
  const parts = name.replace(/^agent[_-]/i, "").split(/[_\-\s.]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? parts[0]?.[1] ?? "")).toUpperCase();
}

/** Agents are rounded squares with a deterministic hue; humans are circles. Identity never relies on color alone. */
export function AgentAvatar({ name, size = 20, className }: { name: string; size?: number; className?: string }) {
  const h = hue(name);
  return (
    <span
      title={name}
      className={cn("relative inline-flex shrink-0 items-center justify-center rounded-[5px] font-mono font-semibold text-white", className)}
      style={{ width: size, height: size, fontSize: Math.max(8, size * 0.42), background: `linear-gradient(135deg, hsl(${h} 55% 42%), hsl(${(h + 40) % 360} 60% 32%))` }}
    >
      {initials(name)}
      <Bot className="absolute -bottom-1 -right-1 rounded-full bg-background p-[1px] text-agent" style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  );
}

export function HumanAvatar({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <span title={name} className="inline-flex shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground" style={{ width: size, height: size }}>
      <User style={{ width: size * 0.6, height: size * 0.6 }} />
    </span>
  );
}

export function AgentName({ name, model, size = 18 }: { name: string; model?: string | null; size?: number }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <AgentAvatar name={name} size={size} />
      <span className="truncate font-medium">{name}</span>
      {model && <span className="hidden truncate font-mono text-2xs text-muted-foreground lg:inline">{model}</span>}
    </span>
  );
}

// ------------------------------------------------------------------ keys
export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <kbd className={cn("inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-border bg-muted px-1 font-sans text-[10px] font-medium text-muted-foreground", className)}>
      {children}
    </kbd>
  );
}

// -------------------------------------------------------------- priority
const PRIORITY: Record<string, string> = {
  P0: "border-destructive/40 bg-destructive/15 text-destructive",
  P1: "border-warning/40 bg-warning/12 text-warning",
  P2: "border-border bg-muted text-muted-foreground",
};
export function PriorityChip({ p }: { p: string }) {
  return <span data-priority={p} className={cn("inline-flex h-[18px] items-center rounded border px-1.5 font-mono text-[10px] font-semibold", PRIORITY[p] ?? PRIORITY.P2)}>{p}</span>;
}

const TASK_PRIORITY_BARS: Record<string, number> = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 };
/** Linear-style signal bars for task priority (shape + label, not color alone). */
export function PriorityBars({ priority }: { priority: string }) {
  const n = TASK_PRIORITY_BARS[priority] ?? 0;
  return (
    <span className="inline-flex items-end gap-[2px]" title={`${priority.toLowerCase()} priority`} aria-label={`${priority} priority`}>
      {[1, 2, 3, 4].map((i) => (
        <span key={i} className={cn("w-[3px] rounded-[1px]", i <= n ? (n === 4 ? "bg-destructive" : "bg-foreground/80") : "bg-muted-foreground/25")} style={{ height: 3 + i * 2.5 }} />
      ))}
    </span>
  );
}

// ------------------------------------------------------------- lifecycle
const LIFECYCLE = ["CREATED", "RUNNING", "CHECKPOINTED", "REVIEW", "MERGED"] as const;
const LIFE_LABEL: Record<string, string> = { CREATED: "Created", RUNNING: "Running", CHECKPOINTED: "Checkpointed", REVIEW: "Review", MERGED: "Merged" };

/** Workspace lifecycle as a segmented stepper; FAILED/ABANDONED replace the remaining steps. */
export function LifecycleStepper({ status, compact }: { status: string; compact?: boolean }) {
  const terminalBad = status === "FAILED" || status === "ABANDONED";
  const idx = terminalBad ? 1 : LIFECYCLE.indexOf(status as (typeof LIFECYCLE)[number]);
  return (
    <div className="flex items-center gap-1" data-lifecycle={status} aria-label={`lifecycle: ${status}`}>
      {LIFECYCLE.map((step, i) => {
        const done = i < idx || (i === idx && status === "MERGED");
        const current = i === idx && !terminalBad && status !== "MERGED";
        return (
          <div key={step} className="flex flex-1 flex-col gap-1">
            <div className={cn("h-1 rounded-full",
              done ? "bg-success" : current ? (status === "RUNNING" ? "working-bar bg-agent/40" : "bg-primary") :
                terminalBad && i >= idx ? "bg-destructive/40" : "bg-muted")} />
            {!compact && <span className={cn("text-2xs", current ? "text-foreground" : "text-muted-foreground")}>{LIFE_LABEL[step]}</span>}
          </div>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ gate
export function GateProgress({ passed, total, status }: { passed: number; total: number; status: string }) {
  const tone = status === "MERGED" || status === "READY" ? "bg-success" : status === "CONFLICT" || status === "BLOCKED" ? "bg-destructive" : "bg-warning";
  return (
    <span className="inline-flex items-center gap-1.5" title={`merge gate: ${passed}/${total} checks passed (${status})`}>
      <span className="flex gap-[2px]">
        {Array.from({ length: total }).map((_, i) => <span key={i} className={cn("h-2.5 w-[5px] rounded-[1.5px]", i < passed ? tone : "bg-muted-foreground/20")} />)}
      </span>
      <span className="font-mono text-2xs tabular-nums text-muted-foreground">Gate {passed}/{total}</span>
    </span>
  );
}

// ------------------------------------------------------------- elapsed
function fmt(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** "2m", re-rendered every second while mounted. */
export function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="tabular-nums">{fmt(now - new Date(since).getTime())}</span>;
}

export function ago(iso: string | null | undefined): string {
  return iso ? fmt(Date.now() - new Date(iso).getTime()) : "—";
}

export function LiveDot({ className }: { className?: string }) {
  return <span className={cn("live-dot inline-block size-1.5 rounded-full bg-agent", className)} />;
}
