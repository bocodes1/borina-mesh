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

  // ── Finance tab ─────────────────────────────────────────────────────────
  getFinanceBrief: () => fetchJSON<FinanceBrief>("/finance/brief"),
  regenerateFinanceBrief: () =>
    fetchJSON<FinanceBrief>("/finance/brief/regenerate", { method: "POST" }),
  getFinanceStatus: () => fetchJSON<FinanceStatus>("/finance/status"),
  getFinanceWatchlist: () =>
    fetchJSON<{ tickers: string[] }>("/finance/watchlist"),
  addFinanceTicker: (ticker: string) =>
    fetchJSON<{ tickers: string[] }>("/finance/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),
  removeFinanceTicker: (ticker: string) =>
    fetchJSON<{ tickers: string[] }>(`/finance/watchlist/${ticker}`, {
      method: "DELETE",
    }),
  getFinanceTicker: (symbol: string) =>
    fetchJSON<FinanceTickerSnapshot>(`/finance/ticker/${symbol}`),
};

export interface FinanceBrief {
  trading_date: string;
  markdown: string | null;
  generated_at: string | null;
  duration_seconds?: number;
  error?: string | null;
  data_source_status?: Record<string, boolean>;
  skipped_sections?: string[];
}

export interface FinanceStatus {
  data_source_status: Record<string, boolean>;
  watchlist_size: number;
  last_brief_generated_at: string | null;
  last_brief_duration_seconds: number | null;
  last_brief_trading_date: string | null;
}

export interface FinanceTickerSnapshot {
  ticker: string;
  name?: string;
  price?: number;
  market_cap?: number;
  forward_pe?: number;
  pe_5y_median?: number;
  pe_10y_median?: number;
  ev_ebitda?: number;
  ev_ebitda_5y_median?: number;
  ps?: number;
  ps_5y_median?: number;
  peers?: string[];
  peer_pe_median?: number;
  peer_ev_ebitda_median?: number;
  peer_ps_median?: number;
  implied_dcf_growth_pct?: number;
  actual_3y_revenue_cagr_pct?: number;
  earnings_in_days?: number | null;
  history_warning?: string | null;
  recent_filings?: Array<{
    form: string;
    filing_date: string;
    primary_doc_url: string;
  }>;
  warning?: string;
}

export function streamJobLog(jobId: number, onLine: (line: string) => void): () => void {
  const es = new EventSource(`${API_BASE}/jobs/${jobId}/log`);
  es.onmessage = (e) => onLine(e.data);
  return () => es.close();
}
