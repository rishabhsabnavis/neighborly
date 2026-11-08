"""Deterministic coverage. Nemotron may quote only what this returns.

SPEC names the tool check_coverage(id, item). The pure function takes a case,
because it needs the policy. check_coverage_id looks the id up for the planner.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.models import CoverageKey, CoverageResult, Policy

_AMOUNT = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")

# First match wins. Water inside the house is dwelling, not a flood exclusion.
_RULES: list[tuple[CoverageKey, tuple[str, ...]]] = [
    (
        "ale",
        (
            "hotel",
            "shelter",
            "displaced",
            "place to stay",
            "temporary housing",
            "can't stay",
            "cant stay",
        ),
    ),
    (
        "auto",
        ("car", "truck", "vehicle", "camry", "toyota", "honda", "civic"),
    ),
    (
        "contents",
        (
            "furniture",
            "electronics",
            "clothes",
            "belongings",
            "couch",
            "tv",
            "television",
        ),
    ),
    ("dwelling", ("roof", "wall", "window", "structure", "water")),
]

_VEHICLE_WORDS = ("car", "truck", "vehicle", "camry", "toyota", "honda", "civic")


class HasPolicy(Protocol):
    policy: Policy


def map_item(item: str) -> CoverageKey | None:
    text = item.lower()
    for key, words in _RULES:
        if any(word in text for word in words):
            return key
    return None


def _has_vehicle(policy: Policy) -> bool:
    blob = " ".join(policy.covered_property).lower()
    return any(word in blob for word in _VEHICLE_WORDS)


def _dwelling_reason(policy: Policy) -> str:
    for entry in policy.covered_property:
        if entry.lower().startswith("dwelling"):
            return entry
    return "Dwelling"


def check_coverage(case: HasPolicy, item: str) -> CoverageResult:
    policy = case.policy
    key = map_item(item)
    deductible = policy.deductible
    if key is None:
        return CoverageResult(
            item=item,
            coverage=None,
            covered=False,
            deductible=deductible,
            reason=f"Coverage review: {item}",
        )

    limit = getattr(policy.coverages, key)
    if key == "auto" and not _has_vehicle(policy):
        return CoverageResult(
            item=item,
            coverage=key,
            covered=False,
            deductible=deductible,
            reason="That vehicle is not listed on this policy",
        )
    if limit is None:
        if key == "dwelling" and policy.type == "renters":
            reason = "the building is covered by your landlord's policy"
        else:
            reason = f"{key.capitalize()} coverage is not on this policy"
        return CoverageResult(
            item=item,
            coverage=key,
            covered=False,
            deductible=deductible,
            reason=reason,
        )
    if key == "dwelling":
        reason = _dwelling_reason(policy)
    elif key == "auto":
        reason = next(
            (
                entry
                for entry in policy.covered_property
                if any(word in entry.lower() for word in _VEHICLE_WORDS)
            ),
            "Auto",
        )
    elif key == "ale":
        reason = "Additional living expenses"
    else:
        reason = "Contents"
    return CoverageResult(
        item=item,
        coverage=key,
        covered=True,
        limit=limit,
        deductible=deductible,
        reason=reason,
    )


def check_coverage_id(
    cases: dict[str, HasPolicy], policyholder_id: str, item: str
) -> CoverageResult:
    case = cases.get(policyholder_id)
    if case is None:
        raise KeyError(policyholder_id)
    return check_coverage(case, item)


def policy_amounts(policy: Policy) -> set[int]:
    amounts = {policy.deductible}
    for key in ("dwelling", "contents", "ale", "auto"):
        value = getattr(policy.coverages, key)
        if value is not None:
            amounts.add(int(value))
    return amounts


def validate_amounts(text: str, policy: Policy) -> str:
    """Drop any sentence whose dollar amount is not a limit or the deductible."""

    allowed = policy_amounts(policy)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept: list[str] = []
    for sentence in sentences:
        if not sentence:
            continue
        numbers = [int(match.replace(",", "")) for match in _AMOUNT.findall(sentence)]
        if any(number not in allowed for number in numbers):
            continue
        kept.append(sentence)
    return " ".join(kept).strip()
