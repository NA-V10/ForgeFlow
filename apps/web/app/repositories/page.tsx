"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderGit2, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Commit, Empty, ErrorBox, Loading, PageHeader } from "@/components/common";
import { Button, Card, Dialog, DialogContent, DialogTrigger, Input, Label, Table, Td, Th, Tr } from "@/components/ui/primitives";
import { api, type Repository } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

function CreateRepository() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", source_url: "", test_command: "pytest -q", description: "" });
  const m = useMutation({
    mutationFn: () => api.post<Repository>("/repositories", {
      name: form.name, description: form.description, source_url: form.source_url || null,
      settings: form.test_command ? { test_command: form.test_command } : {},
    }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["repositories"] }); setOpen(false); },
  });
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild><Button><Plus />Register repository</Button></DialogTrigger>
      <DialogContent title="Register repository" description="Create an empty Git repository or import an existing one by path or URL.">
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate(); }}>
          <div><Label htmlFor="repo-name">Name</Label><Input id="repo-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="payments-service" /></div>
          <div><Label htmlFor="repo-src">Import from (optional)</Label><Input id="repo-src" value={form.source_url} onChange={(e) => setForm({ ...form, source_url: e.target.value })} placeholder="https://github.com/org/repo.git or /path/to/repo" /></div>
          <div><Label htmlFor="repo-test">Test command (run on every merge)</Label><Input id="repo-test" value={form.test_command} onChange={(e) => setForm({ ...form, test_command: e.target.value })} /></div>
          {m.error && <ErrorBox error={m.error} />}
          <div className="flex justify-end"><Button type="submit" disabled={m.isPending}>Register</Button></div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function RepositoriesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["repositories"], queryFn: () => api.get<Repository[]>("/repositories") });
  return (
    <>
      <PageHeader title="Repositories" description="Git-backed repositories under ForgeFlow control." actions={<CreateRepository />} />
      <Card>
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !data?.length ? (
          <Empty icon={FolderGit2} title="No repositories" hint="Register one here or with `forge repo create`." />
        ) : (
          <Table>
            <thead><tr><Th>Name</Th><Th>Branch</Th><Th>Head</Th><Th>Test command</Th><Th>Created</Th></tr></thead>
            <tbody>
              {data.map((r) => (
                <Tr key={r.id}>
                  <Td><Link href={`/repositories/${r.id}`} className="font-medium hover:underline">{r.name}</Link><div className="text-xs text-muted-foreground">{r.description}</div></Td>
                  <Td className="font-mono text-xs">{r.default_branch}</Td>
                  <Td><Commit sha={r.head} /></Td>
                  <Td className="font-mono text-xs text-muted-foreground">{String(r.settings.test_command ?? "—")}</Td>
                  <Td className="text-xs text-muted-foreground">{timeAgo(r.created_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
