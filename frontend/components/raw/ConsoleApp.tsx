"use client";

import { LayoutDashboard, Map as MapIcon, Shield, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { DetailPanel } from "@/components/raw/DetailPanel";
import { getDashboard, getSteps, resetDemo, runCheckin } from "@/lib/api";
import {
  defaultRisks,
  filterRows,
  RISK_ORDER,
  RISK_STYLE,
  type RiskKey,
  type SortMode,
} from "@/lib/display";
import type { PolicyholderRow, Step } from "@/lib/types";
import { usePoll } from "@/lib/usePoll";

type ConsoleValue = {
  rows: PolicyholderRow[];
  total: number;
  shown: number;
  disasterName: string;
  loading: boolean;
  reconnecting: boolean;
  /** True when the backend has never answered (no data yet and the last request failed). */
  offline: boolean;
  selectedId: string | null;
  select: (id: string | null) => void;
};

const ConsoleContext = createContext<ConsoleValue | null>(null);

export function useConsole() {
  const value = useContext(ConsoleContext);
  if (!value) throw new Error("useConsole must be used inside ConsoleApp");
  return value;
}

export function ConsoleApp({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const dashboard = usePoll(getDashboard, 2000);
  const [query, setQuery] = useState("");
  const [risks, setRisks] = useState(defaultRisks);
  const [sort, setSort] = useState<SortMode>("priority");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const since = useRef(0);

  usePoll(async () => {
    const page = await getSteps(since.current || undefined);
    if (page.steps.length === 0) return page;
    since.current = Math.max(since.current, page.steps[page.steps.length - 1].id);
    setSteps((current) => {
      const seen = new Set(current.map((step) => step.id));
      const added = page.steps.filter((step) => !seen.has(step.id));
      if (added.length === 0) return current;
      return [...current, ...added].slice(-200);
    });
    return page;
  }, 1500);

  useEffect(() => {
    if (!selectedId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  const all = dashboard.data?.policyholders ?? [];
  const rows = filterRows(all, query, risks, sort);
  const selected = all.find((row) => row.id === selectedId) ?? null;
  const latest = steps[steps.length - 1];

  const value: ConsoleValue = {
    rows,
    total: all.length,
    shown: rows.length,
    disasterName: dashboard.data?.disaster.name ?? "Loading incident...",
    loading: !dashboard.data,
    reconnecting: Boolean(dashboard.stale || dashboard.error),
    offline: Boolean(dashboard.error && !dashboard.data),
    selectedId,
    select: setSelectedId,
  };

  return (
    <ConsoleContext.Provider value={value}>
      <div className="flex h-screen min-w-[1100px] flex-col bg-[#F4F5F7] text-[15px] text-zinc-900">
        <header className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 border-b-2 border-[#D92D20] bg-white px-4 py-2.5">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2 font-semibold">
              <span className="grid h-8 w-8 place-items-center rounded-lg border border-zinc-200">
                <Shield className="h-4 w-4" aria-hidden />
              </span>
              Response Console
            </div>
            <nav className="flex items-center gap-1" aria-label="Pages">
              <PageLink href="/" active={pathname === "/"} icon={<LayoutDashboard className="h-4 w-4" />}>
                Dashboard
              </PageLink>
              <PageLink href="/map" active={pathname === "/map"} icon={<MapIcon className="h-4 w-4" />}>
                Map
              </PageLink>
            </nav>
          </div>
          <label className="relative block w-[420px]">
            <span className="sr-only">Find instance</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Find instance"
              className="w-full rounded-lg bg-zinc-100 px-3 py-2 text-[15px] text-zinc-900 placeholder:text-zinc-400 focus:outline-none focus:ring-2 focus:ring-zinc-300"
            />
          </label>
          <div className="relative flex items-center justify-end gap-3">
            {value.reconnecting ? (
              <span className="rounded bg-amber-100 px-2 py-1 text-sm text-amber-800">Reconnecting...</span>
            ) : null}
            <button
              type="button"
              aria-expanded={filtersOpen}
              className="inline-flex items-center gap-2 rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm font-medium"
              onClick={() => setFiltersOpen((open) => !open)}
            >
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Filter
            </button>
            {filtersOpen ? (
              <FilterPanel
                risks={risks}
                sort={sort}
                onToggle={(key) => setRisks((current) => ({ ...current, [key]: !current[key] }))}
                onSort={setSort}
                onClose={() => setFiltersOpen(false)}
              />
            ) : null}
          </div>
        </header>

        <div className="flex items-end justify-between gap-6 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <p className="text-[11px] font-semibold tracking-[0.14em] text-zinc-500">ACTIVE INCIDENT</p>
              <span className="rounded-full border border-zinc-300 bg-white px-2 py-0.5 text-xs text-zinc-500">
                Simulated incident
              </span>
            </div>
            <h1 className="mt-1 text-[28px] font-semibold tracking-tight">{value.disasterName}</h1>
            {toast ? <p className="mt-1 text-sm text-zinc-600">{toast}</p> : null}
          </div>
          <div className="flex items-center gap-4 pb-1">
            <p className="text-sm text-zinc-500">
              Showing {value.shown} of {value.total} policyholders
            </p>
            {confirmReset ? (
              <div className="flex items-center gap-2 text-sm">
                <span>Reset the demo and reload the seed?</span>
                <button
                  type="button"
                  className="rounded-md bg-zinc-900 px-2 py-1 text-white"
                  onClick={() => {
                    void resetDemo()
                      .then(() => {
                        setToast("Demo reset");
                        setSteps([]);
                        since.current = 0;
                        setSelectedId(null);
                      })
                      .catch((err: unknown) => setToast(err instanceof Error ? err.message : "Reset failed"))
                      .finally(() => setConfirmReset(false));
                  }}
                >
                  Reset
                </button>
                <button type="button" className="underline" onClick={() => setConfirmReset(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  disabled={running || value.loading}
                  className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  onClick={() => {
                    setRunning(true);
                    void runCheckin()
                      .then((result) => setToast(`Queued ${result.queued}, live ${result.live}`))
                      .catch((err: unknown) => setToast(err instanceof Error ? err.message : "Check-in failed"))
                      .finally(() => setRunning(false));
                  }}
                >
                  {running ? "Running..." : "Run check-in"}
                </button>
                <button type="button" className="text-sm text-zinc-600 underline" onClick={() => setConfirmReset(true)}>
                  Reset demo
                </button>
              </>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 border-t border-zinc-200 bg-white">{children}</div>

        <button
          type="button"
          className="flex items-center justify-between border-t border-zinc-200 bg-white px-6 py-2 text-left text-sm"
          onClick={() => setLogOpen((open) => !open)}
        >
          <span className="font-medium">Agent activity</span>
          <span className="truncate pl-6 text-zinc-500">
            {latest ? `${latest.kind} · ${latest.text}` : "No steps yet"}
          </span>
        </button>
        {logOpen ? (
          <ol className="h-40 overflow-auto border-t border-zinc-100 bg-white px-6 py-2 text-sm">
            {steps.length === 0 ? (
              <li className="text-zinc-500">No steps yet.</li>
            ) : (
              [...steps].reverse().map((step) => (
                <li key={step.id} className="py-1 text-zinc-700">
                  <span className="text-zinc-400">{step.ts}</span> {step.kind} {step.text}
                </li>
              ))
            )}
          </ol>
        ) : null}
        {selected ? <DetailPanel key={selected.id} row={selected} onClose={() => setSelectedId(null)} /> : null}
      </div>
    </ConsoleContext.Provider>
  );
}

function PageLink({
  href,
  active,
  icon,
  children,
}: {
  href: string;
  active: boolean;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium ${
        active ? "border border-zinc-300 bg-white text-zinc-900 shadow-sm" : "text-zinc-500 hover:text-zinc-800"
      }`}
      aria-current={active ? "page" : undefined}
    >
      {icon}
      {children}
    </Link>
  );
}

function FilterPanel({
  risks,
  sort,
  onToggle,
  onSort,
  onClose,
}: {
  risks: Record<RiskKey, boolean>;
  sort: SortMode;
  onToggle: (key: RiskKey) => void;
  onSort: (sort: SortMode) => void;
  onClose: () => void;
}) {
  return (
    <>
      <button type="button" aria-label="Close filters" className="fixed inset-0 z-20 cursor-default" onClick={onClose} />
      <div className="absolute top-11 right-0 z-30 w-72 rounded-lg border border-zinc-200 bg-white p-4 shadow-lg">
        <p className="text-[11px] font-semibold tracking-[0.12em] text-zinc-500">RISK LEVEL</p>
        <ul className="mt-2 space-y-2">
          {RISK_ORDER.map((key) => (
            <li key={key}>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={risks[key]} onChange={() => onToggle(key)} />
                <span
                  className="inline-flex rounded px-2 py-0.5 text-[13px] font-semibold"
                  style={{ backgroundColor: RISK_STYLE[key].bg, color: RISK_STYLE[key].fg }}
                >
                  {RISK_STYLE[key].label}
                </span>
              </label>
            </li>
          ))}
        </ul>
        <p className="mt-4 text-[11px] font-semibold tracking-[0.12em] text-zinc-500">SORT BY LAST RESPONSE</p>
        <ul className="mt-2 space-y-2 text-sm">
          {(
            [
              ["priority", "Risk first"],
              ["latest", "Latest to earliest"],
              ["earliest", "Earliest to latest"],
            ] as const
          ).map(([id, label]) => (
            <li key={id}>
              <label className="flex items-center gap-2">
                <input type="radio" name="sort" checked={sort === id} onChange={() => onSort(id)} />
                {label}
              </label>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
