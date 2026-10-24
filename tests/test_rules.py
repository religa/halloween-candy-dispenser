"""Candy rules: one request per visit (up to MAX_GROUP candies), whatever the outcome, and a
cooldown between requests, enforced in code."""

import ast
from pathlib import Path

import pytest
from voice.brain import ARRIVAL_CUE, PERSONA, TOOL
from voice.dispenser import DispenserError, Outcome
from voice.rules import ALREADY, BROKEN, CAPPED, GIVEN, MAX_GROUP, NO_RETRY, REPLY, CandyRules, group_given, partial_given

VOICE = Path(__file__).resolve().parents[1] / "voice"


class StubDispenser:
    """Dispenser stand-in: records each dispense() call, then raises error or returns outcome.
    script: outcomes (or exceptions) for the first calls, before outcome/error."""

    def __init__(self, outcome=Outcome.CANDY, error=None, script=()):
        self.outcome = outcome
        self.error = error
        self.script = list(script)
        self.calls = []

    def dispense(self):
        self.calls.append("<candy>")
        if self.script:
            next_ = self.script.pop(0)
            if isinstance(next_, Exception):
                raise next_
            return next_
        if self.error:
            raise self.error
        return self.outcome


class FakeClock:
    """time.monotonic stand-in: call it for now; sleep(s) records s and moves now on."""

    def __init__(self, now=0.0):
        self.now = now
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def clocked_rules(dispenser, clock):
    return CandyRules(dispenser, clock=clock, sleep=clock.sleep)


def test_first_request_dispenses():
    dispenser = StubDispenser()
    assert CandyRules(dispenser).request_candy() == GIVEN
    assert len(dispenser.calls) == 1


def test_second_request_in_a_visit_is_refused():
    dispenser = StubDispenser()
    rules = CandyRules(dispenser)
    rules.request_candy()
    assert rules.request_candy() == ALREADY
    assert len(dispenser.calls) == 1


def test_total_given_counts_across_visits():
    dispenser = StubDispenser()
    rules = clocked_rules(dispenser, FakeClock())
    rules.request_candy()
    rules.request_candy()  # refused: already had one
    rules.new_visit()
    rules.request_candy(count=2)
    rules.new_visit()
    dispenser.outcome = Outcome.EMPTY
    rules.request_candy()
    assert rules.total_given == 3


def test_new_visit_rearms_the_allowance():
    dispenser = StubDispenser()
    rules = clocked_rules(dispenser, FakeClock())
    first = rules.request_candy()
    rules.new_visit()
    assert [first, rules.request_candy()] == [GIVEN, GIVEN]
    assert len(dispenser.calls) == 2


def test_empty_bucket_is_reported_and_not_retried():
    dispenser = StubDispenser(Outcome.EMPTY)
    rules = CandyRules(dispenser)
    assert rules.request_candy() == "no candy: the bucket is empty"
    assert rules.request_candy() == NO_RETRY
    assert len(dispenser.calls) == 1


def test_blocked_chute_is_reported():
    assert CandyRules(StubDispenser(Outcome.BLOCKED)).request_candy() == "no candy: the chute is blocked"


def test_dispenser_error_is_broken_and_logged(caplog):
    rules = CandyRules(StubDispenser(error=DispenserError("lost the Arduino: gone")))
    assert rules.request_candy() == BROKEN
    assert "lost the Arduino" in caplog.text
    assert rules.request_candy() == NO_RETRY


def test_every_outcome_has_a_reply():
    assert set(REPLY) == set(Outcome)


def test_only_rules_calls_dispense():
    callers = set()
    for path in VOICE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "dispense":
                callers.add(f"{path.name}:{ast.unparse(node.func.value)}")
    assert callers == {"rules.py:self.dispenser", "dispenser.py:self.inner"}  # Reconnecting only passes it on


def test_persona_names_the_tool():
    assert TOOL["name"] in PERSONA


def test_persona_explains_the_arrival_cue():
    assert ARRIVAL_CUE in PERSONA


def test_persona_names_the_group_limit():
    assert f"at most {MAX_GROUP}" in PERSONA


def test_persona_forbids_writing_brackets():
    assert "Never write square brackets" in PERSONA


def test_persona_keeps_the_users_own_lines():
    for line in ["one to two short sentences", "not related to halloween", "no more batches", "step back and come up again", "when in doubt, give the candy"]:
        assert line in PERSONA


def test_group_request_dispenses_up_to_count():
    dispenser = StubDispenser()
    assert CandyRules(dispenser).request_candy(3) == group_given(3)
    assert len(dispenser.calls) == 3


def test_count_is_capped_at_max_group(caplog):
    caplog.set_level("INFO", logger="voice.rules")
    dispenser = StubDispenser()
    result = CandyRules(dispenser).request_candy(99)
    assert len(dispenser.calls) == 3  # the user's number, written out
    assert result == group_given(3) + CAPPED
    assert "asked for 99, capped at 3" in caplog.text


@pytest.mark.parametrize("count", [None, "x", "3.7", 0, -2, True, [], float("inf")])
def test_bad_counts_mean_one(count):
    dispenser = StubDispenser()
    assert CandyRules(dispenser).request_candy(count) == GIVEN
    assert len(dispenser.calls) == 1


