"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import { motion } from "framer-motion";
import { ArrowLeft, RefreshCw, AlertTriangle, Clock, CheckCircle2 } from "lucide-react";
import { Navbar } from "@/components/navbar";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api, type DeepDive, type DeepDiveStatus } from "@/lib/api";

const POLL_MS = 2000;

export default function DeepDivePage() {
  const params = useParams<{ ticker: string }>();
  const ticker = (params?.ticker ?? "").toUpperCase();

  const [deepdive, setDeepdive] = useState<DeepDive | null>(null);
  const [status, setStatus] = useState<DeepDiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const pollerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load + status check
  useEffect(() => {
    if (!ticker) return;
    let cancelled = false;
    (async () => {
      try {
        const s = await api.getDeepdiveStatus(ticker);
        if (cancelled) return;
        setStatus(s);
        if (s.status === "cached_fresh" || s.status === "cached_stale") {
          const dd = await api.getDeepdive(ticker);
          if (!cancelled) setDeepdive(dd);
        } else if (s.status === "not_found") {
          // Auto-trigger first-time generation
          await onGenerate(false);
        } else if (s.status === "generating") {
          setGenerating(true);
          startPoll();
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
      stopPoll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker]);

  function startPoll() {
    stopPoll();
    pollerRef.current = setInterval(async () => {
      try {
        const s = await api.getDeepdiveStatus(ticker);
        setStatus(s);
        if (s.status === "cached_fresh") {
          stopPoll();
          setGenerating(false);
          const dd = await api.getDeepdive(ticker);
          setDeepdive(dd);
        } else if (s.status === "failed") {
          stopPoll();
          setGenerating(false);
          setError("Generation failed — check logs.");
        }
      } catch {
        // transient; ignore
      }
    }, POLL_MS);
  }

  function stopPoll() {
    if (pollerRef.current) {
      clearInterval(pollerRef.current);
      pollerRef.current = null;
    }
  }

  async function onGenerate(force: boolean) {
    setError(null);
    setGenerating(true);
    try {
      await api.generateDeepdive(ticker, force);
      startPoll();
    } catch (e) {
      setError((e as Error).message);
      setGenerating(false);
    }
  }

  const headerStateLine = useMemo(() => {
    if (generating) {
      return (
        <span className="inline-flex items-center gap-1.5 text-amber-400">
          <RefreshCw className="h-3 w-3 animate-spin" />
          {status?.phase === "running_agent"
            ? "Agent writing analysis…"
            : status?.phase === "gathering"
              ? "Pulling data sources…"
              : "Starting…"}
        </span>
      );
    }
    if (deepdive) {
      const stateClass =
        deepdive.cache_status === "cached_fresh"
          ? "text-emerald-400"
          : "text-amber-400";
      return (
        <span className={`inline-flex items-center gap-1.5 ${stateClass}`}>
          {deepdive.cache_status === "cached_fresh" ? (
            <CheckCircle2 className="h-3 w-3" />
          ) : (
            <Clock className="h-3 w-3" />
          )}
          {deepdive.cache_status === "cached_fresh" ? "Fresh" : "Stale"}
          {deepdive.stale_reason ? ` — ${deepdive.stale_reason}` : ""}
          {" · generated "}
          {new Date(deepdive.generated_at).toLocaleString()}
        </span>
      );
    }
    return <span className="text-muted-foreground">Loading…</span>;
  }, [deepdive, generating, status]);

  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <Link
        href="/finance"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4"
      >
        <ArrowLeft className="h-3.5 w-3.5" /> Finance
      </Link>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6 flex items-baseline justify-between gap-4 flex-wrap"
      >
        <div>
          <h2 className="text-3xl font-bold tracking-tight font-mono">{ticker}</h2>
          <div className="text-sm mt-1">{headerStateLine}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => onGenerate(true)}
            disabled={generating}
            className="gap-2"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${generating ? "animate-spin" : ""}`} />
            {generating ? "Generating…" : "Regenerate"}
          </Button>
        </div>
      </motion.div>

      {error && (
        <Card className="glass p-4 mb-6 border-destructive/40">
          <div className="flex items-center gap-2 text-destructive">
            <AlertTriangle className="h-4 w-4" />
            {error}
          </div>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[14rem_minmax(0,1fr)] gap-6">
        {/* Sticky section nav */}
        <aside className="lg:sticky lg:top-6 self-start hidden lg:block">
          <Card className="glass p-3 text-xs">
            <div className="text-muted-foreground uppercase tracking-wider mb-2">
              Sections
            </div>
            {deepdive?.sections?.length ? (
              <ul className="space-y-1">
                {deepdive.sections.map((s) => (
                  <li key={s.anchor}>
                    <a
                      href={`#${s.anchor}`}
                      className="block px-2 py-1 rounded hover:bg-accent text-muted-foreground hover:text-foreground"
                    >
                      {s.title}
                    </a>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-muted-foreground">—</div>
            )}
          </Card>

          {deepdive?.data_source_status && (
            <Card className="glass p-3 mt-4 text-xs">
              <div className="text-muted-foreground uppercase tracking-wider mb-2">
                Sources
              </div>
              <ul className="space-y-1">
                {Object.entries(deepdive.data_source_status).map(([k, ok]) => (
                  <li key={k} className="flex items-center justify-between gap-2">
                    <span className={ok ? "" : "text-muted-foreground"}>{k}</span>
                    <span className={ok ? "text-emerald-400" : "text-muted-foreground"}>
                      {ok ? "✓" : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </aside>

        {/* Body */}
        <Card className="glass p-6 overflow-hidden">
          {generating && !deepdive ? (
            <div className="space-y-4">
              <SkeletonRow w="60%" h="2rem" />
              <SkeletonRow w="40%" h="0.875rem" />
              <div className="h-px bg-border my-4" />
              <SkeletonRow w="30%" h="1.5rem" />
              <SkeletonRow w="100%" h="0.875rem" />
              <SkeletonRow w="95%" h="0.875rem" />
              <SkeletonRow w="100%" h="0.875rem" />
              <SkeletonRow w="80%" h="0.875rem" />
            </div>
          ) : !deepdive ? (
            <div className="text-muted-foreground">
              No deep-dive yet. Click <strong>Regenerate</strong> to build one.
            </div>
          ) : (
            <ScrollArea className="max-h-[80vh] pr-4">
              <article className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown
                  components={{
                    h2: ({ node, ...props }) => {
                      const text = String(props.children ?? "");
                      const anchor = text
                        .toLowerCase()
                        .replace(/[^a-z0-9]+/g, "-")
                        .replace(/^-|-$/g, "");
                      return <h2 id={anchor} {...props} />;
                    },
                  }}
                >
                  {deepdive.markdown}
                </ReactMarkdown>
              </article>
            </ScrollArea>
          )}
        </Card>
      </div>
    </main>
  );
}

function SkeletonRow({ w, h }: { w: string; h: string }) {
  return (
    <div
      className="rounded bg-accent/40 animate-pulse"
      style={{ width: w, height: h }}
    />
  );
}
