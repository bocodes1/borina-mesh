"use client";

import { ArtifactList } from "@/components/artifact-list";
import { Navbar } from "@/components/navbar";

export default function ArtifactsPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <ArtifactList />
    </main>
  );
}
