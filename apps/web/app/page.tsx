"use client";

import { useState } from "react";
import { AgentGrid } from "@/components/agent-grid";
import { ChatPanel } from "@/components/chat-panel";
import { MissionControl } from "@/components/mission-control";
import { ActivityFeed } from "@/components/activity-feed";
import { Navbar } from "@/components/navbar";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);

  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />
      <MissionControl />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <AgentGrid onSelectAgent={setSelectedAgent} />
        </div>
        <div className="lg:col-span-1">
          <ActivityFeed />
        </div>
      </div>

      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
