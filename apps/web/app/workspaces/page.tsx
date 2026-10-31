"use client";

import { useQuery } from "@tanstack/react-query";
import { Layers } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useListNavigation } from "@/components/command";
import { Empty, ErrorBox, Loading } from "@/components/common";
import { Kbd } from "@/components/forge";
import { ThreadRow, threadState } from "@/components/threads";
import { api, type Thread } from "@/lib/api";
import { cn } from "@/lib/utils";

const VIEWS = [
  { key: "active", label: "Active", match: (t: Thread) => !["MERGED", "ABANDONED"].includes(t.status) },
  { key: "attention", label: "Needs attention", match: (t: Thread) => ["approval", "conflict", "blocked", "failed", "ready"].includes(threadState(t).key) },
  { key: "merged", label: "Merged", match: (t: Thread) => t.status === "MERGED" },
  { key: "all", label: "All", match: () => true },
] as const;

const GROUPS: { key: string; title: string; statuses: string[] }[] = [
  { key: "running", title: "Running", statuses: ["RUNNING"] },
  { key: "review", title: "In review", statuses: ["REVIEW"] },
  { key: "checkpointed", title: "Checkpointed", statuses: ["CHECKPOINTED", "CREATED"] },
  { key: "failed", title: "Failed", statuses: ["FAILED"] },
  { key: "merged", title: "Merged", statuses: ["MERGED"] },
  { key: "abandoned", title: "Abandoned", statuses: ["ABANDONED"] },
];

export default function ThreadsPage() {
  const router = useRouter();
  const [view, setView] = useState<(typeof VIEWS)[number]["key"]>("active");
  const { data, isLoading, error } = useQuery({ queryKey: ["threads", "all"], queryFn: () => api.get<Thread[]>("/threads", { limit: 200 }) });
  const filtered = (data ?? []).filter(VIEWS.find((v) => v.key === view)!.match);
  const ordered = GROUPS.flatMap((g) => filtered.filter((t) => g.statuses.includes(t.status)));
  const nav = useListNavigation(ordered, (t) => router.push(`/workspaces/${t.workspace_id}`));

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-[18px] font-semibold tracking-tight">Threads</h1>
        <span className="text-muted-foreground">Each thread is one agent working on one task in an isolated worktree.</span>
      </div>
      <div className="mb-3 flex items-center gap-1">
        {VIEWS.map((v) => {
          const n = (data ?? []).filter(v.match).length;
          return (
            <button key={v.key} onClick={() => setView(v.key)} className={cn("flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12px]",
              view === v.key ? "border-input bg-accent text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
              {v.label}<span className="font-mono text-2xs text-muted-foreground">{n}</span>
            </button>
          );
        })}
        <span className="ml-auto hidden items-center gap-1 text-2xs text-muted-foreground md:flex"><Kbd>J</Kbd><Kbd>K</Kbd> move <Kbd>↵</Kbd> open</span>
      </div>
      <div className="overflow-hidden rounded-lg border bg-panel">
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !ordered.length ? (
          <Empty icon={Layers} title="No threads in this view" hint="Threads appear when an agent starts working on a task." />
        ) : GROUPS.map((g) => {
          const rows = ordered.filter((t) => g.statuses.includes(t.status));
          if (!rows.length) return null;
          return (
            <div key={g.key}>
              <div className="flex h-8 items-center gap-2 border-b bg-muted/40 px-4 text-[12px] font-medium">
                {g.title}<span className="font-mono text-2xs text-muted-foreground">{rows.length}</span>
              </div>
              {rows.map((t) => <ThreadRow key={t.workspace_id} t={t} active={ordered.indexOf(t) === nav.index} />)}
            </div>
          );
        })}
      </div>
    </div>
  );
}
