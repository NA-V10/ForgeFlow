"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers, Plus } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Commit, Empty, ErrorBox, EventRow, Loading, PageHeader, RiskBadge, StatusBadge, Tests } from "@/components/common";
import { Button, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, type ForgeEvent, type TaskDetail, type Workspace } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const { data: t, error } = useQuery({ queryKey: ["tasks", id], queryFn: () => api.get<TaskDetail>(`/tasks/${id}`) });
  const events = useQuery({ queryKey: ["tasks", id, "events"], queryFn: () => api.get<ForgeEvent[]>("/events", { task_id: id, limit: 50 }) });
  const createWs = useMutation({
    mutationFn: () => api.post<Workspace>("/workspaces", { task_id: id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", id] }),
  });
  if (error) return <ErrorBox error={error} />;
  if (!t) return <Loading />;
  const terminal = ["COMPLETED", "CANCELLED"].includes(t.status);
  return (
    <>
      <PageHeader crumbs={[{ href: "/tasks", label: "Tasks" }]} title={t.title}
        description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={t.status} /> {t.priority} · agent {t.agent?.name ?? "unassigned"} · base <Commit sha={t.base_commit} /></span>}
        actions={!terminal && <Button variant="outline" onClick={() => createWs.mutate()} disabled={createWs.isPending}><Plus />New workspace</Button>} />
      {createWs.error && <div className="mb-4"><ErrorBox error={createWs.error} /></div>}
      {t.description && <p className="mb-6 max-w-3xl text-sm text-muted-foreground">{t.description}</p>}
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Workspaces</CardTitle></CardHeader>
            {t.workspaces.length ? (
              <ul className="divide-y">
                {t.workspaces.map((w) => (
                  <li key={w.id}>
                    <Link href={`/workspaces/${w.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/30">
                      <Layers className="size-4 text-muted-foreground" />
                      <span className="font-mono text-xs">{w.branch}</span>
                      <StatusBadge status={w.status} />
                      <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground"><Commit sha={w.base_commit} /> → <Commit sha={w.current_commit} /></span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <Empty title="No workspace yet" hint="Agents create one automatically when they start, or create one here." />}
          </Card>
          <Card>
            <CardHeader><CardTitle>Executions</CardTitle></CardHeader>
            {t.executions.length ? (
              <ul className="divide-y">
                {t.executions.map((e) => (
                  <li key={e.id}>
                    <Link href={`/executions/${e.id}`} className="flex items-center gap-3 px-4 py-2.5 text-sm hover:bg-accent/30">
                      <StatusBadge status={e.status} />
                      <span className="font-medium">{e.agent.name}</span>
                      <span className="font-mono text-xs text-muted-foreground">{e.model}{e.model_version ? `@${e.model_version}` : ""}</span>
                      <span className="ml-auto"><Tests tests={e.summary.tests} /></span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : <Empty title="No executions" />}
          </Card>
          <Card>
            <CardHeader><CardTitle>Changes</CardTitle><span className="text-xs text-muted-foreground">{t.changes.length} file changes</span></CardHeader>
            {t.changes.length ? (
              <ul className="divide-y">
                {t.changes.map((c) => (
                  <li key={c.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                    <span className="w-4 font-mono text-xs text-muted-foreground">{c.change_type}</span>
                    <span className="flex-1 truncate font-mono text-xs">{c.path}</span>
                    <span className="font-mono text-xs"><span className="text-success">+{c.additions}</span> <span className="text-destructive">-{c.deletions}</span></span>
                    <Commit sha={c.commit_sha} />
                  </li>
                ))}
              </ul>
            ) : <Empty title="No changes yet" />}
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Review status</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="flex items-center justify-between"><span className="text-muted-foreground">Risk</span><RiskBadge score={t.risk?.score} severity={t.risk?.severity} /></div>
              {t.risk?.reasons.map((r) => <div key={r} className="text-xs text-muted-foreground">· {r}</div>)}
              <div className="border-t pt-3">
                <div className="mb-2 text-xs font-medium text-muted-foreground">Approvals</div>
                {t.approvals.length ? t.approvals.map((a) => (
                  <Link key={a.id} href={`/approvals/${a.id}`} className="flex items-start gap-2 py-1 hover:underline"><StatusBadge status={a.status} /><span className="text-xs">{a.reason}</span></Link>
                )) : <div className="text-xs text-muted-foreground">none</div>}
              </div>
              <div className="border-t pt-3">
                <div className="mb-2 text-xs font-medium text-muted-foreground">Merges</div>
                {t.merges.length ? t.merges.map((m) => (
                  <div key={m.id} className="flex items-center gap-2 py-1"><StatusBadge status={m.status} /><Commit sha={m.merge_commit} /></div>
                )) : <div className="text-xs text-muted-foreground">none</div>}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Timeline</CardTitle></CardHeader>
            <div className="max-h-[480px] overflow-y-auto">
              {events.data?.map((e) => <EventRow key={e.seq} e={e} />)}
            </div>
          </Card>
          <div className="text-xs text-muted-foreground">Created {timeAgo(t.created_at)} by {t.created_by ?? "—"}</div>
        </div>
      </div>
    </>
  );
}
