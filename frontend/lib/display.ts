import type { PolicyholderRow, PolicyType, Status, Urgency } from "@/lib/types";

export type RiskKey = "critical" | "high" | "moderate" | "safe" | "none";
export type SortMode = "priority" | "latest" | "earliest";

export const RISK_ORDER: RiskKey[] = ["critical", "high", "moderate", "safe", "none"];

export const RISK_STYLE: Record<RiskKey, { label: string; bg: string; fg: string }> = {
  critical: { label: "Critical", bg: "#D92D20", fg: "#FFFFFF" },
  high: { label: "High", bg: "#F79009", fg: "#FFFFFF" },
  moderate: { label: "Moderate", bg: "#EAB308", fg: "#1D2939" },
  safe: { label: "Safe", bg: "#12B76A", fg: "#FFFFFF" },
  none: { label: "No reply", bg: "#E4E7EC", fg: "#344054" },
};

const EMPTY_RISKS: Record<RiskKey, boolean> = {
  critical: true,
  high: true,
  moderate: true,
  safe: true,
  none: true,
};

export function defaultRisks(): Record<RiskKey, boolean> {
  return { ...EMPTY_RISKS };
}

export function riskKey(urgency: Urgency | null): RiskKey {
  if (urgency === 4) return "critical";
  if (urgency === 3) return "high";
  if (urgency === 2) return "moderate";
  if (urgency === 1) return "safe";
  return "none";
}

export function pinColor(urgency: Urgency | null): string {
  return RISK_STYLE[riskKey(urgency)].bg;
}

export function chipFor(row: { urgency: Urgency | null; status: Status }): { label: string; bg: string; fg: string } {
  if (row.urgency != null) {
    const style = RISK_STYLE[riskKey(row.urgency)];
    return { label: style.label, bg: style.bg, fg: style.fg };
  }
  if (row.status === "calling") return { label: "Calling", bg: "#175CD3", fg: "#FFFFFF" };
  if (row.status === "pending") return { label: "Pending", bg: "#E4E7EC", fg: "#344054" };
  return { label: "No reply", bg: "#E4E7EC", fg: "#344054" };
}

export function clock(iso: string | null | undefined): string {
  if (!iso) return "—";
  const match = /T(\d{2}:\d{2})/.exec(iso);
  return match ? match[1] : "—";
}

function ago(iso: string, now: number): string {
  const mins = Math.round((now - Date.parse(iso)) / 60000);
  if (!Number.isFinite(mins) || mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function lineFor(status: Status, rel: string | null): string {
  if (status === "pending") return "Not contacted yet";
  if (status === "texted") return rel ? `No reply, texted ${rel}` : "No reply yet";
  if (status === "calling") return rel ? `On a call, ${rel}` : "On a call";
  if (status === "unreachable") return rel ? `No answer, ${rel}` : "No answer";
  if (status === "called") return rel ? `Called ${rel}` : "Called";
  if (status === "safe") return rel ? `Responded ${rel}` : "Responded";
  return rel ? `Responded ${rel}` : "No response time";
}

export function contactLine(row: PolicyholderRow, now = Date.now()): string {
  const rel = row.last_contact_at ? ago(row.last_contact_at, now) : null;
  return lineFor(row.status, rel);
}

export function policyLabel(type: PolicyType | null | undefined): string {
  if (type === "homeowners") return "Homeowners";
  if (type === "renters") return "Renters";
  if (type === "auto") return "Auto";
  return "—";
}

export function street(address: string | null | undefined): string | null {
  if (!address) return null;
  const part = address.split(",")[0]?.trim();
  return part || null;
}

export function matchesQuery(row: PolicyholderRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return [row.name, row.county, row.address ?? "", row.claim_id ?? "", row.id]
    .join(" ")
    .toLowerCase()
    .includes(q);
}

export function filterRows(
  rows: PolicyholderRow[],
  query: string,
  risks: Record<RiskKey, boolean>,
  sort: SortMode,
): PolicyholderRow[] {
  const matched = rows.filter((row) => risks[riskKey(row.urgency)] && matchesQuery(row, query));
  if (sort === "priority") return matched;
  return [...matched].sort((a, b) => {
    const ta = a.last_contact_at ?? "";
    const tb = b.last_contact_at ?? "";
    if (!ta && !tb) return a.id.localeCompare(b.id);
    if (!ta) return 1;
    if (!tb) return -1;
    const order = ta.localeCompare(tb);
    return sort === "latest" ? -order : order;
  });
}
