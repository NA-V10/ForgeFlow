"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleSlash, FileCode2, FileText, FolderSearch, RotateCcw, Terminal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Commit, ErrorBox, EventRow, Loading, PageHeader, Spinner, StatusBadge, Tests } from "@/components/common";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, type ExecutionDetail, type ToolCall } from "@/lib/api";
import { between, cn, duration } from "@/lib/utils";

const TOOL_ICON: Record<string, typeof Terminal> = { run_command: Terminal, write_file: FileCode2, read_file: FileText, delete_file: Trash2, list_files: FolderSearch };

function ToolCallItem({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const Icon = call.status === "DENIED" ? CircleSlash : TOOL_ICON[call.tool] ?? Terminal;
  const tests = call.output?.tests;
  return (
    <li className="relative pl-8" data-tool={call.tool} data-tool-status={call.status}>
      <span className={cn("absolute left-0 top-0.5 flex size-6 items-center justify-center rounded-full border bg-background",
        call.status === "DENIED" ? "border-destructive/50 text-destructive" : call.status === "ERROR" ? "border-warning/50 text-warning" : "text-muted-foreground")}>
        <Icon className="size-3.5" />
      </span>
      <button className="w-full text-left" onClick={() => setOpen(!open)}>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-xs text-muted-foreground">#{call.sequence}</span>
          <span className="font-medium">{call.tool}</span>
          <span className="truncate font-mono text-xs">{call.command ?? call.input.path ?? call.input.prefix ?? ""}</span>
          {call.status !== "OK" && <StatusBadge status={call.status} />}
          {call.exit_code != null && <Badge tone={call.exit_code === 0 ? "success" : "danger"}>exit {call.exit_code}</Badge>}
          {tests && <Tests tests={tests} />}
          <span className="ml-auto text-xs text-muted-foreground">{duration(call.duration_ms)}</span>
        </div>
        {call.status === "DENIED" && <div className="mt-1 text-xs text-destructive">{call.output.error}</div>}
      </button>
      {open && (
        <div className="mt-2 space-y-2 text-xs">
          {call.files_affected.length > 0 && <div>files: <span className="font-mono">{call.files_affected.join(", ")}</span></div>}
          <pre className="max-h-64 overflow-auto rounded-md border bg-muted/50 p-2 font-mono text-[11px]">{JSON.stringify({ input: call.input, output: call.output }, null, 2)}</pre>
          {call.policy?.effect && <div className="text-muted-foreground">policy: {call.policy.effect}{call.policy.reasons?.length ? ` — ${call.policy.reasons.join("; ")}` : ""}</div>}
        </div>
      )}
    </li>
  );
}

interface Repro { verdict: string; summary: string; reproducible: string[]; not_reproducible: string[]; steps: { sequence: number; tool: string; action: string; match?: boolean; note?: string | null; path?: string; command?: string }[] }

export default function ExecutionPage() {
  const { id } = useParams<{ id: string }>();
  const { data: e, error } = useQuery({ queryKey: ["executions", id], queryFn: () => api.get<ExecutionDetail>(`/executions/${id}`) });
  const repro = useMutation({ mutationFn: () => api.post<Repro>(`/executions/${id}/reproduce`, {}) });
  if (error) return <ErrorBox error={error} />;
  if (!e) return <Loading />;
  const g = e.environment.guarantees ?? {};
  return (
    <>
      <PageHeader crumbs={[{ href: "/executions", label: "Executions" }]} title={<span>Execution <span className="font-mono">{e.id.slice(0, 8)}</span></span>}
        description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={e.status} /> {e.agent.name} on <Link className="hover:underline" href={`/tasks/${e.task.id}`}>{e.task.title}</Link></span>}
        actions={<Button variant="outline" onClick={() => repro.mutate()} disabled={repro.isPending || e.status === "RUNNING"}>{repro.isPending ? <Spinner /> : <RotateCcw />}Reproduce</Button>} />
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {[
          ["Agent", e.agent.name], ["Model", `${e.model}${e.model_version ? `@${e.model_version}` : ""}`], ["Base commit", <Commit key="b" sha={e.base_commit} />],
          ["Result", <Commit key="r" sha={e.result_commit} />], ["Duration", duration(between(e.started_at, e.finished_at))],
          ["Tools", `${e.tool_calls.length}${e.summary.denied ? ` (${e.summary.denied} denied)` : ""}`], ["Tests", <Tests key="t" tests={e.summary.tests} />],
        ].map(([k, v]) => (
          <Card key={String(k)} className="p-3"><div className="text-[11px] text-muted-foreground">{k}</div><div className="mt-1 truncate text-sm font-medium">{v}</div></Card>
        ))}
      </div>
      {e.error && <div className="mb-6"><ErrorBox error={e.error} /></div>}
      {repro.error && <div className="mb-6"><ErrorBox error={repro.error} /></div>}
      {repro.data && (
        <Card className="mb-6" data-testid="repro-report">
          <CardHeader><CardTitle>Reproduction</CardTitle><Badge tone={repro.data.verdict === "REPRODUCED" ? "success" : repro.data.verdict === "PARTIAL" ? "warning" : "danger"}>{repro.data.verdict}</Badge></CardHeader>
          <CardContent className="grid gap-4 text-sm md:grid-cols-2">
            <div className="md:col-span-2 text-muted-foreground">{repro.data.summary}</div>
            <div><div className="mb-1 text-xs font-semibold">Reproducible</div><ul className="space-y-1">{repro.data.reproducible.map((x) => <li key={x} className="text-xs text-success">+ {x}</li>)}</ul></div>
            <div><div className="mb-1 text-xs font-semibold">Not reproducible</div><ul className="space-y-1">{repro.data.not_reproducible.map((x) => <li key={x} className="text-xs text-warning">– {x}</li>)}</ul></div>
          </CardContent>
        </Card>
      )}
      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <Card>
          <Tabs defaultValue="timeline">
            <CardHeader>
              <TabsList><TabsTrigger value="timeline">Timeline</TabsTrigger><TabsTrigger value="events">Events</TabsTrigger><TabsTrigger value="artifacts">Artifacts</TabsTrigger></TabsList>
            </CardHeader>
            <CardContent>
              <TabsContent value="timeline">
                <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-3 before:top-2 before:w-px before:bg-border" data-testid="execution-timeline">
                  {e.tool_calls.map((c) => <ToolCallItem key={c.id} call={c} />)}
                </ol>
              </TabsContent>
              <TabsContent value="events"><div className="-mx-4">{e.events.map((ev) => <EventRow key={ev.seq} e={ev} />)}</div></TabsContent>
              <TabsContent value="artifacts">
                <ul className="divide-y">
                  {e.artifacts.map((a) => (
                    <li key={a.id} className="flex items-center gap-3 py-2 text-sm">
                      <FileText className="size-4 text-muted-foreground" />
                      <a className="flex-1 font-mono text-xs hover:underline" href={`/api/v1/artifacts/${a.id}/content`} target="_blank" rel="noreferrer">{a.name}</a>
                      <Badge>{a.kind}</Badge><span className="text-xs text-muted-foreground">{a.size} B</span>
                    </li>
                  ))}
                </ul>
              </TabsContent>
            </CardContent>
          </Tabs>
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Commands</CardTitle></CardHeader>
            <CardContent className="space-y-1">{(e.summary.commands ?? []).map((c, i) => <div key={i} className="font-mono text-xs">$ {c}</div>)}{!e.summary.commands?.length && <div className="text-xs text-muted-foreground">none</div>}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Files</CardTitle></CardHeader>
            <CardContent className="space-y-1">{(e.summary.files ?? []).map((f) => <div key={f} className="font-mono text-xs">{f}</div>)}</CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Environment</CardTitle><Badge tone={e.environment.sandbox === "docker" ? "success" : "warning"}>{e.environment.sandbox} sandbox</Badge></CardHeader>
            <CardContent className="space-y-1.5 text-xs">
              {Object.entries(g).map(([k, v]) => (
                <div key={k} className="flex justify-between"><span className="text-muted-foreground">{k.replaceAll("_", " ")}</span><span className={v ? "text-success" : "text-warning"}>{v ? "enforced" : "not enforced"}</span></div>
              ))}
              <div className="flex justify-between border-t pt-1.5"><span className="text-muted-foreground">network policy</span><span>{e.environment.network_policy}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground">platform</span><span className="truncate pl-4">{e.environment.platform}</span></div>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
