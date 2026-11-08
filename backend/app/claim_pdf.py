"""One-page PDF of a confirmed claim for the texted link. All policy data is synthetic."""

from __future__ import annotations

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.models import ClaimDraft

MAX_DAMAGES = 5
LABEL_WIDTH = 42
INK = (29, 41, 57)
MUTED = (102, 112, 133)
ALERT = (180, 35, 24)
RULE = (208, 213, 221)

COVERAGE_LABEL = {
    "dwelling": "Dwelling",
    "contents": "Contents",
    "ale": "Hotel (ALE)",
    "auto": "Auto",
}

# The core PDF fonts are latin-1, and model text often has curly quotes and dashes.
_SWAPS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
    }
)


def _clean(value: object, limit: int = 110) -> str:
    text = " ".join(str(value).translate(_SWAPS).split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text.encode("latin-1", "replace").decode("latin-1")


def _write(pdf: FPDF, text: str, height: float = 5) -> None:
    pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _section(pdf: FPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*INK)
    _write(pdf, title, 6)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1.5)


def _row(pdf: FPDF, label: str, value: object, limit: int = 110) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*MUTED)
    pdf.cell(LABEL_WIDTH, 5.5, label)
    pdf.set_text_color(*INK)
    _write(pdf, _clean(value, limit), 5.5)


def render_claim_pdf(name: str, claim: ClaimDraft) -> bytes:
    pdf = FPDF(format="letter")
    pdf.set_title(f"Claim {_clean(claim.claim_id)}")
    pdf.set_margins(18, 14, 18)
    pdf.set_auto_page_break(False)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*ALERT)
    _write(pdf, "DEMO ONLY - synthetic data. Not an actual insurance claim or policy.")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(*INK)
    _write(pdf, "Claim summary", 10)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*MUTED)
    _write(pdf, f"{_clean(claim.claim_id)}  |  {claim.status.title()}", 6)

    _section(pdf, "Claim details")
    _row(pdf, "Policyholder", name)
    _row(pdf, "Policy number", claim.policy_number)
    _row(pdf, "Loss location", claim.loss_location)
    _row(pdf, "Date of loss", claim.date_of_loss)
    _row(pdf, "Cause of loss", claim.cause_of_loss)

    _section(pdf, "Reported damage")
    if not claim.damages:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*MUTED)
        _write(pdf, "None recorded yet.")
    for damage in claim.damages[:MAX_DAMAGES]:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*INK)
        _write(pdf, _clean(f"{damage.item}: {damage.description}"))
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        coverage = COVERAGE_LABEL.get(damage.coverage, damage.coverage)
        _write(pdf, f"Coverage: {coverage}  |  Severity: {damage.severity}", 4.5)
        pdf.ln(1)
    hidden = len(claim.damages) - MAX_DAMAGES
    if hidden > 0:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        _write(pdf, f"Plus {hidden} more on the full claim.", 4.5)

    _section(pdf, "Needs and coverage")
    _row(pdf, "Hotel (ALE)", "Requested" if claim.ale_requested else "Not requested")
    medical = "; ".join(claim.injuries_or_medical) or "None reported"
    _row(pdf, "Medical needs", medical, 170)
    _row(pdf, "Deductible", f"${claim.deductible:,}")

    if claim.missing_info:
        _section(pdf, "Still needed")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*INK)
        _write(pdf, _clean(", ".join(claim.missing_info), 230))

    return bytes(pdf.output())
