"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { RefreshCw, AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api, type FinanceBrief as Brief } from "@/lib/api";

export function FinanceBrief() {
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setBrief(await api.getFinanceBrief());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function regenerate() {
    setRegenerating(true);
    try {
      setBrief(await api.regenerateFinanceBrief());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRegenerating(false);
    }
  }

  return (
    <Card className="glass p-5">
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold">Today&apos;s brief</h3>
          {brief?.generated_at && (
            <p className="text-xs text-muted-foreground font-mono mt-0.5">
              {brief.trading_date} · generated {new Date(brief.generated_at).toLocaleString()}
              {brief.duration_seconds !== undefined && ` · ${brief.duration_seconds.toFixed(1)}s`}
            </p>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={regenerate}
          disabled={regenerating}
          className="gap-2"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${regenerating ? "animate-spin" : ""}`} />
          {regenerating ? "Generating…" : "Regenerate"}
        </Button>
      </div>

      {brief?.skipped_sections && brief.skipped_sections.length > 0 && (
        <div className="mb-4 p-3 rounded bg-amber-500/10 border border-amber-500/30 text-sm">
          <div className="flex items-center gap-2 text-amber-400 font-medium mb-1">
            <AlertTriangle className="h-4 w-4" />
            Some data sources are unconfigured
          </div>
          <ul className="text-xs text-muted-foreground space-y-0.5 ml-6 list-disc">
            {brief.skipped_sections.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </div>
      )}

      {loading ? (
        <div className="text-muted-foreground">Loading…</div>
      ) : error ? (
        <div className="text-destructive text-sm">{error}</div>
      ) : !brief?.markdown ? (
        <div className="text-muted-foreground">
          {brief?.error ?? "Brief not generated yet. Click Regenerate to build now."}
        </div>
      ) : (
        <ScrollArea className="max-h-[70vh] pr-4">
          <article className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>{brief.markdown}</ReactMarkdown>
          </article>
        </ScrollArea>
      )}
    </Card>
  );
}
