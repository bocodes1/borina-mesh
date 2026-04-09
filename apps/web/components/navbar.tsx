"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";
import { LayoutGrid, Network, BarChart3, FileText, ListTodo, TrendingUp, Terminal } from "lucide-react";
import { cn } from "@/lib/utils";

const links = [
  { href: "/", label: "Mesh", icon: LayoutGrid },
  { href: "/network", label: "Network", icon: Network },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/jobs", label: "Jobs", icon: ListTodo },
  { href: "/artifacts", label: "Files", icon: FileText },
  { href: "/polymarket", label: "Polymarket", icon: TrendingUp },
  { href: "/terminal", label: "Terminal", icon: Terminal },
];

export function Navbar() {
  const pathname = usePathname();

  return (
    <motion.nav
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-6 flex items-center justify-between flex-wrap gap-4"
    >
      <Link href="/" className="flex items-center gap-3">
        <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-purple-400 shadow-lg" />
        <span className="text-xl font-bold tracking-tight">
          Borina
        </span>
      </Link>

      <div className="flex items-center gap-1 glass rounded-full p-1 overflow-x-auto max-w-full">
        {links.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-2 px-3 md:px-4 py-1.5 rounded-full text-sm font-medium transition-colors whitespace-nowrap",
                active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden sm:inline">{label}</span>
            </Link>
          );
        })}
      </div>
    </motion.nav>
  );
}
