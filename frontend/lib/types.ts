/** Types copied from docs/SPEC.md data contracts. */

export type Status =
  | "pending"
  | "texted"
  | "replied"
  | "calling"
  | "called"
  | "unreachable"
  | "safe";

export type Channel = "imessage" | "voice" | "human";
export type PolicyType = "homeowners" | "renters" | "auto";
export type MessageFrom = "agent" | "policyholder" | "voice_agent";
export type MessageChannel = "imessage" | "voice";
export type CallReason = "requested" | "no_reply" | "emergency";
export type CallStatus = "calling" | "done" | "failed";
export type TriageLabel = "critical" | "high" | "moderate" | "safe";
export type TriageSource = "imessage" | "call" | "seed";
export type ClaimStatus = "draft" | "confirmed";
export type CoverageKey = "dwelling" | "contents" | "ale" | "auto";
export type Severity = "minor" | "moderate" | "major";
export type StepKind =
  | "plan"
  | "tool_call"
  | "tool_result"
  | "triage"
  | "claim"
  | "error";
export type Urgency = 1 | 2 | 3 | 4;

export type Counts = {
  total: number;
  safe: number;
  needs_help: number;
  critical: number;
  no_response: number;
  calling: number;
  human_requested: number;
  claims_drafted: number;
};

export type PolicyholderRow = {
  id: string;
  name: string;
  phone_masked: string;
  county: string;
  lat: number;
  lng: number;
  live: boolean;
  status: Status;
  channel: Channel;
  human_requested: boolean;
  urgency: Urgency | null;
  summary: string | null;
  claim_id: string | null;
  last_contact_at: string | null;
  address?: string | null;
  policy_type?: PolicyType | null;
};

export type Dashboard = {
  disaster: { number: number; name: string; state: string; counties: string[] };
  counts: Counts;
  policyholders: PolicyholderRow[];
};

export type Policy = {
  number: string;
  type: PolicyType;
  covered_property: string[];
  coverages: {
    dwelling?: number;
    contents?: number;
    ale?: number;
    auto?: number;
  };
  deductible: number;
  household: { size: number; notes: string[] };
};

export type Message = {
  id: string;
  ts: string;
  from: MessageFrom;
  channel: MessageChannel;
  text: string;
};

export type Call = {
  call_id: string;
  reason: CallReason;
  status: CallStatus;
  duration_s?: number | null;
  transcript_summary?: string | null;
};

export type Triage = {
  urgency: Urgency;
  label: TriageLabel;
  needs: string[];
  summary: string;
  action: string;
  source: TriageSource;
};

export type HumanRequest = {
  requested: boolean;
  reason: string;
  ts: string;
};

export type Damage = {
  item: string;
  description: string;
  coverage: CoverageKey;
  severity: Severity;
};

export type ClaimDraft = {
  claim_id: string;
  status: ClaimStatus;
  policy_number: string;
  date_of_loss: string;
  cause_of_loss: string;
  loss_location: string;
  damages: Damage[];
  ale_requested: boolean;
  injuries_or_medical: string[];
  deductible: number;
  missing_info: string[];
  evidence: string[];
};

export type Case = {
  policyholder: { id: string; name: string; address: string; county: string };
  policy: Policy;
  messages: Message[];
  calls: Call[];
  triage: Triage | null;
  human_request: HumanRequest | null;
  claim_draft: ClaimDraft | null;
};

export type Step = {
  id: number;
  ts: string;
  kind: StepKind;
  policyholder_id: string | null;
  tool: string | null;
  text: string;
  ms: number | null;
};

export type StepPage = { steps: Step[] };

export type CheckinRun = { run_id: string; queued: number; live: number };

export const URGENCY_LABEL: Record<Urgency, string> = {
  4: "Critical",
  3: "High",
  2: "Moderate",
  1: "Safe",
};
