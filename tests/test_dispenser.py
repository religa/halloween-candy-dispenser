"""Dispenser serial protocol, checked offline against a fake link and the firmware source."""

import logging
import re
import shutil
import subprocess
import termios
import time
from pathlib import Path

import pytest
import serial
import voice.dispenser
from test_rules import FakeClock
from voice.dispenser import (
    BEAM_BLOCKED,
    BEAM_CLEAR,
    DISPENSING,
    DISTANCE,
    READY,
    REPLIES,
    SOMEONE_GONE,
    SOMEONE_HERE,
    Dispenser,
    DispenserError,
    Outcome,
    Presence,
    Reconnecting,
    find_port,
)

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "arduino" / "main.ino"
WIRING = ROOT / "docs" / "wiring.md"
# arduino-cli on the PATH (Linux, Homebrew), else the copy bundled with the macOS Arduino IDE
IDE_ARDUINO_CLI = Path("/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli")
ARDUINO_CLI = shutil.which("arduino-cli") or (str(IDE_ARDUINO_CLI) if IDE_ARDUINO_CLI.exists() else None)
READY_LINE = "ready: send 'd' to dispense"
# the order arduino/main.ino prints them: loop() reports the candy in the beam after dispense() returns
CANDY = ["dispensing", "candy! after 312 steps", "beam: BLOCKED", "beam: CLEAR"]
EMPTY = ["dispensing", "no candy after 15 s: refill the bucket or check for a jam"]
BLOCKED = ["beam already blocked: candy stuck in the chute, or the heads are misaligned"]
TIMEOUT = 0.2


class FakeLink:
    """Serial stand-in: readline() pops a queue; every write() queues a fresh copy of replies."""

    def __init__(self, boot=(), replies=(), in_waiting_error=None):
        self.queue = list(boot)
        self.replies = list(replies)
        self.in_waiting_error = in_waiting_error
        self.written = []
        self.resets = 0
        self.reads = 0
        self.closed = False

    @property
    def in_waiting(self):  # pyserial's is a byte count; the code only tests > 0
        if self.in_waiting_error:
            raise self.in_waiting_error
        return len(self.queue)

    def write(self, data):
        self.written.append(data)
        self.queue.extend(self.replies)

    def readline(self):
        self.reads += 1
        if not self.queue:
            time.sleep(0.01)  # like a real port's read timeout, so deadline loops don't spin
            return b""
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, bytes) else item.encode() + b"\r\n"

    def reset_input_buffer(self):
        self.queue.clear()
        self.resets += 1

    def close(self):
        self.closed = True


def test_candy_reply_is_candy():
    link = FakeLink(replies=CANDY)
    assert Dispenser(link).dispense(TIMEOUT) is Outcome.CANDY
    assert link.written == [b"d"]


def test_empty_reply_is_empty():
    assert Dispenser(FakeLink(replies=EMPTY)).dispense(TIMEOUT) is Outcome.EMPTY


def test_blocked_reply_is_blocked():
    assert Dispenser(FakeLink(replies=BLOCKED)).dispense(TIMEOUT) is Outcome.BLOCKED


def test_earlier_dispense_result_before_ours_is_ignored():
    link = FakeLink(replies=["no candy after 15 s: ...", "dispensing", "candy! after 90 steps", "beam: CLEAR"])
    assert Dispenser(link).dispense(TIMEOUT) is Outcome.CANDY


def test_stale_lines_are_dropped_before_sending():
    link = FakeLink(boot=BLOCKED, replies=EMPTY)  # a stale "blocked" would pass the "dispensing" gate
    assert Dispenser(link).dispense(TIMEOUT) is Outcome.EMPTY
    assert link.resets == 1


def test_garbage_before_ready_is_skipped():
    link = FakeLink(boot=[b"\xff\xfe\x00garbage", READY_LINE], replies=CANDY)
    d = Dispenser(link)
    d.wait_ready(TIMEOUT)
    assert d.dispense(TIMEOUT) is Outcome.CANDY


