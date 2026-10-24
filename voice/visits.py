"""When a visit starts and ends, in code (never the model): it starts on an arrival or a heard
line, and ends after quiet or after the sensor's GONE. A visitor talking isn't quiet: a turn that
began before the visit ran out keeps it going. The clock is injected for tests."""

import logging
import time
from collections.abc import Callable

VISIT_TIMEOUT = 10.0  # s with nobody heard and Hazel quiet: the visitor left
AFTER_CANDY_QUIET = 10.0  # s of quiet that ends a visit once a candy request was made
GONE_GRACE = 10.0  # s after the sensor's GONE with nobody heard (the firmware already waited 10 s)

log = logging.getLogger(__name__)


class Visits:
    def __init__(self, rules, clock: Callable[[], float] = time.monotonic):
        """rules: the CandyRules, read for attempted (was a candy request made this visit), never written."""
        self.rules = rules
        self.clock = clock
        self.active = False
        self._last = 0.0  # the last heard line, or the end of Hazel's last reply
        self._gone_since: float | None = None

    def _start(self, why: str) -> None:
        log.info("visit started: %s", why)
        self.active = True
        self._last = self.clock()
        self._gone_since = None

    def arrived(self) -> bool:
        """Someone walked up (the sensor, or start-up): True if this starts a visit (greet them)."""
        if not self.active:
            self._start("someone walked up")
            return True
        if self._gone_since is not None and self.rules.attempted:
            self._start("someone walked up after the last one left")
            return True
        if self._gone_since is not None:
            log.info("sensor HERE: the same visitor is back")
        else:
            log.debug("sensor HERE during the visit: nothing to do")
        self._gone_since = None
        return False

    def heard(self) -> bool:
        """A visitor line: True if it starts a visit."""
        if not self.active:
            self._start("someone spoke")
            return True
        self._last = self.clock()
        self._gone_since = None
        return False

    def spoke(self, seconds: float) -> None:
        """A visitor turn of `seconds` of audio (its pre-roll included) just ended, before
        speech-to-text. If the visit was still on when the turn began, it still is: the turn and
        speech-to-text don't count as quiet, and a pending GONE's grace starts again."""
        if self.active and self._ended(self.clock() - seconds) is None:
            self._last = self.clock()
            if self._gone_since is not None:  # kept, not cleared: a HERE now is someone new walking up
                self._gone_since = self.clock()

    def replied(self) -> None:
        """Hazel finished talking."""
        self._last = self.clock()

    def left(self) -> None:
        """The sensor's GONE."""
        if not self.active:
            log.debug("sensor GONE with no visit: ignored")
        elif self._gone_since is None:
            log.info("sensor GONE: the visit ends in %g s unless they're heard or come back", GONE_GRACE)
            self._gone_since = self.clock()

    def expired(self) -> bool:
        """True once, when the active visit ends."""
        if not self.active or (why := self._ended(self.clock())) is None:
            return False
        log.info("visit over: %s", why)
        self.active = False
        return True

    def _ended(self, at: float) -> str | None:
        """Why the active visit was over at clock time at, or None if it was still on."""
        quiet = AFTER_CANDY_QUIET if self.rules.attempted else VISIT_TIMEOUT
        if self._gone_since is not None and at - self._gone_since >= GONE_GRACE:
            return "they walked away"
        if at - self._last >= quiet:
            return f"{quiet:g} s quiet" + (" after the candy request" if self.rules.attempted else "")
        return None
