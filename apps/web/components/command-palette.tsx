"use client";

import { useEffect, useState } from "react";
import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { LayoutGrid, Network, BarChart3, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Agent } from "@/lib/types";

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [agents, setAgents] = useState<Agent[]>([]);
  const router = useRouter();

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  useEffect(() => {
    if (open && agents.length === 0) {
      api.listAgents().then(setAgents).catch(() => {});
    }
  }, [open, agents.length]);

  const runCommand = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  return (
    <>
      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Command palette"
        className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] bg-black/60 backdrop-blur-sm"
      >
        <div className="w-full max-w-lg rounded-xl border bg-popover text-popover-foreground shadow-2xl">
          <div className="flex items-center border-b px-4">
            <Search className="h-4 w-4 text-muted-foreground mr-2" />
            <Command.Input
              placeholder="Search agents and pages..."
              className="flex h-12 w-full bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground"
            />
          </div>
          <Command.List className="max-h-[400px] overflow-y-auto p-2">
            <Command.Empty className="py-6 text-center text-sm text-muted-foreground">
              No results.
            </Command.Empty>
            <Command.Group heading="Pages" className="text-xs font-medium text-muted-foreground px-2 py-1">
              <Command.Item
                onSelect={() => runCommand(() => router.push("/"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <LayoutGrid className="h-4 w-4" />
                Mesh
              </Command.Item>
              <Command.Item
                onSelect={() => runCommand(() => router.push("/network"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <Network className="h-4 w-4" />
                Network
              </Command.Item>
              <Command.Item
                onSelect={() => runCommand(() => router.push("/analytics"))}
                className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
              >
                <BarChart3 className="h-4 w-4" />
                Analytics
              </Command.Item>
            </Command.Group>
            {agents.length > 0 && (
              <Command.Group heading="Agents" className="text-xs font-medium text-muted-foreground px-2 py-1 mt-2">
                {agents.map((agent) => (
                  <Command.Item
                    key={agent.id}
                    onSelect={() => runCommand(() => router.push(`/?agent=${agent.id}`))}
                    className="flex items-center gap-2 rounded-md px-2 py-2 text-sm cursor-pointer aria-selected:bg-accent"
                  >
                    <span className="text-base">{agent.emoji}</span>
                    <span>{agent.name}</span>
                    <span className="text-xs text-muted-foreground ml-auto">{agent.tagline}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
          <div className="border-t px-3 py-2 text-xs text-muted-foreground flex items-center justify-between">
            <span>
              Press <kbd className="rounded border px-1 font-mono">↵</kbd> to select
            </span>
            <span>
              <kbd className="rounded border px-1 font-mono">ESC</kbd> to close
            </span>
          </div>
        </div>
      </Command.Dialog>
    </>
  );
}
