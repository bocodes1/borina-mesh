"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { MorningBrief } from "@/lib/types";

export function MorningBriefCard() {
  const [brief, setBrief] = useState<MorningBrief | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    api.getLatestBrief().then(setBrief).catch(() => setError(true));
  }, []);

  if (error || !brief) {
    return (
      <Card className="mb-6 border-dashed border-muted-foreground/30">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">
            Morning Brief
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No brief yet today. Runs daily at 7:15 AM.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="mb-6">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium">
            Morning Brief — {brief.date}
          </CardTitle>
          <span className="text-xs text-muted-foreground">
            {brief.total_runs} runs | ${brief.total_cost_usd.toFixed(2)}
          </span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="prose prose-sm prose-invert max-w-none whitespace-pre-wrap">
          {brief.summary}
        </div>
      </CardContent>
    </Card>
  );
}
