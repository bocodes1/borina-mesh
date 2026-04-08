"use client";

import { useState, useEffect } from "react";
import cronstrue from "cronstrue";
import { Clock, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { toast } from "sonner";
import type { Agent } from "@/lib/types";

interface ScheduleEditorProps {
  agent: Agent;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const PRESETS = [
  { label: "Every day at 8 AM", cron: "0 8 * * *" },
  { label: "Every 30 minutes", cron: "*/30 * * * *" },
  { label: "Weekdays at 9 AM", cron: "0 9 * * 1-5" },
  { label: "Sundays at 10 AM", cron: "0 10 * * 0" },
  { label: "Every hour", cron: "0 * * * *" },
];

export function ScheduleEditor({ agent, open, onOpenChange }: ScheduleEditorProps) {
  const [cron, setCron] = useState("");
  const [humanDesc, setHumanDesc] = useState("");
  const [isValid, setIsValid] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      api.listSchedules().then((schedules) => {
        setCron(schedules[agent.id] || "");
      });
    }
  }, [open, agent.id]);

  useEffect(() => {
    if (!cron.trim()) {
      setHumanDesc("");
      setIsValid(false);
      return;
    }
    try {
      setHumanDesc(cronstrue.toString(cron));
      setIsValid(true);
    } catch {
      setHumanDesc("Invalid cron expression");
      setIsValid(false);
    }
  }, [cron]);

  const handleSave = async () => {
    if (!isValid) return;
    setSaving(true);
    try {
      await api.setSchedule(agent.id, cron);
      toast.success(`Schedule saved for ${agent.name}`);
      onOpenChange(false);
    } catch (err) {
      toast.error(`Failed to save: ${err instanceof Error ? err.message : "unknown"}`);
    } finally {
      setSaving(false);
    }
  };

  const handleRemove = async () => {
    setSaving(true);
    try {
      await api.removeSchedule(agent.id);
      toast.success(`Schedule removed for ${agent.name}`);
      setCron("");
      onOpenChange(false);
    } catch (err) {
      toast.error(`Failed to remove: ${err instanceof Error ? err.message : "unknown"}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" /> Schedule — {agent.name}
          </DialogTitle>
          <DialogDescription>
            Set a cron expression to run {agent.name} automatically on a schedule.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <label className="text-sm font-medium mb-2 block">Cron expression</label>
            <Input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              placeholder="0 8 * * *"
              className="font-mono"
            />
            <div className={`mt-2 text-xs ${isValid ? "text-muted-foreground" : "text-destructive"}`}>
              {humanDesc || "Enter a cron expression (minute hour day month weekday)"}
            </div>
          </div>

          <div>
            <div className="text-sm font-medium mb-2">Presets</div>
            <div className="grid grid-cols-1 gap-2">
              {PRESETS.map((preset) => (
                <button
                  key={preset.cron}
                  type="button"
                  onClick={() => setCron(preset.cron)}
                  className="flex items-center justify-between text-left px-3 py-2 rounded-md border border-border hover:bg-accent text-sm"
                >
                  <span>{preset.label}</span>
                  <code className="text-xs text-muted-foreground font-mono">{preset.cron}</code>
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2 pt-2">
            <Button onClick={handleSave} disabled={!isValid || saving} className="flex-1">
              <Save className="h-4 w-4 mr-2" /> Save
            </Button>
            <Button variant="destructive" onClick={handleRemove} disabled={saving}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
