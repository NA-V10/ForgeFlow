"use client";

import { useQuery } from "@tanstack/react-query";
import { GitPullRequestArrow } from "lucide-react";
import Link from "next/link";
import { Commit, Empty, ErrorBox, Loading, PageHeader } from "@/components/common";
import { Badge, Card, Table, Td, Th, Tr } from "@/components/ui/primitives";
import { api, type Change } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

export default function ChangesPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["changes"], queryFn: () => api.get<Change[]>("/changes", { limit: 300 }) });
  return (
    <>
      <PageHeader title="Changes" description="Every file change, attributed to the agent, task and execution that produced it." />
      <Card>
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !data?.length ? <Empty icon={GitPullRequestArrow} title="No changes recorded" /> : (
          <Table>
            <thead><tr><Th>File</Th><Th>Semantic</Th><Th>Agent</Th><Th>Task</Th><Th>Commit</Th><Th>When</Th></tr></thead>
            <tbody>
              {data.map((c) => (
                <Tr key={c.id}>
                  <Td>
                    <div className="flex items-center gap-2">
                      <Badge tone={c.change_type === "A" ? "success" : c.change_type === "D" ? "danger" : "neutral"}>{c.change_type}</Badge>
                      <span className="font-mono text-xs">{c.path}</span>
                    </div>
                    <div className="mt-0.5 font-mono text-[11px]"><span className="text-success">+{c.additions}</span> <span className="text-destructive">-{c.deletions}</span></div>
                  </Td>
                  <Td className="max-w-sm">
                    <div className="flex flex-wrap gap-1">
                      {c.semantic.slice(0, 4).map((s, i) => <Badge key={i} tone="primary">{s.kind.replaceAll("_", " ")}{s.symbol ? `: ${s.symbol}` : ""}</Badge>)}
                      {c.semantic.length > 4 && <Badge>+{c.semantic.length - 4}</Badge>}
                    </div>
                  </Td>
                  <Td>{c.agent?.name ?? "human"}</Td>
                  <Td className="max-w-[220px] truncate"><Link href={`/tasks/${c.task.id}`} className="hover:underline">{c.task.title}</Link></Td>
                  <Td>{c.execution_id ? <Link href={`/executions/${c.execution_id}`}><Commit sha={c.commit_sha} /></Link> : <Commit sha={c.commit_sha} />}</Td>
                  <Td className="text-xs text-muted-foreground">{timeAgo(c.created_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