def test_silent_arduino_times_out():
    start = time.monotonic()
    with pytest.raises(DispenserError, match="no answer"):
        Dispenser(FakeLink()).dispense(TIMEOUT)
    assert time.monotonic() - start < 1


def test_garbage_on_the_ready_line_is_skipped():
    Dispenser(FakeLink(boot=[b"\xff\xfe\x00" + READY_LINE.encode() + b"\r\n"])).wait_ready(TIMEOUT)


def test_no_ready_times_out():
    with pytest.raises(DispenserError, match="didn't say ready"):
        Dispenser(FakeLink(boot=[b"\xff\xfe\x00garbage"])).wait_ready(TIMEOUT)


def test_unplug_mid_dispense_raises_dispenser_error():
    unplug = serial.SerialException("device disconnected")
    with pytest.raises(DispenserError, match="lost the Arduino") as err:
        Dispenser(FakeLink(replies=["dispensing", unplug])).dispense(TIMEOUT)
    assert err.value.__cause__ is unplug


def test_candy_waits_for_the_beam_to_clear():
    # the next 'd' would find the candy still in the beam and report "beam already blocked"
    link = FakeLink(replies=[*CANDY, "after"])
    assert Dispenser(link).dispense(TIMEOUT, clear_timeout=TIMEOUT) is Outcome.CANDY
    assert link.queue == ["after"]


def test_candy_already_out_of_the_beam_returns_without_waiting(monkeypatch):
    # no beam report after "candy!": the candy left during the backspin, before loop() looked
    monkeypatch.setattr(voice.dispenser, "BEAM_REPORT_TIMEOUT", TIMEOUT)
    start = time.monotonic()
    link = FakeLink(replies=["dispensing", "candy! after 312 steps"])
    assert Dispenser(link).dispense(TIMEOUT, clear_timeout=5) is Outcome.CANDY
    assert time.monotonic() - start < 1


def test_candy_that_never_clears_the_beam_is_still_candy():
    start = time.monotonic()
    link = FakeLink(replies=["dispensing", "candy! after 312 steps", "beam: BLOCKED"])
    assert Dispenser(link).dispense(TIMEOUT, clear_timeout=TIMEOUT) is Outcome.CANDY
    assert time.monotonic() - start < 1


def test_unplug_after_candy_is_still_candy():
    # the candy already fell; losing the link while waiting for the beam can't undo that
    link = FakeLink(replies=["dispensing", "candy! after 312 steps", serial.SerialException("device disconnected")])
    assert Dispenser(link).dispense(TIMEOUT, clear_timeout=TIMEOUT) is Outcome.CANDY


def test_failed_flush_raises_dispenser_error():
    class BrokenFlush(FakeLink):  # pyserial's reset_input_buffer() is termios.tcflush, unwrapped
        def reset_input_buffer(self):
            raise termios.error(6, "Device not configured")

    with pytest.raises(DispenserError, match="lost the Arduino"):
        Dispenser(BrokenFlush()).dispense(TIMEOUT)


def test_failed_write_raises_dispenser_error():
    class BrokenWrite(FakeLink):
        def write(self, data):
            raise OSError("gone")

    with pytest.raises(DispenserError, match="lost the Arduino"):
        Dispenser(BrokenWrite()).dispense(TIMEOUT)


def test_on_line_errors_are_not_blamed_on_the_arduino():
    def broken_pipe(line):
        raise BrokenPipeError("stdout closed")

    with pytest.raises(BrokenPipeError):
        Dispenser(FakeLink(replies=CANDY), on_line=broken_pipe).dispense(TIMEOUT)


def test_one_connection_serves_many_candies():
    link = FakeLink(replies=CANDY)
    d = Dispenser(link)
    assert [d.dispense(TIMEOUT) for _ in range(3)] == [Outcome.CANDY] * 3
    assert link.written == [b"d"] * 3
    assert not link.closed


