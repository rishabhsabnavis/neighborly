from __future__ import annotations

import threading

from app.models import Step, StepKind
from app.timeutil import now_iso


class StepLog:
    """Append-only log. The console and the Nvidia demo both read this."""

    def __init__(self) -> None:
        self._steps: list[Step] = []
        self._next = 1
        self._lock = threading.Lock()

    def add(
        self,
        kind: StepKind,
        text: str,
        *,
        policyholder_id: str | None = None,
        tool: str | None = None,
        ms: int | None = None,
    ) -> Step:
        with self._lock:
            step = Step(
                id=self._next,
                ts=now_iso(),
                kind=kind,
                policyholder_id=policyholder_id,
                tool=tool,
                text=text,
                ms=ms,
            )
            self._next += 1
            self._steps.append(step)
            if len(self._steps) > 1000:
                self._steps = self._steps[-1000:]
            return step

    def since(self, after: int | None) -> list[Step]:
        with self._lock:
            if after is None:
                return list(self._steps)
            return [step for step in self._steps if step.id > after]

    def clear(self) -> None:
        with self._lock:
            self._steps.clear()
            self._next = 1
