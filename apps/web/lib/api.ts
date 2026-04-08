import type { Agent, Job, Artifact } from "./types";

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
};
