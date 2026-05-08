"use client";

import { Card } from "@/components/ui/card";
import { CalendarDays } from "lucide-react";

/**
 * Calendar component — placeholder until the earnings calendar endpoint
 * lands. The brief already filters tickers within 5 days of earnings; this
 * pane is for the user's at-a-glance "what's coming this week."
 */
export function FinanceCalendar() {
  return (
    <Card className="glass p-5">
      <div className="flex items-center gap-2 mb-2">
        <CalendarDays className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-lg font-semibold">Calendar</h3>
      </div>
      <p className="text-sm text-muted-foreground">
        Next 7 days of earnings, Fed events, and macro releases for watchlist
        tickers — wired in v2 once FMP&apos;s earnings calendar endpoint is
        active. Today&apos;s brief already excludes any candidate within 5
        trading days of earnings.
      </p>
    </Card>
  );
}
