"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Clock, CheckCircle2, XCircle, Loader2, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { Job, AgentRun } from "@/lib/types";

interface JobDetailModalProps {
  job: Job | null;
  agentName?: string;
  agentEmoji?: string;
  onClose: () => void;
}

const STATUS_ICONS: Record<Job["status"], React.ReactNode> = {
  pending: <Clock className="h-4 w-4 text-muted-foreground" />,
  running: <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />,
  completed: <CheckCircle2 className="h-4 w-4 text-green-400" />,
  failed: <XCircle className="h-4 w-4 text-red-400" />,
  cancelled: <XCircle className="h-4 w-4 text-muted-foreground" />,
};

export function JobDetailModal({ job, agentName, agentEmoji, onClose }: JobDetailModalProps) {
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!job) return;
    setLoading(true);
    api
      .getJobRuns(job.id)
      .then((data) => {
        setRuns(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [job]);

  if (!job) return null;

  const formatDuration = () => {
    if (!job.started_at || !job.completed_at) return "—";
    const start = new Date(job.started_at).getTime();
    const end = new Date(job.completed_at).getTime();
    const ms = end - start;
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
  };

  const copyOutput = () => {
    const full = runs.map((r) => r.output).join("\n\n---\n\n");
    navigator.clipboard.writeText(full);
    toast.success("Output copied to clipboard");
  };

  return (
    <Dialog open={!!job} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl max-h-[85vh] p-0">
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-border">
          <DialogTitle className="flex items-center gap-3">
            <span className="text-3xl">{agentEmoji ?? "🤖"}</span>
            <div className="flex-1">
              <div className="text-xl font-semibold">{agentName ?? job.agent_id}</div>
              <div className="text-xs text-muted-foreground font-mono mt-0.5">Job #{job.id}</div>
            </div>
            <div className="flex items-center gap-2">
              {STATUS_ICONS[job.status]}
              <Badge
                variant={
                  job.status === "completed"
                    ? "success"
                    : job.status === "failed"
                    ? "destructive"
                    : "secondary"
                }
              >
                {job.status}
              </Badge>
            </div>
          </DialogTitle>
        </DialogHeader>

        {/* Metadata strip */}
        <div className="px-6 py-3 bg-muted/30 border-b border-border text-xs font-mono grid grid-cols-3 gap-4">
          <div>
            <div className="text-muted-foreground">created</div>
            <div>{new Date(job.created_at).toLocaleString()}</div>
          </div>
          <div>
            <div className="text-muted-foreground">duration</div>
            <div>{formatDuration()}</div>
          </div>
          <div className="flex items-end justify-end gap-2">
            <Button variant="outline" size="sm" onClick={copyOutput}>
              <Copy className="h-3.5 w-3.5 mr-1.5" /> Copy
            </Button>
          </div>
        </div>

        {/* Prompt */}
        <div className="px-6 py-4 border-b border-border">
          <div className="text-xs font-medium text-muted-foreground mb-2">PROMPT</div>
          <div className="text-sm whitespace-pre-wrap">{job.prompt}</div>
        </div>

        {/* Error (if any) */}
        {job.error && (
          <div className="px-6 py-4 border-b border-border bg-destructive/10">
            <div className="text-xs font-medium text-destructive mb-2">ERROR</div>
            <div className="text-sm whitespace-pre-wrap text-destructive/90 font-mono">{job.error}</div>
          </div>
        )}

        {/* Output */}
        <ScrollArea className="flex-1 max-h-[45vh]">
          <div className="px-6 py-4">
            <div className="text-xs font-medium text-muted-foreground mb-2">OUTPUT</div>
            {loading && <div className="text-sm text-muted-foreground">Loading...</div>}
            {!loading && runs.length === 0 && (
              <div className="text-sm text-muted-foreground italic">No output recorded.</div>
            )}
            {!loading &&
              runs.map((run) => (
                <motion.div
                  key={run.id}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-sm whitespace-pre-wrap font-mono leading-relaxed"
                >
                  {run.output}
                </motion.div>
              ))}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
