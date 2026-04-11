"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import { MissionControl } from "@/components/mission-control";
import { MorningBriefCard } from "@/components/morning-brief";
import { CostWidget } from "@/components/cost-widget";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-4 md:py-6 max-w-7xl">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-8"
      >
        <h1 className="text-6xl font-bold tracking-tight">
          Borina <span className="bg-gradient-to-r from-primary to-purple-400 bg-clip-text text-transparent">Mesh</span>
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Multi-agent command center. Message any agent, anywhere.
        </p>
      </motion.div>

      <MorningBriefCard />
      <MissionControl />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          <AgentGrid onSelectAgent={setSelectedAgent} />
        </div>
        <div className="xl:col-span-1 space-y-6">
          <CostWidget />
        </div>
      </div>

      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
