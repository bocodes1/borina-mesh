export interface ActivityEvent {
  agent_id: string;
  kind: "started" | "streaming" | "completed" | "failed" | "scheduled";
  message: string;
  job_id: number | null;
  timestamp: string;
}

export function subscribeToActivity(onEvent: (event: ActivityEvent) => void): () => void {
  const url = "/api/activity/stream";
  const source = new EventSource(url);

  source.addEventListener("activity", (e) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as ActivityEvent;
      onEvent(data);
    } catch {
      // ignore parse errors
    }
  });

  // Poll recent events every 10s as fallback for SSE proxy issues
  let pollInterval: ReturnType<typeof setInterval> | null = null;
  let lastTimestamp = "";

  const pollEvents = async () => {
    try {
      const res = await fetch("/api/activity/recent");
      if (res.ok) {
        const events: ActivityEvent[] = await res.json();
        for (const event of events) {
          if (event.timestamp > lastTimestamp) {
            lastTimestamp = event.timestamp;
            onEvent(event);
          }
        }
      }
    } catch {
      // ignore poll errors
    }
  };

  pollInterval = setInterval(pollEvents, 10000);

  source.onerror = () => {
    // EventSource auto-reconnects
  };

  return () => {
    source.close();
    if (pollInterval) clearInterval(pollInterval);
  };
}
