"use client";

import { MessageSquare, Phone, X } from "lucide-react";
import { useState } from "react";

import { RiskChip } from "@/components/raw/RiskChip";
import { callPolicyholder, getCase } from "@/lib/api";
import { clock, contactLine, policyLabel } from "@/lib/display";
import { URGENCY_LABEL } from "@/lib/types";
import type {
  Call,
  Case,
  CoverageKey,
  Message,
  PolicyholderRow,
  Triage,
  TriageSource,
} from "@/lib/types";
import { usePoll } from "@/lib/usePoll";

const COVERAGE_LABEL: Record<CoverageKey, string> = {
  dwelling: "Dwelling",
  contents: "Contents",
  ale: "Hotel (ALE)",
  auto: "Auto",
};

const TRIAGE_SOURCE: Record<TriageSource, string> = {
  imessage: "iMessage replies",
  call: "Phone call",
  seed: "Existing case record",
};

type TimelineItem = {
  key: string;
  kind: "Text" | "Call" | "System";
  text: string;
  time: string;
  sort: string;
};

function fromMessage(message: Message): TimelineItem {
  return {
    key: message.id,
    kind: message.channel === "voice" ? "Call" : "Text",
    text: message.text,
    time: clock(message.ts),
    sort: message.ts,
  };
}

function fromCall(call: Call): TimelineItem {
  const reason =
    call.reason === "no_reply"
      ? "No-reply call"
      : call.reason === "emergency"
        ? "Emergency call"
        : "Requested call";
  return {
    key: call.call_id,
    kind: "Call",
    text: call.transcript_summary
      ? `${reason}. ${call.transcript_summary}`
      : `${reason} · ${call.status}`,
    time: "—",
    sort: "9999",
  };
}

export function DetailPanel({
  row,
  onClose,
}: {
  row: PolicyholderRow;
  onClose: () => void;
}) {
  const { data, error, stale } = usePoll(() => getCase(row.id), 2000);
  const [notice, setNotice] = useState<string | null>(null);
  const [calling, setCalling] = useState(false);

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-[400px] max-w-full flex-col border-l border-zinc-200 bg-white shadow-xl">
      <header className="flex items-center justify-between px-5 py-4">
        <p className="text-[11px] font-semibold tracking-[0.14em] text-zinc-500">
          POLICYHOLDER DETAIL
        </p>
        <button
          type="button"
          aria-label="Close"
          className="rounded p-1 text-zinc-500 hover:bg-zinc-100"
          onClick={onClose}
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="border-b-2 border-[#D92D20] px-5 pb-4">
        <h2 className="text-xl font-semibold text-zinc-900">{row.name}</h2>
        <div className="mt-2 flex items-center gap-2">
          <RiskChip row={row} />
          <span className="text-sm text-zinc-500">{contactLine(row)}</span>
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-5 py-4">
        {stale || error ? (
          <p className="text-sm text-amber-700">Reconnecting...</p>
        ) : null}
        <section className="rounded-md border border-zinc-200 px-4 py-3">
          <h3 className="text-[11px] font-semibold tracking-[0.12em] text-zinc-500">
            CURRENT SITUATION
          </h3>
          <p className="mt-2 text-[15px] leading-6 text-zinc-900">
            {row.summary || "No details yet"}
          </p>
          {row.human_requested ? (
            <p className="mt-2 text-sm font-medium text-zinc-700">
              Asked for a State Farm agent.
            </p>
          ) : null}
        </section>
        {data ? (
          <Facts item={data} claimId={row.claim_id} />
        ) : (
          <p className="text-sm text-zinc-500">Loading case...</p>
        )}
      </div>
      <footer className="border-t border-zinc-200 px-5 py-4">
        {notice ? <p className="mb-2 text-sm text-zinc-700">{notice}</p> : null}
        <button
          type="button"
          disabled={calling}
          className="w-full rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={() => {
            setCalling(true);
            void callPolicyholder(row.id)
              .then((result) => setNotice(`Calling ${result.call_id}`))
              .catch((err: unknown) =>
                setNotice(err instanceof Error ? err.message : "Call failed"),
              )
              .finally(() => setCalling(false));
          }}
        >
          {calling ? "Calling..." : "Call now"}
        </button>
      </footer>
    </aside>
  );
}

