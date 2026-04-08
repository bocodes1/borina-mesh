"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Zap, Clock, Server } from "lucide-react";

interface Stats {
  activeJobs: number;
  queuedJobs: number;
  todayRuns: number;
  uptime: string;
}

export function MissionControl() {
  const [stats, setStats] = useState<Stats>({
    activeJobs: 0,
    queuedJobs: 0,
    todayRuns: 0,
    uptime: "—",
  });
  const [currentTime, setCurrentTime] = useState("");

  useEffect(() => {
    const updateTime = () => {
      setCurrentTime(new Date().toLocaleTimeString("en-US", { hour12: false }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-xl px-6 py-4 mb-8 flex items-center justify-between flex-wrap gap-4"
    >
      <div className="flex items-center gap-6 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="relative">
            <div className="h-2 w-2 rounded-full bg-green-500" />
            <div className="absolute inset-0 h-2 w-2 rounded-full bg-green-500 animate-ping opacity-75" />
          </div>
          <span className="text-sm font-mono">system online</span>
        </div>
        <StatItem icon={<Activity className="h-4 w-4" />} label="active" value={stats.activeJobs} />
        <StatItem icon={<Clock className="h-4 w-4" />} label="queued" value={stats.queuedJobs} />
        <StatItem icon={<Zap className="h-4 w-4" />} label="today" value={stats.todayRuns} />
        <StatItem icon={<Server className="h-4 w-4" />} label="host" value="mac-mini" />
      </div>
      <div className="font-mono text-sm text-muted-foreground tabular-nums">{currentTime}</div>
    </motion.div>
  );
}

function StatItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-muted-foreground">{icon}</span>
      <span className="text-muted-foreground">{label}:</span>
      <span className="font-mono font-semibold tabular-nums">{value}</span>
    </div>
  );
}
