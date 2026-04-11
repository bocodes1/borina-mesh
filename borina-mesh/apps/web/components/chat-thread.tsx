"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatMessage } from "@/lib/types";

interface ChatThreadProps {
  agentId: string;
}

export function ChatThread({ agentId }: ChatThreadProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getThread(agentId).then(setMessages).catch(() => {});
  }, [agentId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleClear = async () => {
    await api.clearThread(agentId);
    setMessages([]);
  };

  if (messages.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-8">
        No conversation history yet.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs text-muted-foreground">
          {messages.length} messages
        </span>
        <button
          onClick={handleClear}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          Clear
        </button>
      </div>
      <div className="space-y-3 overflow-y-auto">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`text-sm rounded-lg px-3 py-2 ${
              msg.role === "user"
                ? "bg-primary/10 ml-8"
                : "bg-muted mr-8"
            }`}
          >
            <div className="text-xs text-muted-foreground mb-1">
              {msg.role === "user" ? "You" : agentId} ·{" "}
              {new Date(msg.created_at).toLocaleTimeString()}
            </div>
            <div className="whitespace-pre-wrap">{msg.content}</div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
