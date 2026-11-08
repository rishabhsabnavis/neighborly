"""Env defaults before the app imports .env values it must not override."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


def _defaults() -> None:
    os.environ["MESSENGER"] = "fake"
    os.environ["CALLER"] = "fake"
    os.environ["BRAIN"] = "heuristic"
    os.environ["PLANNER"] = "rules"
    os.environ["DEMO_ASSUME_OPTED_IN"] = "1"
    os.environ["CLAIM_LINK_BASE_URL"] = ""
    os.environ.pop("DEMO_PHONE_A", None)
    os.environ.pop("DEMO_PHONE_B", None)


_defaults()


@pytest.fixture
def client():
    from app.main import app
    from app.runtime import reset

    with TestClient(app) as test_client:
        reset()
        yield test_client
        reset()
