export interface Agent {
  id: string;
  name: string;
  emoji: string;  // keep for backward compat with API response
  tagline: string;
  tools: string[];
  model: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  qa_verdict?: string | null;
  status?: "idle" | "running" | "qa_flagged" | "error";
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
  kind?: string;
  repo_path?: string | null;
  base_branch?: string | null;
  worker_branch?: string | null;
  log_path?: string | null;
  qa_verdict?: string | null;
  qa_notes?: string | null;
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

export interface AgentRun {
  id: number;
  job_id: number;
  agent_id: string;
  output: string;
  tokens_used: number;
  cost_usd: number;
  created_at: string;
}
