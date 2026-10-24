"""When visits start and end, on a fake clock: arrivals, heard lines, quiet, and the sensor's GONE."""

from test_rules import FakeClock
from voice.visits import Visits


class StubRules:
    """CandyRules stand-in: Visits only reads attempted."""

    attempted = False


def make_visits():
    rules, clock = StubRules(), FakeClock()
    return Visits(rules, clock), rules, clock


def test_first_arrival_starts_a_visit_and_a_second_does_not():
    visits, _, _ = make_visits()
    assert visits.arrived()
    assert visits.active
    assert not visits.arrived()


def test_arrival_after_gone_starts_a_new_visit_once_candy_was_requested():
    visits, rules, clock = make_visits()
    visits.arrived()
    rules.attempted = True
    visits.left()
    clock.now = 1.0
    assert visits.arrived()


def test_arrival_after_gone_without_a_request_is_the_same_visitor():
    visits, _, clock = make_visits()
    visits.arrived()
    visits.left()
    clock.now = 1.0
    assert not visits.arrived()
    clock.now = 5.0
    assert not visits.expired()  # the pending GONE was cancelled
    assert visits.active


def test_heard_line_starts_a_visit_when_idle():
    visits, _, _ = make_visits()
    assert visits.heard()
    assert visits.active
    assert not visits.heard()


def test_visit_ends_after_visit_timeout_of_quiet():
    visits, _, clock = make_visits()
    visits.arrived()
    clock.now = 9.9
    assert not visits.expired()
    clock.now = 10.0  # the user's number, written out
    assert visits.expired()
    assert not visits.active
    assert not visits.expired()  # once


def test_visit_ends_after_quiet_after_a_candy_request():
    visits, rules, clock = make_visits()
    visits.arrived()
    rules.attempted = True
    clock.now = 3.0
    visits.replied()
    clock.now = 12.9
    assert not visits.expired()
    clock.now = 13.0  # 10 s after Hazel stopped, the user's number
    assert visits.expired()


def test_speech_and_replies_keep_the_visit_alive():
    visits, _, clock = make_visits()
    visits.arrived()
    clock.now = 8.0
    visits.heard()
    clock.now = 17.0
    assert not visits.expired()
    clock.now = 18.0
    assert visits.expired()


def test_gone_ends_the_visit_after_the_grace():
    visits, _, clock = make_visits()
    visits.arrived()
    clock.now = 4.0
    visits.left()
    visits.replied()  # the quiet alone would end it at 14 s too
    clock.now = 13.9
    assert not visits.expired()
    clock.now = 14.0  # 10 s after GONE, the user's number
    assert visits.expired()


def test_a_second_gone_keeps_the_first_time():
    visits, _, clock = make_visits()
    visits.arrived()
    visits.left()
    clock.now = 1.5
    visits.left()
    clock.now = 5.0
    visits.replied()  # the quiet would end it at 15 s
    clock.now = 10.0
    assert visits.expired()


def test_heard_or_arrived_cancels_gone():
    for cancel in ["heard", "arrived"]:
        visits, _, clock = make_visits()
        visits.arrived()
        visits.left()
        clock.now = 1.0
        getattr(visits, cancel)()
        clock.now = 5.0
        visits.replied()  # the quiet would end it at 15 s
        clock.now = 12.0  # past the cancelled GONE's 10 s
        assert not visits.expired(), cancel


def test_gone_while_idle_is_ignored():
    visits, _, clock = make_visits()
    visits.left()
    assert visits.heard()  # starts a visit: the earlier GONE didn't belong to it
    clock.now = 5.5
    assert not visits.expired()


def messages(caplog):
    return [r.getMessage() for r in caplog.records]


def test_visit_starts_and_ends_are_logged_with_the_reason(caplog):
    caplog.set_level("DEBUG", logger="voice.visits")
    visits, rules, clock = make_visits()
    visits.arrived()
    visits.left()
    visits.arrived()
    rules.attempted = True
    clock.now = 10.0
    visits.expired()
    visits.heard()
    visits.left()
    clock.now = 20.0
    visits.expired()
    visits.left()
    assert messages(caplog) == [
        "visit started: someone walked up",
        "sensor GONE: the visit ends in 10 s unless they're heard or come back",
        "sensor HERE: the same visitor is back",
        "visit over: 10 s quiet after the candy request",
        "visit started: someone spoke",
        "sensor GONE: the visit ends in 10 s unless they're heard or come back",
        "visit over: they walked away",
        "sensor GONE with no visit: ignored",
    ]


def test_arrival_after_a_request_and_gone_is_logged_as_a_new_visitor(caplog):
    caplog.set_level("INFO", logger="voice.visits")
    visits, rules, _ = make_visits()
    visits.arrived()
    rules.attempted = True
    visits.left()
    visits.arrived()
    assert messages(caplog)[-1] == "visit started: someone walked up after the last one left"


def test_a_turn_that_began_before_the_quiet_ran_out_keeps_the_visit():
    visits, rules, clock = make_visits()
    visits.arrived()
    rules.attempted = True
    clock.now = 12.0  # past AFTER_CANDY_QUIET, but the turn began at 12 - 4 = 8 s
    visits.spoke(4.0)
    assert not visits.expired()
    assert not visits.heard()  # the same visit
    clock.now = 21.9  # quiet counts again from the end of the turn
    assert not visits.expired()
    clock.now = 22.0
    assert visits.expired()


def test_a_turn_that_began_after_the_quiet_ran_out_doesnt_save_the_visit():
    visits, _, clock = make_visits()
    visits.arrived()
    clock.now = 14.0  # the turn began at 14 - 3 = 11 s, after VISIT_TIMEOUT
    visits.spoke(3.0)
    assert visits.expired()
    assert visits.heard()  # a new visit


def test_a_turn_after_gone_keeps_the_visit_only_within_the_grace():
    visits, _, clock = make_visits()
    visits.arrived()
    clock.now = 1.0
    visits.left()
    clock.now = 13.0  # began at 9 s, within GONE_GRACE of the GONE at 1 s
    visits.spoke(4.0)
    assert not visits.expired()
    visits2, _, clock2 = make_visits()
    visits2.arrived()
    clock2.now = 1.0
    visits2.left()
    clock2.now = 9.5
    visits2.replied()  # Hazel talked: the quiet timer is fresh, the GONE still counts
    clock2.now = 15.0  # began at 11.5 s, past GONE_GRACE
    visits2.spoke(3.5)
    assert visits2.expired()


def test_spoke_keeps_a_pending_gone():
    # someone new talking isn't the one who left coming back: their HERE still starts a new visit
    visits, rules, clock = make_visits()
    visits.arrived()
    rules.attempted = True
    visits.left()
    clock.now = 3.0
    visits.spoke(2.0)
    assert visits.arrived()


def test_spoke_without_a_visit_does_nothing():
    visits, _, clock = make_visits()
    clock.now = 5.0
    visits.spoke(2.0)
    assert not visits.active