def test_on_line_sees_every_line():
    seen = []
    Dispenser(FakeLink(boot=["", READY_LINE], replies=CANDY), on_line=seen.append).wait_ready(TIMEOUT)
    assert seen == [READY_LINE]
    seen.clear()
    Dispenser(FakeLink(replies=CANDY), on_line=seen.append).dispense(TIMEOUT)
    assert seen == CANDY


def test_context_manager_closes_link():
    link = FakeLink()
    with Dispenser(link) as d:
        assert d.link is link
    assert link.closed


def test_find_port_errors(monkeypatch):
    def fake_glob(ports):
        monkeypatch.setattr(voice.dispenser.glob, "glob", lambda pattern: [p for p in ports if p.startswith(pattern[:-1])])

    fake_glob([])
    with pytest.raises(DispenserError, match="no Arduino found"):
        find_port()
    fake_glob(["/dev/cu.usbmodem1", "/dev/cu.usbserial2"])
    with pytest.raises(DispenserError, match="several serial ports"):
        find_port()
    fake_glob(["/dev/cu.usbmodem14101"])
    assert find_port() == "/dev/cu.usbmodem14101"
    fake_glob(["/dev/ttyACM0"])  # Uno on Linux
    assert find_port() == "/dev/ttyACM0"
    fake_glob(["/dev/ttyUSB0"])  # CH340 clone on Linux
    assert find_port() == "/dev/ttyUSB0"
    fake_glob(["/dev/ttyACM0", "/dev/ttyUSB0"])
    with pytest.raises(DispenserError, match="several serial ports"):
        find_port()
    fake_glob(["/dev/ttyS0", "/dev/tty1"])  # built-in serial and consoles are never the Uno
    with pytest.raises(DispenserError, match="no Arduino found"):
        find_port()


def test_replies_match_firmware():
    calls = re.findall(r"Serial\.print(?:ln)?\((.*?)\);", FIRMWARE.read_text())
    literals = [s for call in calls for s in re.findall(r'"([^"]*)"', call)]
    for prefix in [READY, DISPENSING, BEAM_BLOCKED, BEAM_CLEAR, SOMEONE_HERE, SOMEONE_GONE, DISTANCE, *REPLIES]:
        assert any(s.startswith(prefix) for s in literals), f"{prefix!r} not printed by {FIRMWARE.name}"


def test_open_closes_link_when_not_ready(monkeypatch):
    fake = FakeLink(boot=[b"\xff\xfe\x00garbage"])
    monkeypatch.setattr(voice.dispenser.serial, "Serial", lambda port, baud, timeout, write_timeout: fake)
    with pytest.raises(DispenserError, match="didn't say ready"):
        Dispenser.open(port="x", boot_timeout=TIMEOUT)
    assert fake.closed


def test_open_wraps_termios_errors(monkeypatch):
    def serial_that_fails_to_flush(*args, **kwargs):  # pyserial's open() ends with a bare tcflush
        raise termios.error(6, "Device not configured")

    monkeypatch.setattr(voice.dispenser.serial, "Serial", serial_that_fails_to_flush)
    with pytest.raises(DispenserError, match="can't open x"):
        Dispenser.open(port="x", boot_timeout=TIMEOUT)


def test_open_keeps_the_ready_error_when_close_fails(monkeypatch):
    class BrokenClose(FakeLink):
        def close(self):
            raise OSError("gone")

    monkeypatch.setattr(voice.dispenser.serial, "Serial", lambda *a, **k: BrokenClose())
    with pytest.raises(DispenserError, match="didn't say ready"):
        Dispenser.open(port="x", boot_timeout=TIMEOUT)


def test_poll_returns_arrivals_and_departures_in_order():
    d = Dispenser(FakeLink(boot=["someone: HERE 85 cm", "beam: CLEAR", "someone: GONE"]))
    assert d.poll() == [Presence.HERE, Presence.GONE]
    assert d.poll() == []


def test_poll_ignores_dispense_lines():
    link = FakeLink(boot=CANDY)
    assert Dispenser(link).poll() == []
    assert link.written == []


