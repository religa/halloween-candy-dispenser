"""The conversation with Claude, as Hazel the witch (voice/persona.md).

Reply text streams to `on_text`, so words before a tool call come out before the candy
drops, and `before_tool` runs once that text has streamed (the speaker starts saying it all).
The one tool runs through `CandyRules`, and its result goes back to the model. `greet()` starts
a visit with the arrival cue, so Hazel greets someone who just walked up in her own words, or
records a greeting already said (a recording) as her reply to it.
History is append-only: the whole `response.content`, thinking blocks included, goes back
unchanged.
"""

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from voice.rules import MAX_GROUP, CandyRules

MODEL = "claude-haiku-5-5"  # fastest replies (docs/voice.md, Choices)
EFFORT = "low"  # Haiku 5.5 defaults to medium; low keeps spoken replies quick
MAX_TOKENS = 4096  # adaptive thinking counts toward it; replies are 1-3 sentences
MAX_TOOL_ROUNDS = 3  # requests per visitor line, so a tool-calling loop can't run on
TOOL_CHOICE = {"type": "auto", "disable_parallel_tool_use": True}
LAST_ROUND_CHOICE = {"type": "none"}  # the last request must speak, so no tool result goes unvoiced
PERSONA = (Path(__file__).parent / "persona.md").read_text()
TOOL = {  # the schema tried against the live API
    "name": "dispense_candy",
    "description": "Drop candies down the chute: count is how many kids are trick-or-treating together "
    f"right now (1 for a single visitor, at most {MAX_GROUP}). The result says how many came out.",
    "input_schema": {
        "type": "object",
        "properties": {"count": {"type": "integer", "minimum": 1, "maximum": MAX_GROUP}},
        "required": ["count"],
        "additionalProperties": False,
    },
}
ARRIVAL_CUE = "[a visitor walks up]"  # a user turn that isn't speech: someone arrived
log = logging.getLogger(__name__)
FALLBACK_SPELL = "Heh heh, abracadabra, candy come down! "  # said when the model calls the tool without words first (groups did so in 10 of 20 tries)
FILLER_AFTER = 1.2  # s with no reply text before on_slow: 1 first request in 5 is slower (logs/)


class SlowTimer:
    """Calls on_slow once, on a timer thread, unless text() or the exit comes first. Both wait for
    an on_slow already running, so what it queues is heard before the reply's first words."""

    def __init__(self, on_slow: Callable[[], None] | None, after: float):
        self.on_slow = on_slow
        self.lock = threading.Lock()
        self.timer = threading.Timer(after, self._fire)
        self.timer.daemon = True

    def __enter__(self):
        if self.on_slow:
            self.timer.start()
        return self

    def __exit__(self, *exc):
        self.timer.cancel()
        self.text()
        return False

    def text(self) -> None:
        with self.lock:
            self.on_slow = None

    def _fire(self) -> None:
        with self.lock:
            on_slow, self.on_slow = self.on_slow, None
            if on_slow:
                log.info("no words after %.1f s: saying a filler", self.timer.interval)
                try:
                    on_slow()
                except Exception as e:  # a filler must never break the reply
                    log.warning("filler failed: %s: %s", e.__class__.__name__, e)


class Brain:
    def __init__(
        self,
        client,
        rules: CandyRules,
        on_text: Callable[[str], None],
        before_tool: Callable[[], None] = lambda: None,
        on_slow: Callable[[], None] | None = None,
        slow_after: float = FILLER_AFTER,
    ):
        """client: an anthropic.Anthropic. on_text receives each streamed piece of reply text.
        before_tool is called after a round's text has streamed, before its tools run, so words
        before a tool call start being spoken as the turntable starts to spin. on_slow (a filler, "Hmmm, let me
        see...") is called on a timer thread when a visitor line's first request has no text after
        slow_after s; the reply's text waits for it to return."""
        self.client = client
        self.rules = rules
        self.on_text = on_text
        self.before_tool = before_tool
        self.on_slow = on_slow
        self.slow_after = slow_after
        self.messages = []

    def new_visit(self) -> None:
        """Forget the conversation and re-arm the candy allowance: the one place a visit resets."""
        self.messages = []
        self.rules.new_visit()

    def greet(self, said: str | None = None) -> None:
        """Start a new visit and let Hazel greet it: the arrival cue goes in as the visitor's turn.
        said: a greeting already spoken (a recording): it goes into the history as her reply, and
        the model isn't asked."""
        self.new_visit()
        if said is None:
            self.reply(ARRIVAL_CUE, filler=False)  # "Hmmm, let me see..." before a hello sounds odd
        else:
            self.messages += [{"role": "user", "content": ARRIVAL_CUE}, {"role": "assistant", "content": said}]

    def reply(self, text: str, filler: bool = True) -> None:
        """Answer one visitor line, running dispense_candy if the model calls it. filler: on_slow
        may cover a slow first request (never a later round: the candy has dropped by then).
        anthropic errors propagate; the line stays in the history."""
        self.messages.append({"role": "user", "content": text})
        for n in range(1, MAX_TOOL_ROUNDS + 1):
            start, first = time.monotonic(), None
            slow = SlowTimer(self.on_slow if filler and n == 1 else None, self.slow_after)
            with (
                slow,
                self.client.messages.stream(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=PERSONA,
                    tools=[TOOL],
                    tool_choice=LAST_ROUND_CHOICE if n == MAX_TOOL_ROUNDS else TOOL_CHOICE,
                    output_config={"effort": EFFORT},
                    messages=self.messages,
                ) as stream,
            ):
                spoke = False
                for chunk in stream.text_stream:
                    if first is None:
                        slow.text()  # after a filler that has started: it's heard first
                        first = time.monotonic()
                    self.on_text(chunk)
                    spoke = spoke or bool(chunk.strip())
                message = stream.get_final_message()
            log.debug(
                "request %d: %s in %.2f s (first words after %s)",
                n,
                message.stop_reason,
                time.monotonic() - start,
                f"{first - start:.2f} s" if first else "none",
            )
            tool_uses = [b for b in message.content if b.type == "tool_use"]
            runs_tools = message.stop_reason == "tool_use" and bool(tool_uses)
            if not runs_tools:
                # a tool_use cut off by max_tokens or a refusal is never sent back unanswered
                if message.content and not tool_uses:
                    self.messages.append({"role": "assistant", "content": message.content})
                return
            if not spoke and not self.rules.attempted:  # silence while candy drops; not added to the history
                log.info("tool call with no words before it: saying the fallback spell")
                self.on_text(FALLBACK_SPELL)
            self.before_tool()
            results = [self._run_tool(b) for b in tool_uses]  # first, so a crash can't leave a tool_use unanswered
            self.messages.append({"role": "assistant", "content": message.content})
            self.messages.append({"role": "user", "content": results})

    def _run_tool(self, block) -> dict:
        log.info("tool call: %s %.40r", block.name, block.input)
        if block.name == TOOL["name"] and not isinstance(block.input, dict):
            return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": "invalid input: expected an object with count"}
        if block.name == TOOL["name"]:
            return {"type": "tool_result", "tool_use_id": block.id, "content": self.rules.request_candy(block.input.get("count", 1))}
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": f"unknown tool: {block.name}"}
