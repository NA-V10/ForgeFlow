"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Copy, Plus } from "lucide-react";
import { useState } from "react";
import { Empty, ErrorBox, Loading, PageHeader, StatusBadge } from "@/components/common";
import { Badge, Button, Card, Dialog, DialogContent, DialogTrigger, Input, Label, Select, Table, Td, Th, Tr } from "@/components/ui/primitives";
import { api, type Agent } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

function RegisterAgent() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", model: "claude-opus-5-5", model_version: "", kind: "llm" });
  const m = useMutation({
    mutationFn: () => api.post<Agent & { token: string }>("/agents", { ...form, model_version: form.model_version || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (!o) m.reset(); }}>
      <DialogTrigger asChild><Button><Plus />Register agent</Button></DialogTrigger>
      <DialogContent title="Register agent" description="Agents get a credential for the tool API. It is shown once.">
        {m.data ? (
          <div className="space-y-3">
            <div className="text-sm">Agent <b>{m.data.name}</b> registered. Store this token now; it cannot be retrieved later.</div>
            <div className="flex items-center gap-2 rounded-md border bg-muted p-2 font-mono text-xs">
              <span className="flex-1 break-all" data-testid="agent-token">{m.data.token}</span>
              <Button size="icon" variant="ghost" onClick={() => navigator.clipboard?.writeText(m.data!.token)} aria-label="Copy token"><Copy /></Button>
            </div>
            <div className="text-xs text-muted-foreground">Run it with <code>FORGEFLOW_AGENT_TOKEN=… forge agent start {m.data.name} --task &lt;id&gt; --claude</code></div>
          </div>
        ) : (
          <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
            <div><Label htmlFor="agent-name">Name</Label><Input id="agent-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="agent_billing" /></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label>Model</Label><Input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></div>
              <div><Label>Model version</Label><Input value={form.model_version} onChange={(e) => setForm({ ...form, model_version: e.target.value })} /></div>
            </div>
            <div><Label>Kind</Label>
              <Select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                <option value="llm">LLM</option><option value="scripted">Scripted</option><option value="external">External</option>
              </Select>
            </div>
            {m.error && <ErrorBox error={m.error} />}
            <div className="flex justify-end"><Button type="submit" disabled={m.isPending}>Register</Button></div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

export default function AgentsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["agents"], queryFn: () => api.get<Agent[]>("/agents") });
  return (
    <>
      <PageHeader title="Agents" description="Agent identities. Every action they take is attributed to them." actions={<RegisterAgent />} />
      <Card>
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !data?.length ? <Empty icon={Bot} title="No agents registered" /> : (
          <Table>
            <thead><tr><Th>Agent</Th><Th>Status</Th><Th>Kind</Th><Th>Model</Th><Th>Registered</Th></tr></thead>
            <tbody>
              {data.map((a) => (
                <Tr key={a.id}>
                  <Td><div className="flex items-center gap-2 font-medium"><Bot className="size-4 text-muted-foreground" />{a.name}</div><div className="text-xs text-muted-foreground">{a.description}</div></Td>
                  <Td><StatusBadge status={a.status} /></Td>
                  <Td><Badge>{a.kind}</Badge></Td>
                  <Td className="font-mono text-xs">{a.model}{a.model_version ? `@${a.model_version}` : ""}</Td>
                  <Td className="text-xs text-muted-foreground">{timeAgo(a.created_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
