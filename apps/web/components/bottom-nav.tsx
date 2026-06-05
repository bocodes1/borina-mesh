"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MoreHorizontal, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { PRIMARY_LINKS, SECONDARY_LINKS } from "./nav-config";

/**
 * Mobile-only bottom tab bar (app feel). 4 primary tabs + a "More" sheet for
 * the rest. Hidden on >= sm (desktop uses the top pill nav). Uses safe-area
 * inset so it clears the iPhone home indicator.
 */
export function BottomNav() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const moreActive = SECONDARY_LINKS.some((l) => l.href === pathname);

  return (
    <>
      {moreOpen ? (
        <div
          className="fixed inset-0 z-40 bg-black/60 sm:hidden"
          onClick={() => setMoreOpen(false)}
          role="presentation"
        >
          <div
            className="absolute inset-x-0 bottom-0 rounded-t-3xl border-t border-border bg-surface p-4 pb-[calc(1rem+env(safe-area-inset-bottom))]"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="More tabs"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold">More</span>
              <button onClick={() => setMoreOpen(false)} aria-label="close" className="text-muted-foreground">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {SECONDARY_LINKS.map(({ href, label, icon: Icon }) => {
                const active = pathname === href;
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setMoreOpen(false)}
                    className={cn(
                      "flex flex-col items-center gap-1 rounded-2xl border border-border/50 px-2 py-3 text-xs",
                      active ? "bg-brand/15 text-brand" : "bg-surface-2 text-muted-foreground",
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    {label}
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}

      <nav
        className="fixed inset-x-0 bottom-0 z-30 flex items-stretch border-t border-border bg-surface/95 backdrop-blur pb-[env(safe-area-inset-bottom)] sm:hidden"
        aria-label="Primary"
      >
        {PRIMARY_LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium",
                active ? "text-brand" : "text-muted-foreground",
              )}
            >
              <Icon className="h-5 w-5" />
              {label}
            </Link>
          );
        })}
        <button
          onClick={() => setMoreOpen(true)}
          className={cn(
            "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium",
            moreActive ? "text-brand" : "text-muted-foreground",
          )}
          aria-label="More tabs"
        >
          <MoreHorizontal className="h-5 w-5" />
          More
        </button>
      </nav>
    </>
  );
}
