from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app import runtime
from app.claim_pdf import render_claim_pdf
from app.models import (
    CallStartResponse,
    CaseResponse,
    CheckinRunRequest,
    CheckinRunResponse,
    DashboardResponse,
    OkResponse,
    SimulateReplyRequest,
    StepsResponse,
)

router = APIRouter()


def _ready() -> None:
    runtime.init()


@router.get("/claims/{token}.pdf")
async def claim_pdf(token: str) -> Response:
    _ready()
    assert runtime.store is not None
    case = runtime.store.by_claim_token(token)
    if case is None or case.claim_draft is None:
        raise HTTPException(status_code=404, detail="unknown claim")
    return Response(
        render_claim_pdf(case.name, case.claim_draft),
        media_type="application/pdf",
        headers={"content-disposition": 'inline; filename="claim.pdf"'},
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard() -> DashboardResponse:
    _ready()
    assert runtime.store is not None
    return await runtime.store.dashboard()


@router.get("/cases/{policyholder_id}", response_model=CaseResponse)
async def case_detail(policyholder_id: str) -> CaseResponse:
    _ready()
    assert runtime.store is not None
    found = await runtime.store.case_response(policyholder_id)
    if found is None:
        raise HTTPException(status_code=404, detail="unknown policyholder")
    return found


@router.get("/steps", response_model=StepsResponse)
async def steps(since: int | None = None) -> StepsResponse:
    _ready()
    assert runtime.steps is not None
    return StepsResponse(steps=runtime.steps.since(since))


@router.post("/checkins/run", response_model=CheckinRunResponse)
async def run_checkin(body: CheckinRunRequest) -> CheckinRunResponse:
    _ready()
    assert runtime.flow is not None
    return await runtime.flow.run_checkin(body.disaster_number)


@router.post("/policyholders/{policyholder_id}/call", response_model=CallStartResponse)
async def call_policyholder(policyholder_id: str) -> CallStartResponse:
    _ready()
    assert runtime.flow is not None and runtime.steps is not None
    try:
        call_id = await runtime.flow.place_manual(policyholder_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown policyholder") from None
    except RuntimeError as exc:
        runtime.steps.add(
            "error",
            f"call failed: {exc}",
            policyholder_id=policyholder_id,
            tool="place_call",
        )
        raise HTTPException(status_code=502, detail=f"call failed: {exc}") from None
    return CallStartResponse(call_id=call_id, status="calling")


@router.post("/demo/reset", response_model=OkResponse)
async def demo_reset() -> OkResponse:
    _ready()
    runtime.reset()
    return OkResponse()


@router.post("/dev/simulate-reply", response_model=OkResponse)
async def simulate_reply(body: SimulateReplyRequest) -> OkResponse:
    _ready()
    assert runtime.flow is not None
    try:
        await runtime.flow.handle_id(body.policyholder_id, body.text)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown policyholder") from None
    return OkResponse()
