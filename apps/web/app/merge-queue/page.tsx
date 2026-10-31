"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitMerge, RefreshCw, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Commit, Empty, ErrorBox, GateChecks, Loading, PageHeader, RiskBadge, Spinner, StatusBadge, Tests } from "@/components/common";
import { ConflictList } from "@/components/conflicts";
import { Button, Card, CardContent, CardHeader } from "@/components/ui/primitives";
import { api, type Merge } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

function MergeCard({ m }: { m: Merge }) {
  const qc = useQueryClient();
  const [err, setErr] = useState<unknown>(null);
  const done = () => { setErr(null); ["merges", "dashboard", "workspaces", "tasks", "approvals"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); };
  const evaluate = useMutation({ mutationFn: () => api.post<Merge>(`/merges/${m.id}/evaluate`), onSuccess: done, onError: setErr });
  const execute = useMutation({ mutationFn: () => api.post<Merge>(`/merges/${m.id}/execute`), onSuccess: done, onError: (e) => { setErr(e); done(); } });
  const rollback = useMutation({ mutationFn: () => api.post<Merge>(`/merges/${m.id}/rollback`, { reason: "rolled back from dashboard" }), onSuccess: done, onError: setErr });
  const ev = m.evaluation;
  const isOpen = m.position != null;
  return (
    <Card data-testid="merge-card" data-merge-status={m.status}>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-3">
          {m.position && <span className="flex size-6 items-center justify-center rounded-full bg-muted text-xs font-semibold tabular-nums">{m.position}</span>}
          <div className="min-w-0">
            <Link href={`/workspaces/${m.workspace.id}`} className="truncate text-sm font-semibold hover:underline">{m.task.title}</Link>
            <div className="text-xs text-muted-foreground">{m.workspace.branch} → {m.target_branch} · requested by {m.requested_by} · {timeAgo(m.created_at)}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <RiskBadge score={ev.risk?.score} severity={ev.risk?.severity} />
          <StatusBadge status={m.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <GateChecks checks={ev.checks} />
        {!!ev.semantic_conflicts?.length && <ConflictList conflicts={ev.semantic_conflicts} title="Semantic conflicts with merged work" />}
        {!!ev.reasons?.length && (
          <ul className="space-y-0.5 text-xs text-muted-foreground">{ev.reasons.map((r) => <li key={r}>· {r}</li>)}</ul>
        )}
        {err != null && <ErrorBox error={err} />}
        <div className="flex flex-wrap items-center gap-2">
          {ev.tests && <Tests tests={ev.tests} />}
          {m.merge_commit && <span className="text-xs text-muted-foreground">merged as <Commit sha={m.merge_commit} /></span>}
          {m.revert_commit && <span className="text-xs text-muted-foreground">reverted by <Commit sha={m.revert_commit} /></span>}
          <div className="ml-auto flex gap-2">
            {isOpen && <Button size="sm" variant="outline" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>{evaluate.isPending ? <Spinner /> : <RefreshCw />}Re-evaluate</Button>}
            {m.status === "REQUIRES_APPROVAL" && <Button size="sm" variant="outline" asChild><Link href={`/approvals?workspace=${m.workspace.id}`}>Review approvals</Link></Button>}
            {isOpen && <Button size="sm" onClick={() => execute.mutate()} disabled={execute.isPending || m.status !== "READY"} data-testid="merge-button">{execute.isPending ? <Spinner /> : <GitMerge />}Merge</Button>}
            {m.status === "MERGED" && <Button size="sm" variant="outline" onClick={() => rollback.mutate()} disabled={rollback.isPending}><Undo2 />Roll back</Button>}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function MergeQueuePage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["merges"], queryFn: () => api.get<Merge[]>("/merges") });
  const open = data?.filter((m) => m.position != null).sort((a, b) => a.position! - b.position!) ?? [];
  const closed = data?.filter((m) => m.position == null) ?? [];
  return (
    <>
      <PageHeader title="Merge Queue" description="Each merge passes the gate: base → textual conflicts → semantic conflicts → policy → risk → tests → approvals." />
      {error ? <ErrorBox error={error} /> : isLoading ? <Loading /> : (
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="text-sm font-semibold">Open <span className="text-muted-foreground">({open.length})</span></h2>
            {open.length ? open.map((m) => <MergeCard key={m.id} m={m} />) : <Card><Empty icon={GitMerge} title="Nothing queued" hint="Queue a workspace from its page or with `forge merge`." /></Card>}
          </section>
          {closed.length > 0 && (
            <section className="space-y-3">
              <h2 className="text-sm font-semibold">History</h2>
              {closed.map((m) => <MergeCard key={m.id} m={m} />)}
            </section>
          )}
        </div>
      )}
    </>
  );
}
