"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, GitBranch, GitCommitHorizontal, GitMerge, History, Send, ShieldAlert, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Commit, Empty, ErrorBox, EventRow, GateChecks, Loading, RiskMeter, Spinner, StatusBadge, Tests } from "@/components/common";
import { ConflictList } from "@/components/conflicts";
import { DiffViewer } from "@/components/diff-viewer";
import { AgentAvatar, Elapsed, LifecycleStepper, ago } from "@/components/forge";
import { ThreadState } from "@/components/threads";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import {
  api, type Approval, type Checkpoint, type Diff, type Execution, type ForgeEvent, type Merge, type RiskAssessment, type SemanticConflict,
  type Thread, type Workspace,
} from "@/lib/api";

function ApprovalCard({ a, onDone }: { a: Approval; onDone: () => void }) {
  const decide = useMutation({ mutationFn: (ok: boolean) => api.post(`/approvals/${a.id}/${ok ? "approve" : "reject"}`, {}), onSuccess: onDone });
  return (
    <div className="rounded-md border border-warning/30 bg-warning/[0.06] p-3" data-testid="inline-approval">
      <div className="flex items-start gap-2">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-warning" />
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] leading-snug">{a.reason}</div>
          <div className="mt-1 font-mono text-2xs text-muted-foreground">{a.requirement_key}</div>
        </div>
      </div>
      <div className="mt-2.5 flex items-center gap-1.5">
        <Button size="sm" variant="outline" onClick={() => decide.mutate(false)} disabled={decide.isPending}><X />Reject</Button>
        <Button size="sm" variant="success" onClick={() => decide.mutate(true)} disabled={decide.isPending}>{decide.isPending ? <Spinner /> : <Check />}Approve</Button>
        <Link href={`/approvals/${a.id}`} className="ml-auto text-2xs text-muted-foreground hover:text-foreground">Details</Link>
      </div>
      {decide.error && <div className="mt-2"><ErrorBox error={decide.error} /></div>}
    </div>
  );
}