def test_presence_seen_during_a_dispense_is_kept():
    d = Dispenser(FakeLink(replies=["dispensing", "someone: HERE 70 cm", "candy! after 312 steps", "beam: CLEAR"]))
    assert d.dispense(TIMEOUT, clear_timeout=TIMEOUT) is Outcome.CANDY
    assert d.poll() == [Presence.HERE]


def test_presence_waiting_before_d_is_kept():
    link = FakeLink(boot=["someone: GONE", *BLOCKED], replies=EMPTY)
    d = Dispenser(link)
    assert d.dispense(TIMEOUT) is Outcome.EMPTY  # the stale "blocked" is read, not taken as the outcome
    assert link.resets == 1
    assert d.poll() == [Presence.GONE]


def test_poll_never_blocks():
    link = FakeLink()
    start = time.monotonic()
    assert Dispenser(link).poll() == []
    assert time.monotonic() - start < 0.05
    assert link.reads == 0


def test_poll_on_a_lost_link_raises_dispenser_error():
    with pytest.raises(DispenserError, match="lost the Arduino"):
        Dispenser(FakeLink(in_waiting_error=OSError("Device not configured"))).poll()


def test_on_line_errors_in_poll_are_not_blamed_on_the_arduino():
    def broken_pipe(line):
        raise BrokenPipeError("stdout closed")

    with pytest.raises(BrokenPipeError):
        Dispenser(FakeLink(boot=["someone: GONE"]), on_line=broken_pipe).poll()


def test_garbled_presence_line_is_ignored():
    assert Dispenser(FakeLink(boot=["someone: HERx 3 cm"])).poll() == []


def test_wiring_doc_names_every_firmware_pin():
    wiring = WIRING.read_text()
    pins = re.findall(r"const int (\w+)_PIN = (\d+);", FIRMWARE.read_text())
    assert len(pins) >= 6
    for name, n in pins:
        assert f"pin {n}" in wiring, f"{name}_PIN = {n} not in {WIRING.name}"
    assert "TRIG" in wiring and "ECHO" in wiring


def test_firmware_compiles(tmp_path):
    if ARDUINO_CLI is None:
        pytest.skip("needs arduino-cli (or the Arduino IDE, which bundles it)")
    sketch = tmp_path / "main"
    sketch.mkdir()
    shutil.copy(FIRMWARE, sketch / "main.ino")
    result = subprocess.run([ARDUINO_CLI, "compile", "--fqbn", "arduino:avr:uno", str(sketch)], capture_output=True, text=True, timeout=300, check=False)
    assert result.returncode == 0, result.stderr
    assert "Sketch uses" in result.stdout


def test_sensor_lines_are_logged_at_info_and_the_rest_at_debug(caplog):
    caplog.set_level("DEBUG", logger="voice.dispenser")
    lines = ["distance: 85 cm", "someone: HERE 85 cm", "beam: CLEAR", "distance: none", "someone: GONE"]
    Dispenser(FakeLink(boot=lines)).poll()
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("DEBUG", "sensor: distance: 85 cm"),
        ("INFO", "sensor: someone: HERE 85 cm"),
        ("DEBUG", "arduino: beam: CLEAR"),
        ("DEBUG", "sensor: distance: none"),
        ("INFO", "sensor: someone: GONE"),
    ]


def test_firmware_reports_distance_changes_from_the_ping_loop():
    firmware = FIRMWARE.read_text()
    ping_loop = firmware[firmware.index("void reportVisitorChanges()") :]
    ping_loop = ping_loop[: ping_loop.index("\n}\n")]
    assert "reportDistanceChange(cm);" in ping_loop
    assert re.search(r"const int REPORT_STEP_CM = 50;", firmware)
    assert re.search(r"const int MAX_CM = 200;", firmware)  # the user's 2 m, written out


def test_here_cm_matches_the_firmware():
    firmware = FIRMWARE.read_text()
    assert re.search(r"const int HERE_CM = 150;", firmware)  # 150 cm, written out
    assert voice.dispenser.HERE_CM == 150


