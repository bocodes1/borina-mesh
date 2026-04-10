import type { Agent, Job, MorningBrief, ChatMessage, AgentTask } from "./types";

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
  getLatestBrief: () => fetchJSON<MorningBrief>("/briefs/latest"),
  listBriefs: (limit = 14) => fetchJSON<MorningBrief[]>(`/briefs?limit=${limit}`),
  generateBrief: () =>
    fetchJSON<MorningBrief>("/briefs/generate", { method: "POST" }),
  getThread: (agentId: string, limit = 100) =>
    fetchJSON<ChatMessage[]>(`/threads/${agentId}?limit=${limit}`),
  clearThread: (agentId: string) =>
    fetchJSON<{ agent_id: string; deleted: number }>(`/threads/${agentId}`, {
      method: "DELETE",
    }),
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
};
