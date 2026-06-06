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

  // ── Deep-dive ──────────────────────────────────────────────────────────
  getDeepdive: (ticker: string) =>
    fetchJSON<DeepDive>(`/finance/deepdive/${ticker}`),
  getDeepdiveStatus: (ticker: string) =>
    fetchJSON<DeepDiveStatus>(`/finance/deepdive/${ticker}/status`),
  generateDeepdive: (ticker: string, force = false) =>
    fetchJSON<{ ticker: string; status: string; stream_url: string | null; message: string }>(
      `/finance/deepdive/${ticker}/generate`,
      { method: "POST", body: JSON.stringify({ force }) },
    ),
  invalidateDeepdive: (ticker: string) =>
    fetchJSON<{ ticker: string; removed: boolean }>(
      `/finance/deepdive/${ticker}/cache`,
      { method: "DELETE" },
    ),

  // ── Finance Life-OS (portfolio / quotes) ────────────────────────────────
  getPortfolio: () => fetchJSON<PortfolioResponse>("/finance/portfolio"),
  getQuote: (symbol: string) =>
    fetchJSON<IntegrationEnvelope<QuoteData>>(`/finance/quote/${symbol}`),
  getQuoteHistory: (symbol: string, range = "1M") =>
    fetchJSON<IntegrationEnvelope<{ symbol: string; range: string; points: Array<{ t: number; close: number }> }>>(
      `/finance/history/${symbol}?range=${range}`,
    ),
  getSymbolNews: (symbol: string) =>
    fetchJSON<IntegrationEnvelope<Array<{ title: string; url: string; source: string }>>>(
      `/finance/news/${symbol}`,
    ),

  // ── Daily tab ───────────────────────────────────────────────────────────
  getDailySummary: () => fetchJSON<DailySummary>("/daily/summary"),
  getDailyBrief: () => fetchJSON<DailyBriefResponse>("/daily/brief"),
  generateDailyBrief: (useAgent = false) =>
    fetchJSON<{ written: string; date: string; sections_found: string[] }>(
      `/daily/generate?use_agent=${useAgent}`,
      { method: "POST" },
    ),

  // ── Planner ───────────────────────────────────────────────────────────────
  getDailyPlan: () => fetchJSON<DailyPlan>("/daily/plan"),
  generateDailyPlan: () =>
    fetchJSON<{ day: string; task_count: number; calendar_count: number }>("/daily/plan/generate", { method: "POST" }),
  approvePlanItem: (id: number) =>
    fetchJSON<{ status: string; kind?: string; committed?: boolean; note?: string | null }>(`/daily/plan/${id}/approve`, { method: "POST" }),
  rejectPlanItem: (id: number) =>
    fetchJSON<{ status: string }>(`/daily/plan/${id}/reject`, { method: "POST" }),

  // ── Tasks ───────────────────────────────────────────────────────────────
  listTasks: () => fetchJSON<TaskItem[]>("/tasks"),
  createTask: (body: { title: string; due?: string | null; priority?: string; tag?: string }) =>
    fetchJSON<TaskItem>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  updateTask: (id: number, body: Partial<TaskItem>) =>
    fetchJSON<TaskItem>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteTask: (id: number) =>
    fetch(`${API_BASE}/tasks/${id}`, { method: "DELETE" }).then((r) => r.ok),

  // ── Calendar ────────────────────────────────────────────────────────────
  getCalendarEvents: (from: string, to: string) =>
    fetchJSON<CalendarResponse>(`/calendar/events?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  createCalendarEvent: (body: { summary: string; start: string; end: string; location?: string }) =>
    fetchJSON<IntegrationEnvelope<{ id: string; htmlLink: string }>>("/calendar/events", {
      method: "POST",
      body: JSON.stringify({ ...body, user_initiated: true }),
    }),

  // ── Files tab ───────────────────────────────────────────────────────────
  listFiles: (params?: { source?: string; type?: string; q?: string }) => {
    const qs = new URLSearchParams();
    if (params?.source && params.source !== "all") qs.set("source", params.source);
    if (params?.type && params.type !== "all") qs.set("type", params.type);
    if (params?.q) qs.set("q", params.q);
    const s = qs.toString();
    return fetchJSON<FilesResponse>(`/files${s ? `?${s}` : ""}`);
  },
};

export interface FileItem {
  name: string;
  path: string;
  date: string;
  modified: string;
  size_bytes: number;
  type: string;
  source: string;
  agent: string | null;
  prompt: string | null;
  job_id: number | null;
}
export interface FilesResponse {
  files: FileItem[];
  sources: string[];
  types: string[];
  count: number;
}

// ── Life-OS response types ──────────────────────────────────────────────────
export interface IntegrationEnvelope<T = unknown> {
  source: string;
  connected: boolean;
  data: T | null;
  error: string | null;
}

export interface QuoteData {
  symbol: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  high?: number | null;
  low?: number | null;
  prev_close?: number | null;
}

export interface PortfolioResponse {
  net_worth: number | null;
  brokerage: IntegrationEnvelope<{
    total_value: number | null;
    day_change: number | null;
    day_change_pct: number | null;
    positions: Array<{ symbol: string; qty: number; value: number; day_change_pct: number | null }>;
    allocation: Array<{ label: string; value: number }>;
  }>;
  wallet: IntegrationEnvelope<{
    assets: Array<{ symbol: string; balance: number; value_usd: number; change_24h: number | null }>;
    total_usd: number;
  }>;
}

export interface TaskItem {
  id: number;
  title: string;
  due: string | null;
  priority: string;
  tag: string;
  done: boolean;
  sort_order: number;
  created_at: string;
}

export interface DailySummary {
  date: string;
  has_brief: boolean;
  brief: Record<string, string | null>;
  weather: IntegrationEnvelope<{ temp: number; conditions: string; description: string; location?: string }>;
  open_tasks: TaskItem[];
}

export interface DailyBriefResponse {
  date: string;
  exists: boolean;
  raw: string | null;
  sections: Record<string, string>;
}

export interface PlanItem {
  id: number;
  kind: "task" | "calendar";
  status: "proposed" | "approved" | "rejected";
  title: string;
  rationale: string | null;
  payload: Record<string, unknown>;
  committed_ref: string | null;
}
export interface DailyPlan {
  day: string;
  has_plan: boolean;
  raw: string | null;
  items: PlanItem[];
  tasks: PlanItem[];
  calendar: PlanItem[];
}

export interface CalendarEvent {
  id: string;
  title: string;
  start: string | null;
  end: string | null;
  location?: string | null;
  join_link?: string | null;
  all_day?: boolean;
  kind?: string;
  tag?: string;
}

export interface CalendarResponse {
  calendar: IntegrationEnvelope<unknown>;
  events: CalendarEvent[];
  task_chips: CalendarEvent[];
}

export interface DeepDiveSection {
  anchor: string;
  title: string;
  body: string;
}

export interface DeepDive {
  ticker: string;
  is_crypto: boolean;
  generated_at: string;
  ttl_until: string;
  duration_seconds: number;
  markdown: string;
  sections: DeepDiveSection[];
  error: string | null;
  data_source_status: Record<string, boolean>;
  cache_status: string;
  stale_reason: string | null;
}

export interface DeepDiveStatus {
  ticker: string;
  status: "not_found" | "cached_fresh" | "cached_stale" | "generating" | "failed";
  phase?: string;
  generated_at?: string | null;
  ttl_until?: string | null;
  stale_reason?: string | null;
  events?: Array<{ ts: string; status: string; phase?: string }>;
}

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
