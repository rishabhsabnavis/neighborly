from __future__ import annotations

from app.models import Coverages, Household, Policy
from app.store import StoredCase, mask_phone


def maria_case() -> StoredCase:
    phone = "+15555554410"
    return StoredCase(
        id="ph_017",
        name="Maria Lopez",
        phone=phone,
        phone_masked=mask_phone(phone),
        address="412 Harbor Dr, Panama City, FL",
        county="Bay",
        lat=30.16,
        lng=-85.66,
        live=True,
        status="replied",
        channel="imessage",
        policy=Policy(
            number="SF-HO-88213",
            type="homeowners",
            covered_property=["Dwelling: 412 Harbor Dr", "2019 Toyota Camry"],
            coverages=Coverages(dwelling=320000, contents=160000, ale=18000),
            deductible=2500,
            household=Household(size=3, notes=["Mother, 74, home oxygen"]),
        ),
    )


def renters_case() -> StoredCase:
    phone = "+15555550011"
    return StoredCase(
        id="ph_011",
        name="Lila Brooks",
        phone=phone,
        phone_masked=mask_phone(phone),
        address="243 Oak St, Blountstown, FL",
        county="Calhoun",
        lat=30.4,
        lng=-85.2,
        status="replied",
        channel="imessage",
        policy=Policy(
            number="SF-RN-50011",
            type="renters",
            covered_property=["Contents: 243 Oak St"],
            coverages=Coverages(contents=40000, ale=8000),
            deductible=1000,
            household=Household(size=2, notes=[]),
        ),
    )
