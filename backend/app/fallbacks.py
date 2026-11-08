"""Heuristic brain. This is the demo safety net when Nemotron is unset or slow."""

from __future__ import annotations

from app.coverage import check_coverage, validate_amounts
from app.models import (
    LABEL_FOR,
    ClaimDraft,
    CoverageResult,
    Damage,
    Policy,
    Triage,
    TriageSource,
    claim_id_for,
)

DATE_OF_LOSS = "2026-10-27"
CAUSE_OF_LOSS = "Hurricane Isaias (FEMA-4955): wind + water"

# phrase, need or None, urgency. First matching level wins via max().
_SIGNALS: tuple[tuple[str, str | None, int], ...] = (
    ("oxygen", "medical", 4),
    ("cpap", "medical", 4),
    ("dialysis", "medical", 4),
    ("can't breathe", "medical", 4),
    ("cant breathe", "medical", 4),
    ("chest pain", "medical", 4),
    ("injured", "medical", 4),
    ("trapped", "trapped", 4),
    ("water rising", "trapped", 4),
    ("can't get out", "trapped", 4),
    ("cant get out", "trapped", 4),
    ("we're stuck", "trapped", 4),
    ("were stuck", "trapped", 4),
    ("we are stuck", "trapped", 4),
    ("i'm stuck", "trapped", 4),
    ("im stuck", "trapped", 4),
    ("stuck upstairs", "trapped", 4),
    ("stuck in the attic", "trapped", 4),
    ("stuck on the roof", "trapped", 4),
    ("water's coming in", "trapped", 4),
    ("water is coming in", "trapped", 4),
    ("water coming in", "trapped", 4),
    ("water inside", "trapped", 4),
    ("no power", "power", 3),
    ("power is out", "power", 3),
    ("power out", "power", 3),
    ("unlivable", "shelter", 3),
    ("can't stay", "shelter", 3),
    ("cant stay", "shelter", 3),
    ("cannot stay", "shelter", 3),
    ("hotel", "shelter", 3),
    ("shelter", "shelter", 3),
    ("displaced", "shelter", 3),
    ("place to stay", "shelter", 3),
    ("roof", "repairs", 3),
    ("caved", "repairs", 3),
    ("flood", "repairs", 3),
    ("window", "repairs", 2),
    ("leak", "repairs", 2),
    ("shingle", "repairs", 2),
    ("damage", "repairs", 2),
    ("damaged", "repairs", 2),
    ("all good", None, 1),
    ("we're fine", None, 1),
    ("were fine", None, 1),
    ("i'm fine", None, 1),
    ("im fine", None, 1),
    ("we're safe", None, 1),
    ("we are safe", None, 1),
    ("i'm safe", None, 1),
    ("no help", None, 1),
    ("we're ok", None, 1),
)

_NEED_ORDER = ("medical", "trapped", "shelter", "power", "repairs")
_NEGATIONS = ("no ", "not ", "nobody", "n't ", "without ")


def _hit(text: str, phrase: str) -> bool:
    start = 0
    while True:
        index = text.find(phrase, start)
        if index < 0:
            return False
        window = text[max(0, index - 16) : index]
        if not any(neg in window for neg in _NEGATIONS):
            return True
        start = index + len(phrase)


def _matches(text: str) -> list[tuple[str | None, int]]:
    lowered = text.lower()
    found: list[tuple[str | None, int]] = []
    for phrase, need, level in _SIGNALS:
        if _hit(lowered, phrase):
            found.append((need, level))
    return found


def life_safety(text: str) -> bool:
    return any(level == 4 for _need, level in _matches(text))


def classify(text: str, source: TriageSource = "imessage") -> Triage:
    stripped = " ".join(text.split())
    if stripped == "2":
        return Triage(
            urgency=2,
            label="moderate",
            needs=[],
            summary="Needs help, no details yet",
            action="Ask a follow-up",
            source=source,
        )
    found = _matches(stripped)
    if not found:
        urgency = 2
        needs: list[str] = []
    else:
        urgency = max(level for _need, level in found)
        present = {need for need, _level in found if need}
        needs = [need for need in _NEED_ORDER if need in present]
    summary = stripped if stripped else "No details yet"
    if len(summary) > 140:
        summary = summary[:137] + "..."
    if urgency == 4:
        action = "Emergency"
    elif urgency == 3:
        action = "Offer a call and draft a claim"
    elif urgency == 1:
        action = "No help needed"
    else:
        action = "Ask a follow-up"
    return Triage(
        urgency=urgency,  # type: ignore[arg-type]
        label=LABEL_FOR[urgency],
        needs=needs,
        summary=summary,
        action=action,
        source=source,
    )


def _street(address: str) -> str:
    return address.split(",")[0].strip()


