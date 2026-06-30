"use client";

import { Navbar } from "@/components/navbar";
import { JobLog } from "@/components/job-log";

export default function JobsPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <JobLog />
    </main>
  );
}
