"""Write backend/app/seed/isaias.json. Fixed story list, no randomness.

Run from backend/: uv run python -m app.seed.make_seed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.fallbacks import template_claim
from app.models import Call, Coverages, Household, HumanRequest, Message, Policy, Triage
from app.store import COUNTIES, SEED_PATH, StoredCase, mask_phone
from app.timeutil import to_iso

BASE = datetime(2026, 11, 7, 18, 0, tzinfo=UTC)

CITIES = {
    "Bay": "Panama City",
    "Calhoun": "Blountstown",
    "Escambia": "Pensacola",
    "Franklin": "Apalachicola",
    "Gadsden": "Quincy",
    "Gulf": "Port St. Joe",
    "Holmes": "Bonifay",
    "Jackson": "Marianna",
    "Jefferson": "Monticello",
    "Liberty": "Bristol",
    "Okaloosa": "Crestview",
    "Santa Rosa": "Milton",
    "Wakulla": "Crawfordville",
    "Walton": "DeFuniak Springs",
    "Washington": "Chipley",
}

CENTERS = {
    "Bay": (30.24, -85.63),
    "Calhoun": (30.41, -85.20),
    "Escambia": (30.62, -87.34),
    "Franklin": (29.85, -84.90),
    "Gadsden": (30.58, -84.62),
    "Gulf": (29.96, -85.24),
    "Holmes": (30.87, -85.81),
    "Jackson": (30.79, -85.21),
    "Jefferson": (30.44, -83.90),
    "Liberty": (30.25, -84.88),
    "Okaloosa": (30.69, -86.59),
    "Santa Rosa": (30.70, -87.02),
    "Wakulla": (30.15, -84.40),
    "Walton": (30.60, -86.17),
    "Washington": (30.61, -85.67),
}

NAMES = [
    "Amina Brooks",
    "Luis Ortega",
    "Helen Cho",
    "Marcus Hale",
    "Priya Shah",
    "Owen Blake",
    "Nora Feldman",
    "Andre Willis",
    "Grace Ibarra",
    "Seth Nguyen",
    "Lila Brooks",
    "Jonah Patel",
    "Rosa Kim",
    "Evan Walsh",
    "Maya Chen",
    "Theo Barker",
    "Maria Lopez",
    "Imani Scott",
    "Felix Navarro",
    "Clara Singh",
    "Miles Abbott",
    "June Harlow",
    "Omar Haddad",
    "Pearl Donovan",
    "Nico Alvarez",
    "Sasha Reid",
    "Bea Forrest",
    "Colin Mercer",
    "Hana Suzuki",
    "Victor Lang",
    "Eden Price",
    "Malik Jordan",
    "Ruth Keller",
    "Simon Adeyemi",
    "Willa Grant",
    "Pedro Santos",
    "Ada Okonkwo",
    "Harvey Bloom",
    "Nina Volkov",
    "Ira Solomon",
    "Helen Park",
    "Gia Moretti",
]

STREETS = [
    "Oak St",
    "Palm Ave",
    "Bayou Rd",
    "Pine Ln",
    "Cedar Ct",
    "Magnolia St",
    "Gulf Blvd",
    "Dogwood Dr",
    "Maple Ave",
    "Cypress St",
]

# kind, reply, summary. None reply means the menu went out and nobody answered.
STORIES: dict[str, tuple[str, str | None, str | None]] = {
    "ph_001": ("safe", "1", "Safe, no help needed"),
    "ph_002": (
        "safe",
        "All good, just some branches in the yard",
        "Safe, branches down",
    ),
    "ph_003": (
        "emergency",
        "Dad is on oxygen and the power is out. We're still at the house.",
        "Father on oxygen, power out",
    ),
    "ph_004": ("texted", None, None),
    "ph_005": (
        "human",
        "The roof caved in. I want to talk to a person.",
        "Roof damage, asked for a person",
    ),
    "ph_007": (
        "emergency_call",
        "We're trapped upstairs and the water is rising.",
        "Trapped upstairs, water rising",
    ),
    "ph_008": (
        "emergency_lost",
        "Mom is on oxygen and the power is out.",
        "No answer after an emergency text",
    ),
    "ph_009": ("texted", None, None),
    "ph_011": (
        "renters",
        "The roof is open and rain soaked our couch. We cannot stay here tonight.",
        "Renters, roof open, couch soaked",
    ),
    "ph_012": (
        "human",
        "Rain is in the living room and the roof is leaking. I need a person.",
        "Water inside, asked for a person",
    ),
    "ph_013": (
        "high",
        "The roof caved in and rain is in the living room. We need a hotel tonight.",
        "Roof caved in, needs a hotel",
    ),
    "ph_015": ("texted", None, None),
    "ph_016": (
        "high",
        "A pine came through the roof. Water is in the living room. We cannot stay.",
        "Tree through the roof, cannot stay",
    ),
    "ph_019": (
        "high",
        "The roof is open over the kitchen and the power is out. We need a hotel.",
        "Roof open, power out, needs a hotel",
    ),
    "ph_020": (
        "high",
        "Windows blew in and the roof is leaking into the living room. We need a hotel.",
        "Roof leak, needs a hotel",
    ),
    "ph_022": (
        "high",
        "The carport roof collapsed onto the house. Rain is in the living room. We need shelter.",
        "Carport roof collapsed, needs shelter",
    ),
    "ph_023": ("texted", None, None),
    "ph_024": (
        "high",
        "A big section of roof is gone. Belongings are soaked. We need a hotel tonight.",
        "Roof gone, belongings soaked",
    ),
    "ph_026": (
        "safe",
        "We're fine. Lost a few shingles and that's all.",
        "Safe, a few shingles",
    ),
    "ph_027": ("safe", "All good here. The house is dry.", "Safe, house is dry"),
    "ph_028": (
        "auto",
        "A tree hit our Honda Civic and it will not start.",
        "Tree hit the Honda Civic",
    ),
    "ph_030": (
        "moderate",
        "Some shingles came off and a window cracked, but we can stay.",
        "Shingles and a cracked window",
    ),
    "ph_031": (
        "moderate",
        "The fence is down and one window is cracked. We can stay.",
        "Fence down, window cracked",
    ),
    "ph_032": (
        "moderate",
        "A small leak in the closet. We can stay and wait on repairs.",
        "Small closet leak, can stay",
    ),
    "ph_034": (
        "moderate",
        "Siding is damaged and we lost power for an hour. We're ok now and can stay.",
        "Siding damage, power is back",
    ),
    "ph_035": (
        "moderate",
        "Branches hit the porch. No water inside. We can stay.",
        "Porch damage, can stay",
    ),
    "ph_037": (
        "moderate",
        "Garage door is stuck and a window is cracked. We can stay.",
        "Garage door stuck",
    ),
    "ph_038": ("safe", "1", "Safe, no help needed"),
    "ph_039": (
        "safe",
        "All good, just leaves and small branches.",
        "Safe, yard debris",
    ),
    "ph_042": (
        "moderate",
        "Screen porch is torn up. The house is fine and we can stay.",
        "Screen porch torn",
    ),
}

KINDS: dict[str, dict] = {
    "safe": {
        "status": "safe",
        "urgency": 1,
        "needs": [],
        "action": "No help needed",
        "claim": False,
    },
    "moderate": {
        "status": "replied",
        "urgency": 2,
        "needs": ["repairs"],
        "action": "Ask a follow-up",
        "claim": False,
    },
    "high": {
        "status": "replied",
        "urgency": 3,
        "needs": ["shelter"],
        "action": "Offer a call and draft a claim",
        "claim": True,
    },
    "texted": {
        "status": "texted",
        "urgency": None,
        "needs": [],
        "action": "",
        "claim": False,
    },
    "human": {
        "status": "replied",
        "urgency": 3,
        "needs": ["shelter"],
        "action": "A person will call within 15 min",
        "claim": True,
        "human": "Asked for a person",
    },
    "emergency": {
        "status": "replied",
        "urgency": 4,
        "needs": ["medical", "power"],
        "action": "Emergency",
        "claim": False,
        "human": "Emergency",
    },
    "emergency_call": {
        "status": "calling",
        "urgency": 4,
        "needs": ["trapped"],
        "action": "Emergency",
        "claim": False,
        "human": "Emergency",
    },
    "emergency_lost": {
        "status": "unreachable",
        "urgency": 4,
        "needs": ["medical", "power"],
        "action": "Welfare check recommended",
        "claim": True,
        "human": "Emergency",
    },
    "renters": {
        "status": "replied",
        "urgency": 3,
        "needs": ["shelter"],
        "action": "Coverage review for the building",
        "claim": True,
    },
    "auto": {
        "status": "replied",
        "urgency": 2,
        "needs": ["repairs"],
        "action": "Auto claim draft",
        "claim": True,
    },
}

NOTES = {
    "ph_003": ["Father, 80, home oxygen"],
    "ph_008": ["Mother, 76, home oxygen", "Uses a wheelchair"],
    "ph_012": ["Infant in the home"],
    "ph_019": ["Grandmother, 82, lives in the home"],
}


def stamp(index: int, extra: int = 0) -> str:
    return to_iso(BASE + timedelta(minutes=index * 3 + extra))


def menu(case: StoredCase) -> str:
    first = case.name.split()[0]
    return (
        f"{first}, this is Neighborly. Hurricane Isaias hit {case.county} County. "
        "Reply 1 Safe, 2 Need help, 3 Emergency, 4 Call me, 0 Talk to a person."
    )


def address_for(index: int, county: str, street: str) -> str:
    number = 100 + index * 13
    return f"{number} {street}, {CITIES[county]}, FL"


def policy_for(index: int, kind: str, address: str, notes: list[str]) -> Policy:
    street = address.split(",")[0]
    household = Household(size=1 + (index % 4), notes=notes)
    if kind == "renters":
        return Policy(
            number=f"SF-RN-{50000 + index:05d}",
            type="renters",
            covered_property=[f"Contents: {street}"],
            coverages=Coverages(contents=40000, ale=8000),
            deductible=1000,
            household=household,
        )
    if kind == "auto":
        return Policy(
            number=f"SF-AU-{30000 + index:05d}",
            type="auto",
            covered_property=["2014 Honda Civic"],
            coverages=Coverages(auto=15000),
            deductible=500,
            household=household,
        )
    dwelling = 280000 + (index % 8) * 20000
    covered = [f"Dwelling: {street}"]
    coverages = Coverages(
        dwelling=dwelling,
        contents=dwelling // 2,
        ale=12000 + (index % 5) * 2000,
    )
    return Policy(
        number=f"SF-HO-{80000 + index:05d}",
        type="homeowners",
        covered_property=covered,
        coverages=coverages,
        deductible=1000 if index % 2 == 0 else 2500,
        household=household,
    )


def skeleton(index: int) -> StoredCase:
    pid = f"ph_{index:03d}"
    county = COUNTIES[(index - 1) % len(COUNTIES)]
    street = STREETS[index % len(STREETS)]
    address = address_for(index, county, street)
    lat0, lng0 = CENTERS[county]
    phone = f"+1555555{index:04d}"
    return StoredCase(
        id=pid,
        name=NAMES[index - 1],
        phone=phone,
        phone_masked=mask_phone(phone),
        address=address,
        county=county,
        lat=round(lat0 + ((index * 37) % 25 - 12) * 0.01, 4),
        lng=round(lng0 + ((index * 53) % 25 - 12) * 0.01, 4),
        live=False,
        status="pending",
        channel="imessage",
        policy=policy_for(index, "homeowners", address, NOTES.get(pid, [])),
    )


def maria(case: StoredCase) -> StoredCase:
    case.name = "Maria Lopez"
    case.phone = "+15555554410"
    case.phone_masked = mask_phone(case.phone)
    case.address = "412 Harbor Dr, Panama City, FL"
    case.county = "Bay"
    case.lat = 30.16
    case.lng = -85.66
    case.live = True
    case.status = "pending"
    case.policy = Policy(
        number="SF-HO-88213",
        type="homeowners",
        covered_property=["Dwelling: 412 Harbor Dr", "2019 Toyota Camry"],
        coverages=Coverages(dwelling=320000, contents=160000, ale=18000),
        deductible=2500,
        household=Household(size=3, notes=["Mother, 74, home oxygen"]),
    )
    return case


def helen(case: StoredCase) -> StoredCase:
    case.name = "Helen Park"
    case.county = "Walton"
    case.address = "220 Cypress St, DeFuniak Springs, FL"
    case.lat = 30.72
    case.lng = -86.12
    case.live = True
    case.status = "pending"
    case.policy = policy_for(41, "homeowners", case.address, ["Lives alone"])
    case.policy.number = "SF-HO-80041"
    return case


def apply_story(case: StoredCase, index: int) -> StoredCase:
    kind_name, reply, summary = STORIES[case.id]
    kind = KINDS[kind_name]
    case.policy = policy_for(index, kind_name, case.address, NOTES.get(case.id, []))
    opened = stamp(index, 0)
    case.messages = [
        Message(
            id=f"{case.id}_m1",
            ts=opened,
            from_="agent",
            channel="imessage",
            text=menu(case),
        )
    ]
    case.texted_at = opened
    case.last_contact_at = opened
    if reply:
        replied = stamp(index, 1)
        case.messages.append(
            Message(
                id=f"{case.id}_m2",
                ts=replied,
                from_="policyholder",
                channel="imessage",
                text=reply,
            )
        )
        case.last_contact_at = replied
    case.status = kind["status"]
    case.summary = summary
    case.urgency = kind["urgency"]
    if kind["urgency"] is not None:
        label = {4: "critical", 3: "high", 2: "moderate", 1: "safe"}[kind["urgency"]]
        case.triage = Triage(
            urgency=kind["urgency"],
            label=label,  # type: ignore[arg-type]
            needs=list(kind["needs"]),
            summary=summary or "",
            action=kind["action"],
            source="seed",
        )
    human = kind.get("human")
    if human:
        case.human_requested = True
        case.human_request = HumanRequest(
            requested=True,
            reason=human,
            ts=case.last_contact_at or opened,
        )
        if kind_name == "human":
            case.channel = "human"
    if kind_name == "emergency_call":
        call_id = f"conv_{case.id}"
        case.calls = [Call(call_id=call_id, reason="emergency", status="calling")]
        case.active_call_id = call_id
        case.channel = "voice"
        case.emergency_attempts = 1
    elif kind_name == "emergency_lost":
        case.calls = [
            Call(
                call_id=f"conv_{case.id}",
                reason="emergency",
                status="done",
                duration_s=25,
                transcript_summary="Voicemail left.",
            )
        ]
        case.channel = "voice"
        case.emergency_attempts = 2
    if kind["claim"]:
        case.claim_draft = template_claim(case)
        case.claim_id = case.claim_draft.claim_id
        case.phase = "claim_confirm"
        case.followups_sent = 2
    elif kind_name == "safe":
        case.phase = "closed"
    elif kind_name == "texted":
        case.phase = "menu"
    else:
        case.phase = "followup"
        case.followups_sent = 1
    return case


def build() -> dict:
    people: list[StoredCase] = []
    for index in range(1, 43):
        case = skeleton(index)
        if case.id == "ph_017":
            case = maria(case)
        elif case.id == "ph_041":
            case = helen(case)
        elif case.id in STORIES:
            case = apply_story(case, index)
        people.append(case)
    return {
        "disaster": {
            "number": 4955,
            "name": "Hurricane Isaias",
            "state": "FL",
            "counties": COUNTIES,
        },
        "policyholders": [
            case.model_dump(mode="json", by_alias=True) for case in people
        ],
    }


def main() -> None:
    payload = build()
    ids = [item["id"] for item in payload["policyholders"]]
    assert ids == [f"ph_{i:03d}" for i in range(1, 43)]
    assert len(STORIES) == 30
    SEED_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(ids)} policyholders -> {SEED_PATH}")


if __name__ == "__main__":
    main()
