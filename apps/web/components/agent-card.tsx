"use client";

import { motion } from "framer-motion";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Agent } from "@/lib/types";

interface AgentCardProps {
  agent: Agent;
  onClick: () => void;
  index: number;
}

export function AgentCard({ agent, onClick, index }: AgentCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.08, type: "spring", stiffness: 100 }}
      whileHover={{ y: -4, transition: { duration: 0.2 } }}
      onClick={onClick}
      className="cursor-pointer"
    >
      <Card className="glass relative overflow-hidden group h-full">
        {/* Gradient glow on hover */}
        <div className="absolute inset-0 bg-gradient-to-br from-primary/10 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />

        {/* Status indicator */}
        <div className="absolute top-4 right-4 flex items-center gap-2">
          <div className="relative">
            <div className="h-2 w-2 rounded-full bg-green-500" />
            <div className="absolute inset-0 h-2 w-2 rounded-full bg-green-500 animate-ping opacity-75" />
          </div>
          <span className="text-xs text-muted-foreground">idle</span>
        </div>

        <CardHeader className="relative">
          <div className="text-5xl mb-2">{agent.emoji}</div>
          <CardTitle className="text-xl">{agent.name}</CardTitle>
          <CardDescription className="line-clamp-2">{agent.tagline}</CardDescription>
        </CardHeader>

        <CardContent className="relative">
          <div className="flex flex-wrap gap-1.5">
            {agent.tools.slice(0, 3).map((tool) => (
              <Badge key={tool} variant="secondary" className="text-xs">
                {tool}
              </Badge>
            ))}
            {agent.tools.length > 3 && (
              <Badge variant="outline" className="text-xs">
                +{agent.tools.length - 3}
              </Badge>
            )}
          </div>
          <div className="mt-3 text-xs text-muted-foreground font-mono">{agent.model}</div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
