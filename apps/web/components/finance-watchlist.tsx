"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Plus, X, ExternalLink, BarChart2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, type FinanceTickerSnapshot } from "@/lib/api";

function fmtNum(n: number | undefined | null, suffix = "x"): string {
  if (n === undefined || n === null) return "—";
  return `${n.toFixed(1)}${suffix}`;
}

function fmtMcap(n: number | undefined | null): string {
  if (!n) return "—";
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

export function FinanceWatchlist() {
  const [tickers, setTickers] = useState<string[]>([]);
  const [adding, setAdding] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<FinanceTickerSnapshot | null>(null);
  const [snapLoading, setSnapLoading] = useState(false);

  async function load() {
    try {
      const r = await api.getFinanceWatchlist();
      setTickers(r.tickers);
    } catch {
      // fall through
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function addTicker() {
    const t = adding.trim().toUpperCase();
    if (!t) return;
    try {
      const r = await api.addFinanceTicker(t);
      setTickers(r.tickers);
      setAdding("");
    } catch {
      // ignored — server returns 400 on bad symbol
    }
  }

  async function removeTicker(t: string) {
    try {
      const r = await api.removeFinanceTicker(t);
      setTickers(r.tickers);
    } catch {
      // ignore
    }
  }

  async function openTicker(t: string) {
    setOpen(t);
    setSnapshot(null);
    setSnapLoading(true);
    try {
      setSnapshot(await api.getFinanceTicker(t));
    } catch (e) {
      setSnapshot({ ticker: t, warning: (e as Error).message });
    } finally {
      setSnapLoading(false);
    }
  }

  return (
    <>
      <Card className="glass p-5">
        <h3 className="text-lg font-semibold mb-3">Watchlist</h3>
        <div className="flex gap-2 mb-3">
          <Input
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addTicker()}
            placeholder="Ticker (e.g. NVDA)"
            className="text-sm"
          />
          <Button size="sm" onClick={addTicker} className="shrink-0">
            <Plus className="h-4 w-4" />
          </Button>
        </div>

        {tickers.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            Empty. Add a ticker to start tracking.
          </div>
        ) : (
          <div className="space-y-1.5">
            {tickers.map((t) => (
              <div
                key={t}
                className="flex items-center gap-2 p-2 rounded hover:bg-accent/50 transition-colors"
              >
                <Link
                  href={`/finance/${t}`}
                  className="font-mono font-medium text-sm flex-1 hover:text-primary"
                  title="Open deep-dive"
                >
                  {t}
                </Link>
                <button
                  onClick={() => openTicker(t)}
                  className="text-muted-foreground hover:text-foreground p-1"
                  aria-label={`Quick stats for ${t}`}
                  title="Quick stats"
                >
                  <BarChart2 className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={() => removeTicker(t)}
                  className="text-muted-foreground hover:text-destructive p-1"
                  aria-label={`Remove ${t}`}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="font-mono">
              {open}
              {snapshot?.name && (
                <span className="ml-2 text-sm text-muted-foreground font-sans">
                  {snapshot.name}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>

          {snapLoading ? (
            <div className="text-muted-foreground p-4">Loading…</div>
          ) : !snapshot ? (
            <div className="text-muted-foreground p-4">No data.</div>
          ) : snapshot.warning ? (
            <div className="text-sm text-amber-400 p-3 rounded bg-amber-500/10 border border-amber-500/30">
              {snapshot.warning}
              {snapshot.recent_filings && snapshot.recent_filings.length > 0 && (
                <div className="mt-3 pt-3 border-t border-amber-500/30">
                  <div className="text-xs text-muted-foreground mb-1">Recent filings:</div>
                  {snapshot.recent_filings.map((f, i) => (
                    <a
                      key={i}
                      href={f.primary_doc_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1 text-xs text-blue-400 hover:underline"
                    >
                      {f.form} · {f.filing_date} <ExternalLink className="h-3 w-3" />
                    </a>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
                <div className="text-muted-foreground">Price</div>
                <div className="font-mono">${snapshot.price?.toFixed(2) ?? "—"}</div>
                <div className="text-muted-foreground">Market cap</div>
                <div className="font-mono">{fmtMcap(snapshot.market_cap)}</div>
                {snapshot.earnings_in_days !== null && snapshot.earnings_in_days !== undefined && (
                  <>
                    <div className="text-muted-foreground">Next earnings</div>
                    <div className="font-mono">in {snapshot.earnings_in_days}d</div>
                  </>
                )}
              </div>

              <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                  Lens 1 — vs own history
                </div>
                <div className="grid grid-cols-4 gap-1 text-xs font-mono">
                  <div className="text-muted-foreground">Forward P/E</div>
                  <div>{fmtNum(snapshot.forward_pe)}</div>
                  <div className="text-muted-foreground">5y med</div>
                  <div>{fmtNum(snapshot.pe_5y_median)}</div>

                  <div className="text-muted-foreground">EV/EBITDA</div>
                  <div>{fmtNum(snapshot.ev_ebitda)}</div>
                  <div className="text-muted-foreground">5y med</div>
                  <div>{fmtNum(snapshot.ev_ebitda_5y_median)}</div>

                  <div className="text-muted-foreground">P/S</div>
                  <div>{fmtNum(snapshot.ps)}</div>
                  <div className="text-muted-foreground">5y med</div>
                  <div>{fmtNum(snapshot.ps_5y_median)}</div>
                </div>
                {snapshot.history_warning && (
                  <div className="mt-2 text-xs text-amber-400">
                    ⚠ {snapshot.history_warning}
                  </div>
                )}
              </div>

              <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                  Lens 2 — vs peers ({snapshot.peers?.join(", ") || "—"})
                </div>
                <div className="grid grid-cols-4 gap-1 text-xs font-mono">
                  <div className="text-muted-foreground">P/E</div>
                  <div>{fmtNum(snapshot.peer_pe_median)}</div>
                  <div className="text-muted-foreground">EV/EBITDA</div>
                  <div>{fmtNum(snapshot.peer_ev_ebitda_median)}</div>
                  <div className="text-muted-foreground">P/S</div>
                  <div>{fmtNum(snapshot.peer_ps_median)}</div>
                </div>
              </div>

              <div>
                <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                  Lens 3 — DCF sanity check
                </div>
                <div className="grid grid-cols-2 gap-1 text-xs font-mono">
                  <div className="text-muted-foreground">Implied growth at price</div>
                  <div>{fmtNum(snapshot.implied_dcf_growth_pct, "%/yr")}</div>
                  <div className="text-muted-foreground">Last 3y revenue CAGR</div>
                  <div>{fmtNum(snapshot.actual_3y_revenue_cagr_pct, "%/yr")}</div>
                </div>
              </div>

              {snapshot.recent_filings && snapshot.recent_filings.length > 0 && (
                <div>
                  <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
                    Recent filings
                  </div>
                  <div className="space-y-1">
                    {snapshot.recent_filings.map((f, i) => (
                      <a
                        key={i}
                        href={f.primary_doc_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs text-blue-400 hover:underline"
                      >
                        <span className="font-mono">{f.form}</span>
                        <span className="text-muted-foreground">· {f.filing_date}</span>
                        <ExternalLink className="h-3 w-3 ml-auto" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
