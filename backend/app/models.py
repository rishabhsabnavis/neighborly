"""API models. Field names match docs/SPEC.md "Data contracts"."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer

Status = Literal[
    "pending",
    "texted",
    "replied",
    "calling",
    "called",
    "unreachable",
    "safe",
]
Channel = Literal["imessage", "voice", "human"]
PolicyType = Literal["homeowners", "renters", "auto"]
MessageFrom = Literal["agent", "policyholder", "voice_agent"]
MessageChannel = Literal["imessage", "voice"]
CallReason = Literal["requested", "no_reply", "emergency"]
CallStatus = Literal["calling", "done", "failed"]
# CONTEXT.md danger scale is the label set. SPEC's sample only shows "critical".
TriageLabel = Literal["critical", "high", "moderate", "safe"]
TriageSource = Literal["imessage", "call", "seed"]
ClaimStatus = Literal["draft", "confirmed"]
CoverageKey = Literal["dwelling", "contents", "ale", "auto"]
Severity = Literal["minor", "moderate", "major"]
StepKind = Literal["plan", "tool_call", "tool_result", "triage", "claim", "error"]
Urgency = Literal[1, 2, 3, 4]
MenuChoice = Literal["1", "2", "3", "4", "0", "yes", "free"]


class APIModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class HealthResponse(APIModel):
    status: Literal["ok"]


class CheckinRunRequest(APIModel):
    disaster_number: int


class CheckinRunResponse(APIModel):
    run_id: str
    queued: int
    live: int


class Disaster(APIModel):
    number: int
    name: str
    state: str
    counties: list[str]


class Counts(APIModel):
    total: int
    safe: int
    needs_help: int
    critical: int
    no_response: int
    calling: int
    human_requested: int
    claims_drafted: int


class PolicyholderRow(APIModel):
    id: str
    name: str
    phone_masked: str
    county: str
    lat: float
    lng: float
    live: bool
    status: Status
    channel: Channel
    human_requested: bool
    urgency: Urgency | None = None
    summary: str | None = None
    claim_id: str | None = None
    last_contact_at: str | None = None
    # Additive console fields. Older payloads still validate without them.
    address: str | None = None
    policy_type: PolicyType | None = None


class DashboardResponse(APIModel):
    disaster: Disaster
    counts: Counts
    policyholders: list[PolicyholderRow]


class PolicyholderBrief(APIModel):
    id: str
    name: str
    address: str
    county: str


class Coverages(APIModel):
    """Missing keys mean not covered. Nulls are omitted so they stay missing."""

    dwelling: int | None = None
    contents: int | None = None
    ale: int | None = None
    auto: int | None = None

    @model_serializer(mode="wrap")
    def _omit_nulls(self, handler):
        data = handler(self)
        return {key: value for key, value in data.items() if value is not None}


class Household(APIModel):
    size: int
    notes: list[str] = Field(default_factory=list)


class Policy(APIModel):
    number: str
    type: PolicyType
    covered_property: list[str]
    coverages: Coverages
    deductible: int
    household: Household


class Message(APIModel):
    id: str
    ts: str
    from_: MessageFrom = Field(alias="from")
    channel: MessageChannel
    text: str


class Call(APIModel):
    call_id: str
    reason: CallReason
    status: CallStatus
    duration_s: int | None = None
    transcript_summary: str | None = None


class Triage(APIModel):
    urgency: Urgency
    label: TriageLabel
    needs: list[str]
    summary: str
    action: str
    source: TriageSource


class HumanRequest(APIModel):
    requested: bool
    reason: str
    ts: str


class Damage(APIModel):
    item: str
    description: str
    coverage: CoverageKey
    severity: Severity


class ClaimDraft(APIModel):
    claim_id: str
    status: ClaimStatus
    policy_number: str
    date_of_loss: str
    cause_of_loss: str
    loss_location: str
    damages: list[Damage]
    ale_requested: bool
    injuries_or_medical: list[str]
    deductible: int
    missing_info: list[str]
    evidence: list[str]


class CaseResponse(APIModel):
    policyholder: PolicyholderBrief
    policy: Policy
    messages: list[Message] = Field(default_factory=list)
    calls: list[Call] = Field(default_factory=list)
    triage: Triage | None = None
    human_request: HumanRequest | None = None
    claim_draft: ClaimDraft | None = None


class Step(APIModel):
    id: int
    ts: str
    kind: StepKind
    policyholder_id: str | None = None
    tool: str | None = None
    text: str
    ms: int | None = None


class StepsResponse(APIModel):
    steps: list[Step]


class CallStartResponse(APIModel):
    call_id: str
    status: Literal["calling"]


class OkResponse(APIModel):
    ok: Literal[True] = True


class SimulateReplyRequest(APIModel):
    policyholder_id: str
    text: str


class CoverageResult(APIModel):
    item: str
    coverage: CoverageKey | None = None
    covered: bool
    limit: int | None = None
    deductible: int | None = None
    reason: str


class Action(APIModel):
    """One planner action. Same tools the Nemotron planner will emit later."""

    tool: Literal[
        "send_imessage",
        "place_call",
        "record_triage",
        "request_human",
        "draft_claim",
    ]
    policyholder_id: str
    text: str | None = None
    reason: CallReason | None = None
    urgency: Urgency | None = None
    needs: list[str] = Field(default_factory=list)
    summary: str | None = None
    action: str | None = None


def claim_id_for(policyholder_id: str) -> str:
    number = int(policyholder_id.split("_")[1])
    return f"SF-4955-{number:04d}"


LABEL_FOR: dict[int, TriageLabel] = {
    4: "critical",
    3: "high",
    2: "moderate",
    1: "safe",
}
