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

export interface AgentTask {
  id: number;
  title: string;
  description: string;
  assigned_agent: string | null;
  status: "backlog" | "assigned" | "in_progress" | "review" | "done";
  priority: "low" | "medium" | "high" | "critical";
  input_data: string | null;
  output_data: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface WorkspaceEntry {
  id: number;
  workspace_id: string;
  agent_id: string;
  key: string;
  value: string;
  created_at: string;
}
