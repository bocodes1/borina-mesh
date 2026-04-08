"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { FileText, Download, File } from "lucide-react";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Artifact } from "@/lib/types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function iconForFile(name: string) {
  if (name.endsWith(".pdf")) return <FileText className="h-4 w-4 text-red-400" />;
  if (name.endsWith(".md")) return <FileText className="h-4 w-4 text-blue-400" />;
  if (name.endsWith(".json")) return <FileText className="h-4 w-4 text-yellow-400" />;
  return <File className="h-4 w-4 text-muted-foreground" />;
}

export function ArtifactList() {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .listArtifacts()
      .then((data) => {
        setArtifacts(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="text-muted-foreground">Loading artifacts...</div>;
  }

  // Group by date
  const byDate = artifacts.reduce<Record<string, Artifact[]>>((acc, a) => {
    acc[a.date] = acc[a.date] || [];
    acc[a.date].push(a);
    return acc;
  }, {});

  const dates = Object.keys(byDate).sort().reverse();

  if (dates.length === 0) {
    return (
      <Card className="glass p-8 text-center text-muted-foreground">
        No artifacts yet. Agents will save reports here.
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {dates.map((date, dateIdx) => (
        <motion.div
          key={date}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: dateIdx * 0.05 }}
        >
          <div className="text-sm font-medium text-muted-foreground mb-2 font-mono">{date}</div>
          <Card className="glass overflow-hidden">
            <div className="divide-y divide-border">
              {byDate[date].map((artifact) => (
                <a
                  key={artifact.path}
                  href={`/api/artifacts/${artifact.date}/${artifact.name}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-4 p-4 hover:bg-accent/50 transition-colors"
                >
                  {iconForFile(artifact.name)}
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{artifact.name}</div>
                    <div className="text-xs text-muted-foreground">{formatSize(artifact.size_bytes)}</div>
                  </div>
                  <Download className="h-4 w-4 text-muted-foreground" />
                </a>
              ))}
            </div>
          </Card>
        </motion.div>
      ))}
    </div>
  );
}
