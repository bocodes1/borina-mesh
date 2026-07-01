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
  current_task?: string | null;
  state?: "active" | "parked" | "retired";  // lean-fleet lifecycle (L0)
}

export interface Job {
  id: number;
  agent_id: string;
  prompt: string;
  status: "pending" | "queued" | "running" | "completed" | "failed" | "cancelled";
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
  source?: string | null;
  agent?: string | null;
  prompt?: string | null;
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

// ── Orchestration runs (DAG) ────────────────────────────────────────────────
export interface Run {
  id: number;
  mode: string;            // mission | goal
  status: string;          // planning|running|checkin|paused|done|aborted|failed
  text?: string;
  node_counts?: Record<string, number>;
  created_at?: string;
  updated_at?: string;
}

export interface RunNode {
  key: string;
  agent: string;
  kind: string;            // read | write | verify | synthesize
  status: string;          // pending|ready|active|done|skipped|blocked|awaiting_approval|failed
  result?: string | null;
}

export interface RunEdge {
  src: string;
  dst: string;
}

export interface RunDetail {
  run: Run;
  nodes: RunNode[];
  edges: RunEdge[];
}
