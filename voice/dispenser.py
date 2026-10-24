"""Serial connection to the Uno running arduino/main.ino: send 'd', get back the outcome.

Opening the port resets the Uno (~2 s, then garbage bytes, then "ready"), so open one
`Dispenser` at start-up and keep it for the whole night. One caller at a time: there's no
lock, and the firmware handles one dispense at a time.

The firmware lines this relies on (arduino/main.ino):
- "ready: ..." once after a reset;
- "beam already blocked: ..." instead of dispensing, with no "dispensing" line;
- "dispensing", then "candy! after N steps" or "no candy after 15 s: ...", then a 1 s reverse;
- "beam: BLOCKED" / "beam: CLEAR" whenever the beam changes, outside a dispense;
- "someone: HERE <cm> cm" / "someone: GONE" when the HC-SR04 sees a visitor arrive or leave,
  outside a dispense;
- "distance: <cm> cm" or "distance: none" when the HC-SR04's reading changes by 50 cm or goes
  out of range, and in answer to 'p' (`Dispenser.distance`).
`Dispenser.poll()` returns the arrivals and departures; dispense lines are ignored outside
`dispense()`. `Reconnecting` wraps a Dispenser for the whole night: a lost link (USB
replug, a hub dropping out, the firmware watchdog rebooting the Uno) is reopened.
"""

import contextlib
import glob
import logging
import termios
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Self

import serial

BAUD = 115200  # matches Serial.begin() in arduino/main.ino
BOOT_TIMEOUT = 5.0  # s for the Uno to restart and print "ready"
DISPENSE_TIMEOUT = 25.0  # s; the sketch gives up 15 s after the start (MAX_SPIN_MS)
CLEAR_TIMEOUT = 2.0  # s for a dropped candy to leave the beam before dispense() returns
# where an Uno (or a CH340 clone) shows up: macOS, then Linux
PORT_PATTERNS = ("/dev/cu.usbmodem*", "/dev/cu.usbserial*", "/dev/ttyACM*", "/dev/ttyUSB*")
BEAM_REPORT_TIMEOUT = 2.0  # s; loop() reports a candy still in the beam after the 1 s reverse (BACKSPIN_MS); a candy dispense waits all of it (logs/)
READ_TIMEOUT = 0.5  # s per readline, so deadlines are checked often
DISTANCE_TIMEOUT = 0.2  # s for the answer to 'p': loop() answers within one ping (~25 ms)
WRITE_TIMEOUT = 1.0  # s, so a stalled port can't hang write()
HERE_CM = 150  # cm: closer is someone in front; matches HERE_CM in arduino/main.ino
STARTUP_WAIT = 60.0  # s voice/main.py waits for the Arduino at start-up
RECONNECT_INTERVAL = 2.0  # s from the end of one reopen try to the next while the Arduino is gone
LINK_ERRORS = (OSError, termios.error)  # SerialException is an OSError; pyserial flushes with bare termios

log = logging.getLogger(__name__)


class Outcome(StrEnum):
    CANDY = "candy"
    EMPTY = "empty"
    BLOCKED = "blocked"


class Presence(StrEnum):
    HERE = "here"
    GONE = "gone"


READY = "ready:"  # arduino/main.ino setup(): "ready: send 'd' to dispense"
DISPENSING = "dispensing"  # arduino/main.ino dispense(), once the beam is clear
REPLIES = {  # the last line of a dispense in arduino/main.ino dispense()
    "candy!": Outcome.CANDY,  # "candy! after N steps"
    "no candy": Outcome.EMPTY,  # "no candy after 15 s: ..."
    "beam already blocked": Outcome.BLOCKED,  # printed before "dispensing", then returns
}
BEAM_BLOCKED = "beam: BLOCKED"  # arduino/main.ino reportBeamChanges()
BEAM_CLEAR = "beam: CLEAR"
SOMEONE_HERE = "someone: HERE"  # arduino/main.ino reportVisitorChanges(): "someone: HERE <cm> cm"
SOMEONE_GONE = "someone: GONE"
DISTANCE = "distance:"  # arduino/main.ino reportDistance(): "distance: <cm> cm" or "distance: none"


class DispenserError(Exception):
    """The Arduino can't be used right now; the message is for the operator."""


def find_port() -> str:
    ports = sorted(p for pattern in PORT_PATTERNS for p in glob.glob(pattern))
    if not ports:
        raise DispenserError("no Arduino found: is the USB cable plugged in?")
    if len(ports) > 1:
        raise DispenserError(f"several serial ports, pick one with --port: {', '.join(ports)}")
    return ports[0]


