import type { Agent, Job, MorningBrief, ChatMessage, AgentTask, Artifact, AgentRun } from "./types";

const API_BASE = "/api"; // proxied to backend via next.config.js

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  listAgents: () => fetchJSON<Agent[]>("/agents"),
  getAgent: (id: string) => fetchJSON<Agent>(`/agents/${id}`),
  listJobs: (agentId?: string) =>
    fetchJSON<Job[]>(`/jobs${agentId ? `?agent_id=${agentId}` : ""}`),
  createJob: (agentId: string, prompt: string) =>
    fetchJSON<Job>("/jobs", {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, prompt }),
    }),
  // Phase 5: Morning briefs
  getLatestBrief: () => fetchJSON<MorningBrief>("/briefs/latest"),
  listBriefs: (limit = 14) => fetchJSON<MorningBrief[]>(`/briefs?limit=${limit}`),
  generateBrief: () =>
    fetchJSON<MorningBrief>("/briefs/generate", { method: "POST" }),
  // Phase 5: Chat threads
  getThread: (agentId: string, limit = 100) =>
    fetchJSON<ChatMessage[]>(`/threads/${agentId}?limit=${limit}`),
  clearThread: (agentId: string) =>
    fetchJSON<{ agent_id: string; deleted: number }>(`/threads/${agentId}`, {
      method: "DELETE",
    }),
  // Phase 5: Task management
  listTasks: (status?: string, agentId?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (agentId) params.set("agent_id", agentId);
    const qs = params.toString();
    return fetchJSON<AgentTask[]>(`/tasks${qs ? `?${qs}` : ""}`);
  },
  createTask: (title: string, assignedAgent?: string, priority = "medium") =>
    fetchJSON<AgentTask>("/tasks", {
      method: "POST",
      body: JSON.stringify({ title, assigned_agent: assignedAgent ?? null, priority }),
    }),
  updateTask: (taskId: number, updates: Record<string, unknown>) =>
    fetchJSON<AgentTask>(`/tasks/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    }),
  deleteTask: (taskId: number) =>
    fetchJSON<{ id: number; deleted: boolean }>(`/tasks/${taskId}`, {
      method: "DELETE",
    }),
  // Phase 4: Schedules
  listSchedules: () => fetchJSON<Record<string, string>>("/schedules"),
  setSchedule: (agentId: string, cron: string) =>
    fetchJSON<{ agent_id: string; cron: string }>(`/schedules/${agentId}`, {
      method: "PUT",
      body: JSON.stringify({ cron }),
    }),
  removeSchedule: (agentId: string) =>
    fetchJSON<{ agent_id: string; removed: boolean }>(`/schedules/${agentId}`, {
      method: "DELETE",
    }),
  // Phase 4: Artifacts & runs
  listArtifacts: () => fetchJSON<Artifact[]>("/artifacts"),
  getJobRuns: (jobId: number) => fetchJSON<AgentRun[]>(`/jobs/${jobId}/runs`),
  // Phase 4: Handoff & job management
  createHandoff: (body: { repo_path: string; base_branch: string; prompt: string }) =>
    fetchJSON<{ job_id: number; dashboard_url: string; worktree_path: string }>("/jobs/handoff", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  cancelJob: (jobId: number) =>
    fetchJSON<{ ok: boolean }>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  cleanupJob: (jobId: number) =>
    fetchJSON<{ ok: boolean }>(`/jobs/${jobId}/cleanup`, { method: "POST" }),
  getAgentModels: () => fetchJSON<Record<string, string>>("/agents/models"),
};

export function streamJobLog(jobId: number, onLine: (line: string) => void): () => void {
  const es = new EventSource(`${API_BASE}/jobs/${jobId}/log`);
  es.onmessage = (e) => onLine(e.data);
  return () => es.close();
}
