"use client";

import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { FileText, ExternalLink } from "lucide-react";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Stable color hue per agent so the dashboard reads at a glance.
function agentAccent(agent: string): string {
  const palette: Record<string, string> = {
    trader: "text-emerald-400",
    "polymarket-intel": "text-fuchsia-400",
    "inbox-triage": "text-sky-400",
    ceo: "text-amber-400",
    "ecommerce-scout": "text-rose-400",
    researcher: "text-indigo-400",
    "adset-optimizer": "text-orange-400",
    "qa-director": "text-purple-400",
    uncategorized: "text-muted-foreground",
  };
  return palette[agent] ?? "text-blue-400";
}

function agentLabel(agent: string): string {
  if (agent === "uncategorized") return "Uncategorized";
  return agent
    .split("-")
    .map((w) => w[0].toUpperCase() + w.slice(1))
    .join(" ");
}

export function ArtifactList() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState<Artifact | null>(null);
  const [content, setContent] = useState<string>("");
  const [contentLoading, setContentLoading] = useState(false);

  useEffect(() => {
    api
      .listArtifacts()
      .then((data) => {
        setArtifacts(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // Group by agent. Within each agent, newest date first.
  const byAgent = useMemo(() => {
    const groups: Record<string, Artifact[]> = {};
    for (const a of artifacts) {
      (groups[a.agent] ||= []).push(a);
    }
    for (const list of Object.values(groups)) {
      list.sort((x, y) =>
        x.date === y.date ? x.name.localeCompare(y.name) : y.date.localeCompare(x.date),
      );
    }
    return groups;
  }, [artifacts]);

  const agents = useMemo(() => {
    const known = Object.keys(byAgent);
    // Stable display order: most files first, "uncategorized" last.
    return known.sort((a, b) => {
      if (a === "uncategorized") return 1;
      if (b === "uncategorized") return -1;
      return byAgent[b].length - byAgent[a].length;
    });
  }, [byAgent]);

  async function openArtifact(a: Artifact) {
    setOpen(a);
    setContent("");
    setContentLoading(true);
    try {
      const text = await api.getArtifactText(a.date, a.name);
      setContent(text);
    } catch (e) {
      setContent(`> Failed to load: ${(e as Error).message}`);
    } finally {
      setContentLoading(false);
    }
  }

  if (loading) {
    return <div className="text-muted-foreground">Loading artifacts...</div>;
  }

  if (agents.length === 0) {
    return (
      <Card className="glass p-8 text-center text-muted-foreground">
        No artifacts yet. Agents will save reports here.
      </Card>
    );
  }

  return (
    <>
      <div className="space-y-6">
        {agents.map((agent, agentIdx) => (
          <motion.div
            key={agent}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: agentIdx * 0.05 }}
          >
            <div className="flex items-baseline justify-between mb-2">
              <div className={`text-sm font-semibold font-mono ${agentAccent(agent)}`}>
                {agentLabel(agent)}
              </div>
              <div className="text-xs text-muted-foreground">
                {byAgent[agent].length} file{byAgent[agent].length === 1 ? "" : "s"}
              </div>
            </div>
            <Card className="glass overflow-hidden">
              <div className="divide-y divide-border">
                {byAgent[agent].map((artifact) => (
                  <button
                    key={artifact.path}
                    onClick={() => openArtifact(artifact)}
                    className="w-full flex items-center gap-4 p-4 hover:bg-accent/50 transition-colors text-left"
                  >
                    <FileText className={`h-4 w-4 ${agentAccent(agent)}`} />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-sm truncate">{artifact.name}</div>
                      <div className="text-xs text-muted-foreground font-mono">
                        {artifact.date} · {formatSize(artifact.size_bytes)}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </Card>
          </motion.div>
        ))}
      </div>

      <Dialog open={open !== null} onOpenChange={(o) => !o && setOpen(null)}>
        <DialogContent className="max-w-4xl max-h-[85vh]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-3">
              <span className={agentAccent(open?.agent ?? "uncategorized")}>
                {open ? agentLabel(open.agent) : ""}
              </span>
              <span className="font-mono text-sm text-muted-foreground">
                {open?.name}
              </span>
              {open && (
                <a
                  href={`/api/artifacts/${open.date}/${open.name}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ml-auto text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
                  onClick={(e) => e.stopPropagation()}
                >
                  <ExternalLink className="h-3 w-3" /> raw
                </a>
              )}
            </DialogTitle>
          </DialogHeader>
          <ScrollArea className="h-[70vh] pr-4">
            {contentLoading ? (
              <div className="text-muted-foreground p-4">Loading…</div>
            ) : (
              <article className="prose prose-invert prose-sm max-w-none">
                <ReactMarkdown>{content}</ReactMarkdown>
              </article>
            )}
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  );
}
