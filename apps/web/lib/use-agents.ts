"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Agent } from "./types";

/**
 * Single shared `/agents` poll for the dashboard. Both the status bar and the
 * agent fleet read the same source instead of each opening their own interval
 * (which doubled the request rate against the same endpoint).
 */
export function useAgentsPoll(intervalMs = 8000) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(
    () =>
      api
        .listAgents()
        .then((a) => {
          setAgents(a);
          setError(null);
        })
        .catch((e) => setError((e as Error).message))
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    reload();
    const id = setInterval(reload, intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs]);

  return { agents, loading, error, reload };
}
