"use client";

import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Bot, FolderGit2, GitBranch, GitCommitHorizontal, GitMerge, Hammer, Layers } from "lucide-react";
import { useMemo, useState } from "react";
import type { GraphData } from "@/lib/api";
import { cn } from "@/lib/utils";
import { StatusBadge } from "./common";

const ICON = { repository: FolderGit2, branch: GitBranch, task: Hammer, agent: Bot, workspace: Layers, change: GitCommitHorizontal, merge: GitMerge };
// layout columns follow the provenance chain left → right
const COLUMN: Record<string, number> = { repository: 0, task: 1, agent: 2, workspace: 2, change: 3, merge: 3, branch: 4 };
const LANE_ORDER = ["repository", "task", "agent", "workspace", "change", "merge", "branch"];

type NodeData = { label: string; kind: string; meta: Record<string, any> };

function GraphNode({ data, selected }: NodeProps<Node<NodeData>>) {
  const Icon = ICON[data.kind as keyof typeof ICON] ?? GitBranch;
  const status = data.meta.status as string | undefined;
  return (
    <div className={cn("min-w-[160px] max-w-[220px] rounded-md border border-l-[3px] bg-elevated px-2.5 py-2 text-xs shadow-sm", ACCENT[data.kind], selected && "ring-2 ring-ring")}>
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-muted-foreground/50" />
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-muted-foreground"><Icon className="size-3" />{data.kind}</div>
      <div className="mt-1 truncate font-medium text-foreground">{data.label}</div>
      {status && <div className="mt-1"><StatusBadge status={status} /></div>}
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-muted-foreground/50" />
    </div>
  );
}

const nodeTypes = { forge: GraphNode };

// lane accent per node type (shape + label also identify the type)
const ACCENT: Record<string, string> = {
  repository: "border-l-foreground/60", task: "border-l-primary", agent: "border-l-agent", workspace: "border-l-info",
  change: "border-l-muted-foreground", merge: "border-l-success", branch: "border-l-warning",
};
const LEGEND = ["repository", "task", "agent", "workspace", "change", "merge", "branch"] as const;

export function RepoGraph({ graph, onSelect }: { graph: GraphData; onSelect?: (n: GraphData["nodes"][number]) => void }) {
  const [selected, setSelected] = useState<string | null>(null);
  const { nodes, edges } = useMemo(() => {
    const rows: Record<number, number> = {};
    const sorted = [...graph.nodes].sort((a, b) => LANE_ORDER.indexOf(a.type) - LANE_ORDER.indexOf(b.type));
    const nodes: Node<NodeData>[] = sorted.map((n) => {
      const col = COLUMN[n.type] ?? 4;
      const row = (rows[col] = (rows[col] ?? -1) + 1);
      return { id: n.id, type: "forge", position: { x: col * 250, y: row * 92 }, data: { label: n.label, kind: n.type, meta: n.data }, selected: n.id === selected };
    });
    const edges: Edge[] = graph.edges.map((e) => ({
      id: e.id, source: e.source, target: e.target, label: e.label, labelStyle: { fontSize: 10, fill: "hsl(var(--muted-foreground))" },
      labelBgStyle: { fill: "hsl(var(--background))" }, style: { stroke: "hsl(var(--muted-foreground) / 0.45)", strokeWidth: 1.25 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "hsl(var(--muted-foreground) / 0.6)" },
    }));
    return { nodes, edges };
  }, [graph, selected]);

  return (
    <div className="overflow-hidden rounded-lg border bg-background" data-testid="repo-graph">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-panel px-3 py-2 text-2xs text-muted-foreground">
        {LEGEND.map((k) => {
          const Icon = ICON[k];
          return <span key={k} className="flex items-center gap-1.5"><span className={cn("h-3 border-l-[3px]", ACCENT[k])} /><Icon className="size-3" />{k}</span>;
        })}
        <span className="ml-auto">provenance flows left → right · click a node</span>
      </div>
      <div className="h-[540px]">
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.2} nodesConnectable={false}
        onNodeClick={(_, n) => { setSelected(n.id); const g = graph.nodes.find((x) => x.id === n.id); if (g) onSelect?.(g); }}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="hsl(var(--border))" />
        <Controls showInteractive={false} className="!border !bg-panel [&>button]:!border-border [&>button]:!bg-panel [&>button]:!fill-foreground" />
      </ReactFlow>
      </div>
    </div>
  );
}
