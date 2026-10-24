"""The Claude conversation, offline: a fake client replays responses built from real anthropic.types."""

import time

import anthropic
import httpx2
import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage
from test_rules import FakeClock
from voice.brain import ARRIVAL_CUE, FALLBACK_SPELL, MAX_TOOL_ROUNDS, PERSONA, TOOL, Brain
from voice.dispenser import Outcome
from voice.rules import ALREADY, GIVEN, MAX_GROUP, REPLY, CandyRules


def text(s):
    return TextBlock(type="text", text=s, citations=None)


def tool(id="toolu_1", name="dispense_candy", input=None):
    return ToolUseBlock(type="tool_use", id=id, name=name, input=input or {})


def thinking():
    return ThinkingBlock(type="thinking", thinking="", signature="sig")


def turn(*blocks, stop_reason):
    return Message(
        id="msg_x",
        type="message",
        role="assistant",
        model="claude-haiku-5-5",
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
        content=list(blocks),
    )


class FakeStream:
    """messages.stream() stand-in: streams the text blocks, then hands back the whole message."""

    def __init__(self, message):
        self.message = message
        self.text_stream = iter([b.text for b in message.content if b.type == "text"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class SlowStream(FakeStream):
    """A FakeStream whose first text comes after delay seconds."""

    def __init__(self, message, delay):
        super().__init__(message)
        self.text_stream = self._slow(self.text_stream, delay)

    @staticmethod
    def _slow(chunks, delay):
        time.sleep(delay)
        yield from chunks


class FakeClient:
    """Anthropic stand-in: records each request and replays the queued turns in order; each
    request waits delays[n] seconds (if given) before its first text."""

    def __init__(self, *turns, error=None, delays=()):
        self.turns = list(turns)
        self.error = error
        self.delays = list(delays)
        self.requests = []
        self.messages = self

    def stream(self, **kwargs):
        self.requests.append(dict(kwargs, messages=list(kwargs["messages"])))
        if self.error:
            error, self.error = self.error, None
            raise error
        delay = self.delays.pop(0) if self.delays else 0
        return SlowStream(self.turns.pop(0), delay) if delay else FakeStream(self.turns.pop(0))


class StubDispenser:
    """Dispenser stand-in: records each dispense() call and returns outcome."""

    def __init__(self, outcome=Outcome.CANDY):
        self.outcome = outcome
        self.calls = []

    def dispense(self):
        self.calls.append("<candy>")
        return self.outcome


TOOL_TURN = turn(text("Bubble!"), tool(), stop_reason="tool_use")
GRAB_TURN = turn(text("Grab it!"), stop_reason="end_turn")


def make_brain(*turns, outcome=Outcome.CANDY, error=None):
    client = FakeClient(*turns, error=error)
    dispenser = StubDispenser(outcome)
    events = []
    clock = FakeClock()  # the cooldown between visits passes instantly
    brain = Brain(client, CandyRules(dispenser, clock=clock, sleep=clock.sleep), on_text=events.append)
    return brain, client, dispenser, events


def test_text_reply_streams_and_is_recorded():
    brain, _, _, events = make_brain(turn(text("Heh heh, hello!"), stop_reason="end_turn"))
    brain.reply("hi")
    assert events == ["Heh heh, hello!"]
    assert [m["role"] for m in brain.messages] == ["user", "assistant"]


def test_tool_call_dispenses_once_and_result_goes_back():
    brain, client, dispenser, _ = make_brain(TOOL_TURN, GRAB_TURN)
    brain.reply("trick or treat")
    assert len(dispenser.calls) == 1
    assert client.requests[1]["messages"][-1]["content"] == [{"type": "tool_result", "tool_use_id": "toolu_1", "content": GIVEN}]


def test_text_before_tool_then_candy_then_text():
    brain, _, dispenser, events = make_brain(TOOL_TURN, GRAB_TURN)
    dispenser.calls = events
    brain.reply("trick or treat")
    assert events == ["Bubble!", "<candy>", "Grab it!"]


def test_second_tool_call_in_a_visit_is_refused():
    brain, client, dispenser, _ = make_brain(TOOL_TURN, GRAB_TURN, turn(tool(id="toolu_2"), stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat")
    brain.reply("another one!")
    assert len(dispenser.calls) == 1
    assert client.requests[-1]["messages"][-1]["content"][-1]["content"] == ALREADY


def test_empty_bucket_reaches_the_model():
    brain, client, _, _ = make_brain(TOOL_TURN, GRAB_TURN, outcome=Outcome.EMPTY)
    brain.reply("trick or treat")
    assert client.requests[1]["messages"][-1]["content"][0]["content"] == REPLY[Outcome.EMPTY]


def test_request_parameters():
    brain, client, _, _ = make_brain(GRAB_TURN)
    brain.reply("hi")
    request = client.requests[0]
    assert request["model"] == "claude-haiku-5-5"  # docs/voice.md, Choices
    assert request["tools"][0]["name"] == "dispense_candy"
    assert request["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    assert request["output_config"] == {"effort": "low"}
    assert request["system"] == PERSONA
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(request)


def test_thinking_blocks_are_sent_back_unchanged():
    blocks = [thinking(), text("Hmm!"), tool()]
    brain, client, _, _ = make_brain(turn(*blocks, stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat")
    assert client.requests[1]["messages"][1]["content"] == blocks


def test_parallel_tool_calls_get_one_result_each():
    brain, client, dispenser, _ = make_brain(turn(tool("a"), tool("b"), stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat")
    results = client.requests[1]["messages"][-1]["content"]
    assert [(r["tool_use_id"], r["content"]) for r in results] == [("a", GIVEN), ("b", ALREADY)]
    assert len(dispenser.calls) == 1


def test_truncated_tool_call_is_not_run():
    brain, _, dispenser, _ = make_brain(turn(tool(), stop_reason="max_tokens"))
    brain.reply("trick or treat")
    assert dispenser.calls == []
    assert brain.messages == [{"role": "user", "content": "trick or treat"}]


def test_empty_content_is_not_appended():
    brain, _, _, _ = make_brain(turn(stop_reason="refusal"))
    brain.reply("hi")
    assert brain.messages == [{"role": "user", "content": "hi"}]


def test_tool_rounds_are_capped():
    turns = [turn(tool(id=f"t{i}"), stop_reason="tool_use") for i in range(MAX_TOOL_ROUNDS + 2)]
    brain, client, _, _ = make_brain(*turns)
    brain.reply("trick or treat")
    assert len(client.requests) == MAX_TOOL_ROUNDS
    assert brain.messages[-1]["role"] == "user"


def test_last_round_must_speak_about_the_tool_result():
    turns = [turn(tool(id=f"t{i}"), stop_reason="tool_use") for i in range(MAX_TOOL_ROUNDS - 1)]
    brain, client, _, events = make_brain(*turns, GRAB_TURN)
    brain.reply("trick or treat")
    assert [r["tool_choice"]["type"] for r in client.requests] == ["auto"] * (MAX_TOOL_ROUNDS - 1) + ["none"]
    assert events[-1] == "Grab it!"


def test_unknown_tool_is_an_error_result():
    brain, client, dispenser, _ = make_brain(turn(tool(name="open_door"), stop_reason="tool_use"), GRAB_TURN)
    brain.reply("open the door")
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert dispenser.calls == []


def test_new_visit_clears_history_and_allowance():
    brain, client, dispenser, _ = make_brain(TOOL_TURN, GRAB_TURN, TOOL_TURN, GRAB_TURN)
    brain.reply("trick or treat")
    brain.new_visit()
    brain.reply("trick or treat, me too")
    assert len(dispenser.calls) == 2
    assert client.requests[-2]["messages"][0]["content"] == "trick or treat, me too"


def test_api_error_propagates_and_keeps_history():
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    brain, client, _, _ = make_brain(turn(text("hi"), stop_reason="end_turn"), error=error)
    with pytest.raises(anthropic.APIConnectionError):
        brain.reply("a")
    brain.reply("b")
    assert client.requests[-1]["messages"] == [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]


def test_tool_crash_leaves_no_unanswered_tool_call():
    brain, _, dispenser, _ = make_brain(TOOL_TURN)
    dispenser.dispense = lambda: "not an Outcome"  # REPLY[...] raises KeyError
    with pytest.raises(KeyError):
        brain.reply("trick or treat")
    assert brain.messages == [{"role": "user", "content": "trick or treat"}]


def test_before_tool_runs_after_text_and_before_the_tool():
    brain, _, dispenser, events = make_brain(TOOL_TURN, GRAB_TURN)
    dispenser.calls = events
    brain.before_tool = lambda: events.append("<pause>")
    brain.reply("trick or treat")
    assert events == ["Bubble!", "<pause>", "<candy>", "Grab it!"]


def test_before_tool_is_not_called_without_a_tool_round():
    pauses = []
    brain = Brain(FakeClient(GRAB_TURN), CandyRules(StubDispenser()), on_text=print, before_tool=lambda: pauses.append(1))
    brain.reply("hi")
    assert pauses == []


def test_tool_schema_max_is_max_group():
    count = TOOL["input_schema"]["properties"]["count"]
    assert count["maximum"] == 3  # the user's number, written out
    assert count["maximum"] == MAX_GROUP
    assert TOOL["input_schema"]["required"] == ["count"]


def test_tool_count_reaches_the_rules():
    brain, _, dispenser, _ = make_brain(turn(text("Bubble!"), tool(input={"count": 3}), stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat, there are three of us")
    assert len(dispenser.calls) == 3


def test_greet_starts_a_visit_with_the_cue():
    brain, client, dispenser, _ = make_brain(TOOL_TURN, GRAB_TURN, GRAB_TURN, TOOL_TURN, GRAB_TURN)
    brain.reply("trick or treat")
    brain.greet()
    assert client.requests[-1]["messages"] == [{"role": "user", "content": ARRIVAL_CUE}]
    brain.reply("trick or treat")
    assert len(dispenser.calls) == 2


def test_recorded_greeting_goes_into_the_history_without_asking_the_model():
    brain, client, dispenser, events = make_brain(TOOL_TURN, GRAB_TURN, GRAB_TURN)
    brain.reply("trick or treat")
    asked = len(client.requests)
    brain.greet(said="Hello, dearie!")
    assert len(client.requests) == asked and "Hello, dearie!" not in events  # main prints and plays it
    assert brain.messages == [{"role": "user", "content": ARRIVAL_CUE}, {"role": "assistant", "content": "Hello, dearie!"}]
    brain.reply("trick or treat")  # a new visit: the allowance is back
    assert client.requests[-1]["messages"][:2] == brain.messages[:2]
    assert len(dispenser.calls) == 1


def silent_tool_brain(*blocks):
    brain, _, dispenser, events = make_brain(turn(*blocks, tool(), stop_reason="tool_use"), GRAB_TURN)
    dispenser.calls = events
    brain.before_tool = lambda: events.append("<before_tool>")
    return brain, events


def test_silent_tool_round_says_the_fallback_spell_first():
    brain, events = silent_tool_brain()
    brain.reply("trick or treat")
    assert events == [FALLBACK_SPELL, "<before_tool>", "<candy>", "Grab it!"]
    assert brain.messages[1]["content"] == [tool()]  # the model's own message, without the fallback


def test_tool_round_with_text_has_no_fallback():
    brain, _, _, events = make_brain(TOOL_TURN, GRAB_TURN)
    brain.reply("trick or treat")
    assert FALLBACK_SPELL not in events


def test_whitespace_only_text_gets_the_fallback():
    brain, events = silent_tool_brain(text(" "))
    brain.reply("trick or treat")
    assert events == [" ", FALLBACK_SPELL, "<before_tool>", "<candy>", "Grab it!"]


def test_text_only_round_has_no_fallback():
    brain, _, _, events = make_brain(GRAB_TURN)
    brain.reply("hi")
    assert events == ["Grab it!"]


def test_refused_silent_tool_call_gets_no_fallback():
    brain, _, dispenser, events = make_brain(TOOL_TURN, GRAB_TURN, turn(tool(id="toolu_2"), stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat")
    brain.reply("another one!")
    assert FALLBACK_SPELL not in events  # no candy will drop: no spell promising one
    assert len(dispenser.calls) == 1


def test_tool_input_that_is_not_an_object_is_an_error_and_keeps_the_allowance():
    bad = ToolUseBlock.model_construct(type="tool_use", id="toolu_1", name="dispense_candy", input=None)
    brain, client, dispenser, _ = make_brain(turn(text("Bubble!"), bad, stop_reason="tool_use"), GRAB_TURN)
    brain.reply("trick or treat")
    assert client.requests[1]["messages"][-1]["content"][0]["is_error"] is True
    assert dispenser.calls == []
    assert not brain.rules.attempted


SLOW = 0.3  # s a slow fake request waits before its first text
SLOW_AFTER = 0.05  # s before the filler, in these tests


def make_slow_brain(*turns, delays):
    client = FakeClient(*turns, delays=delays)
    events = []
    clock = FakeClock()
    rules = CandyRules(StubDispenser(), clock=clock, sleep=clock.sleep)
    brain = Brain(client, rules, on_text=events.append, on_slow=lambda: events.append("<filler>"), slow_after=SLOW_AFTER)
    return brain, events


def test_slow_first_request_says_one_filler_before_its_words():
    brain, events = make_slow_brain(turn(text("Ooh, a pirate!"), stop_reason="end_turn"), delays=[SLOW])
    brain.reply("I'm a pirate")
    assert events == ["<filler>", "Ooh, a pirate!"]


def test_fast_first_request_has_no_filler():
    brain, events = make_slow_brain(turn(text("Ooh, a pirate!"), stop_reason="end_turn"), delays=[0])
    brain.reply("I'm a pirate")
    time.sleep(2 * SLOW_AFTER)  # a timer left running would fire now
    assert events == ["Ooh, a pirate!"]


def test_slow_round_after_the_candy_has_no_filler():
    brain, events = make_slow_brain(TOOL_TURN, GRAB_TURN, delays=[0, SLOW])
    brain.reply("trick or treat")
    assert events == ["Bubble!", "Grab it!"]


def test_a_greeting_written_by_the_model_has_no_filler():
    brain, events = make_slow_brain(turn(text("Hello, dearie!"), stop_reason="end_turn"), delays=[SLOW])
    brain.greet()
    assert events == ["Hello, dearie!"]


def test_a_failing_filler_doesnt_break_the_reply():
    client = FakeClient(turn(text("Ooh!"), stop_reason="end_turn"), delays=[SLOW])
    events = []

    def broken():
        raise RuntimeError("no speaker")

    brain = Brain(client, CandyRules(StubDispenser()), on_text=events.append, on_slow=broken, slow_after=SLOW_AFTER)
    brain.reply("hi")
    assert events == ["Ooh!"]
