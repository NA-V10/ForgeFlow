"use client";

import { useQuery } from "@tanstack/react-query";
import { GitBranch, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useListNavigation } from "@/components/command";
import { Empty, ErrorBox, Loading, StatusBadge } from "@/components/common";
import { Kbd, ago } from "@/components/forge";
import { api, type Approval } from "@/lib/api";
import { cn } from "@/lib/utils";

const FILTERS = ["PENDING", "APPROVED", "REJECTED", "STALE", ""];

function ApprovalsList() {
  const router = useRouter();
  const workspace = useSearchParams().get("workspace");
  const [status, setStatus] = useState("PENDING");
  const { data, isLoading, error } = useQuery({
    queryKey: ["approvals", status, workspace],
    queryFn: () => api.get<Approval[]>("/approvals", { status, workspace_id: workspace }),
  });
  const rows = data ?? [];
  const nav = useListNavigation(rows, (a) => router.push(`/approvals/${a.id}`));
  return (
    <>
      <div className="mb-3 flex items-center gap-1">
        {FILTERS.map((s) => (
          <button key={s || "all"} onClick={() => setStatus(s)} className={cn("h-7 rounded-md border px-2.5 text-[12px] capitalize",
            status === s ? "border-input bg-accent text-foreground" : "border-transparent text-muted-foreground hover:text-foreground")}>
            {s ? s.toLowerCase() : "all"}
          </button>
        ))}
        <span className="ml-auto hidden items-center gap-1 text-2xs text-muted-foreground md:flex"><Kbd>J</Kbd><Kbd>K</Kbd> move <Kbd>↵</Kbd> review</span>
      </div>
      <div className="overflow-hidden rounded-lg border bg-panel" data-testid="approvals-table">
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !rows.length ? (
          <Empty icon={ShieldCheck} title="Nothing here" hint="Approvals appear when a policy or a semantic conflict requires a human decision." />
        ) : rows.map((a, i) => (
          <Link key={a.id} href={`/approvals/${a.id}`} className="row h-auto py-2.5" data-active={i === nav.index}>
            <ShieldCheck className={cn("size-4 shrink-0", a.kind === "semantic_conflict" ? "text-destructive" : "text-warning")} />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-medium">{a.task.title}</span>
              <span className="block truncate text-2xs text-muted-foreground">{a.reason}</span>
            </span>
            <span className="hidden w-44 shrink-0 items-center gap-1 truncate font-mono text-2xs text-muted-foreground lg:flex"><GitBranch className="size-3" />{a.workspace.branch.replace("forgeflow/ws/", "")}</span>
            <span className="w-24 shrink-0 text-right"><StatusBadge status={a.status} /></span>
            <span className="hidden w-24 shrink-0 truncate text-right text-2xs text-muted-foreground md:block">{a.decided_by ? `by ${a.decided_by}` : ""}</span>
            <span className="w-9 shrink-0 text-right text-2xs tabular-nums text-muted-foreground">{ago(a.created_at)}</span>
          </Link>
        ))}
      </div>
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-[18px] font-semibold tracking-tight">Approvals</h1>
        <span className="text-muted-foreground">Human gates. Agents cannot approve their own work or bypass a required approval.</span>
      </div>
      <Suspense fallback={<Loading />}><ApprovalsList /></Suspense>
    </div>
  );
}
