"use client";

import { useEffect, useState } from "react";
import { api, streamJobLog } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "./status-dot";
import type { Job } from "@/lib/types";
import { Square, Trash2, Terminal } from "lucide-react";

export function OvernightWorkers() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLog, setSelectedLog] = useState<number | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);

  useEffect(() => {
    api.listJobs().then((all) => {
      setJobs(all.filter((j) => j.kind === "overnight_code"));
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    if (selectedLog === null) return;
    setLogLines([]);
    const close = streamJobLog(selectedLog, (line) => {
      setLogLines((prev) => [...prev, line]);
    });
    return close;
  }, [selectedLog]);

  if (loading) return <div className="animate-pulse h-32 rounded-xl bg-card/50" />;

  const statusMap: Record<string, "idle" | "running" | "qa_flagged" | "error"> = {
    pending: "idle",
    running: "running",
    completed: "idle",
    failed: "error",
    cancelled: "error",
  };

  return (
    <div className="space-y-4">
      {jobs.length === 0 ? (
        <Card className="glass">
          <CardContent className="p-6 text-center text-muted-foreground">
            No overnight jobs yet. Use <code>/handoff</code> from Claude Code to queue one.
          </CardContent>
        </Card>
      ) : (
        jobs.map((job) => (
          <Card key={job.id} className="glass">
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <StatusDot status={statusMap[job.status] ?? "idle"} />
                    <span className="font-semibold">Job #{job.id}</span>
                    <Badge variant="secondary" className="text-xs">{job.status}</Badge>
                    {job.qa_verdict && (
                      <Badge
                        variant={job.qa_verdict === "approve" ? "default" : "destructive"}
                        className="text-xs"
                      >
                        QA: {job.qa_verdict}
                      </Badge>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground line-clamp-2">{job.prompt}</p>
                  {job.worker_branch && (
                    <p className="text-xs text-muted-foreground mt-1 font-mono">{job.worker_branch}</p>
                  )}
                  {job.qa_notes && (
                    <p className="text-xs text-amber-600 mt-1">{job.qa_notes}</p>
                  )}
                </div>
                <div className="flex gap-1 ml-4">
                  {job.log_path && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setSelectedLog(selectedLog === job.id ? null : job.id)}
                    >
                      <Terminal className="h-4 w-4" />
                    </Button>
                  )}
                  {job.status === "running" && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => api.cancelJob(job.id)}
                    >
                      <Square className="h-4 w-4" />
                    </Button>
                  )}
                  {["completed", "failed", "cancelled"].includes(job.status) && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => api.cleanupJob(job.id)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </div>

              {selectedLog === job.id && (
                <div className="mt-3 bg-black/90 rounded-lg p-3 max-h-64 overflow-y-auto font-mono text-xs text-green-400">
                  {logLines.length === 0 ? (
                    <span className="text-muted-foreground">Waiting for log output...</span>
                  ) : (
                    logLines.map((line, i) => <div key={i}>{line}</div>)
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
