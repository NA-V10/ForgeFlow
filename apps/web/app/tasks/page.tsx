"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Circle, CircleDashed, CircleDot, CircleSlash, Hammer, Plus, XCircle, Eye } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useListNavigation } from "@/components/command";
import { Empty, ErrorBox, Loading } from "@/components/common";
import { AgentAvatar, Kbd, PriorityBars, ago } from "@/components/forge";
import { Button, Dialog, DialogContent, Input, Label, Select, Textarea } from "@/components/ui/primitives";
import { api, type Agent, type Repository, type Task } from "@/lib/api";
import { cn } from "@/lib/utils";

const TASK_GROUPS: { status: string; title: string; icon: typeof Circle; tone: string }[] = [
  { status: "RUNNING", title: "Running", icon: CircleDot, tone: "text-agent" },
  { status: "BLOCKED", title: "Blocked", icon: CircleSlash, tone: "text-destructive" },
  { status: "REVIEW", title: "In review", icon: Eye, tone: "text-primary" },
  { status: "PENDING", title: "Pending", icon: CircleDashed, tone: "text-muted-foreground" },
  { status: "FAILED", title: "Failed", icon: XCircle, tone: "text-destructive" },
  { status: "COMPLETED", title: "Completed", icon: CheckCircle2, tone: "text-success" },
  { status: "CANCELLED", title: "Cancelled", icon: Circle, tone: "text-muted-foreground" },
];

function CreateTask({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient();
  const router = useRouter();
  const repos = useQuery({ queryKey: ["repositories"], queryFn: () => api.get<Repository[]>("/repositories") });
  const agents = useQuery({ queryKey: ["agents"], queryFn: () => api.get<Agent[]>("/agents") });
  const [form, setForm] = useState({ repository_id: "", title: "", description: "", priority: "MEDIUM", agent_id: "" });
  const m = useMutation({
    mutationFn: () => api.post<Task>("/tasks", { ...form, repository_id: form.repository_id || repos.data?.[0]?.id, agent_id: form.agent_id || null }),
    onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["tasks"] }); onOpenChange(false); router.push(`/tasks/${t.id}`); },
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New task" description="A unit of work for an agent. Its base commit is the repository head right now.">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") m.mutate(); }}>
          <Input id="task-title" aria-label="Title" autoFocus required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
            placeholder="Implement OAuth authentication" className="h-10 border-0 bg-transparent px-0 text-[15px] font-medium focus-visible:ring-0" />
          <Textarea id="task-desc" aria-label="Description" rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Add a description…" className="border-0 bg-transparent px-0 focus-visible:ring-0" />
          <div className="grid grid-cols-3 gap-2 border-t pt-3">
            <div><Label htmlFor="task-repo">Repository</Label>
              <Select id="task-repo" value={form.repository_id} onChange={(e) => setForm({ ...form, repository_id: e.target.value })}>
                {repos.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </Select>
            </div>
            <div><Label htmlFor="task-agent">Agent</Label>
              <Select id="task-agent" value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}>
                <option value="">Unassigned</option>
                {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </div>
            <div><Label htmlFor="task-prio">Priority</Label>
              <Select id="task-prio" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => <option key={p}>{p}</option>)}
              </Select>
            </div>
          </div>
          {m.error && <ErrorBox error={m.error} />}
          <div className="flex items-center justify-end gap-2">
            <span className="text-2xs text-muted-foreground"><Kbd>⌘</Kbd> <Kbd>↵</Kbd></span>
            <Button type="submit" disabled={m.isPending || !repos.data?.length}>Create task</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function TasksView() {
  const router = useRouter();
  const params = useSearchParams();
  const [createOpen, setCreateOpen] = useState(false);
  const [showDone, setShowDone] = useState(true);
  useEffect(() => { if (params.get("new")) setCreateOpen(true); }, [params]);
  const { data, isLoading, error } = useQuery({ queryKey: ["tasks"], queryFn: () => api.get<Task[]>("/tasks", { limit: 500 }) });
  const groups = TASK_GROUPS.filter((g) => showDone || !["COMPLETED", "CANCELLED"].includes(g.status))
    .map((g) => ({ ...g, rows: (data ?? []).filter((t) => t.status === g.status) })).filter((g) => g.rows.length);
  const flat = groups.flatMap((g) => g.rows);
  const nav = useListNavigation(flat, (t) => router.push(`/tasks/${t.id}`));

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <h1 className="text-[18px] font-semibold tracking-tight">Tasks</h1>
        <span className="text-muted-foreground">{data?.length ?? 0}</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={() => setShowDone(!showDone)} className="h-7 rounded-md border px-2.5 text-[12px] text-muted-foreground hover:text-foreground">
            {showDone ? "Hide completed" : "Show completed"}
          </button>
          <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="new-task"><Plus />New task<Kbd className="ml-1 border-black/10 bg-black/10 text-primary-foreground">C</Kbd></Button>
        </div>
      </div>
      <CreateTask open={createOpen} onOpenChange={(o) => { setCreateOpen(o); if (!o && params.get("new")) router.replace("/tasks"); }} />
      <div className="overflow-hidden rounded-lg border bg-panel" data-testid="tasks-table">
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !flat.length ? (
          <Empty icon={Hammer} title="No tasks" hint={<>Press <Kbd>C</Kbd> to create one.</>} />
        ) : groups.map((g) => (
          <div key={g.status}>
            <div className="flex h-8 items-center gap-2 border-b bg-muted/40 px-4 text-[12px] font-medium">
              <g.icon className={cn("size-3.5", g.tone)} />{g.title}<span className="font-mono text-2xs text-muted-foreground">{g.rows.length}</span>
            </div>
            {g.rows.map((t) => (
              <Link key={t.id} href={`/tasks/${t.id}`} className="row" data-active={flat.indexOf(t) === nav.index}>
                <PriorityBars priority={t.priority} />
                <span className="w-[70px] shrink-0 font-mono text-2xs text-muted-foreground">FF-{t.id.slice(0, 4).toUpperCase()}</span>
                <g.icon className={cn("size-3.5 shrink-0", g.tone)} />
                <span className="min-w-0 flex-1 truncate">{t.title}</span>
                {t.labels.map((l) => <span key={l} className="hidden rounded-full border px-2 text-2xs text-muted-foreground md:inline">{l}</span>)}
                <span className="hidden w-36 shrink-0 items-center justify-end gap-1.5 text-2xs text-muted-foreground sm:flex">
                  {t.agent ? <><AgentAvatar name={t.agent.name} size={16} /><span className="truncate">{t.agent.name}</span></> : "unassigned"}
                </span>
                <span className="w-10 shrink-0 text-right text-2xs tabular-nums text-muted-foreground">{ago(t.created_at)}</span>
              </Link>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TasksPage() {
  return <Suspense fallback={<Loading />}><TasksView /></Suspense>;
}
