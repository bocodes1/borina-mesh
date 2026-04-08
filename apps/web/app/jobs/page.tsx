"use client";

import { motion } from "framer-motion";
import { JobHistory } from "@/components/job-history";
import { Navbar } from "@/components/navbar";

export default function JobsPage() {
  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <h2 className="text-3xl font-bold tracking-tight">Job History</h2>
        <p className="text-muted-foreground mt-1">All agent runs — filter by agent, inspect errors.</p>
      </motion.div>

      <JobHistory />
    </main>
  );
}
