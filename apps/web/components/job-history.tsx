"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, XCircle, Loader2, Clock } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { Job, Agent } from "@/lib/types";
import { JobDetailModal } from "./job-detail-modal";

const STATUS_ICONS: Record<Job["status"], React.ReactNode> = {
  pending: <Clock className="h-4 w-4 text-muted-foreground" />,
  running: <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />,
  completed: <CheckCircle2 className="h-4 w-4 text-green-400" />,
  failed: <XCircle className="h-4 w-4 text-red-400" />,
  cancelled: <XCircle className="h-4 w-4 text-muted-foreground" />,
};

const STATUS_VARIANTS: Record<Job["status"], "default" | "success" | "destructive" | "secondary"> = {
  pending: "secondary",
  running: "default",
  completed: "success",
  failed: "destructive",
  cancelled: "secondary",
};

export function JobHistory() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(true);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);

  useEffect(() => {
    Promise.all([api.listJobs(), api.listAgents()])
      .then(([jobsData, agentsData]) => {
        setJobs(jobsData);
        setAgents(agentsData);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const agentMap = Object.fromEntries(agents.map((a) => [a.id, a]));
  const filtered = filter === "all" ? jobs : jobs.filter((j) => j.agent_id === filter);

  if (loading) {
    return <div className="text-muted-foreground">Loading job history...</div>;
  }

  return (
    <div className="space-y-4">
      {/* Filter tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setFilter("all")}
          className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
            filter === "all" ? "bg-primary text-primary-foreground" : "glass text-muted-foreground hover:text-foreground"
          }`}
        >
          All
        </button>
        {agents.map((agent) => (
          <button
            key={agent.id}
            onClick={() => setFilter(agent.id)}
            className={`px-3 py-1.5 rounded-full text-sm transition-colors flex items-center gap-1.5 ${
              filter === agent.id ? "bg-primary text-primary-foreground" : "glass text-muted-foreground hover:text-foreground"
            }`}
          >
            <span>{agent.emoji}</span>
            {agent.name}
          </button>
        ))}
      </div>

      {/* Job table */}
      <Card className="glass overflow-hidden">
        <div className="divide-y divide-border">
          {filtered.length === 0 && (
            <div className="p-8 text-center text-muted-foreground">
              No jobs yet. Run an agent to see history here.
            </div>
          )}
          {filtered.map((job, i) => (
            <motion.div
              key={job.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: Math.min(i * 0.02, 0.5) }}
              onClick={() => setSelectedJob(job)}
              className="p-4 hover:bg-accent/50 transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-4">
                <div>{STATUS_ICONS[job.status]}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-lg">{agentMap[job.agent_id]?.emoji ?? "🤖"}</span>
                    <span className="font-medium text-sm">{agentMap[job.agent_id]?.name ?? job.agent_id}</span>
                    <Badge variant={STATUS_VARIANTS[job.status]} className="text-xs">
                      {job.status}
                    </Badge>
                  </div>
                  <div className="text-sm text-muted-foreground truncate">{job.prompt}</div>
                </div>
                <div className="text-xs text-muted-foreground font-mono text-right">
                  <div>{new Date(job.created_at).toLocaleDateString()}</div>
                  <div>{new Date(job.created_at).toLocaleTimeString()}</div>
                </div>
              </div>
              {job.error && (
                <div className="mt-2 ml-8 text-xs text-destructive bg-destructive/10 rounded p-2">
                  {job.error}
                </div>
              )}
            </motion.div>
          ))}
        </div>
      </Card>
      <JobDetailModal
        job={selectedJob}
        agentName={selectedJob ? agentMap[selectedJob.agent_id]?.name : undefined}
        agentEmoji={selectedJob ? agentMap[selectedJob.agent_id]?.emoji : undefined}
        onClose={() => setSelectedJob(null)}
      />
    </div>
  );
}
