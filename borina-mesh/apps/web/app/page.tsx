"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-12 max-w-7xl">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="mb-12"
      >
        <h1 className="text-6xl font-bold tracking-tight">
          Borina <span className="bg-gradient-to-r from-primary to-purple-400 bg-clip-text text-transparent">Mesh</span>
        </h1>
        <p className="mt-3 text-lg text-muted-foreground">
          Multi-agent command center. Message any agent, anywhere.
        </p>
      </motion.div>

      <AgentGrid onSelectAgent={setSelectedAgent} />
      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
