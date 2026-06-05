"use client";

import { OvernightWorkers } from "@/components/overnight-workers";
import { Navbar } from "@/components/navbar";
import { JobLog } from "@/components/job-log";
import { SectionHeader } from "@/components/ui/section-header";

export default function JobsPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />

      <div className="mb-8">
        <SectionHeader title="Overnight workers" description="Headless Claude Code jobs in git worktrees" />
        <OvernightWorkers />
      </div>

      <JobLog />
    </main>
  );
}
