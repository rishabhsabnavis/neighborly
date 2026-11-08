"use client";

import { DashboardTable } from "@/components/raw/DashboardTable";
import { useConsole } from "@/components/raw/ConsoleApp";

export default function HomePage() {
  const { rows, selectedId, select } = useConsole();
  return <DashboardTable rows={rows} selectedId={selectedId} onSelect={(id) => select(id)} />;
}
