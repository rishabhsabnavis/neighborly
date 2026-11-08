import { ChevronRight } from "lucide-react";

import { RiskChip } from "@/components/raw/RiskChip";
import { clock, contactLine, policyLabel, street } from "@/lib/display";
import type { PolicyholderRow } from "@/lib/types";

export function DashboardTable({
  rows,
  selectedId,
  onSelect,
  emptyText,
}: {
  rows: PolicyholderRow[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  emptyText?: string;
}) {
  return (
    <div className="h-full overflow-auto bg-white">
      <table className="w-full min-w-[960px] border-collapse text-[15px]">
        <thead className="sticky top-0 z-10 bg-white text-left text-[12px] font-medium uppercase tracking-wide text-zinc-500">
          <tr className="border-b border-zinc-200">
            <th className="px-6 py-3 font-medium">Timestamp</th>
            <th className="px-3 py-3 font-medium">Name</th>
            <th className="px-3 py-3 font-medium">Risk level</th>
            <th className="px-3 py-3 font-medium">Situation</th>
            <th className="px-3 py-3 font-medium">Location</th>
            <th className="px-3 py-3 font-medium">Policy type</th>
            <th className="w-10 px-3 py-3 font-medium">
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={7} className="px-6 py-16 text-center text-zinc-500">
                {emptyText ?? "No policyholders match this search or filter."}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const place = street(row.address);
              const selected = row.id === selectedId;
              return (
                <tr
                  key={row.id}
                  tabIndex={0}
                  aria-selected={selected}
                  className={`cursor-pointer border-b border-zinc-100 ${selected ? "bg-zinc-100" : "hover:bg-zinc-50"}`}
                  onClick={() => onSelect(row.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(row.id);
                    }
                  }}
                >
                  <td className="whitespace-nowrap px-6 py-4 text-zinc-700">{clock(row.last_contact_at)}</td>
                  <td className="px-3 py-4">
                    <p className="font-semibold text-zinc-900">{row.name}</p>
                    <p className="text-[13px] text-zinc-500">
                      {row.human_requested ? "Asked for a person" : row.phone_masked}
                    </p>
                  </td>
                  <td className="px-3 py-4">
                    <RiskChip row={row} />
                  </td>
                  <td className="max-w-[360px] px-3 py-4">
                    <p className="truncate text-zinc-900">{row.summary || "No details yet"}</p>
                    <p className="text-[13px] text-zinc-500">{contactLine(row)}</p>
                  </td>
                  <td className="px-3 py-4">
                    <p className="text-zinc-900">{row.county} County</p>
                    {place ? <p className="max-w-[220px] truncate text-[13px] text-zinc-500">{place}</p> : null}
                  </td>
                  <td className="whitespace-nowrap px-3 py-4 text-zinc-800">{policyLabel(row.policy_type)}</td>
                  <td className="px-3 py-4 text-zinc-400">
                    <ChevronRight className="h-4 w-4" aria-hidden />
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
