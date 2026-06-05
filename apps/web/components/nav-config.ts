import {
  LayoutGrid,
  Network,
  BarChart3,
  FileText,
  ListTodo,
  TrendingUp,
  LineChart,
  Sun,
  CalendarDays,
  type LucideIcon,
} from "lucide-react";

export interface NavLink {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown directly in the mobile bottom bar (vs. behind "More"). */
  primary?: boolean;
}

export const NAV_LINKS: NavLink[] = [
  { href: "/", label: "Mesh", icon: LayoutGrid, primary: true },
  { href: "/finance", label: "Finance", icon: LineChart, primary: true },
  { href: "/daily", label: "Daily", icon: Sun, primary: true },
  { href: "/calendar", label: "Calendar", icon: CalendarDays, primary: true },
  { href: "/network", label: "Network", icon: Network },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/jobs", label: "Jobs", icon: ListTodo },
  { href: "/artifacts", label: "Files", icon: FileText },
  { href: "/polymarket", label: "Polymarket", icon: TrendingUp },
];

export const PRIMARY_LINKS = NAV_LINKS.filter((l) => l.primary);
export const SECONDARY_LINKS = NAV_LINKS.filter((l) => !l.primary);
