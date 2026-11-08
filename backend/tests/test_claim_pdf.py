from __future__ import annotations

import re

from app import runtime
from app.claim_pdf import render_claim_pdf
from app.models import ClaimDraft, Damage

BASE = "https://demo.example.test"


def _reply(client, text: str) -> None:
    client.post("/dev/simulate-reply", json={"policyholder_id": "ph_017", "text": text})


def _confirm_claim(client) -> list[str]:
    _reply(client, "roof caved in, need hotel")
    _reply(client, "YES")
    case = client.get("/cases/ph_017").json()
    assert case["claim_draft"]["status"] == "confirmed"
    return [m["text"] for m in case["messages"]]


def _claim(**overrides) -> ClaimDraft:
    data = {
        "claim_id": "SF-4955-0017",
        "status": "confirmed",
        "policy_number": "SF-HO-88213",
        "date_of_loss": "2026-10-27",
        "cause_of_loss": "Hurricane Isaias (FEMA-4955)",
        "loss_location": "412 Harbor Dr, Panama City, FL",
        "damages": [
            Damage(
                item="Roof",
                description="Caved in",
                coverage="dwelling",
                severity="major",
            )
        ],
        "ale_requested": True,
        "injuries_or_medical": ["Mother on home oxygen, power out"],
        "deductible": 2500,
        "missing_info": ["Photos of damage"],
        "evidence": [],
    }
    return ClaimDraft.model_validate({**data, **overrides})


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


def test_yes_texts_a_link_that_serves_the_pdf(client, monkeypatch) -> None:
    monkeypatch.setenv("CLAIM_LINK_BASE_URL", BASE + "/")
    texts = _confirm_claim(client)
    confirmed = next(text for text in texts if text.startswith("Confirmed claim"))
    match = re.search(rf"View it here: {re.escape(BASE)}/claims/([\w-]+)$", confirmed)
    assert match is not None
    token = match.group(1)
    assert len(token) >= 20

    pdf = client.get(f"/claims/{token}.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.content.startswith(b"%PDF")
    assert _pages(pdf.content) == 1


def test_no_link_without_a_public_url(client) -> None:
    texts = _confirm_claim(client)
    assert "Confirmed claim SF-4955-0017." in texts
    assert runtime.store.cases["ph_017"].claim_token is None


def test_unknown_token_is_404(client) -> None:
    missing = client.get("/claims/not-a-real-token.pdf")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown claim"


def test_unconfirmed_claim_has_no_link(client, monkeypatch) -> None:
    monkeypatch.setenv("CLAIM_LINK_BASE_URL", BASE)
    _reply(client, "roof caved in, need hotel")
    case = client.get("/cases/ph_017").json()
    assert case["claim_draft"]["status"] == "draft"
    assert not any("/claims/" in m["text"] for m in case["messages"])


def test_pdf_survives_model_punctuation_and_stays_one_page() -> None:
    long_text = "Water came “through” the ceiling — it’s bad \U0001f622 " * 20
    damages = [
        Damage(
            item=f"Room {index}",
            description=long_text,
            coverage="contents",
            severity="moderate",
        )
        for index in range(30)
    ]
    pdf = render_claim_pdf(
        "María López",
        _claim(
            damages=damages,
            injuries_or_medical=[long_text] * 10,
            missing_info=[long_text] * 10,
        ),
    )
    assert pdf.startswith(b"%PDF")
    assert _pages(pdf) == 1


def test_pdf_handles_a_sparse_claim() -> None:
    pdf = render_claim_pdf(
        "Maria Lopez",
        _claim(
            damages=[], ale_requested=False, injuries_or_medical=[], missing_info=[]
        ),
    )
    assert _pages(pdf) == 1
