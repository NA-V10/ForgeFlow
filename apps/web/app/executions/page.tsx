"use client";

import { useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import Link from "next/link";
import { Commit, Empty, ErrorBox, Loading, PageHeader, StatusBadge, Tests } from "@/components/common";
import { Card, Table, Td, Th, Tr } from "@/components/ui/primitives";
import { api, type Execution } from "@/lib/api";
import { duration, timeAgo } from "@/lib/utils";

export default function ExecutionsPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["executions"], queryFn: () => api.get<Execution[]>("/executions") });
  return (
    <>
      <PageHeader title="Executions" description="Every agent run: model, commands, files, tests and evidence." />
      <Card>
        {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !data?.length ? <Empty icon={Play} title="No executions yet" /> : (
          <Table>
            <thead><tr><Th>Execution</Th><Th>Agent</Th><Th>Task</Th><Th>Model</Th><Th>Tools</Th><Th>Tests</Th><Th>Duration</Th><Th>Started</Th></tr></thead>
            <tbody>
              {data.map((e) => (
                <Tr key={e.id}>
                  <Td><Link href={`/executions/${e.id}`} className="flex items-center gap-2 hover:underline"><StatusBadge status={e.status} /><Commit sha={e.id} /></Link></Td>
                  <Td className="font-medium">{e.agent.name}</Td>
                  <Td className="max-w-[240px] truncate">{e.task.title}</Td>
                  <Td className="font-mono text-xs">{e.model}{e.model_version ? `@${e.model_version}` : ""}</Td>
                  <Td className="tabular-nums">{e.summary.tool_calls ?? "—"}{e.summary.denied ? <span className="text-destructive"> ({e.summary.denied} denied)</span> : null}</Td>
                  <Td><Tests tests={e.summary.tests} /></Td>
                  <Td className="text-xs">{duration(e.summary.duration_ms)}</Td>
                  <Td className="text-xs text-muted-foreground">{timeAgo(e.started_at)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
