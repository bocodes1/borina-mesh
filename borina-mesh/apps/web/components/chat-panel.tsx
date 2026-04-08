"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { streamChat } from "@/lib/sse";
import type { Agent } from "@/lib/types";

interface Message {
  role: "user" | "agent";
  content: string;
}

interface ChatPanelProps {
  agent: Agent | null;
  onClose: () => void;
}

export function ChatPanel({ agent, onClose }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    // Reset when agent changes
    setMessages([]);
    setInput("");
  }, [agent?.id]);

  const handleSend = async () => {
    if (!agent || !input.trim() || streaming) return;

    const userMessage = input.trim();
    setMessages((m) => [...m, { role: "user", content: userMessage }, { role: "agent", content: "" }]);
    setInput("");
    setStreaming(true);

    try {
      await streamChat(agent.id, userMessage, (chunk) => {
        if (chunk.type === "text") {
          setMessages((m) => {
            const updated = [...m];
            const last = updated[updated.length - 1];
            if (last?.role === "agent") {
              updated[updated.length - 1] = { role: "agent", content: last.content + chunk.content };
            }
            return updated;
          });
        }
      });
    } catch (err) {
      setMessages((m) => {
        const updated = [...m];
        updated[updated.length - 1] = {
          role: "agent",
          content: `Error: ${err instanceof Error ? err.message : "unknown"}`,
        };
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <AnimatePresence>
      {agent && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-40"
          />
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 30, stiffness: 300 }}
            className="fixed right-0 top-0 bottom-0 w-full md:w-[600px] bg-card border-l border-border z-50 flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-border">
              <div className="flex items-center gap-4">
                <div className="text-4xl">{agent.emoji}</div>
                <div>
                  <div className="font-semibold text-lg">{agent.name}</div>
                  <div className="text-sm text-muted-foreground">{agent.tagline}</div>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={onClose}>
                <X className="h-5 w-5" />
              </Button>
            </div>

            {/* Messages */}
            <ScrollArea className="flex-1 px-6 py-4">
              <div ref={scrollRef} className="space-y-4">
                {messages.length === 0 && (
                  <div className="text-center text-muted-foreground mt-12">
                    <div className="text-6xl mb-4">{agent.emoji}</div>
                    <p>Start a conversation with {agent.name}</p>
                  </div>
                )}
                {messages.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[85%] rounded-2xl px-4 py-3 ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted"
                      }`}
                    >
                      <div className="whitespace-pre-wrap text-sm">
                        {msg.content || (streaming && i === messages.length - 1 && <Loader2 className="h-4 w-4 animate-spin" />)}
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            </ScrollArea>

            {/* Input */}
            <div className="p-6 border-t border-border">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
                  placeholder={`Message ${agent.name}...`}
                  disabled={streaming}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                />
                <Button onClick={handleSend} disabled={streaming || !input.trim()}>
                  {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