export default function WorkspacePage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [message, setMessage] = useState("");
  const ws = useQuery({ queryKey: ["workspaces", id], queryFn: () => api.get<Workspace>(`/workspaces/${id}`) });
  const thread = useQuery({ queryKey: ["threads", "all"], queryFn: () => api.get<Thread[]>("/threads", { limit: 200 }),
    select: (ts) => ts.find((t) => t.workspace_id === ws.data?.id), enabled: !!ws.data });
  const diff = useQuery({ queryKey: ["diff", id], queryFn: () => api.get<Diff>(`/workspaces/${id}/diff`) });
  const cps = useQuery({ queryKey: ["checkpoints", id], queryFn: () => api.get<Checkpoint[]>("/checkpoints", { workspace_id: id }) });
  const risk = useQuery({ queryKey: ["risk", id], queryFn: () => api.get<RiskAssessment[]>("/risk-assessments", { workspace_id: id }) });
  const approvals = useQuery({ queryKey: ["approvals", "ws", id], queryFn: () => api.get<Approval[]>("/approvals", { workspace_id: id, status: "PENDING" }) });
  const executions = useQuery({ queryKey: ["executions", "ws", id], queryFn: () => api.get<Execution[]>("/executions", { workspace_id: id }) });
  const events = useQuery({ queryKey: ["workspaces", id, "events"], queryFn: () => api.get<ForgeEvent[]>("/events", { workspace_id: id, limit: 300 }) });
  const conflicts = useQuery({ queryKey: ["workspaces", id, "conflicts"], queryFn: () => api.get<{ conflicts: SemanticConflict[] }>(`/workspaces/${id}/conflicts`) });
  const merges = useQuery({ queryKey: ["merges", "ws", id], queryFn: () => api.get<Merge[]>("/merges").then((ms) => ms.filter((m) => m.workspace.id === ws.data?.id || m.workspace.id === id)) });

  const refresh = () => ["workspaces", "diff", "checkpoints", "risk", "merges", "approvals", "tasks", "threads", "inbox", "executions"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const checkpoint = useMutation({ mutationFn: () => api.post(`/workspaces/${id}/checkpoints`, { message: message || null }), onSuccess: () => { setMessage(""); refresh(); } });
  const review = useMutation({ mutationFn: () => api.post(`/workspaces/${id}/review`), onSuccess: refresh });
  const evaluate = useMutation({ mutationFn: () => api.post<Merge>("/merges", { workspace_id: id }), onSuccess: refresh });
  const execute = useMutation({ mutationFn: (mid: string) => api.post<Merge>(`/merges/${mid}/execute`), onSuccess: refresh, onError: refresh });
  const restore = useMutation({ mutationFn: (cp: string) => api.post(`/checkpoints/${cp}/restore`), onSuccess: refresh });

  if (ws.error) return <ErrorBox error={ws.error} />;
  if (!ws.data) return <Loading />;
  const w = ws.data;
  const t = thread.data;
  const open = !["MERGED", "ABANDONED"].includes(w.status);
  const latestRisk = risk.data?.[0];
  const latestMerge = merges.data?.[0];
  const running = executions.data?.find((e) => e.status === "RUNNING");
  const actionError = checkpoint.error ?? review.error ?? evaluate.error ?? restore.error ?? execute.error;

  return (
    <div className="space-y-6">
      <header className="space-y-4">
        <div className="flex flex-wrap items-start gap-4">
          {w.agent ? <AgentAvatar name={w.agent.name} size={40} /> : <span className="size-10 rounded-md bg-muted" />}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[20px] font-semibold leading-tight tracking-tight">{w.task.title}</h1>
              {t && <ThreadState t={t} />}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-muted-foreground">
              <span className="font-medium text-foreground/85">{w.agent?.name ?? "unassigned"}</span>
              {running && <span className="font-mono">{running.model}</span>}
              <span className="flex items-center gap-1 font-mono"><GitBranch className="size-3" />{w.branch}</span>
              <span className="flex items-center gap-1"><Commit sha={w.base_commit} /> → <Commit sha={w.current_commit} /></span>
              <Link href={`/tasks/${w.task.id}`} className="hover:text-foreground">task {w.task.id.slice(0, 8)}</Link>
              <span>updated {ago(w.updated_at)} ago</span>
            </div>
          </div>
          {open && (
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => review.mutate()} disabled={review.isPending || !["CHECKPOINTED", "REVIEW"].includes(w.status)}>
                {review.isPending ? <Spinner /> : <Send />}Submit for review
              </Button>
              {latestMerge?.status === "READY" ? (
                <Button variant="success" onClick={() => execute.mutate(latestMerge.id)} disabled={execute.isPending} data-testid="merge-now">
                  {execute.isPending ? <Spinner /> : <GitMerge />}Merge
                </Button>
              ) : (
                <Button onClick={() => evaluate.mutate()} disabled={evaluate.isPending || !["CHECKPOINTED", "REVIEW"].includes(w.status)} data-testid="evaluate-merge">
                  {evaluate.isPending ? <Spinner /> : <GitMerge />}{latestMerge ? "Re-run merge gate" : "Queue for merge"}
                </Button>
              )}
            </div>
          )}
        </div>
        <div className="max-w-xl"><LifecycleStepper status={w.status} /></div>
        {running && (
          <div className="flex items-center gap-3 rounded-md border border-agent/30 bg-agent/[0.06] px-3 py-2 text-[12.5px]">
            <span className="working-bar h-1 w-16 rounded-full bg-agent/30" />
            <span className="text-agent">{w.agent?.name} is working · <Elapsed since={running.started_at} /></span>
            {t?.execution?.last_tool && <span className="truncate font-mono text-2xs text-muted-foreground">last: {t.execution.last_tool.tool} {t.execution.last_tool.target}</span>}
            <Link href={`/executions/${running.id}`} className="ml-auto text-2xs text-muted-foreground hover:text-foreground">Live timeline</Link>
          </div>
        )}
        {actionError && <ErrorBox error={actionError} />}
      </header>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0 space-y-6">
          <ConflictList conflicts={conflicts.data?.conflicts ?? []} title="Potential semantic conflicts with other open threads" />
          <Tabs defaultValue="changes">
            <TabsList>
              <TabsTrigger value="changes">Changes{diff.data && <span className="font-mono text-2xs text-muted-foreground">{diff.data.files.length}</span>}</TabsTrigger>
              <TabsTrigger value="activity">Activity{events.data && <span className="font-mono text-2xs text-muted-foreground">{events.data.length}</span>}</TabsTrigger>
              <TabsTrigger value="checkpoints">Checkpoints{cps.data && <span className="font-mono text-2xs text-muted-foreground">{cps.data.length}</span>}</TabsTrigger>
            </TabsList>
            <TabsContent value="changes" className="mt-4">
              <Card>
                <CardHeader className="py-2.5">
                  <CardTitle>Diff against base</CardTitle>
                  {diff.data && <span className="text-2xs text-muted-foreground">{diff.data.files.length} files · <span className="text-success">+{diff.data.additions}</span> <span className="text-destructive">-{diff.data.deletions}</span>{diff.data.includes_uncommitted && " · includes uncommitted"}</span>}
                </CardHeader>
                <CardContent>{diff.isLoading ? <Loading /> : diff.data ? <DiffViewer patch={diff.data.patch} semantic={diff.data.semantic} /> : <ErrorBox error={diff.error} />}</CardContent>
              </Card>
            </TabsContent>
            <TabsContent value="activity" className="mt-4">
              <Card className="overflow-hidden">
                {executions.data?.length ? (
                  <div className="flex flex-wrap gap-2 border-b px-4 py-2.5">
                    {executions.data.map((e) => (
                      <Link key={e.id} href={`/executions/${e.id}`} className="flex items-center gap-2 rounded-md border px-2 py-1 text-2xs hover:bg-accent">
                        <StatusBadge status={e.status} /><span className="font-mono">{e.id.slice(0, 8)}</span><Tests tests={e.summary.tests} />
                      </Link>
                    ))}
                  </div>
                ) : null}
                <div className="max-h-[640px] overflow-y-auto">{events.data?.length ? events.data.map((e) => <EventRow key={e.seq} e={e} />) : <Empty title="No activity yet" />}</div>
              </Card>
            </TabsContent>
            <TabsContent value="checkpoints" className="mt-4">
              <Card className="overflow-hidden">
                {open && (
                  <form className="flex gap-2 border-b p-3" onSubmit={(e) => { e.preventDefault(); checkpoint.mutate(); }}>
                    <Input placeholder="Checkpoint message" value={message} onChange={(e) => setMessage(e.target.value)} className="h-8" />
                    <Button size="sm" variant="outline" disabled={checkpoint.isPending}><GitCommitHorizontal />Checkpoint</Button>
                  </form>
                )}
                {cps.data?.length ? [...cps.data].reverse().map((c) => (
                  <div key={c.id} className="row h-auto py-2.5">
                    <History className="size-4 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <div className="truncate">{c.message}</div>
                      <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-muted-foreground"><Commit sha={c.commit_sha} />{c.filesystem.changed} files · {ago(c.created_at)} ago</div>
                    </div>
                    {c.commit_sha === w.current_commit ? <Badge tone="primary">current</Badge> : open && (
                      <Button size="sm" variant="ghost" onClick={() => restore.mutate(c.id)} disabled={restore.isPending}>Restore</Button>
                    )}
                  </div>
                )) : <Empty title="No checkpoints" />}
              </Card>
            </TabsContent>
          </Tabs>
        </div>

        <aside className="space-y-4">
          {!!approvals.data?.length && (
            <Card className="overflow-hidden border-warning/30">
              <CardHeader className="py-2.5"><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-warning" />Waiting on you</CardTitle><span className="font-mono text-2xs text-warning">{approvals.data.length}</span></CardHeader>
              <CardContent className="space-y-2 p-3">{approvals.data.map((a) => <ApprovalCard key={a.id} a={a} onDone={refresh} />)}</CardContent>
            </Card>
          )}
          <Card className="overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle className="flex items-center gap-2"><GitMerge className="size-4" />Merge gate</CardTitle>{latestMerge && <StatusBadge status={latestMerge.status} />}</CardHeader>
            <CardContent>
              {latestMerge ? <GateChecks checks={latestMerge.evaluation.checks} /> : <div className="text-2xs text-muted-foreground">Not queued yet. The gate checks the base, textual and semantic conflicts, policy, risk, tests on the merged tree and approvals.</div>}
            </CardContent>
          </Card>
          <Card className="overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle className="flex items-center gap-2"><ShieldAlert className="size-4" />Risk</CardTitle></CardHeader>
            <CardContent>
              {latestRisk ? (
                <div className="space-y-3">
                  <RiskMeter score={latestRisk.score} severity={latestRisk.severity} />
                  <ul className="space-y-1">
                    {latestRisk.signals.map((s) => (
                      <li key={s.name} className="flex justify-between gap-3 text-2xs"><span className="text-muted-foreground">{s.reason}</span><span className="font-mono tabular-nums">{s.points > 0 ? "+" : ""}{s.points}</span></li>
                    ))}
                  </ul>
                </div>
              ) : <div className="text-2xs text-muted-foreground">Computed deterministically on review.</div>}
            </CardContent>
          </Card>
          <Card className="overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle>Permissions</CardTitle></CardHeader>
            <CardContent className="space-y-1.5 text-2xs">
              {Object.entries(w.permissions).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3"><span className="text-muted-foreground">{k.replaceAll("_", " ")}</span><span className="truncate font-mono">{v == null ? "default" : Array.isArray(v) ? v.join(", ") || "—" : String(v)}</span></div>
              ))}
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
