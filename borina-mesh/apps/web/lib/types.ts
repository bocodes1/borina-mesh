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

export interface MorningBrief {
  id: number;
  date: string;
  summary: string;
  cost_summary: string;
  total_runs: number;
  total_cost_usd: number;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  agent_id: string;
  role: "user" | "assistant";
  content: string;
  job_id: number | null;
  created_at: string;
}
