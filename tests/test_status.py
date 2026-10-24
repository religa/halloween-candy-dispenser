"""The operator's status line, offline: a fixed clock and a list for the printed lines."""

import time

from voice.status import HEARTBEAT, PARTS, Status

NINE_PM = time.mktime((2026, 10, 31, 19, 16, 0, 0, 0, -1))  # local time


def make_status(**kwargs):
    out = []
    status = Status(write=out.append, clock=lambda: NINE_PM, **kwargs)
    return status, out


def test_line_shows_parts_counts_and_last_error():
    status, _ = make_status(candies=lambda: 2)
    assert status.line() == "status: arduino OK · mic OK · LLM OK · ears OK · voice OK · visits 0 · candies 2"
    status.visit()
    status.visit()
    status.visit()
    status.set("arduino", False, "lost the Arduino: device disconnected")
    assert status.line() == (
        "status: arduino LOST · mic OK · LLM OK · ears OK · voice OK · visits 3 · candies 2 · last error 19:16 arduino: lost the Arduino: device disconnected"
    )
    status.set("arduino", True)
    assert status.line().startswith("status: arduino OK")
    assert status.line().endswith("last error 19:16 arduino: lost the Arduino: device disconnected")  # kept after recovery


def test_set_prints_only_on_change():
    status, out = make_status()
    status.set("LLM", True)
    assert out == []
    status.set("LLM", False, "APIConnectionError: Connection error.")
    status.set("LLM", False, "APITimeoutError: Request timed out.")
    assert len(out) == 1 and "LLM LOST" in out[0]
    assert status.line().endswith("LLM: APITimeoutError: Request timed out.")  # the latest
    status.set("LLM", True)
    assert len(out) == 2 and "LLM OK" in out[1]


def test_visit_does_not_print_and_show_does():
    status, out = make_status()
    status.visit()
    assert out == []
    status.show()
    assert out == ["status: arduino OK · mic OK · LLM OK · ears OK · voice OK · visits 1 · candies 0"]


def test_parts_can_be_left_out():
    status, _ = make_status(parts=("LLM",))
    assert status.line() == "status: LLM OK · visits 0 · candies 0"
    assert set(PARTS) == {"arduino", "mic", "LLM", "ears", "voice"}


def test_distance_is_asked_each_time_the_line_is_printed():
    readings = iter(["87 cm", "none"])
    status, out = make_status(parts=("arduino",), distance=lambda: next(readings))
    status.show()
    status.show()
    assert out == ["status: arduino OK · distance 87 cm · visits 0 · candies 0", "status: arduino OK · distance none · visits 0 · candies 0"]


def test_set_ignores_parts_left_out():
    status, out = make_status(parts=("LLM",))
    status.set("arduino", False, "lost")
    assert out == []
    assert "last error" not in status.line()


def test_detail_is_truncated():
    status, _ = make_status()
    status.set("ears", False, "x" * 200)
    assert status.line().endswith("ears: " + "x" * 80)


def test_beat_prints_the_line_every_heartbeat_since_it_was_last_shown():
    now = [NINE_PM]
    out = []
    status = Status(write=out.append, clock=lambda: now[0])
    assert HEARTBEAT == 15 * 60  # the user's number, written out
    now[0] += HEARTBEAT - 1
    status.beat()
    assert out == []
    now[0] += 1
    status.beat()
    assert len(out) == 1
    now[0] += HEARTBEAT / 2
    status.set("LLM", False, "APIConnectionError: Connection error.")  # a change prints it too
    now[0] += HEARTBEAT / 2
    status.beat()
    assert len(out) == 2  # counted from that change, not from the last beat
    now[0] += HEARTBEAT / 2
    status.beat()
    assert len(out) == 3 and "LLM LOST" in out[2]
