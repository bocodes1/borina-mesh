"use client";

import { useEffect, useState } from "react";
import { AgentCard } from "./agent-card";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";

interface AgentGridProps {
  onSelectAgent: (agent: Agent) => void;
}

export function AgentGrid({ onSelectAgent }: AgentGridProps) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listAgents()
      .then((data) => {
        setAgents(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-64 rounded-xl bg-card/50 animate-pulse" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/50 bg-destructive/10 p-6 text-destructive">
        Failed to load agents: {error}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      {agents.map((agent, i) => (
        <AgentCard key={agent.id} agent={agent} index={i} onClick={() => onSelectAgent(agent)} />
      ))}
    </div>
  );
}
