"""The candy limit lives here, in code: the LLM asks, this decides.

This is the only module that calls `Dispenser.dispense()` (guarded by a test in
tests/test_rules.py). Up to MAX_GROUP candies per visit in one request, whatever the outcome,
so an empty bucket isn't spun again for the same visitor; COOLDOWN between requests, waited out.
"""

import logging
import time
from collections.abc import Callable

from voice.dispenser import DispenserError, Outcome

MAX_GROUP = 3  # candies for one visit, for a group that says so
COOLDOWN = 15.0  # s from the end of one request's dispensing to the next request's first: rate-limits re-triggered visits

# Tool results: the model reads them, voice/persona.md explains them.
GIVEN = "candy given: candy came down the chute"  # never a count: the chute sometimes drops more than one
REPLY = {  # one per voice/dispenser.py Outcome
    Outcome.CANDY: GIVEN,
    Outcome.EMPTY: "no candy: the bucket is empty",
    Outcome.BLOCKED: "no candy: the chute is blocked",
}
BROKEN = "no candy: the dispenser isn't working right now"
ALREADY = "refused: this visit already had its candy; a new trick-or-treater should step back and come up again"
NO_RETRY = "no candy: the dispenser already failed for this visitor and can't try again"
CAPPED = f"; {MAX_GROUP} is the most for one visit"

log = logging.getLogger(__name__)


def group_given(k: int) -> str:
    return f"candy given: candy came down the chute for all {k} kids"


def partial_given(k: int, n: int, failure: str) -> str:
    return f"candy given: candy came down the chute for {k} of the {n} kids, then {failure}"


def _clamp(count) -> tuple[int, bool]:
    """The model's count as 1..MAX_GROUP, and whether it asked for more. Anything that isn't a
    number means 1: the schema isn't trusted."""
    try:
        n = int(count)
    except (TypeError, ValueError, OverflowError):
        n = 1
    return max(1, min(n, MAX_GROUP)), n > MAX_GROUP


class CandyRules:
    def __init__(
        self,
        dispenser,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        """dispenser: anything with dispense() -> Outcome."""
        self.dispenser = dispenser
        self.clock = clock
        self.sleep = sleep
        self._last_dispense: float | None = None  # kept across visits: the cooldown outlives them
        self.total_given = 0  # candies dropped this evening, for the status line
        self.new_visit()

    def new_visit(self) -> None:
        self.attempted = False
        self.given = 0  # candies dropped this visit

    def request_candy(self, count=1) -> str:
        """Try to drop count candies (one per kid) and return the tool result for the model."""
        if self.attempted:
            log.info("refused: already tried this visit")
            return ALREADY if self.given else NO_RETRY
        n, capped = _clamp(count)
        log.info("candy request: count %d", n)
        if capped:
            log.info("asked for %.20r, capped at %d", count, MAX_GROUP)
        self.attempted = True  # before dispensing, so an exception can't leave the visit re-armed
        try:
            if self._last_dispense is not None and (wait := self._last_dispense + COOLDOWN - self.clock()) > 0:
                log.info("cooldown: waiting %.1f s", wait)
                self.sleep(wait)
            failure = self._dispense(n)
        finally:
            self._last_dispense = self.clock()  # a failed request rate-limits too
        if not self.given:
            result = failure
        elif n == 1:
            result = GIVEN
        elif self.given == n:
            result = group_given(n)
        else:
            result = partial_given(self.given, n, failure)
        return result + CAPPED if capped else result

    def _dispense(self, n: int) -> str | None:
        """Drop up to n candies, stopping at the first failure; return that failure's result."""
        for _ in range(n):
            try:
                outcome = self.dispenser.dispense()
            except DispenserError as e:
                log.warning("dispenser error: %s", e)
                return BROKEN
            log.info("dispensed: %s", outcome)
            if outcome is not Outcome.CANDY:
                return REPLY[outcome]
            self.given += 1
            self.total_given += 1
        return None
