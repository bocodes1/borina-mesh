"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScheduleEditor } from "./schedule-editor";
import { getAgentVisual } from "@/lib/agent-icons";
import { ModelBadge } from "./model-badge";
import { StatusDot } from "./status-dot";
import type { Agent } from "@/lib/types";

interface AgentCardProps {
  agent: Agent;
  onClick: () => void;
  index: number;
}

function relativeTime(iso?: string | null) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function AgentCard({ agent, onClick, index }: AgentCardProps) {
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const { icon: Icon, accent } = getAgentVisual(agent.id);
  const status = agent.status ?? "idle";

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: index * 0.08, type: "spring", stiffness: 100 }}
        whileHover={{ y: -4, transition: { duration: 0.2 } }}
        className="cursor-pointer"
        onClick={onClick}
      >
        <Card className="glass relative overflow-hidden group h-full">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

          <CardContent className="relative p-5">
            <div className="flex items-start justify-between mb-3">
              <div
                className="w-11 h-11 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: `${accent}1a`, color: accent }}
              >
                <Icon className="w-6 h-6" strokeWidth={1.75} />
              </div>
              <StatusDot status={status} />
            </div>

            <div className="font-semibold text-foreground mb-1">{agent.name}</div>
            <div className="text-sm text-muted-foreground mb-4 line-clamp-2 min-h-[2.5rem]">
              {agent.tagline}
            </div>

            {status === "running" && agent.current_task && (
              <div className="text-xs text-blue-400 mb-2 truncate animate-pulse">
                {agent.current_task}
              </div>
            )}

            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <ModelBadge model={agent.model} />
              <span>last: {relativeTime(agent.last_run_at)}</span>
            </div>

            <div className="mt-3 flex justify-end">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 px-2"
                onClick={(e) => {
                  e.stopPropagation();
                  setScheduleOpen(true);
                }}
              >
                <Clock className="h-3.5 w-3.5 mr-1" />
                <span className="text-xs">Schedule</span>
              </Button>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      <ScheduleEditor agent={agent} open={scheduleOpen} onOpenChange={setScheduleOpen} />
    </>
  );
}
