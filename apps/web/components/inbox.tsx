"use client";

import { AlertTriangle, GitMerge, ShieldCheck, XCircle } from "lucide-react";
import type { InboxItem } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentAvatar, PriorityChip, ago } from "./forge";

export const NEEDS_LABEL: Record<InboxItem["needs"], string> = {
  approve: "Needs approval", merge: "Ready to merge", resolve: "Resolve conflict", investigate: "Investigate",
};

export function InboxIcon({ item }: { item: InboxItem }) {
  if (item.kind === "approval") return <ShieldCheck className="size-4 text-warning" />;
  if (item.kind === "merge") return item.needs === "merge" ? <GitMerge className="size-4 text-success" /> : <AlertTriangle className="size-4 text-destructive" />;
  return <XCircle className="size-4 text-destructive" />;
}

export function InboxRow({ item, active, onClick }: { item: InboxItem; active?: boolean; onClick?: () => void }) {
  return (
    <button onClick={onClick} data-active={active} data-testid="inbox-row" data-kind={item.kind} data-priority={item.priority}
      className={cn("row h-auto w-full py-2.5 text-left")}>
      <PriorityChip p={item.priority} />
      <InboxIcon item={item} />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{item.title}</span>
        <span className="block truncate text-2xs text-muted-foreground">{item.reason}</span>
      </span>
      <span className="hidden shrink-0 items-center gap-1.5 text-2xs text-muted-foreground sm:flex">
        {item.agent && <AgentAvatar name={item.agent.name} size={16} />}
        <span className="max-w-[110px] truncate">{item.agent?.name}</span>
      </span>
      <span className="hidden w-[118px] shrink-0 justify-end lg:flex">
        <span className={cn("rounded-full border px-2 py-0.5 text-2xs font-medium",
          item.needs === "approve" ? "border-warning/35 text-warning" : item.needs === "merge" ? "border-success/30 text-success" : "border-destructive/35 text-destructive")}>
          {NEEDS_LABEL[item.needs]}
        </span>
      </span>
      <span className="w-9 shrink-0 text-right text-2xs tabular-nums text-muted-foreground">{ago(item.created_at)}</span>
    </button>
  );
}
