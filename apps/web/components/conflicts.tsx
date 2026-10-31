"use client";

import { AlertTriangle } from "lucide-react";
import type { SemanticConflict } from "@/lib/api";
import { Badge, Card, CardHeader, CardTitle } from "./ui/primitives";

export function ConflictList({ conflicts, title }: { conflicts: SemanticConflict[]; title: string }) {
  if (!conflicts.length) return null;
  return (
    <Card className="border-warning/40">
      <CardHeader><CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-warning" />{title}</CardTitle></CardHeader>
      <ul className="divide-y">
        {conflicts.map((c, i) => (
          <li key={i} className="space-y-1 px-4 py-3 text-sm" data-testid="semantic-conflict">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={c.severity === "MEDIUM" ? "warning" : "danger"}>{c.severity}</Badge>
              <span className="font-mono text-xs">{c.conflict_type}</span>
              {c.with && <span className="text-xs text-muted-foreground">with {c.with}</span>}
            </div>
            <div>{c.explanation}</div>
            <div className="text-xs text-muted-foreground">symbols: {c.affected_symbols.join(", ")} · files: {c.affected_files.join(", ")}</div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
