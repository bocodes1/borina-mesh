"use client";

import { Wallet, Landmark, Coins } from "lucide-react";
import { api, type PortfolioResponse } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { KpiCard } from "@/components/ui/kpi-card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonKpiStrip } from "@/components/ui/loading-skeleton";

function money(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

/** Net-worth strip: brokerage + crypto wallet. Either source may be
 *  "Connect X" without ever crashing the tab. */
export function FinancePortfolio() {
  const { data, loading, error, reload } = useAsync<PortfolioResponse>(() => api.getPortfolio(), []);

  if (loading) return <SkeletonKpiStrip count={3} />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No portfolio data" />;

  const broker = data.brokerage;
  const wallet = data.wallet;
  const bk = broker.connected ? broker.data : null;
  const wd = wallet.connected ? wallet.data : null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <KpiCard label="Net worth" value={money(data.net_worth)} icon={<Wallet className="h-4 w-4" />} />
        <KpiCard
          label="Brokerage"
          value={broker.connected ? money(bk?.total_value) : "—"}
          delta={bk?.day_change_pct != null ? `${bk.day_change_pct > 0 ? "+" : ""}${bk.day_change_pct}%` : undefined}
          deltaTone={(bk?.day_change_pct ?? 0) >= 0 ? "positive" : "negative"}
          icon={<Landmark className="h-4 w-4" />}
        />
        <KpiCard label="Crypto" value={wallet.connected ? money(wd?.total_usd) : "—"} icon={<Coins className="h-4 w-4" />} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Brokerage */}
        {broker.connected && bk ? (
          <div className="surface-card rounded-2xl p-4">
            <p className="mb-2 text-sm font-medium">Positions</p>
            <div className="space-y-1.5">
              {bk.positions.map((p) => (
                <div key={p.symbol} className="flex items-center justify-between text-sm">
                  <span className="font-medium">{p.symbol}</span>
                  <span className="tabular-nums text-muted-foreground">{money(p.value)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState
            title="Brokerage not connected"
            description="Add BROKERAGE_API_KEY to see read-only positions."
            icon={<Landmark />}
          />
        )}

        {/* Wallet */}
        {wallet.connected && wd ? (
          <div className="surface-card rounded-2xl p-4">
            <p className="mb-2 text-sm font-medium">Wallet assets</p>
            <div className="space-y-1.5">
              {wd.assets.map((a) => (
                <div key={a.symbol} className="flex items-center justify-between text-sm">
                  <span className="font-medium">{a.symbol}</span>
                  <span className="tabular-nums text-muted-foreground">{money(a.value_usd)}</span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <EmptyState
            title="Wallet not connected"
            description="Add WALLET_ADDRESSES for read-only balances."
            icon={<Coins />}
          />
        )}
      </div>
    </div>
  );
}
