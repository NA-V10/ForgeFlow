"use client";

// Keyboard-first layer: ⌘K command palette, "G then X" navigation, "C" to create, "?" for help.

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight, Bot, FolderGit2, GitMerge, Hammer, Inbox, Layers, LayoutDashboard, Moon, Play, Plus, Search, Settings,
  ShieldCheck, Workflow, GitPullRequestArrow,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type Repository, type Task, type Thread } from "@/lib/api";
import { cn } from "@/lib/utils";
import { AgentAvatar, Kbd } from "./forge";

export const NAV_SHORTCUTS: { key: string; href: string; label: string; icon: typeof Inbox }[] = [
  { key: "h", href: "/", label: "Command center", icon: LayoutDashboard },
  { key: "i", href: "/inbox", label: "Inbox", icon: Inbox },
  { key: "t", href: "/tasks", label: "Tasks", icon: Hammer },
  { key: "w", href: "/workspaces", label: "Threads", icon: Layers },
  { key: "m", href: "/merge-queue", label: "Merge queue", icon: GitMerge },
  { key: "a", href: "/approvals", label: "Approvals", icon: ShieldCheck },
  { key: "c", href: "/changes", label: "Changes", icon: GitPullRequestArrow },
  { key: "e", href: "/executions", label: "Executions", icon: Play },
  { key: "g", href: "/agents", label: "Agents", icon: Bot },
  { key: "r", href: "/repositories", label: "Repositories", icon: FolderGit2 },
  { key: "p", href: "/policies", label: "Policies", icon: Workflow },
  { key: "s", href: "/settings", label: "Settings", icon: Settings },
];

interface Ctx { openPalette: () => void; openHelp: () => void }
const CommandCtx = createContext<Ctx>({ openPalette: () => {}, openHelp: () => {} });
export const useCommand = () => useContext(CommandCtx);

function isTyping(e: KeyboardEvent) {
  const el = e.target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

/**
 * Register a single-key shortcut while the component is mounted. ``key`` is matched against
 * ``KeyboardEvent.key`` exactly, so "A" means Shift+A. Ignored while typing, with Ctrl/⌘/Alt held,
 * or while a dialog is open.
 */
export function useHotkey(key: string, handler: (e: KeyboardEvent) => void, enabled = true) {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector("[role=dialog]")) return;
      if (e.key === key) { e.preventDefault(); ref.current(e); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [key, enabled]);
}

/** j/k (and arrow) navigation over a list; Enter activates. */
export function useListNavigation<T>(items: T[], onOpen: (item: T) => void) {
  const [index, setIndex] = useState(0);
  useEffect(() => { if (index >= items.length) setIndex(Math.max(0, items.length - 1)); }, [items.length, index]);
  useHotkey("j", () => setIndex((i) => Math.min(items.length - 1, i + 1)), items.length > 0);
  useHotkey("ArrowDown", () => setIndex((i) => Math.min(items.length - 1, i + 1)), items.length > 0);
  useHotkey("k", () => setIndex((i) => Math.max(0, i - 1)), items.length > 0);
  useHotkey("ArrowUp", () => setIndex((i) => Math.max(0, i - 1)), items.length > 0);
  useHotkey("Enter", () => items[index] && onOpen(items[index]), items.length > 0);
  return { index, setIndex, current: items[index] as T | undefined };
}

interface Item { id: string; group: string; label: string; hint?: string; icon?: ReactNode; keywords?: string; run: () => void; shortcut?: string[] }