class Dispenser:
    def __init__(self, link, on_line: Callable[[str], None] | None = None):
        """link: an open serial-like object (in_waiting, readline, write, reset_input_buffer, close).
        on_line receives every non-empty line the Arduino prints."""
        self.link = link
        self.on_line = on_line
        self._presence: list[Presence] = []  # seen since the last poll()

    @classmethod
    def open(
        cls,
        port: str | None = None,
        on_line: Callable[[str], None] | None = None,
        boot_timeout: float = BOOT_TIMEOUT,
    ) -> "Dispenser":
        """Open the port (which resets the Uno) and wait for its "ready" line."""
        port = port or find_port()
        try:
            link = serial.Serial(port, BAUD, timeout=READ_TIMEOUT, write_timeout=WRITE_TIMEOUT)
        except LINK_ERRORS as e:
            raise DispenserError(f"can't open {port}: {e}. Is the Arduino IDE's Serial Monitor open?") from e
        dispenser = cls(link, on_line)
        try:
            dispenser.wait_ready(boot_timeout)
        except BaseException:
            with contextlib.suppress(DispenserError):  # keep the error that got us here
                dispenser.close()
            raise
        log.info("Arduino ready on %s", port)
        return dispenser

    def wait_ready(self, timeout: float) -> None:
        for line in self._lines(timeout):
            if READY in line:  # reset garbage can share the line
                return
        raise DispenserError("the Arduino didn't say ready: is arduino/main.ino uploaded?")

    def dispense(self, timeout: float = DISPENSE_TIMEOUT, clear_timeout: float = CLEAR_TIMEOUT) -> Outcome:
        """Drop one candy and return what happened.

        A candy or empty result counts only after our "dispensing" line: one printed before
        it belongs to an earlier dispense, one that timed out before its result arrived.
        After a candy it waits (up to clear_timeout) for the candy to leave the beam; losing
        the link during that wait still returns CANDY, since the candy already fell.
        """
        outcome = self._send_d(timeout)
        if outcome is Outcome.CANDY:
            with contextlib.suppress(DispenserError):  # the next dispense reports the lost link
                self._wait_beam_clear(clear_timeout)
        return outcome

    def poll(self) -> list[Presence]:
        """Arrivals and departures since the last call, oldest first; never blocks. Raises
        DispenserError if the link is gone."""
        self._read_waiting()
        events, self._presence = self._presence, []
        return events

    def distance(self, timeout: float = DISTANCE_TIMEOUT) -> int | None:
        """The HC-SR04's last reading in cm, or None for no echo, no answer in time, or firmware
        without 'p'. Presence lines read on the way are kept for poll(). Raises DispenserError if
        the link is gone."""
        self._read_waiting()  # a stale answer from a timed-out call isn't taken for this one
        with self._guard():
            self.link.write(b"p")
        for line in self._lines(timeout):
            if line.startswith(DISTANCE):
                cm = line.removeprefix(DISTANCE).split()[:1]
                return int(cm[0]) if cm and cm[0].isdigit() else None
        return None

    def _send_d(self, timeout: float) -> Outcome:
        self._read_waiting()  # presence lines in the buffer survive the reset below
        with self._guard():
            self.link.reset_input_buffer()  # stale beam reports or an old result
            self.link.write(b"d")
        started = False
        for line in self._lines(timeout):
            if READY in line:  # setup() ran again: the motor stopped, no outcome will come
                raise DispenserError("the Arduino restarted during a dispense (watchdog or power)")
            if line.startswith(DISPENSING):
                started = True
            for prefix, outcome in REPLIES.items():
                if line.startswith(prefix) and (started or outcome is Outcome.BLOCKED):
                    return outcome
        raise DispenserError(f"no answer from the Arduino within {timeout:.0f} s")

    def _wait_beam_clear(self, timeout: float) -> None:
        """The firmware stops as the candy breaks the beam and reverses 1 s; if the candy is
        still in the beam then, a 'd' sent now would get "beam already blocked". No
        "beam: BLOCKED" report soon after means it had already left. A candy still there after timeout is stuck, and the next
        dispense reports BLOCKED."""
        for line in self._lines(BEAM_REPORT_TIMEOUT):
            if line.startswith(BEAM_BLOCKED):
                break
        else:
            return
        for line in self._lines(timeout):
            if line.startswith(BEAM_CLEAR):
                return

    def close(self) -> None:
        with self._guard():
            self.link.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _lines(self, timeout: float):
        """Yield each non-empty line from the Arduino until the deadline."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._guard():
                line = self.link.readline().decode(errors="replace").strip()
            if line:
                self._seen(line)
                yield line

    def _read_waiting(self) -> None:
        """Handle every line already received, without waiting for more."""
        while True:
            with self._guard():
                waiting = self.link.in_waiting
            if not waiting:
                return
            with self._guard():
                line = self.link.readline().decode(errors="replace").strip()
            if line:
                self._seen(line)

    def _seen(self, line: str) -> None:
        """Every non-empty line goes to on_line and the log, and a presence line is recorded for poll()."""
        if self.on_line:
            self.on_line(line)
        if line.startswith(SOMEONE_HERE):
            self._presence.append(Presence.HERE)
        elif line.startswith(SOMEONE_GONE):
            self._presence.append(Presence.GONE)
        elif line.startswith(DISTANCE):
            log.debug("sensor: %s", line)
            return
        else:
            log.debug("arduino: %s", line)
            return
        log.info("sensor: %s", line)  # the whole line: HERE carries the distance

    @contextlib.contextmanager
    def _guard(self):
        try:
            yield
        except LINK_ERRORS as e:
            raise DispenserError(f"lost the Arduino: {e}. Is the USB cable plugged in?") from e


class Reconnecting:
    """A Dispenser that survives a USB replug: a lost link is closed and reopened, finding the
    port again (so /dev/ttyACM0 may come back as /dev/ttyACM1). While the Arduino is gone,
    poll() returns no events, distance() and dispense() raise DispenserError (CandyRules
    answers BROKEN). on_change(connected, detail) hears each loss and each return."""

    def __init__(
        self,
        port: str | None = None,
        on_line: Callable[[str], None] | None = None,
        on_change: Callable[[bool, str], None] = lambda connected, detail: None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., Dispenser] | None = None,
    ):
        self.port = port
        self.on_line = on_line
        self.on_change = on_change
        self.clock = clock
        self.sleep = sleep
        self.opener = opener or (lambda *args, **kwargs: Dispenser.open(*args, **kwargs))  # looked up per call: tests patch it
        self.inner: Dispenser | None = None
        self._next_try = 0.0  # clock time of the next reopen try while gone

    @property
    def connected(self) -> bool:
        return self.inner is not None

    def wait_connected(self, timeout: float) -> None:
        """Start-up: try every RECONNECT_INTERVAL until connected (at least once), else raise the
        last DispenserError. The first connection isn't reported to on_change."""
        deadline = self.clock() + timeout
        first = True
        while True:
            try:
                self.inner = self.opener(self.port, on_line=self.on_line)
                return
            except DispenserError as e:
                if self.clock() >= deadline:
                    raise
                if first:
                    log.warning("waiting up to %g s for the Arduino: %s", timeout, e)
                    first = False
            self.sleep(RECONNECT_INTERVAL)

    def poll(self) -> list[Presence]:
        """Arrivals and departures, or [] while the Arduino is gone (a reopen is tried at most
        every RECONNECT_INTERVAL). Never raises DispenserError."""
        if self.inner is None:
            if self.clock() >= self._next_try:
                self._try()
            return []
        try:
            return self.inner.poll()
        except DispenserError as e:
            self._lost(e)
            return []

    def dispense(self) -> Outcome:
        """While gone, one reopen try first (up to BOOT_TIMEOUT), else DispenserError."""
        if self.inner is None:
            self._try()  # now, whatever the interval: a visitor is waiting
        with self._watch():
            return self.inner.dispense()

    def distance(self, timeout: float = DISTANCE_TIMEOUT) -> int | None:
        with self._watch():
            return self.inner.distance(timeout)

    def close(self) -> None:
        """Never raises: the link may be gone already."""
        if self.inner is not None:
            with contextlib.suppress(DispenserError):
                self.inner.close()
            self.inner = None

    def _try(self) -> None:
        try:
            self.inner = self.opener(self.port, on_line=self.on_line)
        except DispenserError as e:
            log.debug("Arduino not back yet: %s", e)
            self._next_try = self.clock() + RECONNECT_INTERVAL
            return
        log.info("Arduino back")  # Dispenser.open just logged the port
        self.on_change(True, "")

    def _lost(self, e: DispenserError) -> None:
        log.warning("lost the Arduino (%s): reconnecting", e)
        self.close()
        self._next_try = self.clock() + RECONNECT_INTERVAL
        self.on_change(False, str(e))

    @contextlib.contextmanager
    def _watch(self):
        """Raise while gone; a DispenserError from the link marks it lost, then propagates."""
        if self.inner is None:
            raise DispenserError("the Arduino is disconnected")
        try:
            yield
        except DispenserError as e:
            self._lost(e)
            raise
