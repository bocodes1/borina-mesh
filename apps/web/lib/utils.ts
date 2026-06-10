import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Human label for a job/agent task prompt: drops the [scheduled] tag and the
 *  machine timestamp suffix ("Current time: 677454.631" / "Now: 2026-…Z"). */
export function cleanTaskLabel(prompt?: string | null): string {
  if (!prompt) return "";
  return prompt
    .replace(/^\[scheduled\]\s*/i, "")
    .replace(/\s*\bCurrent time:\s*[\d.]+\s*$/i, "")
    .replace(/\s*\bNow:\s*[\d:.TZ+-]+\s*$/i, "")
    .trim();
}

export function isScheduledPrompt(prompt?: string | null): boolean {
  return /^\[scheduled\]/i.test(prompt ?? "");
}