function Palette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const tasks = useQuery({ queryKey: ["tasks", "palette"], queryFn: () => api.get<Task[]>("/tasks", { limit: 200 }), enabled: open });
  const threads = useQuery({ queryKey: ["threads", "palette"], queryFn: () => api.get<Thread[]>("/threads", { limit: 100 }), enabled: open });
  const repos = useQuery({ queryKey: ["repositories"], queryFn: () => api.get<Repository[]>("/repositories"), enabled: open });

  const go = useCallback((href: string) => { onOpenChange(false); router.push(href); }, [onOpenChange, router]);
  const items = useMemo<Item[]>(() => {
    const out: Item[] = [
      { id: "new-task", group: "Actions", label: "Create task", icon: <Plus className="size-4" />, run: () => go("/tasks?new=1"), shortcut: ["C"] },
      {
        id: "theme", group: "Actions", label: "Toggle light / dark theme", icon: <Moon className="size-4" />,
        run: () => { const d = !document.documentElement.classList.contains("dark"); document.documentElement.classList.toggle("dark", d); try { localStorage.setItem("ff-theme", d ? "dark" : "light"); } catch { /* ignore */ } onOpenChange(false); },
      },
      ...NAV_SHORTCUTS.map((n) => ({ id: `nav-${n.href}`, group: "Navigate", label: `Go to ${n.label}`, icon: <n.icon className="size-4" />, run: () => go(n.href), shortcut: ["G", n.key.toUpperCase()] })),
    ];
    for (const t of threads.data ?? []) {
      out.push({ id: `ws-${t.workspace_id}`, group: "Agent threads", label: t.task.title, hint: `${t.agent?.name ?? "—"} · ${t.status.toLowerCase()}`, keywords: `${t.branch} ${t.agent?.name}`,
        icon: t.agent ? <AgentAvatar name={t.agent.name} size={16} /> : <Layers className="size-4" />, run: () => go(`/workspaces/${t.workspace_id}`) });
    }
    for (const t of tasks.data ?? []) {
      out.push({ id: `task-${t.id}`, group: "Tasks", label: t.title, hint: t.status.toLowerCase(), keywords: t.id, icon: <Hammer className="size-4" />, run: () => go(`/tasks/${t.id}`) });
    }
    for (const r of repos.data ?? []) {
      out.push({ id: `repo-${r.id}`, group: "Repositories", label: r.name, hint: r.default_branch, icon: <FolderGit2 className="size-4" />, run: () => go(`/repositories/${r.id}`) });
    }
    return out;
  }, [threads.data, tasks.data, repos.data, go, onOpenChange]);

  const filtered = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const list = terms.length ? items.filter((i) => terms.every((t) => `${i.label} ${i.hint ?? ""} ${i.keywords ?? ""} ${i.group}`.toLowerCase().includes(t))) : items.filter((i) => i.group !== "Tasks");
    return list.slice(0, 60);
  }, [items, q]);

  // Enter reads the latest results through refs so a re-render racing the keypress can't drop it.
  const filteredRef = useRef(filtered);
  const selRef = useRef(sel);
  filteredRef.current = filtered;
  selRef.current = sel;
  useEffect(() => { setSel(0); }, [q]);
  useEffect(() => { if (!open) setQ(""); }, [open]);
  useEffect(() => { listRef.current?.querySelector(`[data-index="${sel}"]`)?.scrollIntoView({ block: "nearest" }); }, [sel]);

  let lastGroup = "";
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 backdrop-blur-[1px]" />
        <DialogPrimitive.Content aria-describedby={undefined} className="panel-shadow fixed left-1/2 top-[14vh] z-50 w-[calc(100%-2rem)] max-w-[620px] -translate-x-1/2 overflow-hidden rounded-xl border bg-elevated" data-testid="command-palette">
          <DialogPrimitive.Title className="sr-only">Command menu</DialogPrimitive.Title>
          <div className="flex items-center gap-2.5 border-b px-4">
            <Search className="size-4 text-muted-foreground" />
            <input
              autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a command or search threads, tasks, repositories…"
              className="h-12 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground"
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(filtered.length - 1, s + 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(0, s - 1)); }
                if (e.key === "Enter") { e.preventDefault(); filteredRef.current[Math.min(selRef.current, filteredRef.current.length - 1)]?.run(); }
              }}
            />
            <Kbd>esc</Kbd>
          </div>
          <div ref={listRef} className="scrollbar-thin max-h-[420px] overflow-y-auto p-1.5">
            {filtered.length === 0 && <div className="px-3 py-8 text-center text-muted-foreground">No results for “{q}”</div>}
            {filtered.map((it, i) => {
              const header = it.group !== lastGroup ? (lastGroup = it.group) : null;
              return (
                <div key={it.id}>
                  {header && <div className="eyebrow px-2.5 pb-1 pt-2.5">{header}</div>}
                  <button data-index={i} data-selected={i === sel} onMouseMove={() => setSel(i)} onClick={it.run}
                    className={cn("flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-left", i === sel ? "bg-accent text-foreground" : "text-foreground/85")}>
                    <span className="text-muted-foreground">{it.icon}</span>
                    <span className="flex-1 truncate">{it.label}</span>
                    {it.hint && <span className="truncate text-2xs text-muted-foreground">{it.hint}</span>}
                    {it.shortcut && <span className="flex gap-1">{it.shortcut.map((k) => <Kbd key={k}>{k}</Kbd>)}</span>}
                    {i === sel && !it.shortcut && <ArrowRight className="size-3.5 text-muted-foreground" />}
                  </button>
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-4 border-t px-4 py-2 text-2xs text-muted-foreground">
            <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd> navigate</span>
            <span className="flex items-center gap-1"><Kbd>↵</Kbd> open</span>
            <span className="ml-auto flex items-center gap-1"><Kbd>?</Kbd> all shortcuts</span>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

const HELP: { title: string; keys: [string[], string][] }[] = [
  { title: "General", keys: [[["⌘", "K"], "Command menu"], [["/"], "Command menu"], [["C"], "Create task"], [["?"], "This help"], [["Esc"], "Close / back"]] },
  { title: "Navigation", keys: NAV_SHORTCUTS.map((n) => [["G", n.key.toUpperCase()], n.label] as [string[], string]) },
  { title: "Lists", keys: [[["J"], "Next item"], [["K"], "Previous item"], [["↵"], "Open"]] },
  { title: "Inbox & approvals", keys: [[["⇧", "A"], "Approve selected request"], [["⇧", "R"], "Reject selected request"], [["⇧", "M"], "Merge selected ready item"]] },
];

function Help({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <DialogPrimitive.Content aria-describedby={undefined} className="panel-shadow fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-[640px] -translate-x-1/2 -translate-y-1/2 rounded-xl border bg-elevated p-5" data-testid="shortcuts-help">
          <DialogPrimitive.Title className="text-[15px] font-semibold">Keyboard shortcuts</DialogPrimitive.Title>
          <div className="mt-4 grid gap-6 sm:grid-cols-2">
            {HELP.map((g) => (
              <div key={g.title}>
                <div className="eyebrow mb-2">{g.title}</div>
                <ul className="space-y-1.5">
                  {g.keys.map(([keys, label]) => (
                    <li key={label} className="flex items-center justify-between gap-3">
                      <span className="text-foreground/85">{label}</span>
                      <span className="flex gap-1">{keys.map((k, i) => <Kbd key={i}>{k}</Kbd>)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

export function CommandProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);
  const pendingG = useRef<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); return; }
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || palette || help) return;
      if (pendingG.current !== null) {
        window.clearTimeout(pendingG.current);
        pendingG.current = null;
        const target = NAV_SHORTCUTS.find((n) => n.key === e.key.toLowerCase());
        if (target) { e.preventDefault(); router.push(target.href); }
        return;
      }
      if (e.key === "g") { pendingG.current = window.setTimeout(() => { pendingG.current = null; }, 1200); return; }
      if (e.key === "/") { e.preventDefault(); setPalette(true); return; }
      if (e.key === "?") { e.preventDefault(); setHelp(true); return; }
      if (e.key === "c") { e.preventDefault(); router.push("/tasks?new=1"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, palette, help]);

  return (
    <CommandCtx.Provider value={{ openPalette: () => setPalette(true), openHelp: () => setHelp(true) }}>
      {children}
      <Palette open={palette} onOpenChange={setPalette} />
      <Help open={help} onOpenChange={setHelp} />
    </CommandCtx.Provider>
  );
}