function Facts({ item, claimId }: { item: Case; claimId: string | null }) {
  const events: TimelineItem[] = [
    ...item.messages.map(fromMessage),
    ...item.calls.map(fromCall),
  ];
  if (item.human_request?.requested) {
    events.push({
      key: "human",
      kind: "System",
      text: item.human_request.reason,
      time: clock(item.human_request.ts),
      sort: item.human_request.ts,
    });
  }
  events.sort((a, b) => b.sort.localeCompare(a.sort));
  const notes = item.policy.household.notes.filter(Boolean);

  return (
    <>
      {item.triage ? <TriageFacts triage={item.triage} /> : null}
      <section className="overflow-hidden rounded-md border border-zinc-200">
        <h3 className="border-b border-zinc-200 px-4 py-2 text-[13px] font-semibold text-zinc-800">
          Policyholder information
        </h3>
        <dl className="text-[14px]">
          <Fact label="Address" value={item.policyholder.address} />
          <Fact label="County" value={`${item.policyholder.county} County`} />
          <Fact label="Policy type" value={policyLabel(item.policy.type)} />
          <Fact label="Policy number" value={item.policy.number} />
          <Fact
            label="Claim number"
            value={item.claim_draft?.claim_id || claimId || "—"}
          />
          <Fact
            label="Household"
            value={
              notes.length
                ? notes.join("; ")
                : `${item.policy.household.size} people`
            }
          />
        </dl>
      </section>
      {item.claim_draft ? (
        <section className="overflow-hidden rounded-md border border-zinc-200">
          <h3 className="flex items-center justify-between border-b border-zinc-200 px-4 py-2 text-[13px] font-semibold text-zinc-800">
            <span>Claim {item.claim_draft.claim_id}</span>
            <span className="font-medium text-zinc-500">
              {item.claim_draft.status === "confirmed" ? "Confirmed" : "Draft"}
            </span>
          </h3>
          {item.claim_draft.damages.length ? (
            <ul className="space-y-1 px-4 py-3 text-[14px] text-zinc-800">
              {item.claim_draft.damages.map((damage) => (
                <li key={`${damage.coverage}-${damage.item}`}>
                  {damage.item}: {damage.description}
                  <span className="text-[13px] text-zinc-500">
                    {" "}
                    · {COVERAGE_LABEL[damage.coverage]} · {damage.severity}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          <dl className="border-t border-zinc-100 text-[14px]">
            <Fact
              label="Hotel (ALE)"
              value={
                item.claim_draft.ale_requested ? "Requested" : "Not requested"
              }
            />
            <Fact
              label="Medical needs"
              value={
                item.claim_draft.injuries_or_medical.join("; ") ||
                "None reported"
              }
            />
            <Fact
              label="Deductible"
              value={`$${item.claim_draft.deductible.toLocaleString("en-US")}`}
            />
          </dl>
          {item.claim_draft.missing_info.length ? (
            <p className="border-t border-zinc-100 px-4 py-2 text-[13px] text-zinc-500">
              Still needed: {item.claim_draft.missing_info.join(", ")}
            </p>
          ) : null}
        </section>
      ) : null}
      <section>
        <h3 className="mb-3 text-[13px] font-semibold text-zinc-800">
          Communication timeline
        </h3>
        {events.length === 0 ? (
          <p className="text-sm text-zinc-500">No messages yet.</p>
        ) : (
          <ol className="space-y-4">
            {events.map((event) => (
              <li key={event.key} className="flex gap-3">
                <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-zinc-100 text-zinc-600">
                  {event.kind === "Call" ? (
                    <Phone className="h-4 w-4" />
                  ) : (
                    <MessageSquare className="h-4 w-4" />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="font-medium text-zinc-900">{event.kind}</p>
                    <time className="shrink-0 text-[13px] text-zinc-500">
                      {event.time}
                    </time>
                  </div>
                  <p className="text-[14px] leading-5 text-zinc-600">
                    {event.text}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </>
  );
}

function TriageFacts({ triage }: { triage: Triage }) {
  const needs = triage.needs.map((need) => need.replace(/_/g, " ")).join(", ");
  return (
    <section className="overflow-hidden rounded-md border border-zinc-200">
      <h3 className="border-b border-zinc-200 px-4 py-2 text-[13px] font-semibold text-zinc-800">
        Triage
      </h3>
      <dl className="text-[14px]">
        <Fact
          label="Urgency"
          value={`${triage.urgency} · ${URGENCY_LABEL[triage.urgency]}`}
        />
        <Fact label="Needs" value={needs || "None recorded"} />
        <Fact label="Recommended action" value={triage.action || "—"} />
        <Fact label="Based on" value={TRIAGE_SOURCE[triage.source]} />
      </dl>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-4 py-2.5 last:border-b-0">
      <dt className="shrink-0 text-zinc-500">{label}</dt>
      <dd className="text-right text-zinc-900">{value}</dd>
    </div>
  );
}
