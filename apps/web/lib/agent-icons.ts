import {
  Briefcase, Search, Compass, LineChart, Megaphone,
  Inbox, TrendingUp, ShieldCheck, type LucideIcon,
} from "lucide-react";

export type AgentVisual = { icon: LucideIcon; accent: string };

export const AGENT_VISUALS: Record<string, AgentVisual> = {
  ceo:         { icon: Briefcase,    accent: "#7c3aed" },
  researcher:  { icon: Search,       accent: "#0ea5e9" },
  "ecommerce-scout": { icon: Compass, accent: "#22c55e" },
  trader:      { icon: LineChart,    accent: "#f59e0b" },
  "adset-optimizer": { icon: Megaphone, accent: "#ec4899" },
  "inbox-triage": { icon: Inbox,     accent: "#64748b" },
  "polymarket-intel": { icon: TrendingUp, accent: "#14b8a6" },
  qa_director: { icon: ShieldCheck,  accent: "#dc2626" },
};

export function getAgentVisual(id: string): AgentVisual {
  return AGENT_VISUALS[id] ?? { icon: Briefcase, accent: "#94a3b8" };
}
