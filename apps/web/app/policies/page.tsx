"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorBox, Loading, PageHeader } from "@/components/common";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input, Label, Table, Td, Textarea, Th, Tr } from "@/components/ui/primitives";
import { api, type Policy } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Effective { default: string; policies: { name: string; effect: string; actions: string[]; paths: string[]; agents: string[]; commands: string[]; min_risk: number | null; severity: string | null; reason: string | null }[] }
interface Decision { effect: string; reasons: string[] }

const EFFECT_TONE: Record<string, "danger" | "warning" | "primary" | "success"> = { deny: "danger", require_approval: "warning", require_review: "primary", allow: "success" };

export default function PoliciesPage() {
  const qc = useQueryClient();
  const docs = useQuery({ queryKey: ["policies"], queryFn: () => api.get<Policy[]>("/policies") });
  const eff = useQuery({ queryKey: ["policies", "effective"], queryFn: () => api.get<Effective>("/policies/effective") });
  const global = docs.data?.find((d) => d.scope === "global");
  const [doc, setDoc] = useState("");
  useEffect(() => { if (global) setDoc(global.document); }, [global?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({ mutationFn: () => api.put<Policy>("/policies/global", { document: doc }), onSuccess: () => qc.invalidateQueries({ queryKey: ["policies"] }) });

  const [check, setCheck] = useState({ action: "merge", paths: "package.json, src/app.py", risk_score: "" });
  const run = useMutation({
    mutationFn: () => api.post<Decision>("/policies/check", {
      action: check.action, paths: check.paths.split(",").map((s) => s.trim()).filter(Boolean),
      risk_score: check.risk_score ? Number(check.risk_score) : null,
    }),
  });

  return (
    <>
      <PageHeader title="Policies" description="Deterministic YAML rules. Precedence: deny › require approval › require review › allow." />
      <div className="grid gap-6 xl:grid-cols-[1fr_420px]">
        <div className="space-y-6">
          <Card>
            <CardHeader><CardTitle>Effective rules</CardTitle>{eff.data && <span className="text-xs text-muted-foreground">default: {eff.data.default}</span>}</CardHeader>
            {eff.isLoading ? <Loading /> : (
              <Table>
                <thead><tr><Th>Rule</Th><Th>Effect</Th><Th>Matches</Th></tr></thead>
                <tbody>
                  {eff.data?.policies.map((p) => (
                    <Tr key={p.name}>
                      <Td className="font-mono text-xs">{p.name}</Td>
                      <Td><Badge tone={EFFECT_TONE[p.effect]}>{p.effect.replace("_", " ")}</Badge></Td>
                      <Td className="text-xs text-muted-foreground">
                        {[p.actions.length && `action ${p.actions.join(", ")}`, p.paths.length && `paths ${p.paths.join(", ")}`,
                          p.agents.length && `agents ${p.agents.join(", ")}`, p.commands.length && `command ${p.commands.join(", ")}`,
                          p.min_risk != null && `risk ≥ ${p.min_risk}`, p.severity && `severity ≥ ${p.severity}`].filter(Boolean).join(" · ")}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Global policy document</CardTitle>
              {global && <span className="text-xs text-muted-foreground">v{global.version} · {global.created_by} · {timeAgo(global.created_at)}</span>}
            </CardHeader>
            <CardContent className="space-y-3">
              <Textarea rows={22} spellCheck={false} className="font-mono text-xs" value={doc} onChange={(e) => setDoc(e.target.value)} data-testid="policy-editor" />
              {save.error && <ErrorBox error={save.error} />}
              <div className="flex items-center justify-end gap-3">
                {save.isSuccess && <span className="text-xs text-success">Published v{save.data.version}</span>}
                <Button onClick={() => save.mutate()} disabled={save.isPending || doc === global?.document}><Save />Publish new version</Button>
              </div>
            </CardContent>
          </Card>
        </div>
        <Card className="h-fit">
          <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4" />Policy check</CardTitle></CardHeader>
          <CardContent>
            <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); run.mutate(); }}>
              <div><Label htmlFor="pc-action">Action</Label><Input id="pc-action" value={check.action} onChange={(e) => setCheck({ ...check, action: e.target.value })} /></div>
              <div><Label htmlFor="pc-paths">Paths (comma separated)</Label><Input id="pc-paths" value={check.paths} onChange={(e) => setCheck({ ...check, paths: e.target.value })} /></div>
              <div><Label htmlFor="pc-risk">Risk score</Label><Input id="pc-risk" type="number" value={check.risk_score} onChange={(e) => setCheck({ ...check, risk_score: e.target.value })} /></div>
              <Button type="submit" variant="outline" className="w-full" disabled={run.isPending}>Evaluate</Button>
            </form>
            {run.data && (
              <div className="mt-4 rounded-md border p-3" data-testid="policy-decision">
                <Badge tone={run.data.effect === "DENY" ? "danger" : run.data.effect === "ALLOW" ? "success" : "warning"}>{run.data.effect}</Badge>
                <ul className="mt-2 space-y-1">{run.data.reasons.map((r) => <li key={r} className="text-xs text-muted-foreground">· {r}</li>)}</ul>
              </div>
            )}
            {run.error && <div className="mt-3"><ErrorBox error={run.error} /></div>}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
