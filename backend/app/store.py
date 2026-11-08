"""In-memory cases loaded from the Isaias seed. One lock around mutations."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import Field

from app.models import (
    APIModel,
    Call,
    CaseResponse,
    Channel,
    ClaimDraft,
    Counts,
    DashboardResponse,
    Disaster,
    HumanRequest,
    Message,
    Policy,
    PolicyholderBrief,
    PolicyholderRow,
    Status,
    Triage,
)
from app.settings import assume_opted_in, demo_phone
from app.timeutil import now_iso

SEED_PATH = Path(__file__).resolve().parent / "seed" / "isaias.json"

COUNTIES = [
    "Bay",
    "Calhoun",
    "Escambia",
    "Franklin",
    "Gadsden",
    "Gulf",
    "Holmes",
    "Jackson",
    "Jefferson",
    "Liberty",
    "Okaloosa",
    "Santa Rosa",
    "Wakulla",
    "Walton",
    "Washington",
]


def mask_phone(phone: str) -> str:
    digits = "".join(char for char in phone if char.isdigit())
    last4 = digits[-4:] if len(digits) >= 4 else "0000"
    return f"***-***-{last4}"


class StoredCase(APIModel):
    id: str
    name: str
    phone: str
    phone_masked: str
    address: str
    county: str
    lat: float
    lng: float
    live: bool = False
    opted_in: bool = False
    call_only: bool = False
    status: Status = "pending"
    channel: Channel = "imessage"
    human_requested: bool = False
    urgency: int | None = None
    summary: str | None = None
    claim_id: str | None = None
    last_contact_at: str | None = None
    policy: Policy
    messages: list[Message] = Field(default_factory=list)
    calls: list[Call] = Field(default_factory=list)
    triage: Triage | None = None
    human_request: HumanRequest | None = None
    claim_draft: ClaimDraft | None = None
    texted_at: str | None = None
    followups_sent: int = 0
    phase: str = "menu"
    emergency_attempts: int = 0
    emergency_retry_at: str | None = None
    active_call_id: str | None = None

    def to_row(self) -> PolicyholderRow:
        urgency = self.urgency if self.urgency in (1, 2, 3, 4) else None
        return PolicyholderRow(
            id=self.id,
            name=self.name,
            phone_masked=self.phone_masked,
            county=self.county,
            lat=self.lat,
            lng=self.lng,
            live=self.live,
            status=self.status,
            channel=self.channel,
            human_requested=self.human_requested,
            urgency=urgency,  # type: ignore[arg-type]
            summary=self.summary,
            claim_id=self.claim_id,
            last_contact_at=self.last_contact_at,
            address=self.address,
            policy_type=self.policy.type,
        )

    def to_case(self) -> CaseResponse:
        return CaseResponse(
            policyholder=PolicyholderBrief(
                id=self.id,
                name=self.name,
                address=self.address,
                county=self.county,
            ),
            policy=self.policy,
            messages=self.messages,
            calls=self.calls,
            triage=self.triage,
            human_request=self.human_request,
            claim_draft=self.claim_draft,
        )


def sort_key(case: StoredCase) -> tuple:
    urgency_rank = -case.urgency if case.urgency is not None else 1
    contact = case.last_contact_at or "9999-12-31T23:59:59Z"
    live_human_first = 0 if case.human_requested and case.live else 1
    return (
        0 if case.human_requested else 1,
        live_human_first,
        urgency_rank,
        contact,
        case.id,
    )


def make_counts(cases: list[StoredCase]) -> Counts:
    return Counts(
        total=len(cases),
        safe=sum(1 for case in cases if case.urgency == 1 or case.status == "safe"),
        needs_help=sum(1 for case in cases if case.urgency in (2, 3)),
        critical=sum(1 for case in cases if case.urgency == 4),
        no_response=sum(1 for case in cases if case.status in {"pending", "texted"}),
        calling=sum(1 for case in cases if case.status == "calling"),
        human_requested=sum(1 for case in cases if case.human_requested),
        claims_drafted=sum(1 for case in cases if case.claim_id),
    )


class Store:
    def __init__(self) -> None:
        self.cases: dict[str, StoredCase] = {}
        self.disaster = Disaster(
            number=4955,
            name="Hurricane Isaias",
            state="FL",
            counties=list(COUNTIES),
        )
        self.run_count = 0
        self.lock = asyncio.Lock()

    def reload(self) -> None:
        raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        self.disaster = Disaster.model_validate(raw["disaster"])
        self.cases = {}
        for item in raw["policyholders"]:
            case = StoredCase.model_validate(item)
            self._overlay_env(case)
            self.cases[case.id] = case
        self.run_count = 0

    def _overlay_env(self, case: StoredCase) -> None:
        if case.id == "ph_017":
            phone = demo_phone("DEMO_PHONE_A")
            if phone:
                case.phone = phone
                case.phone_masked = mask_phone(phone)
        elif case.id == "ph_041":
            # SPEC: phone B only gets calls, so it never needs to text JOIN.
            case.call_only = True
            phone = demo_phone("DEMO_PHONE_B")
            if phone:
                case.phone = phone
                case.phone_masked = mask_phone(phone)
        if case.live and assume_opted_in():
            case.opted_in = True

    @classmethod
    def load(cls) -> Store:
        store = cls()
        store.reload()
        return store

    def get(self, policyholder_id: str) -> StoredCase | None:
        return self.cases.get(policyholder_id)

    def by_phone(self, phone: str) -> StoredCase | None:
        for case in self.cases.values():
            if case.phone == phone:
                return case
        return None

    async def dashboard(self) -> DashboardResponse:
        async with self.lock:
            ordered = sorted(self.cases.values(), key=sort_key)
            return DashboardResponse(
                disaster=self.disaster,
                counts=make_counts(ordered),
                policyholders=[case.to_row() for case in ordered],
            )

    async def case_response(self, policyholder_id: str) -> CaseResponse | None:
        async with self.lock:
            case = self.cases.get(policyholder_id)
            if case is None:
                return None
            return case.to_case()


def touch(case: StoredCase) -> str:
    stamp = now_iso()
    case.last_contact_at = stamp
    return stamp
