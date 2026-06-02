"use client";

import { motion } from "framer-motion";
import { Navbar } from "@/components/navbar";
import { FinanceBrief } from "@/components/finance-brief";
import { FinanceWatchlist } from "@/components/finance-watchlist";
import { FinanceCalendar } from "@/components/finance-calendar";
import { FinanceSettings } from "@/components/finance-settings";
import { FinancePortfolio } from "@/components/finance-portfolio";

export default function FinancePage() {
  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6"
      >
        <h2 className="text-3xl font-bold tracking-tight">Finance</h2>
        <p className="text-muted-foreground mt-1">
          Morning brief, watchlist, and ticker deep-dives. Surfaces facts and
          multiples — never recommendations.
        </p>
      </motion.div>

      <div className="mb-6">
        <FinancePortfolio />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <FinanceBrief />
          <FinanceCalendar />
        </div>
        <div className="space-y-6">
          <FinanceWatchlist />
          <FinanceSettings />
        </div>
      </div>
    </main>
  );
}
