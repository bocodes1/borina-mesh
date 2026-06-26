"use client";

import { Mail, Send, Inbox, Clock } from "lucide-react";
import { api, type OutreachSummary } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { Navbar } from "@/components/navbar";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonKpiStrip, SkeletonCard } from "@/components/ui/loading-skeleton";

const STATUS_COLORS: Record<string, string> = {
  proposed: "bg-surface-2 text-muted-foreground",
  sent: "bg-blue-500/15 text-blue-300",
  replied: "bg-positive/15 text-positive",
  skipped: "bg-surface-2 text-muted-foreground",
  failed: "bg-negative/15 text-negative",
};

const FLAG_COLORS: Record<string, string> = {
  interview: "bg-positive/15 text-positive",
  rejection: "bg-negative/15 text-negative",
  neutral: "bg-surface-2 text-muted-foreground",
};

export default function OutreachPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <OutreachBody />
    </main>
  );
}

function OutreachBody() {
  const { data, loading, error, reload } = useAsync<OutreachSummary>(() => api.getOutreachSummary(), []);

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonKpiStrip count={3} />
        <SkeletonCard />
      </div>
    );
  }
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data) return <EmptyState title="No outreach data" />;

  const { counts, rows, replies, week } = data;
  const hasAny = rows.length > 0;

  return (
    <div className="space-y-6">
      {/* Week KPI strip */}
      <div className="grid grid-cols-3 gap-3">
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Send className="h-4 w-4" /> Sent (7d)
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.sent}</p>
        </div>
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Inbox className="h-4 w-4" /> Replies (7d)
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.replied}</p>
        </div>
        <div className="surface-card rounded-2xl p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Clock className="h-4 w-4" /> Awaiting follow-up
          </div>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{week.awaiting_followup}</p>
        </div>
      </div>

      {/* Stage counts */}
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([stage, n]) => (
          <span key={stage} className={`rounded-md px-2.5 py-1 text-xs ${STATUS_COLORS[stage] ?? STATUS_COLORS.proposed}`}>
            {stage}: <span className="tabular-nums">{n}</span>
          </span>
        ))}
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Pipeline rows */}
        <section>
          <SectionHeader title="Pipeline" icon={<Mail className="h-4 w-4" />} description="Per-company outreach" />
          {!hasAny ? (
            <EmptyState title="No outreach yet" description="Stage a batch from Telegram with apply:" />
          ) : (
            <div className="space-y-2">
              {rows.map((r) => (
                <div key={r.id} className="flex items-center gap-3 rounded-xl border border-border/40 bg-surface px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">
                      {r.company}
                      {r.is_followup ? <span className="ml-1 text-xs text-muted-foreground">(follow-up)</span> : null}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">{r.contact_email}</p>
                  </div>
                  <span className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-muted-foreground">{r.track}</span>
                  <span className={`rounded-md px-2 py-0.5 text-xs ${STATUS_COLORS[r.status] ?? STATUS_COLORS.proposed}`}>
                    {r.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Replies */}
        <section>
          <SectionHeader title="Replies" icon={<Inbox className="h-4 w-4" />} description="Flagged for your glance — confirm in Telegram" />
          {replies.length === 0 ? (
            <EmptyState title="No replies yet" description="Detected automatically from your mailbox." />
          ) : (
            <div className="space-y-2">
              {replies.map((rep, i) => (
                <div key={i} className="flex items-center gap-3 rounded-xl border border-border/40 bg-surface px-3 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-foreground">{rep.from_email}</p>
                    <p className="truncate text-xs text-muted-foreground">{rep.subject}</p>
                  </div>
                  <span className={`rounded-md px-2 py-0.5 text-xs ${FLAG_COLORS[rep.flag] ?? FLAG_COLORS.neutral}`}>
                    {rep.flag}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
