"use client";

import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Terminal, Trash2, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Navbar } from "@/components/navbar";

interface LogSource {
  name: string;
  path: string;
  exists: boolean;
  size_bytes: number;
}

export default function TerminalPage() {
  const [sources, setSources] = useState<LogSource[]>([]);
  const [selected, setSelected] = useState<string>("api");
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const autoScroll = useRef(true);

  useEffect(() => {
    fetch("/api/logs/sources")
      .then((r) => r.json())
      .then(setSources)
      .catch(() => setSources([]));
  }, []);

  useEffect(() => {
    setLines([]);
    const source = new EventSource(`/api/logs/stream/${selected}`);
    setConnected(false);

    source.addEventListener("log", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data);
        setLines((prev) => {
          const next = [...prev, data.line];
          return next.length > 2000 ? next.slice(-2000) : next;
        });
        setConnected(true);
      } catch {}
    });

    source.onerror = () => setConnected(false);

    return () => source.close();
  }, [selected]);

  useEffect(() => {
    if (autoScroll.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [lines]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    autoScroll.current = scrollTop + clientHeight >= scrollHeight - 50;
  };

  const colorize = (line: string) => {
    if (/ERROR|FATAL|CRITICAL/i.test(line)) return "text-red-400";
    if (/WARN/i.test(line)) return "text-yellow-400";
    if (/INFO/i.test(line)) return "text-blue-400";
    if (/DEBUG/i.test(line)) return "text-muted-foreground";
    if (/✓|success|ok/i.test(line)) return "text-green-400";
    return "text-foreground";
  };

  const clear = () => setLines([]);
  const download = () => {
    const blob = new Blob([lines.join("\n")], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selected}-${new Date().toISOString()}.log`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6 flex items-center justify-between flex-wrap gap-4"
      >
        <div>
          <h2 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <Terminal className="h-8 w-8" />
            Terminal
          </h2>
          <p className="text-muted-foreground mt-1">Live log streams from all services</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-2 text-xs">
            <div className={`h-2 w-2 rounded-full ${connected ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
            {connected ? "live" : "disconnected"}
          </div>
          <Button variant="outline" size="sm" onClick={clear}>
            <Trash2 className="h-4 w-4 mr-2" />
            Clear
          </Button>
          <Button variant="outline" size="sm" onClick={download}>
            <Download className="h-4 w-4 mr-2" />
            Download
          </Button>
        </div>
      </motion.div>

      {/* Source selector */}
      <div className="mb-4 flex items-center gap-2 flex-wrap">
        {sources.map((source) => (
          <button
            key={source.name}
            onClick={() => setSelected(source.name)}
            disabled={!source.exists}
            className={`px-3 py-1.5 rounded-full text-sm transition-colors flex items-center gap-2 ${
              selected === source.name
                ? "bg-primary text-primary-foreground"
                : source.exists
                ? "glass text-muted-foreground hover:text-foreground"
                : "glass text-muted-foreground/40 cursor-not-allowed"
            }`}
          >
            <span className="font-mono text-xs">{source.name}</span>
            {source.exists ? (
              <span className="text-xs opacity-60">
                {source.size_bytes > 1024 * 1024
                  ? `${(source.size_bytes / 1024 / 1024).toFixed(1)}M`
                  : `${(source.size_bytes / 1024).toFixed(0)}k`}
              </span>
            ) : (
              <span className="text-xs opacity-60">missing</span>
            )}
          </button>
        ))}
      </div>

      <Card className="glass overflow-hidden">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="bg-black/60 p-4 font-mono text-xs overflow-y-auto"
          style={{ height: "calc(100vh - 300px)" }}
        >
          {lines.length === 0 && (
            <div className="text-muted-foreground text-center py-8">
              Connecting to {selected}...
            </div>
          )}
          {lines.map((line, i) => (
            <div key={i} className={`whitespace-pre-wrap break-all leading-5 ${colorize(line)}`}>
              {line || "\u00A0"}
            </div>
          ))}
        </div>
      </Card>
    </main>
  );
}
