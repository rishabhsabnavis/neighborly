"use client";

import dynamic from "next/dynamic";

import { useConsole } from "@/components/raw/ConsoleApp";

const CountyMap = dynamic(() => import("@/components/map/CountyMap"), {
  ssr: false,
  loading: () => <p className="p-6 text-zinc-500">Loading map...</p>,
});

export default function MapPage() {
  const { rows, selectedId, select } = useConsole();
  return (
    <CountyMap
      rows={rows}
      selectedId={selectedId}
      onSelect={(id) => select(id)}
    />
  );
}
