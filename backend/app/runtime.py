"""Process-wide store, flow, and agent. Lifespan starts the poll loops."""

from __future__ import annotations

import asyncio

from app.agent import Agent
from app.flow import Flow
from app.integrations import build_brain, build_caller, build_messenger
from app.integrations.fake import FakeCaller, FakeMessenger
from app.steps import StepLog
from app.store import Store

store: Store | None = None
steps: StepLog | None = None
flow: Flow | None = None
agent: Agent | None = None


def init() -> None:
    global store, steps, flow, agent
    if (
        store is not None
        and steps is not None
        and flow is not None
        and agent is not None
    ):
        return
    steps = StepLog()
    messenger = build_messenger(steps)
    caller = build_caller(steps)
    brain = build_brain(steps)
    fake = messenger if isinstance(messenger, FakeMessenger) else FakeMessenger()
    store = Store.load()
    flow = Flow(store, steps, messenger, caller, brain, fake)
    agent = Agent(store, steps, flow)


def reset() -> None:
    init()
    assert store is not None and steps is not None and flow is not None
    steps.clear()
    store.reload()
    caller = flow.caller
    if isinstance(caller, FakeCaller):
        caller.reset()
    if isinstance(flow.messenger, FakeMessenger):
        flow.messenger.reset()
    if isinstance(flow.fake, FakeMessenger) and flow.fake is not flow.messenger:
        flow.fake.reset()
    flow.placed.clear()


async def start_background() -> list[asyncio.Task[None]]:
    init()
    assert agent is not None
    return [
        asyncio.create_task(agent.tick_loop()),
        asyncio.create_task(agent.poll_message_loop()),
        asyncio.create_task(agent.poll_call_loop()),
    ]
