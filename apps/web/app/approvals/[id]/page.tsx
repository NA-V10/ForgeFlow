"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, FileCode2, Hammer, ShieldAlert, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Commit, ErrorBox, Loading, PageHeader, RiskMeter, Spinner, StatusBadge, Tests } from "@/components/common";
import { DiffViewer } from "@/components/diff-viewer";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Textarea } from "@/components/ui/primitives";
import { api, type ApprovalDetail } from "@/lib/api";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 py-1.5 text-sm">
      <dt className="w-24 shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1">{children}</dd>
    </div>
  );
}

export default function ApprovalPage() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const { data: a, error } = useQuery({ queryKey: ["approvals", id], queryFn: () => api.get<ApprovalDetail>(`/approvals/${id}`) });
  const decide = useMutation({
    mutationFn: (approve: boolean) => api.post(`/approvals/${id}/${approve ? "approve" : "reject"}`, { comment: comment || null }),
    onSuccess: () => ["approvals", "dashboard", "merges", "tasks"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })),
  });
  if (error) return <ErrorBox error={error} />;
  if (!a) return <Loading />;
  const c = a.context;
  const pending = a.status === "PENDING";
  return (
    <>
      <PageHeader crumbs={[{ href: "/approvals", label: "Approvals" }]} title={c.task.title}
        description={<span className="flex items-center gap-2"><StatusBadge status={a.status} /> {a.kind.replace("_", " ")} · requirement <span className="font-mono text-xs">{a.requirement_key}</span></span>} />
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-6">
          <Card className="border-warning/40">
            <CardHeader><CardTitle className="flex items-center gap-2"><ShieldAlert className="size-4 text-warning" />Policy reason</CardTitle></CardHeader>
            <CardContent className="text-sm">{c.policy_reason}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Diff</CardTitle><span className="text-xs text-muted-foreground">{c.files.length} files</span></CardHeader>
            <CardContent>
              <DiffViewer patch={c.diff} semantic={c.semantic} defaultTab={a.kind === "semantic_conflict" ? "semantic" : "unified"} />
              {c.diff_truncated && <div className="mt-2 text-xs text-muted-foreground">Diff truncated; open the workspace for the full change.</div>}
            </CardContent>
          </Card>
        </div>
        <div className="space-y-6">
          <Card data-testid="approval-decision">
            <CardHeader><CardTitle>Decision</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {pending ? (
                <>
                  <Textarea rows={3} placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
                  <div className="flex gap-2">
                    <Button variant="success" className="flex-1" onClick={() => decide.mutate(true)} disabled={decide.isPending} data-testid="approve">{decide.isPending ? <Spinner /> : <Check />}Approve</Button>
                    <Button variant="destructive" className="flex-1" onClick={() => decide.mutate(false)} disabled={decide.isPending} data-testid="reject"><X />Reject</Button>
                  </div>
                  <div className="text-[11px] text-muted-foreground">Approval is bound to commit <Commit sha={a.head_commit} />. New changes make it stale.</div>
                </>
              ) : (
                <div className="text-sm">{a.status.toLowerCase()} by <b>{a.decided_by ?? "—"}</b>{a.comment && <div className="mt-1 text-muted-foreground">“{a.comment}”</div>}</div>
              )}
              {decide.error && <ErrorBox error={decide.error} />}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Request</CardTitle></CardHeader>
            <CardContent>
              <dl>
                <Field label="Agent">{c.agent ? <span className="flex items-center gap-1.5"><Bot className="size-3.5" />{c.agent.name} <span className="font-mono text-xs text-muted-foreground">{c.agent.model}</span></span> : "—"}</Field>
                <Field label="Task"><Link href={`/tasks/${c.task.id}`} className="flex items-center gap-1.5 hover:underline"><Hammer className="size-3.5" />{c.task.title}</Link></Field>
                <Field label="Action"><Badge>{c.action}</Badge> into main</Field>
                <Field label="Workspace"><Link href={`/workspaces/${c.workspace.id}`} className="font-mono text-xs hover:underline">{c.workspace.branch}</Link></Field>
                <Field label="Tests"><Tests tests={c.tests} /></Field>
                <Field label="Files">
                  <ul className="space-y-0.5">{c.files.map((f) => <li key={f.path} className="flex items-center gap-1.5 font-mono text-xs"><FileCode2 className="size-3" />{f.path}<span className="text-success">+{f.additions}</span><span className="text-destructive">-{f.deletions}</span></li>)}</ul>
                </Field>
              </dl>
            </CardContent>
          </Card>
          {c.risk && (
            <Card>
              <CardHeader><CardTitle>Risk</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <RiskMeter score={c.risk.score} severity={c.risk.severity} />
                <ul className="space-y-1">{c.risk.reasons.map((r) => <li key={r} className="text-xs text-muted-foreground">· {r}</li>)}</ul>
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-sm">
              {c.evidence.executions.map((e) => (
                <Link key={e.id} href={`/executions/${e.id}`} className="block rounded-md border p-2.5 hover:bg-accent/40">
                  <div className="flex items-center gap-2"><StatusBadge status={e.status} /><span className="font-mono text-xs">{e.model}{e.model_version ? `@${e.model_version}` : ""}</span><span className="ml-auto text-xs text-muted-foreground">{e.sandbox} sandbox</span></div>
                  <div className="mt-1.5 text-xs text-muted-foreground">{e.tool_calls} tool calls{e.denied ? `, ${e.denied} denied` : ""}</div>
                  {e.commands.map((cmd, i) => <div key={i} className="mt-1 truncate font-mono text-[11px]">$ {cmd}</div>)}
                </Link>
              ))}
              {c.evidence.checkpoints.map((cp) => <div key={cp.id} className="flex items-center gap-2 text-xs"><Commit sha={cp.commit} />{cp.message}</div>)}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
