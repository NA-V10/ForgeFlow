"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Check, GitBranch, GitMerge, Inbox as InboxIcon, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useHotkey, useListNavigation } from "@/components/command";
import { ErrorBox, GateChecks, Loading, RiskBadge, Spinner, Tests } from "@/components/common";
import { AgentName, Kbd, PriorityChip, ago } from "@/components/forge";
import { InboxRow, NEEDS_LABEL } from "@/components/inbox";
import { Button, Textarea } from "@/components/ui/primitives";
import { api, type ApprovalDetail, type InboxItem, type Merge } from "@/lib/api";

const GROUP_TITLE: Record<string, string> = { P0: "Urgent", P1: "High", P2: "Normal" };

function Preview({ item }: { item: InboxItem }) {
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const approval = useQuery({ queryKey: ["approvals", item.approval_id], enabled: !!item.approval_id,
    queryFn: () => api.get<ApprovalDetail>(`/approvals/${item.approval_id}`) });
  const merge = useQuery({ queryKey: ["merges", item.merge_id], enabled: !!item.merge_id, queryFn: () => api.get<Merge>(`/merges/${item.merge_id}`) });
  const refresh = () => ["inbox", "approvals", "merges", "dashboard", "threads", "tasks"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const decide = useMutation({
    mutationFn: (approve: boolean) => api.post(`/approvals/${item.approval_id}/${approve ? "approve" : "reject"}`, { comment: comment || null }),
    onSuccess: refresh,
  });
  const doMerge = useMutation({ mutationFn: () => api.post<Merge>(`/merges/${item.merge_id}/execute`), onSuccess: refresh, onError: refresh });
  const canDecide = item.kind === "approval" && !decide.isPending;
  const canMerge = item.needs === "merge" && !doMerge.isPending;
  useHotkey("A", () => canDecide && decide.mutate(true), canDecide);
  useHotkey("R", () => canDecide && decide.mutate(false), canDecide);
  useHotkey("M", () => canMerge && doMerge.mutate(), canMerge);

  const ctx = approval.data?.context;
  return (
    <div className="flex h-full flex-col" data-testid="inbox-preview">
      <div className="border-b px-6 py-5">
        <div className="flex items-center gap-2">
          <PriorityChip p={item.priority} />
          <span className="text-2xs font-medium text-muted-foreground">{NEEDS_LABEL[item.needs]}</span>
          <span className="ml-auto text-2xs text-muted-foreground">waiting {ago(item.created_at)}</span>
        </div>
        <h2 className="mt-2 text-[17px] font-semibold leading-snug">{item.title}</h2>
        <p className="mt-1.5 text-foreground/80">{item.reason}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-2xs text-muted-foreground">
          {item.agent && <AgentName name={item.agent.name} model={item.agent.model} />}
          {item.branch && <span className="flex items-center gap-1 font-mono"><GitBranch className="size-3" />{item.branch.replace("forgeflow/ws/", "")}</span>}
          {item.risk && <RiskBadge score={item.risk.score} severity={item.risk.severity} />}
        </div>
      </div>

      <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-6 py-5">
        {ctx && (
          <>
            <section>
              <div className="eyebrow mb-2">What changed</div>
              {ctx.semantic && Object.keys(ctx.semantic.domains).length ? (
                <div className="space-y-2">
                  {Object.entries(ctx.semantic.domains).slice(0, 5).map(([domain, lines]) => (
                    <div key={domain}>
                      <div className="text-[12px] font-medium">{domain}</div>
                      {lines.slice(0, 4).map((l) => <div key={l} className="truncate text-2xs text-muted-foreground">– {l}</div>)}
                    </div>
                  ))}
                </div>
              ) : <div className="text-2xs text-muted-foreground">{ctx.files.length} files changed</div>}
            </section>
            <section className="grid grid-cols-2 gap-4">
              <div><div className="eyebrow mb-1.5">Tests</div><Tests tests={ctx.tests} /></div>
              <div><div className="eyebrow mb-1.5">Evidence</div>
                <span className="text-2xs text-muted-foreground">{ctx.evidence.executions.length} run(s), {ctx.evidence.executions.reduce((n, e) => n + (e.tool_calls ?? 0), 0)} tool calls</span></div>
            </section>
            {ctx.risk && (
              <section>
                <div className="eyebrow mb-1.5">Risk reasons</div>
                {ctx.risk.reasons.map((r) => <div key={r} className="text-2xs text-muted-foreground">· {r}</div>)}
              </section>
            )}
          </>
        )}
        {merge.data && (
          <section>
            <div className="eyebrow mb-2">Merge gate</div>
            <GateChecks checks={merge.data.evaluation.checks} />
          </section>
        )}
        {(approval.isLoading || merge.isLoading) && <Loading rows={3} />}
        {(decide.error || doMerge.error) && <ErrorBox error={decide.error ?? doMerge.error} />}
      </div>

      <div className="border-t bg-panel/60 px-6 py-4">
        {item.kind === "approval" ? (
          <div className="space-y-3">
            <Textarea rows={2} placeholder="Comment (optional)" value={comment} onChange={(e) => setComment(e.target.value)} />
            <div className="flex items-center gap-2">
              <Button variant="success" onClick={() => decide.mutate(true)} disabled={!canDecide} data-testid="inbox-approve">
                {decide.isPending ? <Spinner /> : <Check />}Approve<Kbd className="ml-1 border-white/20 bg-white/15 text-white">⇧A</Kbd>
              </Button>
              <Button variant="outline" onClick={() => decide.mutate(false)} disabled={!canDecide}><X />Reject<Kbd className="ml-1">⇧R</Kbd></Button>
              <Link href={item.href} className="ml-auto flex items-center gap-1 text-2xs text-muted-foreground hover:text-foreground">Full review <ArrowUpRight className="size-3" /></Link>
            </div>
          </div>
        ) : item.needs === "merge" ? (
          <div className="flex items-center gap-2">
            <Button onClick={() => doMerge.mutate()} disabled={!canMerge} data-testid="inbox-merge">
              {doMerge.isPending ? <Spinner /> : <GitMerge />}Merge<Kbd className="ml-1 border-black/10 bg-black/10 text-primary-foreground">⇧M</Kbd>
            </Button>
            <span className="text-2xs text-muted-foreground">The gate is re-run before merging.</span>
            <Link href={item.href} className="ml-auto flex items-center gap-1 text-2xs text-muted-foreground hover:text-foreground">Open thread <ArrowUpRight className="size-3" /></Link>
          </div>
        ) : (
          <Button variant="outline" asChild><Link href={item.href}>Open<ArrowUpRight /></Link></Button>
        )}
      </div>
    </div>
  );
}

export default function InboxPage() {
  const router = useRouter();
  const { data, isLoading, error } = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<InboxItem[]>("/inbox") });
  const items = data ?? [];
  const nav = useListNavigation(items, (i) => router.push(i.href));
  const current = nav.current;

  let lastGroup = "";
  return (
    <div className="-mx-4 -my-6 flex h-[calc(100vh-48px)] md:-mx-8">
      <div className="flex w-full flex-col border-r lg:w-[52%] xl:w-[46%]">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
          <InboxIcon className="size-4 text-primary" />
          <h1 className="font-semibold">Inbox</h1>
          <span className="text-muted-foreground">{items.length ? `${items.length} need${items.length === 1 ? "s" : ""} you` : ""}</span>
          <span className="ml-auto hidden items-center gap-1 text-2xs text-muted-foreground sm:flex"><Kbd>J</Kbd><Kbd>K</Kbd> move <Kbd>↵</Kbd> open</span>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto" data-testid="inbox-list">
          {error ? <div className="p-4"><ErrorBox error={error} /></div> : isLoading ? <Loading /> : !items.length ? (
            <div className="flex flex-col items-center gap-2 px-6 py-20 text-center">
              <Sparkles className="size-6 text-success" />
              <div className="font-medium">Inbox zero</div>
              <div className="max-w-xs text-2xs text-muted-foreground">Approvals, conflicts, blocked merges and failed agent runs appear here, ranked by urgency.</div>
            </div>
          ) : items.map((it, i) => {
            const header = it.priority !== lastGroup ? (lastGroup = it.priority) : null;
            return (
              <div key={it.id}>
                {header && <div className="eyebrow sticky top-0 z-10 flex items-center gap-2 border-b bg-panel/95 px-4 py-1.5 backdrop-blur"><PriorityChip p={header} />{GROUP_TITLE[header]}</div>}
                <InboxRow item={it} active={i === nav.index}
                  onClick={() => (window.innerWidth < 1024 ? router.push(it.href) : nav.setIndex(i))} />
              </div>
            );
          })}
        </div>
      </div>
      <div className="hidden flex-1 lg:block">
        {current ? <Preview key={current.id} item={current} /> : (
          <div className="flex h-full items-center justify-center text-muted-foreground">Select an item</div>
        )}
      </div>
    </div>
  );
}
