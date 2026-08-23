"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { api, type DailyBriefResponse } from "@/lib/api";
import { useAsync } from "@/lib/use-async";
import { Navbar } from "@/components/navbar";
import { MarkdownOutput } from "@/components/markdown-output";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { SkeletonCard } from "@/components/ui/loading-skeleton";

export default function DailyBriefPage() {
  const { data, loading, error, reload } = useAsync<DailyBriefResponse>(() => api.getDailyBrief(), []);

  return (
    <main className="container mx-auto max-w-3xl px-4 py-6">
      <Navbar />
      <Link
        href="/daily"
        className="mt-4 mb-2 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> Back to Today
      </Link>
      {loading ? (
        <SkeletonCard />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !data?.exists ? (
        <EmptyState title="No brief yet today" description="It's generated every morning at 6am ET." />
      ) : (
        <div className="surface-card rounded-2xl p-6">
          <p className="mb-4 text-xs uppercase tracking-wide text-muted-foreground">{data.date}</p>
          <MarkdownOutput content={data.raw ?? ""} />
        </div>
      )}
    </main>
  );
}
