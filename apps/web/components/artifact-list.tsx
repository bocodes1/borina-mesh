"use client";

import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { FileText, FileType, Download, Send } from "lucide-react";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";
import { SectionHeader } from "@/components/ui/section-header";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/loading-skeleton";

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function icon(name: string) {
  if (name.endsWith(".pdf")) return <FileType className="h-4 w-4 text-negative" />;
  return <FileText className="h-4 w-4 text-brand" />;
}

export function ArtifactList() {
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState("all");

  const load = () =>
    api.listArtifacts().then((d) => { setArtifacts(d); setError(null); }).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    const id = setInterval(load, 8000); // new artifacts animate in as produced
    return () => clearInterval(id);
  }, []);

  const agents = useMemo(
    () => Array.from(new Set((artifacts ?? []).map((a) => a.agent).filter(Boolean))) as string[],
    [artifacts],
  );
  const filtered = (artifacts ?? []).filter((a) => agent === "all" || a.agent === agent);

  return (
    <div>
      <SectionHeader
        title="Artifacts"
        description={artifacts ? `${artifacts.length} files` : "loading…"}
        actions={
          agents.length ? (
            <select value={agent} onChange={(e) => setAgent(e.target.value)} aria-label="filter agent" className="rounded border border-border bg-surface px-2 py-1 font-mono text-xs">
              <option value="all">all agents</option>
              {agents.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          ) : null
        }
      />

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : artifacts === null ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : filtered.length === 0 ? (
        <EmptyState title="No artifacts yet" description="Agent reports and Telegram PDFs land here." icon={<FileText />} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <AnimatePresence initial={false}>
            {filtered.map((a) => (
              <motion.div
                key={a.path}
                layout
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0 }}
                className="surface-card flex flex-col gap-2 rounded-lg p-3"
              >
                <div className="flex items-start gap-2">
                  {icon(a.name)}
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-foreground/90">{a.name}</span>
                  <a href={`/api/artifacts/${a.path}`} download aria-label={`download ${a.name}`} className="shrink-0 text-muted-foreground hover:text-brand">
                    <Download className="h-4 w-4" />
                  </a>
                </div>

                {a.source === "telegram" ? (
                  <div className="rounded border border-brand-2/20 bg-brand-2/[0.06] px-2 py-1">
                    <span className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wide text-brand-2">
                      <Send className="h-3 w-3" /> telegram{a.agent ? ` · ${a.agent}` : ""}
                    </span>
                    {a.prompt ? <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">“{a.prompt}”</p> : null}
                  </div>
                ) : null}

                <div className="mt-auto flex items-center justify-between font-mono text-[10px] text-muted-foreground/60">
                  <span className="tabular-nums">{a.date}</span>
                  <span className="tabular-nums">{fmtSize(a.size_bytes)}</span>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
}
