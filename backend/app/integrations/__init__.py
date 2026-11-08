"""Pick messenger, caller, and brain from env. Live imports stay inside the builders."""

from __future__ import annotations

import os

from app.integrations.fake import FakeCaller, FakeMessenger
from app.steps import StepLog

_messenger: FakeMessenger | object | None = None
_caller: FakeCaller | object | None = None
_brain: object | None = None


def _choice(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip().lower() or default


def build_messenger(steps: StepLog) -> FakeMessenger | object:
    global _messenger
    if _messenger is not None:
        return _messenger
    kind = _choice("MESSENGER", "fake")
    if kind == "photon":
        try:
            from app.integrations.photon import PhotonMessenger

            _messenger = PhotonMessenger()
            return _messenger
        except Exception as exc:  # noqa: BLE001 - a missing key or SDK must not stop startup
            steps.add(
                "error",
                f"Photon messenger unavailable: {type(exc).__name__}: {exc}"[:240],
            )
    elif kind != "fake":
        steps.add("error", f"Unknown MESSENGER={kind}; using fake")
    _messenger = FakeMessenger()
    return _messenger


def build_caller(steps: StepLog) -> FakeCaller | object:
    global _caller
    if _caller is not None:
        return _caller
    kind = _choice("CALLER", "fake")
    if kind == "elevenlabs":
        try:
            from app.integrations.elevenlabs import ElevenLabsCaller

            _caller = ElevenLabsCaller()
            return _caller
        except Exception as exc:  # noqa: BLE001 - a missing key must not stop startup
            steps.add(
                "error",
                f"ElevenLabs caller unavailable: {type(exc).__name__}: {exc}"[:240],
            )
    elif kind != "fake":
        steps.add("error", f"Unknown CALLER={kind}; using fake")
    _caller = FakeCaller()
    return _caller


def build_brain(steps: StepLog) -> object:
    global _brain
    if _brain is not None:
        return _brain
    kind = _choice("BRAIN", "heuristic")
    if kind == "nemotron":
        try:
            from app.integrations.nemotron import NemotronBrain

            _brain = NemotronBrain()
            return _brain
        except Exception as exc:  # noqa: BLE001 - missing nemotron.py falls back to heuristic
            steps.add(
                "error",
                f"Nemotron brain unavailable: {type(exc).__name__}: {exc}"[:240],
            )
    elif kind != "heuristic":
        steps.add("error", f"Unknown BRAIN={kind}; using heuristic")
    from app.fallbacks import HeuristicBrain

    _brain = HeuristicBrain()
    return _brain


def get_messenger() -> FakeMessenger | object:
    if _messenger is None:
        raise RuntimeError("messenger is not initialized")
    return _messenger


def get_caller() -> FakeCaller | object:
    if _caller is None:
        raise RuntimeError("caller is not initialized")
    return _caller


def reset_integrations() -> None:
    """Test helper. Drops cached clients so the next build reads env again."""

    global _messenger, _caller, _brain
    _messenger = None
    _caller = None
    _brain = None
