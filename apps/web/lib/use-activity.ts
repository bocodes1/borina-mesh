"use client";

import { useEffect, useRef, useState } from "react";
import { subscribeToActivity, type ActivityEvent } from "./activity";

const MAX_EVENTS = 60;
const BUCKETS = 16;
const TICK_MS = 3000;

/**
 * Single shared subscription to the live activity SSE stream. Provides the
 * recent event list AND a per-agent rolling activity histogram (real
 * events-per-tick) that drives the fleet sparklines — no placeholder data.
 */
export function useActivityStream() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [byAgent, setByAgent] = useState<Record<string, number[]>>({});
  const pending = useRef<Record<string, number>>({});

  useEffect(() => {
    const unsub = subscribeToActivity((e) => {
      setEvents((prev) => {
        // de-dupe identical consecutive events (SSE + poll fallback overlap)
        if (prev[0] && prev[0].timestamp === e.timestamp && prev[0].message === e.message) return prev;
        return [e, ...prev].slice(0, MAX_EVENTS);
      });
      pending.current[e.agent_id] = (pending.current[e.agent_id] ?? 0) + 1;
    });

    const interval = setInterval(() => {
      setByAgent((prev) => {
        const next: Record<string, number[]> = {};
        const ids = new Set([...Object.keys(prev), ...Object.keys(pending.current)]);
        for (const id of ids) {
          const base = prev[id] ?? new Array(BUCKETS).fill(0);
          const arr = base.slice(-(BUCKETS - 1));
          arr.push(pending.current[id] ?? 0);
          next[id] = arr;
        }
        pending.current = {};
        return next;
      });
    }, TICK_MS);

    return () => {
      unsub();
      clearInterval(interval);
    };
  }, []);

  return { events, byAgent };
}

export type { ActivityEvent };
