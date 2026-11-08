import { chipFor } from "@/lib/display";
import type { PolicyholderRow } from "@/lib/types";

export function RiskChip({
  row,
}: {
  row: Pick<PolicyholderRow, "urgency" | "status" | "human_requested">;
}) {
  const chip = chipFor(row);
  return (
    <span
      className="inline-flex shrink-0 items-center rounded px-2 py-0.5 text-[13px] font-semibold leading-5"
      style={{ backgroundColor: chip.bg, color: chip.fg }}
    >
      {chip.label}
    </span>
  );
}
