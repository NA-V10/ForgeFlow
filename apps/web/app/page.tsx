"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Inbox, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Empty, EventRow, Loading, SEV_COLOR } from "@/components/common";
import { Kbd } from "@/components/forge";
import { InboxRow } from "@/components/inbox";
import { ThreadCard, threadState } from "@/components/threads";
import { Card, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api, type Dashboard, type InboxItem, type Severity, type Thread } from "@/lib/api";
import { useEvents } from "@/lib/events";
import { cn } from "@/lib/utils";

const SEVERITIES: Severity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

function Stat({ label, value, tone, href }: { label: string; value: number; tone?: string; href: string }) {
  return (
    <Link href={href} data-testid={`stat-${label.toLowerCase().replaceAll(" ", "-")}`} className="group flex flex-col rounded-md px-3 py-1.5 hover:bg-accent/60">
      <span className="text-2xs text-muted-foreground group-hover:text-foreground">{label}</span>
      <span className={cn("text-xl font-semibold tabular-nums leading-tight", tone)}>{value}</span>
    </Link>
  );
}

function RiskDistribution({ dist }: { dist: Record<Severity, number> }) {
  const total = SEVERITIES.reduce((n, s) => n + (dist[s] ?? 0), 0);
  if (!total) return <div className="px-4 py-6 text-center text-2xs text-muted-foreground">No assessed workspaces yet</div>;
  return (
    <div className="px-4 py-3">
      <div className="flex h-2 gap-[2px] overflow-hidden rounded-full" role="img" aria-label="Risk distribution of open and merged workspaces">
        {SEVERITIES.filter((s) => dist[s]).map((s) => (
          <div key={s} title={`${s}: ${dist[s]}`} className={cn("h-full", SEV_COLOR[s])} style={{ width: `${(dist[s] / total) * 100}%` }} />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-4 gap-1">
        {SEVERITIES.map((s) => (
          <div key={s}>
            <dt className="flex items-center gap-1 text-[10px] text-muted-foreground"><span className={cn("size-1.5 rounded-sm", SEV_COLOR[s])} />{s.toLowerCase()}</dt>
            <dd className="font-semibold tabular-nums">{dist[s] ?? 0}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function CommandCenter() {
  const router = useRouter();
  const [filter, setFilter] = useState<"active" | "all">("active");
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard") });
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<InboxItem[]>("/inbox") });
  const threads = useQuery({ queryKey: ["threads"], queryFn: () => api.get<Thread[]>("/threads", { limit: 60 }) });
  const { events } = useEvents();

  const all = threads.data ?? [];
  const order = (t: Thread) => ({ working: 0, conflict: 1, blocked: 1, failed: 1, approval: 2, ready: 3, review: 4 }[threadState(t).key] ?? 5);
  const active = all.filter((t) => !["MERGED", "ABANDONED"].includes(t.status)).sort((a, b) => order(a) - order(b));
  const shown = filter === "active" ? active : all;
  const working = all.filter((t) => t.execution?.status === "RUNNING").length;
  const d = dash.data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Command center</h1>
          <p className="mt-0.5 text-muted-foreground">
            {working > 0 ? <><span className="text-agent">{working} agent{working === 1 ? "" : "s"} working</span> · </> : null}
            {inbox.data?.length ? <>{inbox.data.length} item{inbox.data.length === 1 ? "" : "s"} need you</> : "Nothing needs you right now"}
          </p>
        </div>
        {d && (
          <div className="flex items-center rounded-lg border bg-panel p-1">
            <Stat label="Active agents" value={d.active_agents.length} tone={d.active_agents.length ? "text-agent" : undefined} href="/agents" />
            <Stat label="Running tasks" value={d.running_tasks.length} href="/tasks" />
            <Stat label="Pending approvals" value={d.pending_approvals.length} tone={d.pending_approvals.length ? "text-warning" : undefined} href="/approvals" />
            <Stat label="Merge queue" value={d.merge_queue.length} href="/merge-queue" />
          </div>
        )}
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          <Card className="overflow-hidden" data-testid="needs-you">
            <CardHeader className="py-2.5">
              <CardTitle className="flex items-center gap-2"><Inbox className="size-4 text-primary" />Needs you
                {!!inbox.data?.length && <span className="rounded bg-primary/15 px-1.5 font-mono text-[10px] text-primary">{inbox.data.length}</span>}</CardTitle>
              <Link href="/inbox" className="flex items-center gap-1.5 text-2xs text-muted-foreground hover:text-foreground">Open inbox <Kbd>G</Kbd><Kbd>I</Kbd></Link>
            </CardHeader>
            {inbox.isLoading ? <Loading rows={2} /> : inbox.data?.length ? (
              <div>
                {inbox.data.slice(0, 5).map((i) => <InboxRow key={i.id} item={i} onClick={() => router.push(i.href)} />)}
                {inbox.data.length > 5 && (
                  <Link href="/inbox" className="flex h-9 items-center justify-center gap-1 text-2xs text-muted-foreground hover:text-foreground">
                    {inbox.data.length - 5} more <ArrowRight className="size-3" />
                  </Link>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-3 px-4 py-4 text-muted-foreground"><Sparkles className="size-4 text-success" />Inbox zero. Agents are either working or done.</div>
            )}
          </Card>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="flex items-center gap-2 text-[14px] font-semibold">Agent threads <span className="font-normal text-muted-foreground">{shown.length}</span></h2>
              <div className="flex rounded-md border bg-panel p-0.5 text-2xs">
                {(["active", "all"] as const).map((f) => (
                  <button key={f} onClick={() => setFilter(f)} className={cn("rounded px-2.5 py-1 capitalize", filter === f ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground")}>{f}</button>
                ))}
              </div>
            </div>
            {threads.isLoading ? <Loading rows={4} /> : shown.length ? (
              <div className="grid gap-3 sm:grid-cols-2 2xl:grid-cols-3" data-testid="thread-grid">
                {shown.slice(0, 18).map((t) => <ThreadCard key={t.workspace_id} t={t} />)}
              </div>
            ) : (
              <Card><Empty title={filter === "active" ? "No active threads" : "No threads yet"} hint="Start an agent with `forge agent start` or run demo/run_demo.py --api http://localhost:8000." /></Card>
            )}
          </section>
        </div>

        <div className="space-y-6">
          <Card className="flex max-h-[560px] flex-col overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle>Live activity</CardTitle><span className="text-2xs text-muted-foreground">streamed</span></CardHeader>
            <div className="scrollbar-thin flex-1 overflow-y-auto" data-testid="activity-feed">
              {events.length ? events.slice(0, 80).map((e) => <EventRow key={e.seq} e={e} compact />) : <Empty title="Waiting for events…" />}
            </div>
          </Card>
          <Card className="overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle>Risk distribution</CardTitle></CardHeader>
            {d ? <RiskDistribution dist={d.risk_distribution} /> : <Loading rows={1} />}
          </Card>
          <Card className="overflow-hidden">
            <CardHeader className="py-2.5"><CardTitle>Merge queue</CardTitle><Link href="/merge-queue" className="text-2xs text-muted-foreground hover:text-foreground">View</Link></CardHeader>
            {d?.merge_queue.length ? d.merge_queue.map((m, i) => (
              <Link key={m.id} href={`/workspaces/${m.workspace.id}`} className="row">
                <span className="w-4 font-mono text-2xs text-muted-foreground">{i + 1}</span>
                <span className="min-w-0 flex-1 truncate">{m.task.title}</span>
                <span className={cn("text-2xs font-medium", m.status === "READY" ? "text-success" : m.status === "CONFLICT" || m.status === "BLOCKED" ? "text-destructive" : "text-warning")}>{m.status.replaceAll("_", " ").toLowerCase()}</span>
              </Link>
            )) : <div className="px-4 py-4 text-2xs text-muted-foreground">Queue is empty</div>}
          </Card>
        </div>
      </div>
    </div>
  );
}
