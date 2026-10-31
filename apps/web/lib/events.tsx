"use client";

// Live event stream: one WebSocket per tab, fanned out to subscribers and used to
// invalidate React Query caches so every page updates in real time.

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { wsUrl, type ForgeEvent } from "./api";

type Status = "connecting" | "live" | "offline";
interface EventsCtx { events: ForgeEvent[]; status: Status }

const Ctx = createContext<EventsCtx>({ events: [], status: "connecting" });
const MAX_EVENTS = 300;

// Which cached queries an event type makes stale.
const INVALIDATES: Record<string, string[]> = {
  repository: ["repositories", "dashboard", "graph"],
  agent: ["agents", "dashboard", "executions", "tasks"],
  task: ["tasks", "dashboard", "graph"],
  workspace: ["workspaces", "tasks", "dashboard", "graph"],
  execution: ["executions", "dashboard"],
  file: ["workspaces", "diff"],
  tool: ["executions"],
  test: ["executions", "dashboard"],
  checkpoint: ["workspaces", "checkpoints", "changes", "dashboard", "graph", "diff", "tasks"],
  review: ["workspaces", "tasks", "approvals", "risk", "dashboard"],
  risk: ["risk", "dashboard", "tasks"],
  approval: ["approvals", "dashboard", "tasks", "merges"],
  merge: ["merges", "dashboard", "workspaces", "tasks", "graph", "repositories"],
  conflict: ["merges", "dashboard"],
  policy: ["policies"],
  reproduce: ["executions"],
};

export function EventsProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<ForgeEvent[]>([]);
  const [status, setStatus] = useState<Status>("connecting");
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ping: ReturnType<typeof setInterval> | undefined;
    let closed = false;
    let pending = new Set<string>();
    let flush: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus("connecting");
      ws = new WebSocket(`${wsUrl()}?backfill=60`);
      ws.onopen = () => {
        retry.current = 0;
        setStatus("live");
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25_000);
      };
      ws.onmessage = (msg) => {
        const e: ForgeEvent = JSON.parse(msg.data);
        setEvents((prev) => (prev.some((p) => p.seq === e.seq) ? prev : [e, ...prev].slice(0, MAX_EVENTS)));
        for (const key of INVALIDATES[e.type.split(".")[0]] ?? []) pending.add(key);
        // every state change can alter what needs a human and each agent thread's summary
        pending.add("inbox");
        pending.add("threads");
        // batch invalidations so a burst of tool calls causes one refetch
        flush ??= setTimeout(() => {
          pending.forEach((key) => qc.invalidateQueries({ queryKey: [key] }));
          pending = new Set();
          flush = undefined;
        }, 400);
      };
      ws.onclose = () => {
        clearInterval(ping);
        setStatus("offline");
        if (!closed) timer = setTimeout(connect, Math.min(10_000, 1000 * 2 ** retry.current++));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearTimeout(flush);
      clearInterval(ping);
      ws?.close();
    };
  }, [qc]);

  return <Ctx.Provider value={{ events, status }}>{children}</Ctx.Provider>;
}

export function useEvents(filter?: (e: ForgeEvent) => boolean) {
  const { events, status } = useContext(Ctx);
  return { events: filter ? events.filter(filter) : events, status };
}