def follow_up_text(case: object) -> str | None:
    policy: Policy = case.policy  # type: ignore[attr-defined]
    sent = int(getattr(case, "followups_sent", 0))
    if sent >= 2:
        return None
    roof = check_coverage(case, "roof")  # type: ignore[arg-type]
    hotel = check_coverage(case, "hotel")  # type: ignore[arg-type]
    car = check_coverage(case, "car")  # type: ignore[arg-type]
    first = str(getattr(case, "name", "there")).split()[0]
    address = str(getattr(case, "address", "")).strip()
    if policy.type == "auto" or (car.covered and not roof.covered):
        thing = policy.covered_property[0] if policy.covered_property else "vehicle"
        return validate_amounts(f"{first}, is your {thing} damaged?", policy)
    if roof.covered:
        ale = _ale_sentence(hotel)
        text = (
            f"Is there damage to your home at {_street(address) or 'your home'}?{ale} "
            "Do you need a place to stay tonight?"
        )
        return validate_amounts(text, policy)
    if hotel.covered and hotel.limit:
        text = (
            f"Are your belongings damaged? Your policy includes up to ${hotel.limit:,} "
            "for a place to stay if you can't sleep there tonight."
        )
        return validate_amounts(text, policy)
    return f"{first}, what was damaged?"


def _ale_sentence(hotel: CoverageResult) -> str:
    if hotel.covered and hotel.limit:
        return f" Your policy includes up to ${hotel.limit:,} for hotel or temporary housing."
    return ""


def _combined_text(case: object) -> str:
    messages = getattr(case, "messages", [])
    parts = [getattr(message, "text", "") for message in messages]
    return "\n".join(parts).lower()


def template_claim(case: object) -> ClaimDraft:
    policy: Policy = case.policy  # type: ignore[attr-defined]
    text = _combined_text(case)
    damages: list[Damage] = []
    missing: list[str] = []

    if "roof" in text or "window" in text or "wall" in text:
        roof = check_coverage(case, "roof")  # type: ignore[arg-type]
        if roof.covered and roof.coverage:
            damages.append(
                Damage(
                    item="Roof",
                    description="Caved in"
                    if "caved" in text or "roof" in text
                    else "Structure damaged",
                    coverage=roof.coverage,
                    severity="major" if "roof" in text else "moderate",
                )
            )
        elif "roof" in text:
            missing.append("Coverage review: roof")

    contents_words = ("couch", "furniture", "tv", "television", "belongings", "clothes")
    if any(word in text for word in contents_words) or (
        "water" in text and "living" in text
    ):
        contents = check_coverage(case, "furniture")  # type: ignore[arg-type]
        if contents.covered and contents.coverage:
            damages.append(
                Damage(
                    item="Living room contents",
                    description="Water intrusion"
                    if "water" in text
                    else "Damaged belongings",
                    coverage=contents.coverage,
                    severity="moderate",
                )
            )

    vehicle_words = ("car", "truck", "vehicle", "honda", "camry", "civic", "toyota")
    if any(word in text for word in vehicle_words):
        auto = check_coverage(case, "car")  # type: ignore[arg-type]
        if auto.covered and auto.coverage:
            damages.append(
                Damage(
                    item="Vehicle",
                    description="Vehicle damage",
                    coverage=auto.coverage,
                    severity="major",
                )
            )
        elif any(word in text for word in vehicle_words):
            missing.append("Coverage review: vehicle")

    ale_requested = False
    if any(
        word in text
        for word in ("hotel", "shelter", "cannot stay", "can't stay", "place to stay")
    ):
        ale = check_coverage(case, "hotel")  # type: ignore[arg-type]
        if ale.covered:
            ale_requested = True
        else:
            missing.append("Coverage review: hotel")

    injuries: list[str] = []
    notes = list(policy.household.notes)
    if any(word in text for word in ("oxygen", "injured", "chest pain", "trapped")):
        injuries.extend(notes)
        if not injuries and "oxygen" in text:
            injuries.append("Medical need reported: oxygen")
        if "trapped" in text and not any(
            "trapped" in note.lower() for note in injuries
        ):
            injuries.append("Reported trapped")

    for item in ("Photos of damage", "Estimated repair cost"):
        if item not in missing:
            missing.append(item)

    evidence = [message.id for message in getattr(case, "messages", [])]
    evidence.extend(call.call_id for call in getattr(case, "calls", []))
    policyholder_id = str(case.id)
    return ClaimDraft(
        claim_id=claim_id_for(policyholder_id),
        status="draft",
        policy_number=policy.number,
        date_of_loss=DATE_OF_LOSS,
        cause_of_loss=CAUSE_OF_LOSS,
        loss_location=str(getattr(case, "address", "")),
        damages=damages,
        ale_requested=ale_requested,
        injuries_or_medical=injuries,
        deductible=policy.deductible,
        missing_info=missing,
        evidence=evidence,
    )


class HeuristicBrain:
    async def triage(self, case: object) -> Triage:
        messages = getattr(case, "messages", [])
        text = ""
        for message in reversed(messages):
            if getattr(message, "from_", None) == "policyholder":
                text = message.text
                break
        source: TriageSource = (
            "call" if getattr(case, "channel", "") == "voice" else "imessage"
        )
        return classify(text, source)

    async def follow_up(self, case: object) -> str | None:
        return follow_up_text(case)

    async def draft_claim(self, case: object) -> ClaimDraft:
        return template_claim(case)
