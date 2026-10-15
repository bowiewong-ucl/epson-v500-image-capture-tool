"""Fixed-rate scan schedule. Pure logic (no Qt) so it can be unit tested.

Slots are anchored to the start time: slot k is due at ``start + k * interval``.
Times are epoch seconds, which keeps the maths correct across daylight-saving
changes. A slot that comes due while a scan is still running, or that was
missed entirely (e.g. the computer was asleep), is skipped rather than run
late, so the images stay evenly spaced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Tick:
    """What the caller should do after a poll."""

    fire: int | None = None  # slot index to scan now, if any
    skipped: list[int] = field(default_factory=list)  # slot indices given up on
    skip_reason: str = ""
    finished: bool = False  # end time reached; start no more scans


class Scheduler:
    def __init__(self, start: float, interval: float, end: float | None = None):
        if interval <= 0:
            raise ValueError("interval must be positive")
        if end is not None and end <= start:
            raise ValueError("end time must be after the start time")
        self.start = start
        self.interval = interval
        self.end = end
        self.next_index = 0

    def slot_time(self, index: int) -> float:
        return self.start + index * self.interval

    def is_finished(self, now: float) -> bool:
        return self.end is not None and now >= self.end

    def next_time(self) -> float | None:
        """When the next scan is due, or None if no more scans will happen."""
        t = self.slot_time(self.next_index)
        if self.end is not None and t >= self.end:
            return None
        return t

    def remaining_slots(self) -> int | None:
        """Scans still to come (including the next one); None if open-ended."""
        if self.end is None:
            return None
        t = self.slot_time(self.next_index)
        if t >= self.end:
            return 0
        return math.ceil((self.end - t) / self.interval)

    def poll(self, now: float, busy: bool) -> Tick:
        if self.is_finished(now):
            return Tick(finished=True)
        if now < self.start:
            return Tick()
        last_due = int((now - self.start) // self.interval)
        if last_due < self.next_index:
            return Tick()
        due = list(range(self.next_index, last_due + 1))
        self.next_index = last_due + 1
        if busy:
            return Tick(skipped=due, skip_reason="previous scan was still running")
        # Run the most recent due slot; anything older was missed.
        return Tick(fire=due[-1], skipped=due[:-1],
                    skip_reason="missed (computer asleep or busy)")
