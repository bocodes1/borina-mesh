"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, AlertCircle, Play, Clock, Zap } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Card } from "@/components/ui/card";
import { subscribeToActivity, type ActivityEvent } from "@/lib/activity";

const KIND_ICONS: Record<ActivityEvent["kind"], React.ReactNode> = {
  started: <Play className="h-4 w-4 text-blue-400" />,
  streaming: <Zap className="h-4 w-4 text-yellow-400" />,
  completed: <CheckCircle2 className="h-4 w-4 text-green-400" />,
  failed: <AlertCircle className="h-4 w-4 text-red-400" />,
  scheduled: <Clock className="h-4 w-4 text-purple-400" />,
};

export function ActivityFeed() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);

  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      setEvents((prev) => [event, ...prev].slice(0, 50));
    });
    return unsubscribe;
  }, []);

  return (
    <Card className="glass">
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-sm">Activity Feed</h3>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <div className="h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
            live
          </div>
        </div>
      </div>
      <ScrollArea className="h-[400px]">
        <div className="p-4 space-y-2">
          {events.length === 0 && (
            <div className="text-sm text-muted-foreground text-center py-8">
              No activity yet. Message an agent to see events stream in.
            </div>
          )}
          <AnimatePresence initial={false}>
            {events.map((event, i) => (
              <motion.div
                key={`${event.timestamp}-${i}`}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.25 }}
                className="flex items-start gap-3 py-2 border-b border-border/50 last:border-0"
              >
                <div className="mt-0.5">{KIND_ICONS[event.kind]}</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{event.message}</div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    <span className="font-mono">{event.agent_id}</span>
                    {" · "}
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </ScrollArea>
    </Card>
  );
}
