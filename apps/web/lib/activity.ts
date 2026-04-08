export interface ActivityEvent {
  agent_id: string;
  kind: "started" | "streaming" | "completed" | "failed" | "scheduled";
  message: string;
  job_id: number | null;
  timestamp: string;
}

export function subscribeToActivity(onEvent: (event: ActivityEvent) => void): () => void {
  const source = new EventSource("/api/activity/stream");

  source.addEventListener("activity", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as ActivityEvent;
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  });

  source.onerror = () => {
    // EventSource auto-reconnects; no action needed
  };

  return () => source.close();
}
