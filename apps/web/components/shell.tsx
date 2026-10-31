"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Bot, ChevronRight, FolderGit2, GitMerge, GitPullRequestArrow, Hammer, HelpCircle, Inbox, Layers, LayoutDashboard,
  Moon, Play, Plus, Search, Settings, ShieldCheck, Sun, Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Dashboard, type InboxItem, type Repository } from "@/lib/api";
import { useEvents } from "@/lib/events";
import { cn } from "@/lib/utils";
import { CommandProvider, useCommand } from "./command";
import { Kbd } from "./forge";

type NavItem = { href: string; label: string; icon: typeof Inbox; count?: "inbox" | "merge" | "approvals"; shortcut: string };

const SECTIONS: { title?: string; items: NavItem[] }[] = [
  { items: [
    { href: "/inbox", label: "Inbox", icon: Inbox, count: "inbox", shortcut: "I" },
    { href: "/", label: "Command center", icon: LayoutDashboard, shortcut: "H" },
  ] },
  { title: "Agent work", items: [
    { href: "/workspaces", label: "Threads", icon: Layers, shortcut: "W" },
    { href: "/tasks", label: "Tasks", icon: Hammer, shortcut: "T" },
    { href: "/executions", label: "Executions", icon: Play, shortcut: "E" },
    { href: "/agents", label: "Agents", icon: Bot, shortcut: "G" },
  ] },
  { title: "Delivery", items: [
    { href: "/merge-queue", label: "Merge queue", icon: GitMerge, count: "merge", shortcut: "M" },
    { href: "/approvals", label: "Approvals", icon: ShieldCheck, count: "approvals", shortcut: "A" },
    { href: "/changes", label: "Changes", icon: GitPullRequestArrow, shortcut: "C" },
  ] },
  { title: "Governance", items: [
    { href: "/policies", label: "Policies", icon: Workflow, shortcut: "P" },
    { href: "/settings", label: "Settings", icon: Settings, shortcut: "S" },
  ] },
];

const ALL_ITEMS = SECTIONS.flatMap((s) => s.items);

function isActive(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
}

function useTheme() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    let stored: string | null = null;
    try { stored = localStorage.getItem("ff-theme"); } catch { /* storage unavailable */ }
    const d = stored ? stored === "dark" : true;
    setDark(d);
    document.documentElement.classList.toggle("dark", d);
    const obs = new MutationObserver(() => setDark(document.documentElement.classList.contains("dark")));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => obs.disconnect();
  }, []);
  const toggle = () => {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try { localStorage.setItem("ff-theme", next ? "dark" : "light"); } catch { /* ignore */ }
  };
  return { dark, toggle };
}

function LiveIndicator({ compact }: { compact?: boolean }) {
  const { status } = useEvents();
  const color = status === "live" ? "bg-success" : status === "connecting" ? "bg-warning" : "bg-destructive";
  return (
    <span className="flex items-center gap-1.5 text-2xs text-muted-foreground" data-testid="live-status" data-status={status}
      title={status === "live" ? "Receiving real-time events" : status === "connecting" ? "Connecting to event stream" : "Event stream offline"}>
      <span className={cn("size-1.5 rounded-full", color, status === "live" && "live-dot !bg-success")} />
      {!compact && (status === "live" ? "Live" : status === "connecting" ? "Connecting" : "Offline")}
    </span>
  );
}

