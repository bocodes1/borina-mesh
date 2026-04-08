"use client";

import { useEffect } from "react";
import { toast } from "sonner";
import { subscribeToActivity } from "@/lib/activity";

export function ToastListener() {
  useEffect(() => {
    const unsubscribe = subscribeToActivity((event) => {
      if (event.kind === "completed") {
        toast.success(event.message, {
          description: `${event.agent_id} · ${new Date(event.timestamp).toLocaleTimeString()}`,
        });
      } else if (event.kind === "failed") {
        toast.error(event.message, {
          description: `${event.agent_id} · ${new Date(event.timestamp).toLocaleTimeString()}`,
        });
      }
    });
    return unsubscribe;
  }, []);

  return null;
}
