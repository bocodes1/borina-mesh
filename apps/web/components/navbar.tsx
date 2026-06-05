"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { NAV_LINKS } from "./nav-config";

export function Navbar() {
  const pathname = usePathname();

  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6 flex items-center justify-between gap-4"
    >
      <Link href="/" className="flex items-center gap-2">
        <span className="text-xl font-bold tracking-tight">Borina</span>
      </Link>

      {/* Desktop tab pill — hidden on mobile (mobile uses the bottom nav). */}
      <div className="hidden items-center gap-1 glass rounded-full p-1 sm:flex">
        {NAV_LINKS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap md:px-4",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden md:inline">{label}</span>
            </Link>
          );
        })}
      </div>
    </motion.nav>
  );
}
