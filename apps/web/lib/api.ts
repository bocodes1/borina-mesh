import type { Agent, Job, Artifact, AgentRun } from "./types";

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
  listArtifacts: () => fetchJSON<Artifact[]>("/artifacts"),
  getJobRuns: (jobId: number) => fetchJSON<AgentRun[]>(`/jobs/${jobId}/runs`),
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
