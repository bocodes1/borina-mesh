export interface Agent {
  id: string;
  name: string;
  emoji: string;
  tagline: string;
  tools: string[];
  model: string;
}

export interface Job {
  id: number;
  agent_id: string;
  prompt: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
}

export interface StreamChunk {
  type: "text" | "tool_use" | "done" | "error";
  content: string;
}

export interface Schedule {
  agent_id: string;
  cron: string;
}

export interface Artifact {
  date: string;
  name: string;
  size_bytes: number;
  modified: string;
  path: string;
}