@pytest.mark.parametrize("count", ["3", 3.7])
def test_numeric_strings_and_floats_are_truncated(count):
    dispenser = StubDispenser()
    assert CandyRules(dispenser).request_candy(count) == group_given(3)
    assert len(dispenser.calls) == 3


def test_capped_string_count():
    dispenser = StubDispenser()
    assert CandyRules(dispenser).request_candy("99").endswith(CAPPED)
    assert len(dispenser.calls) == 3


def test_capped_suffix_on_a_failure():
    assert CandyRules(StubDispenser(Outcome.EMPTY)).request_candy(10) == REPLY[Outcome.EMPTY] + CAPPED


def test_group_stops_at_the_first_failure():
    dispenser = StubDispenser(script=[Outcome.CANDY, Outcome.EMPTY])
    assert CandyRules(dispenser).request_candy(3) == partial_given(1, 3, REPLY[Outcome.EMPTY])
    assert len(dispenser.calls) == 2


def test_group_dispenser_error_midway(caplog):
    dispenser = StubDispenser(script=[Outcome.CANDY, DispenserError("lost the Arduino: gone")])
    assert CandyRules(dispenser).request_candy(3) == partial_given(1, 3, BROKEN)
    assert "lost the Arduino" in caplog.text
    assert len(dispenser.calls) == 2


def test_second_group_request_in_a_visit_is_refused():
    dispenser = StubDispenser()
    rules = CandyRules(dispenser)
    rules.request_candy(3)
    assert rules.request_candy(1) == ALREADY
    assert len(dispenser.calls) == 3


def test_group_results_name_the_counts():
    assert group_given(3) == "candy given: candy came down the chute for all 3 kids"
    assert partial_given(1, 3, BROKEN) == f"candy given: candy came down the chute for 1 of the 3 kids, then {BROKEN}"
    assert CAPPED == "; 3 is the most for one visit"


def test_cooldown_waits_out_the_rest(caplog):
    caplog.set_level("INFO", logger="voice.rules")
    clock, dispenser = FakeClock(), StubDispenser()
    rules = clocked_rules(dispenser, clock)
    rules.request_candy()
    rules.new_visit()
    clock.now = 5.0
    assert rules.request_candy() == GIVEN
    assert clock.slept == [pytest.approx(10.0)]  # 15 s, the user's number, written out
    assert len(dispenser.calls) == 2
    assert "cooldown: waiting 10.0 s" in caplog.text


def test_no_wait_after_the_cooldown():
    clock = FakeClock()
    rules = clocked_rules(StubDispenser(), clock)
    rules.request_candy()
    rules.new_visit()
    clock.now = 20.0
    rules.request_candy()
    assert clock.slept == []


def test_first_request_never_waits():
    clock = FakeClock(now=100.0)
    clocked_rules(StubDispenser(), clock).request_candy(3)
    assert clock.slept == []


def test_failed_request_still_starts_the_cooldown():
    clock = FakeClock()
    rules = clocked_rules(StubDispenser(Outcome.EMPTY), clock)
    rules.request_candy()
    rules.new_visit()
    clock.now = 1.0
    rules.request_candy()
    assert clock.slept == [pytest.approx(14.0)]


def test_refused_request_neither_waits_nor_restarts_the_cooldown():
    clock = FakeClock()
    rules = clocked_rules(StubDispenser(), clock)
    rules.request_candy()
    clock.now = 10.0
    assert rules.request_candy() == ALREADY
    rules.new_visit()
    clock.now = 15.0
    rules.request_candy()
    assert clock.slept == []


def test_unexpected_error_mid_group_still_uses_up_the_visit_and_starts_the_cooldown():
    clock = FakeClock()
    dispenser = StubDispenser(script=[Outcome.CANDY, RuntimeError("serial bug")])
    rules = clocked_rules(dispenser, clock)
    with pytest.raises(RuntimeError):
        rules.request_candy(3)
    assert rules.request_candy(3) == ALREADY
    assert len(dispenser.calls) == 2
    rules.new_visit()
    clock.now = 5.0
    rules.request_candy()
    assert clock.slept == [pytest.approx(10.0)]


def test_cooldown_counts_from_the_end_of_dispensing():
    clock = FakeClock()

    class SlowDispenser(StubDispenser):
        def dispense(self):
            clock.now += 4.0  # one spin takes real time
            return super().dispense()

    rules = clocked_rules(SlowDispenser(), clock)
    rules.request_candy(3)  # ends at t=12
    rules.new_visit()
    clock.now = 17.0
    rules.request_candy()
    assert clock.slept == [pytest.approx(10.0)]


def test_every_request_is_logged(caplog):
    caplog.set_level("INFO", logger="voice.rules")
    rules = CandyRules(StubDispenser())
    rules.request_candy(2)
    rules.request_candy()
    assert [r.getMessage() for r in caplog.records] == [
        "candy request: count 2",
        "dispensed: candy",
        "dispensed: candy",
        "refused: already tried this visit",
    ]


def test_no_result_counts_the_candies():
    # the chute sometimes drops more than one: results say candy came down, never how much
    results = [GIVEN, group_given(3), partial_given(1, 3, BROKEN), *REPLY.values(), ALREADY]
    for result in results:
        assert "one candy" not in result and "candies" not in result and "a candy" not in result, result


def test_persona_never_counts_the_candies():
    assert "Never say how many candies came down" in PERSONA
    assert "a candy dropped" not in PERSONA
