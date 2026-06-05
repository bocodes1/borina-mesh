"use client";

import { useState } from "react";
import { ChatPanel } from "@/components/chat-panel";
import { Navbar } from "@/components/navbar";
import { CommandStatusBar } from "@/components/command-status-bar";
import { LiveActivityStream } from "@/components/live-activity-stream";
import { AgentFleet } from "@/components/agent-fleet";
import { useActivityStream } from "@/lib/use-activity";
import type { Agent } from "@/lib/types";

export default function Home() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const { events, byAgent } = useActivityStream();

  return (
    <main className="container mx-auto max-w-7xl px-4 py-4 md:py-6">
      <Navbar />
      <CommandStatusBar />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <AgentFleet byAgent={byAgent} onSelectAgent={setSelectedAgent} />
        </div>
        <div className="xl:col-span-1">
          <LiveActivityStream events={events} />
        </div>
      </div>

      <ChatPanel agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
    </main>
  );
}
