"use client";

import { FilesBrowser } from "@/components/files-browser";
import { Navbar } from "@/components/navbar";

export default function ArtifactsPage() {
  return (
    <main className="container mx-auto max-w-7xl px-4 py-6">
      <Navbar />
      <FilesBrowser />
    </main>
  );
}
