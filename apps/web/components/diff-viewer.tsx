"use client";

import { Braces, Boxes, ChevronDown, ChevronRight, FileCode2, Globe, Package, Settings2, Shapes, Variable } from "lucide-react";
import { useMemo, useState } from "react";
import type { SemanticChange, SemanticDiff } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Empty } from "./common";
import { Badge, Tabs, TabsContent, TabsList, TabsTrigger } from "./ui/primitives";

// ------------------------------------------------------------ patch parsing
interface Line { kind: "ctx" | "add" | "del"; text: string; old?: number; new?: number }
interface Hunk { header: string; lines: Line[] }
interface FilePatch { path: string; hunks: Hunk[]; binary: boolean; status: string }

export function parsePatch(patch: string): FilePatch[] {
  const files: FilePatch[] = [];
  let file: FilePatch | null = null;
  let hunk: Hunk | null = null;
  let oldNo = 0;
  let newNo = 0;
  for (const raw of patch.split("\n")) {
    if (raw.startsWith("diff --git ")) {
      const m = raw.match(/^diff --git a\/(.+) b\/(.+)$/);
      file = { path: m ? m[2] : raw.slice(11), hunks: [], binary: false, status: "M" };
      files.push(file);
      hunk = null;
    } else if (!file) {
      continue;
    } else if (raw.startsWith("new file mode")) {
      file.status = "A";
    } else if (raw.startsWith("deleted file mode")) {
      file.status = "D";
    } else if (raw.startsWith("Binary files")) {
      file.binary = true;
    } else if (raw.startsWith("@@")) {
      const m = raw.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/);
      oldNo = m ? parseInt(m[1], 10) : 0;
      newNo = m ? parseInt(m[2], 10) : 0;
      hunk = { header: raw, lines: [] };
      file.hunks.push(hunk);
    } else if (hunk) {
      if (raw.startsWith("+") && !raw.startsWith("+++")) hunk.lines.push({ kind: "add", text: raw.slice(1), new: newNo++ });
      else if (raw.startsWith("-") && !raw.startsWith("---")) hunk.lines.push({ kind: "del", text: raw.slice(1), old: oldNo++ });
      else if (raw.startsWith(" ")) hunk.lines.push({ kind: "ctx", text: raw.slice(1), old: oldNo++, new: newNo++ });
    }
  }
  return files;
}

function lineClass(kind: Line["kind"]) {
  return kind === "add" ? "diff-add" : kind === "del" ? "diff-del" : "";
}

function Gutter({ n }: { n?: number }) {
  return <td className="w-10 select-none border-r px-2 text-right align-top text-[11px] text-muted-foreground/70 tabular-nums">{n ?? ""}</td>;
}

