"use client";

import { useEffect, useState } from "react";
import { Settings as SettingsIcon, Check, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { api, type FinanceStatus } from "@/lib/api";

const SOURCE_LABELS: Record<string, string> = {
  edgar: "SEC EDGAR (filings)",
  fred: "FRED (macro)",
  fmp: "Financial Modeling Prep (fundamentals)",
  polygon: "Polygon.io (price/volume)",
  coingecko: "CoinGecko (crypto)",
};

export function FinanceSettings() {
  const [status, setStatus] = useState<FinanceStatus | null>(null);

  useEffect(() => {
    api.getFinanceStatus().then(setStatus).catch(() => undefined);
  }, []);

  return (
    <Card className="glass p-5">
      <div className="flex items-center gap-2 mb-3">
        <SettingsIcon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-lg font-semibold">Settings</h3>
      </div>

      <div className="space-y-3 text-sm">
        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
            Data sources
          </div>
          {status ? (
            <div className="space-y-1">
              {Object.entries(status.data_source_status).map(([k, ok]) => (
                <div key={k} className="flex items-center gap-2 text-xs">
                  {ok ? (
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <X className="h-3.5 w-3.5 text-muted-foreground" />
                  )}
                  <span className={ok ? "" : "text-muted-foreground"}>
                    {SOURCE_LABELS[k] ?? k}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">Loading…</div>
          )}
        </div>

        <div className="pt-3 border-t border-border">
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
            Last brief
          </div>
          {status?.last_brief_generated_at ? (
            <div className="text-xs space-y-0.5">
              <div className="font-mono">{status.last_brief_trading_date}</div>
              <div className="text-muted-foreground">
                {new Date(status.last_brief_generated_at).toLocaleString()}
                {status.last_brief_duration_seconds !== null &&
                  ` · ${status.last_brief_duration_seconds.toFixed(1)}s`}
              </div>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">Not yet generated</div>
          )}
        </div>

        <div className="pt-3 border-t border-border text-xs text-muted-foreground">
          Auto-runs at <span className="font-mono text-foreground">5:00 AM ET</span>{" "}
          daily. Watchlist: <span className="font-mono text-foreground">{status?.watchlist_size ?? "—"}</span> tickers.
        </div>
      </div>
    </Card>
  );
}
