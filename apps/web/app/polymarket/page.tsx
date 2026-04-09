"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { ExternalLink, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Navbar } from "@/components/navbar";

const DEFAULT_URL = "http://localhost:8080";

export default function PolymarketPage() {
  const [url, setUrl] = useState(DEFAULT_URL);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <main className="container mx-auto px-4 py-6 max-w-7xl">
      <Navbar />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-6 flex items-center justify-between flex-wrap gap-4"
      >
        <div>
          <h2 className="text-3xl font-bold tracking-tight">Polymarket Bot</h2>
          <p className="text-muted-foreground mt-1">Live trading bot dashboard — embedded view</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setRefreshKey((k) => k + 1)}>
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
          <Button variant="outline" size="sm" asChild>
            <a href={url} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="h-4 w-4 mr-2" />
              Open in new tab
            </a>
          </Button>
        </div>
      </motion.div>

      <Card className="glass overflow-hidden" style={{ height: "calc(100vh - 220px)" }}>
        <iframe
          key={refreshKey}
          src={url}
          className="w-full h-full border-0"
          title="Polymarket Bot Dashboard"
          sandbox="allow-same-origin allow-scripts allow-popups allow-forms"
        />
      </Card>

      <p className="mt-4 text-xs text-muted-foreground">
        If the embed fails to load, the Polymarket bot dashboard may not be running on port 8080.
        Click "Open in new tab" to access it directly.
      </p>
    </main>
  );
}