function FileHeader({ f, open, toggle, stats }: { f: FilePatch; open: boolean; toggle: () => void; stats: { add: number; del: number } }) {
  return (
    <button onClick={toggle} className="flex w-full items-center gap-2 border-b bg-muted/50 px-3 py-2 text-left text-[13px]">
      {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
      <FileCode2 className="size-4 text-muted-foreground" />
      <span className="font-mono">{f.path}</span>
      <Badge tone={f.status === "A" ? "success" : f.status === "D" ? "danger" : "neutral"}>{f.status === "A" ? "added" : f.status === "D" ? "deleted" : "modified"}</Badge>
      <span className="ml-auto font-mono text-xs"><span className="text-success">+{stats.add}</span> <span className="text-destructive">-{stats.del}</span></span>
    </button>
  );
}

function useOpen(files: FilePatch[]) {
  const [closed, setClosed] = useState<Set<string>>(new Set());
  return {
    isOpen: (p: string) => !closed.has(p),
    toggle: (p: string) => setClosed((s) => { const n = new Set(s); if (n.has(p)) n.delete(p); else n.add(p); return n; }),
    files,
  };
}

function stats(f: FilePatch) {
  let add = 0, del = 0;
  f.hunks.forEach((h) => h.lines.forEach((l) => { if (l.kind === "add") add++; else if (l.kind === "del") del++; }));
  return { add, del };
}

function UnifiedView({ files }: { files: FilePatch[] }) {
  const o = useOpen(files);
  return (
    <div className="space-y-3">
      {files.map((f) => (
        <div key={f.path} className="overflow-hidden rounded-lg border" data-diff-file={f.path}>
          <FileHeader f={f} open={o.isOpen(f.path)} toggle={() => o.toggle(f.path)} stats={stats(f)} />
          {o.isOpen(f.path) && (f.binary ? <div className="p-3 text-xs text-muted-foreground">Binary file</div> : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse font-mono text-[12px] leading-5">
                <tbody>
                  {f.hunks.map((h, hi) => [
                    <tr key={`h${hi}`} className="bg-info/5 text-info/90"><td colSpan={3} className="px-3 py-1 text-[11px]">{h.header}</td></tr>,
                    ...h.lines.map((l, li) => (
                      <tr key={`${hi}-${li}`} className={lineClass(l.kind)}>
                        <Gutter n={l.old} /><Gutter n={l.new} />
                        <td className="whitespace-pre px-3"><span className="mr-2 select-none text-muted-foreground">{l.kind === "add" ? "+" : l.kind === "del" ? "-" : " "}</span>{l.text}</td>
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function pairLines(lines: Line[]): [Line | null, Line | null][] {
  const rows: [Line | null, Line | null][] = [];
  let dels: Line[] = [], adds: Line[] = [];
  const flush = () => {
    const n = Math.max(dels.length, adds.length);
    for (let i = 0; i < n; i++) rows.push([dels[i] ?? null, adds[i] ?? null]);
    dels = []; adds = [];
  };
  for (const l of lines) {
    if (l.kind === "del") dels.push(l);
    else if (l.kind === "add") adds.push(l);
    else { flush(); rows.push([l, l]); }
  }
  flush();
  return rows;
}

function SplitView({ files }: { files: FilePatch[] }) {
  const o = useOpen(files);
  return (
    <div className="space-y-3">
      {files.map((f) => (
        <div key={f.path} className="overflow-hidden rounded-lg border">
          <FileHeader f={f} open={o.isOpen(f.path)} toggle={() => o.toggle(f.path)} stats={stats(f)} />
          {o.isOpen(f.path) && !f.binary && (
            <div className="overflow-x-auto">
              <table className="w-full table-fixed border-collapse font-mono text-[12px] leading-5">
                <colgroup><col className="w-10" /><col /><col className="w-10" /><col /></colgroup>
                <tbody>
                  {f.hunks.map((h, hi) => [
                    <tr key={`h${hi}`} className="bg-info/5 text-info/90"><td colSpan={4} className="px-3 py-1 text-[11px]">{h.header}</td></tr>,
                    ...pairLines(h.lines).map(([a, b], i) => (
                      <tr key={`${hi}-${i}`}>
                        <Gutter n={a?.old} />
                        <td className={cn("overflow-hidden whitespace-pre border-r px-3", a && a.kind === "del" && "diff-del")}>{a?.text ?? ""}</td>
                        <Gutter n={b?.new} />
                        <td className={cn("overflow-hidden whitespace-pre px-3", b && b.kind === "add" && "diff-add")}>{b?.text ?? ""}</td>
                      </tr>
                    )),
                  ])}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

const GROUPS: { key: string; title: string; icon: typeof Braces }[] = [
  { key: "functions", title: "Functions", icon: Braces },
  { key: "classes", title: "Classes", icon: Boxes },
  { key: "imports", title: "Imports", icon: Shapes },
  { key: "apis", title: "APIs", icon: Globe },
  { key: "dependencies", title: "Dependencies", icon: Package },
  { key: "configuration", title: "Configuration", icon: Settings2 },
  { key: "variables", title: "Module variables", icon: Variable },
  { key: "files", title: "Files", icon: FileCode2 },
];

function kindTone(kind: string): "success" | "danger" | "warning" | "neutral" {
  if (kind.endsWith("_added")) return "success";
  if (kind.endsWith("_removed")) return "danger";
  if (kind.endsWith("_modified") || kind.endsWith("_changed")) return "warning";
  return "neutral";
}

function verb(kind: string) {
  const v = kind.split("_").pop()!;
  return { added: "added", removed: "removed", modified: "modified", changed: "changed" }[v] ?? v;
}

export function SemanticView({ semantic }: { semantic: SemanticDiff | null | undefined }) {
  if (!semantic || !Object.keys(semantic.groups).length) return <Empty title="No semantic changes" hint="Only formatting, comments or unsupported files changed." />;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="space-y-3">
        {GROUPS.filter((g) => semantic.groups[g.key]?.length).map(({ key, title, icon: Icon }) => (
          <div key={key} className="rounded-lg border" data-semantic-group={key}>
            <div className="flex items-center gap-2 border-b bg-muted/50 px-3 py-2 text-[13px] font-medium">
              <Icon className="size-4 text-muted-foreground" />{title}
              <span className="ml-auto text-xs text-muted-foreground">{semantic.groups[key].length}</span>
            </div>
            <ul className="divide-y">
              {semantic.groups[key].map((c: SemanticChange, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <Badge tone={kindTone(c.kind)}>{verb(c.kind)}</Badge>
                  <span className="font-mono text-[13px]">{c.category === "imports"
                    ? (c.details.names?.length ? `${c.details.names.join(", ")} from ${c.details.module}` : c.details.module)
                    : c.category === "apis" ? `${c.details.method} ${c.details.path}`
                    : c.symbol ?? c.details.package ?? c.details.key ?? c.path}</span>
                  {c.details.signature_changed && <Badge tone="danger">signature changed</Badge>}
                  {c.details.sensitive && <Badge tone="danger">sensitive</Badge>}
                  <span className="text-xs text-muted-foreground">{c.path}{c.line ? `:${c.line}` : ""}</span>
                  <span className="ml-auto flex gap-1">{c.domains.filter((d) => !["Dependencies", "Configuration"].includes(d)).map((d) => <Badge key={d} tone="primary">{d}</Badge>)}</span>
                  {c.details.signature_changed && (
                    <div className="w-full font-mono text-[12px] text-muted-foreground">{c.details.old_signature} → {c.details.new_signature}</div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="h-fit rounded-lg border">
        <div className="border-b bg-muted/50 px-3 py-2 text-[13px] font-medium">Summary by domain</div>
        <div className="space-y-3 p-3">
          {Object.entries(semantic.domains).map(([domain, items]) => (
            <div key={domain}>
              <div className="text-xs font-semibold">{domain}</div>
              <ul className="mt-1 space-y-0.5">
                {items.map((it) => <li key={it} className="text-xs text-muted-foreground">– {it}</li>)}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function DiffViewer({ patch, semantic, defaultTab = "unified" }: { patch: string; semantic?: SemanticDiff | null; defaultTab?: string }) {
  const files = useMemo(() => parsePatch(patch), [patch]);
  return (
    <Tabs defaultValue={defaultTab}>
      <TabsList>
        <TabsTrigger value="unified">Unified</TabsTrigger>
        <TabsTrigger value="split">Split</TabsTrigger>
        <TabsTrigger value="semantic">Semantic</TabsTrigger>
      </TabsList>
      <div className="mt-3">
        <TabsContent value="unified">{files.length ? <UnifiedView files={files} /> : <Empty title="No changes" />}</TabsContent>
        <TabsContent value="split">{files.length ? <SplitView files={files} /> : <Empty title="No changes" />}</TabsContent>
        <TabsContent value="semantic"><SemanticView semantic={semantic} /></TabsContent>
      </div>
    </Tabs>
  );
}