function Sidebar() {
  const path = usePathname();
  const { openPalette, openHelp } = useCommand();
  const { dark, toggle } = useTheme();
  const dash = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dashboard>("/dashboard") });
  const inbox = useQuery({ queryKey: ["inbox"], queryFn: () => api.get<InboxItem[]>("/inbox") });
  const repos = useQuery({ queryKey: ["repositories"], queryFn: () => api.get<Repository[]>("/repositories") });
  const counts = {
    inbox: inbox.data?.length ?? 0,
    merge: dash.data?.merge_queue.length ?? 0,
    approvals: dash.data?.pending_approvals.length ?? 0,
  };
  const urgent = inbox.data?.some((i) => i.priority === "P0");

  return (
    <aside className="sticky top-0 hidden h-screen w-[232px] shrink-0 flex-col border-r bg-panel md:flex">
      <div className="flex h-12 items-center gap-2 px-3">
        <div className="flex size-6 items-center justify-center rounded-md bg-gradient-to-br from-primary to-[hsl(8_90%_48%)] shadow-sm">
          <svg viewBox="0 0 16 16" className="size-3.5 text-primary-foreground" fill="currentColor" aria-hidden><path d="M3 2h8l-2 4h4L6 14l1.5-5H4z" /></svg>
        </div>
        <span className="text-[13.5px] font-semibold tracking-tight">ForgeFlow</span>
        <span className="ml-auto"><LiveIndicator compact /></span>
      </div>
      <div className="px-2 pb-2">
        <button onClick={openPalette} data-testid="open-palette"
          className="flex h-8 w-full items-center gap-2 rounded-md border bg-background/60 px-2.5 text-muted-foreground transition-colors hover:border-input hover:text-foreground">
          <Search className="size-3.5" />
          <span className="flex-1 text-left">Search or jump to…</span>
          <Kbd>⌘K</Kbd>
        </button>
      </div>
      <nav className="scrollbar-thin flex-1 overflow-y-auto px-2 pb-3">
        {SECTIONS.map((section, si) => (
          <div key={si} className={cn(section.title && "mt-4")}>
            {section.title && <div className="eyebrow mb-1 px-2">{section.title}</div>}
            {section.items.map((item) => {
              const n = item.count ? counts[item.count] : 0;
              const active = isActive(path, item.href);
              return (
                <Link key={item.href} href={item.href} title={`G then ${item.shortcut}`} className={cn(
                  "group flex h-[30px] items-center gap-2.5 rounded-md px-2 transition-colors",
                  active ? "bg-accent text-foreground" : "text-foreground/70 hover:bg-accent/60 hover:text-foreground",
                )}>
                  <item.icon className={cn("size-[15px]", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                  <span className="flex-1">{item.label}</span>
                  {n > 0 && (
                    <span data-testid={`nav-count-${item.count}`} className={cn("min-w-[18px] rounded px-1 text-center font-mono text-[10px] font-semibold tabular-nums",
                      item.count === "inbox" ? (urgent ? "bg-destructive/15 text-destructive" : "bg-primary/15 text-primary")
                        : item.count === "approvals" ? "bg-warning/15 text-warning" : "bg-muted text-muted-foreground")}>{n}</span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}
        <div className="mt-4">
          <Link href="/repositories" className="eyebrow mb-1 flex items-center justify-between px-2 hover:text-foreground">Repositories<ChevronRight className="size-3" /></Link>
          {repos.data?.slice(0, 8).map((r) => {
            const href = `/repositories/${r.id}`;
            return (
              <Link key={r.id} href={href} className={cn("flex h-[30px] items-center gap-2.5 rounded-md px-2",
                isActive(path, href) ? "bg-accent text-foreground" : "text-foreground/70 hover:bg-accent/60 hover:text-foreground")}>
                <FolderGit2 className="size-[15px] text-muted-foreground" />
                <span className="truncate">{r.name}</span>
              </Link>
            );
          })}
          {repos.data && repos.data.length === 0 && <div className="px-2 py-1 text-2xs text-muted-foreground">No repositories yet</div>}
        </div>
      </nav>
      <div className="flex items-center gap-1 border-t px-2 py-2">
        <Link href="/tasks?new=1" className="flex h-7 flex-1 items-center gap-2 rounded-md px-2 text-foreground/80 hover:bg-accent hover:text-foreground">
          <Plus className="size-3.5" />New task<Kbd className="ml-auto">C</Kbd>
        </Link>
        <button onClick={openHelp} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Keyboard shortcuts"><HelpCircle className="size-4" /></button>
        <button onClick={toggle} className="rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground" aria-label="Toggle theme">
          {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
      </div>
    </aside>
  );
}

function TopBar() {
  const path = usePathname();
  const { openPalette } = useCommand();
  const section = [...ALL_ITEMS, { href: "/repositories", label: "Repositories", icon: FolderGit2, shortcut: "R" }]
    .filter((i) => isActive(path, i.href)).sort((a, b) => b.href.length - a.href.length)[0];
  const detail = section && path !== section.href && section.href !== "/";
  return (
    <header className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur md:px-6">
      <nav className="flex min-w-0 items-center gap-1.5 text-[13px]" aria-label="Breadcrumb">
        {section ? (
          <>
            <Link href={section.href} className={cn("flex items-center gap-2", detail ? "text-muted-foreground hover:text-foreground" : "font-medium")}>
              <section.icon className="size-3.5" />{section.label}
            </Link>
            {detail && <><ChevronRight className="size-3.5 text-muted-foreground/60" /><span className="truncate font-mono text-[12px] text-muted-foreground">{path.split("/").pop()?.slice(0, 8)}</span></>}
          </>
        ) : <span className="font-medium">ForgeFlow</span>}
      </nav>
      <div className="ml-auto flex items-center gap-3">
        <button onClick={openPalette} className="flex items-center gap-1.5 rounded-md px-2 py-1 text-muted-foreground hover:bg-accent hover:text-foreground md:hidden" aria-label="Search">
          <Search className="size-4" />
        </button>
        <LiveIndicator />
      </div>
    </header>
  );
}

function MobileNav() {
  const path = usePathname();
  return (
    <nav className="flex gap-1 overflow-x-auto border-b px-2 py-1.5 md:hidden">
      {ALL_ITEMS.map(({ href, label }) => (
        <Link key={href} href={href} className={cn("whitespace-nowrap rounded px-2 py-1 text-2xs", isActive(path, href) ? "bg-accent" : "text-muted-foreground")}>{label}</Link>
      ))}
    </nav>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <CommandProvider>
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <MobileNav />
          <main className="mx-auto w-full max-w-[1480px] flex-1 px-4 py-6 md:px-8">{children}</main>
        </div>
      </div>
    </CommandProvider>
  );
}