def test_distance_asks_with_p_and_reads_the_answer():
    link = FakeLink(replies=["distance: 85 cm"])
    assert Dispenser(link).distance(TIMEOUT) == 85
    assert link.written == [b"p"]


def test_distance_with_no_echo_is_none():
    assert Dispenser(FakeLink(replies=["distance: none"])).distance(TIMEOUT) is None


@pytest.mark.parametrize("line", ["distance:", "distance: x cm"])
def test_garbled_distance_answer_is_none(line):
    assert Dispenser(FakeLink(replies=[line])).distance(TIMEOUT) is None


def test_no_distance_answer_is_none_and_quick():
    start = time.monotonic()
    assert Dispenser(FakeLink()).distance(TIMEOUT) is None  # e.g. older firmware without 'p'
    assert time.monotonic() - start < 1


def test_presence_read_while_asking_for_the_distance_is_kept():
    d = Dispenser(FakeLink(boot=["someone: HERE 70 cm"], replies=["someone: GONE", "distance: none"]))
    assert d.distance(TIMEOUT) is None
    assert d.poll() == [Presence.HERE, Presence.GONE]


def test_a_stale_distance_answer_is_not_taken_for_the_new_one():
    link = FakeLink(boot=["distance: 40 cm"], replies=["distance: 120 cm"])
    assert Dispenser(link).distance(TIMEOUT) == 120


def test_distance_on_a_lost_link_raises_dispenser_error():
    with pytest.raises(DispenserError, match="lost the Arduino"):
        Dispenser(FakeLink(in_waiting_error=OSError("Device not configured"))).distance(TIMEOUT)


def test_ready_after_d_means_the_arduino_restarted():
    start = time.monotonic()
    with pytest.raises(DispenserError, match="restarted"):
        Dispenser(FakeLink(boot=(), replies=["dispensing", READY_LINE])).dispense()  # the default 25 s timeout
    assert time.monotonic() - start < 1


