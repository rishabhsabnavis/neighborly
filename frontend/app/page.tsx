"use client";

import { DashboardTable } from "@/components/raw/DashboardTable";
import { useConsole } from "@/components/raw/ConsoleApp";

const OFFLINE_TEXT =
  "Can't reach the Neighborly backend. Retrying every 2 seconds...";

export default function HomePage() {
  const { rows, selectedId, select, offline } = useConsole();
  return (
    <DashboardTable
      rows={rows}
      selectedId={selectedId}
      onSelect={(id) => select(id)}
      emptyText={offline ? OFFLINE_TEXT : undefined}
    />
  );
}
