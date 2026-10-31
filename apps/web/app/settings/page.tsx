"use client";

import { useQuery } from "@tanstack/react-query";
import { ErrorBox, Loading, PageHeader } from "@/components/common";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "@/components/ui/primitives";
import { api } from "@/lib/api";

interface RuntimeSettings {
  principal: { type: string; name: string }; auth_mode: string; database: string; event_bus: string; artifact_store: string;
  version_engine: string; command_timeout: number;
  sandbox: { sandbox: string; guarantees: Record<string, boolean>; network_policy: string; allowed_commands: string[]; platform: string; python: string };
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-4 border-b py-2 text-sm last:border-0"><span className="text-muted-foreground">{k}</span><span className="text-right">{v}</span></div>;
}

export default function SettingsPage() {
  const { data: s, error } = useQuery({ queryKey: ["settings"], queryFn: () => api.get<RuntimeSettings>("/settings") });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => api.get<{ valid: boolean; checked: number }>("/events/verify") });
  if (error) return <ErrorBox error={error} />;
  if (!s) return <Loading />;
  return (
    <>
      <PageHeader title="Settings" description="Runtime configuration of this control plane. Change it with FORGEFLOW_* environment variables." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Platform</CardTitle></CardHeader>
          <CardContent>
            <Row k="Signed in as" v={`${s.principal.name} (${s.principal.type})`} />
            <Row k="Auth mode" v={<Badge tone={s.auth_mode === "dev" ? "warning" : "success"}>{s.auth_mode}</Badge>} />
            <Row k="Metadata database" v={s.database} />
            <Row k="Event bus" v={s.event_bus} />
            <Row k="Artifact store" v={s.artifact_store} />
            <Row k="Version engine" v={s.version_engine} />
            <Row k="Audit chain" v={verify.data ? <Badge tone={verify.data.valid ? "success" : "danger"}>{verify.data.valid ? "valid" : "broken"} · {verify.data.checked} events</Badge> : "…"} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Sandbox</CardTitle><Badge tone={s.sandbox.sandbox === "docker" ? "success" : "warning"}>{s.sandbox.sandbox}</Badge></CardHeader>
          <CardContent>
            {Object.entries(s.sandbox.guarantees).map(([k, v]) => <Row key={k} k={k.replaceAll("_", " ")} v={<Badge tone={v ? "success" : "warning"}>{v ? "enforced" : "not enforced"}</Badge>} />)}
            <Row k="Network policy" v={s.sandbox.network_policy} />
            <Row k="Command timeout" v={`${s.command_timeout}s`} />
            <div className="pt-3 text-xs text-muted-foreground">Allowed executables</div>
            <div className="mt-1.5 flex flex-wrap gap-1">{s.sandbox.allowed_commands.map((c) => <Badge key={c}>{c}</Badge>)}</div>
            {s.sandbox.sandbox === "local" && (
              <p className="mt-4 text-xs text-warning">The local sandbox confines the working directory and scrubs the environment but cannot enforce network or resource limits. Set FORGEFLOW_SANDBOX=docker for production.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