class Opener:
    """Dispenser.open stand-in for Reconnecting: each call takes the next result, an exception
    (raised) or a link (opened as a Dispenser); the last one repeats."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, port, on_line=None):
        self.calls.append(port)
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return Dispenser(result, on_line)


NO_ARDUINO = DispenserError("no Arduino found: is the USB cable plugged in?")


def reconnecting(opener, clock=None, changes=None):
    clock = clock or FakeClock()
    changes = [] if changes is None else changes
    return Reconnecting(opener=opener, on_change=lambda ok, detail: changes.append((ok, detail)), clock=clock, sleep=clock.sleep)


def test_wait_connected_does_not_report_a_change():
    opener, changes = Opener(FakeLink()), []
    d = reconnecting(opener, changes=changes)
    d.wait_connected(0)
    assert d.connected
    assert changes == []
    assert len(opener.calls) == 1


def test_reconnecting_waits_for_the_arduino_at_start_up(caplog):
    caplog.set_level(logging.WARNING, logger="voice.dispenser")
    opener, clock = Opener(NO_ARDUINO, NO_ARDUINO, FakeLink()), FakeClock()
    d = reconnecting(opener, clock)
    d.wait_connected(60)
    assert d.connected
    assert len(opener.calls) == 3
    assert clock.slept == [voice.dispenser.RECONNECT_INTERVAL] * 2
    assert [r.getMessage() for r in caplog.records] == [f"waiting up to 60 s for the Arduino: {NO_ARDUINO}"]


def test_reconnecting_gives_up_after_the_start_up_wait():
    clock = FakeClock()
    d = reconnecting(Opener(NO_ARDUINO), clock)
    with pytest.raises(DispenserError, match="no Arduino found"):
        d.wait_connected(60)
    assert clock.now >= 60
    assert not d.connected


def test_lost_link_in_poll_reconnects(caplog):
    caplog.set_level(logging.INFO, logger="voice.dispenser")
    clock, changes = FakeClock(), []
    opener = Opener(FakeLink(in_waiting_error=OSError("Device not configured")), FakeLink(boot=["someone: HERE 80 cm"]))
    d = reconnecting(opener, clock, changes)
    d.wait_connected(0)
    assert d.poll() == []
    assert not d.connected
    assert changes == [(False, "lost the Arduino: Device not configured. Is the USB cable plugged in?")]
    assert "lost the Arduino" in caplog.text
    clock.now += voice.dispenser.RECONNECT_INTERVAL / 2
    assert d.poll() == []
    assert len(opener.calls) == 1  # too soon to try again
    clock.now += voice.dispenser.RECONNECT_INTERVAL
    assert d.poll() == []  # this tick reopens; the next one reads
    assert d.connected
    assert len(opener.calls) == 2
    assert changes[-1] == (True, "")
    assert "Arduino back" in caplog.text
    assert d.poll() == [Presence.HERE]


def test_dispense_while_gone_tries_once_then_raises():
    opener = Opener(FakeLink(in_waiting_error=OSError("gone")), NO_ARDUINO)
    d = reconnecting(opener)
    d.wait_connected(0)
    d.poll()  # loses the link
    with pytest.raises(DispenserError, match="disconnected"):
        d.dispense()
    assert len(opener.calls) == 2
    opener.results = [FakeLink(replies=CANDY)]
    assert d.dispense() is Outcome.CANDY
    assert d.connected


def test_lost_link_mid_dispense_is_reraised_and_reconnects_later():
    changes = []
    d = reconnecting(Opener(FakeLink(replies=["dispensing", serial.SerialException("device disconnected")])), changes=changes)
    d.wait_connected(0)
    with pytest.raises(DispenserError, match="lost the Arduino"):
        d.dispense()
    assert not d.connected
    assert changes[0][0] is False


def test_reconnecting_close_never_raises():
    class BrokenClose(FakeLink):
        def close(self):
            raise OSError("gone")

    d = reconnecting(Opener(BrokenClose()))
    d.wait_connected(0)
    d.close()
    reconnecting(Opener(NO_ARDUINO)).close()  # never connected


def test_distance_while_gone_raises():
    d = reconnecting(Opener(FakeLink(in_waiting_error=OSError("gone")), NO_ARDUINO))
    d.wait_connected(0)
    d.poll()
    with pytest.raises(DispenserError, match="disconnected"):
        d.distance()


def test_reconnecting_looks_up_dispenser_open_at_call_time(monkeypatch):
    seen = []
    monkeypatch.setattr(Dispenser, "open", lambda *a, **k: seen.append((a, k)) or Dispenser(FakeLink()))
    d = Reconnecting("/dev/ttyACM1", on_line=print)
    d.wait_connected(0)
    assert seen == [(("/dev/ttyACM1",), {"on_line": print})]


def loop_bodies(source):
    """(condition, body) of every while/for loop in C source, braces matched."""
    for m in re.finditer(r"\b(?:while|for) \((.*?)\) \{", source):
        depth, i = 1, m.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(source[i], 0)
            i += 1
        yield m.group(1), source[m.end() : i]


def test_every_long_firmware_loop_feeds_the_watchdog():
    firmware = FIRMWARE.read_text()
    loops = list(loop_bodies(firmware))
    assert len(loops) == len(re.findall(r"\b(?:while|for|do)\b", re.sub(r'//.*|"[^"]*"', "", firmware)))  # none written another way
    for condition, body in loops:
        if condition == "Serial.available() > 0":
            continue  # drains at most the 64-byte RX buffer
        assert "wdt_reset();" in body, f"loop ({condition}) doesn't feed the watchdog"
    setup = firmware[firmware.index("void setup() {") :]
    setup = setup[: setup.index("\n}\n")]
    assert setup.split("{", 1)[1].lstrip().startswith("MCUSR = 0;")
    assert "wdt_enable(WDTO_2S);" in setup
    main_loop = firmware[firmware.index("void loop() {") :]
    assert main_loop.split("{", 1)[1].lstrip().startswith("wdt_reset();")
