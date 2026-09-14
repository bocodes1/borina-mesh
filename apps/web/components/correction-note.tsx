"use client";

import { useState } from "react";
import { MessageSquarePlus } from "lucide-react";
import { api } from "@/lib/api";

/** A direct, explicit note to the nightly learner (Phase D2) — distinct from
 * ambient Telegram chat, which is inferred; this is Bo telling the profile
 * something on purpose (e.g. correcting a wrong inference, flagging what
 * actually mattered today). */
export function CorrectionNote() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function send() {
    if (!text.trim()) return;
    setBusy(true);
    try {
      await api.addCorrection(text.trim());
      setText("");
      setSent(true);
      setTimeout(() => setSent(false), 2500);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="surface-card rounded-2xl p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-medium text-foreground">
        <MessageSquarePlus className="h-4 w-4" /> Tell the profile something
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        A direct note for tonight&apos;s profile update — not inferred, straight from you.
      </p>
      <div className="flex gap-2">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="e.g. the launch actually slipped to Friday…"
          aria-label="correction note"
          className="flex-1 rounded-xl border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={send}
          disabled={busy || !text.trim()}
          className="rounded-xl bg-brand px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {sent ? "Saved" : "Send"}
        </button>
      </div>
    </div>
  );
}
