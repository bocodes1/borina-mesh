"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface AnalyticsSummary {
  total_runs: number;
  total_tokens: number;
  total_cost_usd: number;
  runs_by_agent: Record<string, { runs: number; tokens: number; cost_usd: number }>;
}

export function CostWidget() {
  const [data, setData] = useState<AnalyticsSummary | null>(null);

  useEffect(() => {
    fetch("/api/analytics/summary")
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, []);

  if (!data) return null;

  const agents = Object.entries(data.runs_by_agent).sort(
    ([, a], [, b]) => b.cost_usd - a.cost_usd
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium">Cost Summary</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Total runs</span>
          <span>{data.total_runs}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Total tokens</span>
          <span>{data.total_tokens.toLocaleString()}</span>
        </div>
        <div className="flex justify-between text-sm font-medium">
          <span className="text-muted-foreground">Total cost</span>
          <span>${data.total_cost_usd.toFixed(2)}</span>
        </div>
        {agents.length > 0 && (
          <div className="pt-2 border-t border-border mt-2 space-y-1">
            {agents.slice(0, 5).map(([id, stats]) => (
              <div key={id} className="flex justify-between text-xs text-muted-foreground">
                <span>{id}</span>
                <span>{stats.runs} runs · ${stats.cost_usd.toFixed(2)}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
