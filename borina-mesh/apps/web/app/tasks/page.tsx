"use client";

import { TaskBoard } from "@/components/task-board";

export default function TasksPage() {
  return (
    <main className="container mx-auto px-4 py-4 md:py-6 max-w-7xl">
      <h1 className="text-xl font-semibold mb-4">Task Board</h1>
      <TaskBoard />
    </main>
  );
}
