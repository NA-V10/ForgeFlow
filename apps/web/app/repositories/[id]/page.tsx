"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, FileCode2, User } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Commit, Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/common";
import { RepoGraph } from "@/components/repo-graph";
import { Badge, Card, CardContent, CardHeader, CardTitle, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/primitives";
import { api, type GraphData, type Repository } from "@/lib/api";
import { cn, short, timeAgo } from "@/lib/utils";

interface BlameLine { line: number; content: string; commit: string; author: string; message: string; origin: string; agent: string | null; task: string | null; execution_id: string | null; task_id: string | null; model: string | null }
interface Trace { chain: { type: string; id: string; label?: string }[]; explanation: string }

function NodeDetails({ node }: { node: GraphData["nodes"][number] | null }) {
  if (!node) return <Empty title="Select a node" hint="Click any node in the graph to see its details." />;
  const href: Record<string, string> = {
    task: `/tasks/${node.data.id}`, workspace: `/workspaces/${node.data.id}`, agent: "/agents", merge: "/merge-queue",
    change: `/workspaces/${node.data.workspace_id}`,
  };
  return (
    <div className="space-y-3 text-sm" data-testid="node-details">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{node.type}</div>
      <div className="font-medium">{node.label}</div>
      <dl className="space-y-1.5">
        {Object.entries(node.data).map(([k, v]) => (
          <div key={k} className="flex gap-2"><dt className="w-20 shrink-0 text-xs text-muted-foreground">{k}</dt>
            <dd className="min-w-0 break-all font-mono text-xs">{k === "status" ? <StatusBadge status={String(v)} /> : String(v ?? "—")}</dd></div>
        ))}
      </dl>
      {href[node.type] && <Link href={href[node.type]} className="text-xs text-primary hover:underline">Open {node.type} →</Link>}
    </div>
  );
}

function FileBrowser({ repo }: { repo: Repository }) {
  const [path, setPath] = useState<string | null>(null);
  const [line, setLine] = useState<number | null>(null);
  const files = useQuery({ queryKey: ["repositories", repo.id, "files"], queryFn: () => api.get<string[]>(`/repositories/${repo.id}/files`) });
  const blame = useQuery({ queryKey: ["repositories", repo.id, "blame", path], enabled: !!path,
    queryFn: () => api.get<{ lines: BlameLine[] }>(`/repositories/${repo.id}/blame`, { path }) });
  const trace = useQuery({ queryKey: ["repositories", repo.id, "trace", path, line], enabled: !!path && line != null,
    queryFn: () => api.get<Trace>(`/repositories/${repo.id}/provenance`, { path, line }) });
  return (
    <div className="grid gap-4 lg:grid-cols-[240px_1fr_300px]">
      <Card className="max-h-[600px] overflow-y-auto">
        {files.data?.map((f) => (
          <button key={f} onClick={() => { setPath(f); setLine(null); }} className={cn("flex w-full items-center gap-2 px-3 py-1.5 text-left font-mono text-xs hover:bg-accent", f === path && "bg-accent")}>
            <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" /><span className="truncate">{f}</span>
          </button>
        ))}
      </Card>
      <Card className="max-h-[600px] overflow-auto">
        {!path ? <Empty title="Pick a file" hint="Each line shows which agent, task and model produced it. Click a line to trace it." /> : blame.isLoading ? <Loading /> : (
          <table className="w-full font-mono text-[12px] leading-5">
            <tbody>
              {blame.data?.lines.map((l, i) => {
                const first = i === 0 || blame.data!.lines[i - 1].commit !== l.commit;
                return (
                  <tr key={l.line} onClick={() => setLine(l.line)} className={cn("cursor-pointer hover:bg-accent/50", line === l.line && "bg-primary/10")}>
                    <td className="w-40 truncate border-r px-2 align-top text-[11px] text-muted-foreground">
                      {first && <span className="flex items-center gap-1">{l.origin === "agent" ? <Bot className="size-3 text-info" /> : <User className="size-3" />}{l.agent ?? l.author.split(" <")[0]}</span>}
                    </td>
                    <td className="w-10 select-none px-2 text-right text-muted-foreground/60">{l.line}</td>
                    <td className="whitespace-pre px-2">{l.content}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      <Card className="h-fit">
        <CardHeader><CardTitle>Why does this line exist?</CardTitle></CardHeader>
        <CardContent>
          {line == null ? <div className="text-xs text-muted-foreground">Select a line.</div> : trace.isLoading ? <Loading rows={3} /> : trace.error ? <ErrorBox error={trace.error} /> : (
            <ol className="relative space-y-3 border-l pl-4" data-testid="provenance-chain">
              {trace.data?.chain.map((c, i) => (
                <li key={i} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-background bg-primary" />
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{c.type}</div>
                  <div className="break-all font-medium">
                    {c.type === "execution" ? <Link className="hover:underline" href={`/executions/${c.id}`}>{c.label}</Link>
                      : c.type === "task" ? <Link className="hover:underline" href={`/tasks/${c.id}`}>{c.label}</Link> : (c.label ?? c.id)}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function RepositoryPage() {
  const { id } = useParams<{ id: string }>();
  const repo = useQuery({ queryKey: ["repositories", id], queryFn: () => api.get<Repository>(`/repositories/${id}`) });
  const graph = useQuery({ queryKey: ["graph", id], queryFn: () => api.get<GraphData>(`/repositories/${id}/graph`) });
  const commits = useQuery({ queryKey: ["repositories", id, "commits"], queryFn: () => api.get<{ sha: string; author: string; message: string; timestamp: number; trailers: Record<string, string> }[]>(`/repositories/${id}/commits`) });
  const [selected, setSelected] = useState<GraphData["nodes"][number] | null>(null);
  if (repo.error) return <ErrorBox error={repo.error} />;
  if (!repo.data) return <Loading />;
  return (
    <>
      <PageHeader crumbs={[{ href: "/repositories", label: "Repositories" }]} title={repo.data.name}
        description={<span className="flex items-center gap-2">{repo.data.default_branch} @ <Commit sha={repo.data.head} /> · engine {repo.data.engine}</span>} />
      <Tabs defaultValue="graph">
        <TabsList><TabsTrigger value="graph">Graph</TabsTrigger><TabsTrigger value="files">Files & provenance</TabsTrigger><TabsTrigger value="history">History</TabsTrigger></TabsList>
        <TabsContent value="graph" className="mt-4">
          <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
            {graph.data ? <RepoGraph graph={graph.data} onSelect={setSelected} /> : <Loading />}
            <Card className="h-fit"><CardHeader><CardTitle>Details</CardTitle></CardHeader><CardContent><NodeDetails node={selected} /></CardContent></Card>
          </div>
        </TabsContent>
        <TabsContent value="files" className="mt-4"><FileBrowser repo={repo.data} /></TabsContent>
        <TabsContent value="history" className="mt-4">
          <Card>
            <ul className="divide-y">
              {commits.data?.map((c) => (
                <li key={c.sha} className="flex items-start gap-3 px-4 py-2.5 text-sm">
                  <Commit sha={c.sha} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{c.message.split("\n")[0]}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1 text-xs text-muted-foreground">
                      {c.author.split(" <")[0]} · {timeAgo(new Date(c.timestamp * 1000).toISOString())}
                      {Object.entries(c.trailers).filter(([k]) => k.startsWith("ForgeFlow-")).map(([k, v]) => (
                        <Badge key={k} tone={k === "ForgeFlow-Kind" ? "primary" : "neutral"}>{k.replace("ForgeFlow-", "")}: {k === "ForgeFlow-Model" || k === "ForgeFlow-Kind" ? v : short(v)}</Badge>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </TabsContent>
      </Tabs>
    </>
  );
}
