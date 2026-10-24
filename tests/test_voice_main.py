"""The chat command, typed and by voice, offline: a fake brain for the loop, fake clients for the
credentials check, fake ears for voice mode."""

import argparse
import ast
import dataclasses
import functools
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import anthropic
import httpx2
import pytest
import sounddevice
import voice.dispenser
import voice.main
from elevenlabs.core.api_error import ApiError
from test_dispenser import CANDY, FakeLink
from test_rules import FakeClock
from test_speak import FakePlayer
from voice.devices import DeviceError
from voice.dispenser import Dispenser, DispenserError, Outcome, Presence
from voice.fallback import FILLERS, GREETINGS, LINES
from voice.hear import CLOSE_LIMIT, MicError, SilentMic, Turn
from voice.main import (
    TICK,
    VOICE_GREETING,
    Console,
    FakeDispenser,
    SensorNote,
    chat,
    check_credentials,
    door,
    main,
    make_speaker,
    nobody_there,
    pick_line,
    sensor_reading,
    setup_logging,
)
from voice.rules import CandyRules
from voice.speak import TTS_TIMEOUT, VOICE_ID
from voice.status import HEARTBEAT, Status
from voice.visits import AFTER_CANDY_QUIET, VISIT_TIMEOUT, Visits

MESSAGES_URL = "https://api.anthropic.com/v1/messages"
MODEL_URL = "https://api.anthropic.com/v1/models/claude-haiku-5-5"


@pytest.fixture(autouse=True)
def restore_logging(monkeypatch, tmp_path):
    """main() sets up logging for the whole process and writes a log file: keep the file out of the
    repo, and put logging back after each test."""
    monkeypatch.setattr(voice.main, "LOG_DIR", tmp_path / "logs")
    root, voice_log = logging.getLogger(), logging.getLogger("voice")
    handlers, level, voice_level = root.handlers[:], root.level, voice_log.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)
    voice_log.setLevel(voice_level)


@pytest.fixture(autouse=True)
def devices(monkeypatch):
    """No test touches real audio devices (CI has no P10S): main() resolves --device to (1, 2).
    Returns the names asked for."""
    names = []
    monkeypatch.setattr(voice.main, "wait_for_devices", lambda name, **kwargs: names.append(name) or (1, 2))
    return names


class FakeBrain:
    """Brain stand-in: records each line, then raises the queued error once."""

    def __init__(self, error=None):
        self.error = error
        self.visits = 0
        self.replies = []

    def new_visit(self):
        self.visits += 1

    def reply(self, line):
        self.replies.append(line)
        if self.error:
            error, self.error = self.error, None
            raise error

    def greet(self, said=None):
        if said is None:
            self.reply("<greet>")
        else:
            self.new_visit()
            self.replies.append(f"<greeted:{said}>")


def run_chat(brain, lines, out=None, after_reply=lambda: None):
    """Feed lines to chat() as typed input, then EOF; return everything it wrote."""
    lines = iter(lines)
    out = [] if out is None else out

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    chat(brain, read, lambda *a, end="\n": out.append("".join(map(str, a)) + end), after_reply=after_reply)
    return "".join(out)


class FakeModels:
    def __init__(self, error):
        self.error = error

    def retrieve(self, model):
        raise self.error


class FakeClient:
    """Anthropic stand-in whose models.retrieve() raises error."""

    def __init__(self, error):
        self.models = FakeModels(error)


def status_error(cls, status):
    response = httpx2.Response(status, request=httpx2.Request("GET", MODEL_URL))
    return cls(message="x", response=response, body=None)


def test_chat_sends_lines_and_handles_next():
    brain = FakeBrain()
    out = run_chat(brain, ["trick or treat", "", "/next", "hello", "/quit", "never sent"])
    assert brain.replies == ["trick or treat", "hello"]
    assert brain.visits == 2
    assert "-- new visitor --" in out


def test_chat_ends_on_eof():
    brain = FakeBrain()
    run_chat(brain, ["hi"])
    assert brain.replies == ["hi"]


def test_api_error_keeps_the_chat_going():
    brain = FakeBrain(error=anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL)))
    out = run_chat(brain, ["a", "b"])
    assert brain.replies == ["a", "b"]
    assert "can't talk right now" in out


def test_fake_dispenser_returns_its_outcome(caplog):
    caplog.set_level("INFO", logger="voice.main")
    assert FakeDispenser(Outcome.EMPTY).dispense() is Outcome.EMPTY
    assert "fake dispenser: empty" in caplog.text


def test_fake_dispenser_has_no_sensor():
    assert FakeDispenser(Outcome.CANDY).poll() == []


def test_missing_credentials_exit_with_a_hint():
    with pytest.raises(SystemExit, match="no Anthropic credentials"):
        check_credentials(FakeClient(TypeError("Could not resolve authentication method")))


@pytest.mark.parametrize(
    "error, message",
    [
        (status_error(anthropic.AuthenticationError, 401), "rejected"),
        (status_error(anthropic.NotFoundError, 404), "not available"),
        (anthropic.APIConnectionError(request=httpx2.Request("GET", MODEL_URL)), "check failed"),
    ],
)
def test_rejected_key_and_unknown_model_exit(error, message):
    with pytest.raises(SystemExit, match=message):
        check_credentials(FakeClient(error))


def test_missing_arduino_suggests_fake_dispenser(monkeypatch):
    def no_arduino(*args, **kwargs):
        raise DispenserError("no Arduino found: is the USB cable plugged in?")

    monkeypatch.setattr(Dispenser, "open", no_arduino)
    monkeypatch.setattr(voice.main, "STARTUP_WAIT", 0)  # one try, not a 60 s wait
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: None)
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(voice.main, "make_speaker", lambda args, **kwargs: (None, {}))
    with pytest.raises(SystemExit) as exit:
        main(["--text"])
    assert "--fake-dispenser" in str(exit.value.code)


def test_dropped_connection_mid_reply_keeps_the_chat_going():
    brain = FakeBrain(error=httpx2.ReadError("connection reset"))  # the SDK doesn't wrap errors mid-stream
    out = run_chat(brain, ["a", "b"])
    assert brain.replies == ["a", "b"]
    assert "can't talk right now" in out


def test_sdk_without_credentials_raises_type_error(monkeypatch, tmp_path):
    """The oracle for check_credentials' `except TypeError`: no key fails at the first request."""
    for name in ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_CONFIG_DIR", "ANTHROPIC_PROFILE"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    client = anthropic.Anthropic(base_url="http://127.0.0.1:9", max_retries=0)
    with pytest.raises(SystemExit, match="no Anthropic credentials"):
        check_credentials(client)


class FakePort:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_credentials_checked_before_the_port_opens_and_port_closed_on_ctrl_c(monkeypatch):
    port = FakePort()
    events = []

    def open_port(*args, **kwargs):
        events.append("open")
        return port

    def interrupted_chat(brain, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(Dispenser, "open", open_port)
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: events.append("credentials"))
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(voice.main, "make_speaker", lambda args, **kwargs: (None, {}))
    monkeypatch.setattr(voice.main, "chat", interrupted_chat)
    main(["--text"])
    assert events == ["credentials", "open"]
    assert port.closed


def test_chat_calls_after_reply_after_every_reply():
    brain = FakeBrain(error=anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL)))
    calls = []
    run_chat(brain, ["a", "", "/next", "b"], after_reply=lambda: calls.append(1))
    assert len(calls) == 2


def test_after_reply_speaks_partial_text_after_an_error():
    brain = FakeBrain(error=anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL)))
    out = []
    run_chat(brain, ["a"], out=out, after_reply=lambda: out.append("<after>"))
    assert out.count("<after>") == 1
    error_line = next(i for i, line in enumerate(out) if "can't talk right now" in line)
    assert error_line < out.index("<after>")


class FakeSpeaker:
    """Speaker stand-in for main(): records feed/play/flush/drain/reset_output/close; closed (voice gone
    for good) once drain() has run `mute_after` times; reply_failed for `failing_drains` drains."""

    def __init__(self, events, mute_after=None, failing_drains=0):
        self.events = events
        self.mute_after = mute_after
        self.failing_drains = failing_drains  # this many drains in a row report reply_failed
        self.closed = False
        self.reply_failed = False
        self.player = ReleasablePlayer(events)

    def feed(self, s):
        self.events.append(f"feed:{s}")

    def play(self, pcm):
        self.events.append(f"play:{pcm!r}")

    def flush(self):
        self.events.append("flush")

    def drain(self):
        self.events.append("drain")
        if self.mute_after is not None and self.events.count("drain") >= self.mute_after:
            self.closed = True
        self.reply_failed = self.reply_failed or self.failing_drains > 0
        self.failing_drains -= 1

    def take_reply_failed(self):
        failed, self.reply_failed = self.reply_failed, False
        return failed

    def reset_output(self):
        self.events.append("reset output")

    def close(self):
        self.events.append("speaker closed")


class RecordingPort(FakePort):
    def __init__(self, events):
        super().__init__()
        self.events = events

    def poll(self):
        return []  # nobody walks up

    def distance(self, timeout=None):
        return None  # nothing in range

    def close(self):
        self.events.append("port closed")


def patch_main(monkeypatch, events, open_port=None, speaker=None, ears=None, lines=None):
    """main() offline: credentials pass, make_speaker returns speaker and the recorded fallback
    lines, the port opens via open_port, open_ears returns ears (a (listener, transcriber) pair)."""
    lines = {} if lines is None else lines
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: events.append("credentials"))
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())

    def fake_make_speaker(args, device=None):
        events.append("voice")
        return speaker, lines

    monkeypatch.setattr(voice.main, "make_speaker", fake_make_speaker)
    monkeypatch.setattr(voice.main, "STARTUP_WAIT", 0)  # a failing open_port fails at once
    if ears:

        def fake_open_ears(*args, **kwargs):
            events.append("ears")
            return ears

        monkeypatch.setattr(voice.main, "open_ears", fake_open_ears)
    if open_port:
        monkeypatch.setattr(Dispenser, "open", open_port)


def test_missing_elevenlabs_key_exits_and_names_mute(monkeypatch):
    events = []
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: None)
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(Dispenser, "open", lambda *a, **k: events.append("open"))
    with pytest.raises(SystemExit) as exit:
        main(["--text"])
    assert "--mute" in str(exit.value.code)
    assert events == []


def test_mute_needs_no_elevenlabs(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("constructed with --mute")

    chats = []
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: None)
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(voice.main, "ElevenLabs", forbidden)
    monkeypatch.setattr(voice.main, "SoundPlayer", forbidden)
    monkeypatch.setattr(voice.main, "chat", lambda brain, **kwargs: chats.append(brain))
    main(["--text", "--mute", "--fake-dispenser", "candy"])
    assert len(chats) == 1


def test_voice_checked_before_the_port_opens_and_speaker_closed_first(monkeypatch):
    events = []

    def open_port(*args, **kwargs):
        events.append("open")
        return RecordingPort(events)

    def interrupted_chat(brain, **kwargs):
        raise KeyboardInterrupt

    patch_main(monkeypatch, events, open_port, FakeSpeaker(events))
    monkeypatch.setattr(voice.main, "chat", interrupted_chat)
    main(["--text"])
    assert events == ["credentials", "voice", "open", "speaker closed", "port closed"]


def test_speaker_is_wired_into_brain_and_chat(monkeypatch, capsys):
    events = []
    speaker = FakeSpeaker(events)
    seen = {}

    def recording_chat(brain, **kwargs):
        seen.update(kwargs, brain=brain)

    patch_main(monkeypatch, events, speaker=speaker)
    monkeypatch.setattr(voice.main, "chat", recording_chat)
    main(["--text", "--fake-dispenser", "candy"])
    seen["brain"].on_text("Boo!")
    assert "feed:Boo!" in events
    assert "Boo!" in capsys.readouterr().out
    seen["after_reply"]()
    assert events[-1] == "drain"
    assert seen["brain"].before_tool == speaker.flush  # never blocks: the spell is said while the candy spins


def test_voice_id_env_override(monkeypatch):
    voices, clients = [], []
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    monkeypatch.setattr(voice.main, "ElevenLabs", lambda **kwargs: clients.append(kwargs) or object())
    monkeypatch.setattr(voice.main, "SoundPlayer", lambda device=None: FakePlayer([]))
    monkeypatch.setattr(voice.main, "check_voice", lambda client, voice_id: voices.append(voice_id))
    monkeypatch.setattr(voice.main, "load_lines", lambda tts, voice_id: voices.append(f"lines:{voice_id}") or {"ears": b"\0\0"})
    args = argparse.Namespace(mute=False)
    for value in ["abc", ""]:
        monkeypatch.setenv("ELEVENLABS_VOICE_ID", value)
        speaker, lines = make_speaker(args)
        speaker.close()
        assert lines == {"ears": b"\0\0"}
    assert voices == ["abc", "lines:abc", VOICE_ID, f"lines:{VOICE_ID}"]  # recorded in the voice in use
    assert clients[0] == {"timeout": TTS_TIMEOUT}


def test_no_audio_device_exits_and_names_mute(monkeypatch):
    def no_device(device=None):
        raise sounddevice.PortAudioError("Error querying device -1")

    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    monkeypatch.setattr(voice.main, "ElevenLabs", lambda **kwargs: object())
    monkeypatch.setattr(voice.main, "check_voice", lambda client, voice_id: None)
    monkeypatch.setattr(voice.main, "load_lines", lambda tts, voice_id: {})
    monkeypatch.setattr(voice.main, "SoundPlayer", no_device)
    with pytest.raises(SystemExit) as exit:
        make_speaker(argparse.Namespace(mute=False))
    assert "--mute" in str(exit.value.code)


def test_speaker_closed_when_the_arduino_is_missing(monkeypatch):
    def no_arduino(*args, **kwargs):
        raise DispenserError("no Arduino found: is the USB cable plugged in?")

    events = []
    patch_main(monkeypatch, events, no_arduino, FakeSpeaker(events))
    with pytest.raises(SystemExit) as exit:
        main(["--text"])
    assert "--fake-dispenser" in str(exit.value.code)
    assert "speaker closed" in events


def test_ctrl_c_while_the_port_opens_closes_the_speaker(monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    events = []
    patch_main(monkeypatch, events, interrupted, FakeSpeaker(events))
    main(["--text"])  # a quiet exit, no traceback
    assert "speaker closed" in events


def test_sigterm_while_waiting_for_the_p10s_exits_quietly(monkeypatch):
    def stopped_wait(name, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(1)

    events = []
    patch_main(monkeypatch, events)
    monkeypatch.setattr(voice.main, "wait_for_devices", stopped_wait)
    main([])
    assert events == ["credentials"]  # nothing opened


def test_mute_needs_no_portaudio():
    """sounddevice loads PortAudio when imported, so only make_speaker may import it (fresh interpreter)."""
    code = "import sys, voice.main; assert 'sounddevice' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


TURN = Turn(pcm=b"\0\0", start=0.0, end=1.0, voiced=0.8, level=-30.0)


class EventListener:
    """Listener stand-in for voice mode: listen() records "listen" and takes the next script item:
    a Turn (returned), a number (a turn that long, and took that long), None (the clock moves on by
    timeout, then None) or an exception class (raised); EOFError once the script is done.
    resume() records "resume"."""

    def __init__(self, events, script=(), clock=None):
        self.events = events
        self.script = list(script)
        self.clock = clock
        self.mic = EventMic(events)

    def resume(self):
        self.events.append("resume")

    def listen(self, timeout=None):
        self.events.append("listen")
        if not self.script:
            raise EOFError
        item = self.script.pop(0)
        if item is None:
            self.clock.now += timeout
            return None
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item
        if isinstance(item, (int, float)):
            self.clock.now += item
            return dataclasses.replace(TURN, end=float(item))  # as long as it took
        return item


class EventMic:
    def __init__(self, events):
        self.events = events
        self.device = None

    def close(self):
        self.events.append("mic closed")


class EventEars:
    """Transcriber stand-in: transcribe returns the next of texts; close records it."""

    def __init__(self, events, texts=("Trick or treat",)):
        self.events = events
        self.texts = list(texts)

    def transcribe(self, pcm):
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return text

    def close(self):
        self.events.append("ears closed")


class EventBrain(FakeBrain):
    """Records "greet" and "reply"; greet raises greet_error once."""

    def __init__(self, events, greet_error=None):
        super().__init__()
        self.events = events
        self.greet_error = greet_error

    def greet(self):
        self.events.append("greet")
        if self.greet_error:
            error, self.greet_error = self.greet_error, None
            raise error

    def reply(self, line):
        self.events.append("reply")
        super().reply(line)


class FakeSensorDispenser:
    """Dispenser stand-in for door(): poll() returns the next list of polls ([] when done)."""

    def __init__(self, polls=()):
        self.polls = list(polls)

    def poll(self):
        return self.polls.pop(0) if self.polls else []


class StubRules:
    def __init__(self, attempted=False):
        self.attempted = attempted


def run_door(script=(), texts=(), polls=(), brain=None, dispenser=None, rules=None, status=None, **kwargs):
    """door() on a FakeClock with an EventListener; returns (events, lines written, brain). A
    status=True gets a Status writing into the same lines; status="clocked" one on the FakeClock too.
    kwargs go to door()."""
    events, out, clock = [], [], FakeClock()
    brain = brain or EventBrain(events)
    brain.events = events
    if status:
        status = Status(write=out.append, **({"clock": clock} if status == "clocked" else {}))
    door(
        brain,
        EventListener(events, script, clock),
        EventEars(events, texts),
        dispenser or FakeSensorDispenser(polls),
        Visits(rules or StubRules(), clock),
        after_reply=lambda: events.append("drain"),
        write=lambda *a, end="\n": out.append("".join(map(str, a))),
        status=status,
        **kwargs,
    )
    return events, out, brain


def ticks(seconds):
    return [None] * round(seconds / TICK)


def test_door_greets_at_start_up():
    events, out, _ = run_door()
    assert events == ["greet", "drain", "resume", "listen"]
    assert out[0] == VOICE_GREETING


def test_door_reply_then_drain_then_resume_before_listening():
    events, _, brain = run_door([TURN, TURN], ["Trick or treat", "A vampire"])
    assert events == ["greet", "drain", "resume", "listen", "reply", "drain", "resume", "listen", "reply", "drain", "resume", "listen"]
    assert brain.replies == ["Trick or treat", "A vampire"]


def test_arrival_greets_only_when_no_visit_is_active():
    quiet = ticks(VISIT_TIMEOUT)  # the poll before the tick that reaches VISIT_TIMEOUT
    polls = [[], [Presence.HERE]] + [[]] * (len(quiet) - 1) + [[], [Presence.HERE]]
    events, out, _ = run_door(quiet + [None, None, None], polls=polls)
    assert events.count("greet") == 2
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert out.count("-- new visitor --") == 1  # the HERE during the first visit didn't greet


def test_heard_line_after_a_visit_ended_starts_a_new_one_without_greeting():
    events, out, brain = run_door(ticks(VISIT_TIMEOUT) + [TURN], ["hi"])
    assert "-- visit over --" in out
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert brain.visits == 1
    assert events.count("greet") == 1
    assert brain.replies == ["hi"]


def test_heard_line_during_a_visit_does_not_start_a_new_one():
    _, out, brain = run_door([TURN], ["hi"])
    assert brain.visits == 0
    assert "-- new visitor --" not in out


def test_empty_and_failed_transcripts_are_not_replied_to():
    events, out, _ = run_door([TURN, TURN], ["", ApiError(status_code=500, body="x")])
    assert events == ["greet", "drain", "resume", "listen", "listen", "drain", "resume", "listen"]  # the failed one gets the ears line
    assert sum("didn't catch that" in line for line in out) == 1


def test_failed_transcript_with_nobody_there_gets_no_ears_line():
    events, out, _ = run_door([TURN], [ApiError(status_code=500, body="x")], alone=lambda: True)
    assert events == ["greet", "drain", "resume", "listen", "listen"]  # no "Eh?" to an empty porch
    assert sum("didn't catch that" in line for line in out) == 1  # still on screen


def test_door_hands_keep_each_turn():
    kept = []
    run_door([TURN, TURN], ["hi", ""], keep=lambda turn, outcome: kept.append(outcome))
    assert kept == ["text", "notext"]


def test_reply_error_during_a_greeting_still_drains_and_resumes():
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL))
    events, out, _ = run_door(brain=EventBrain([], greet_error=error))
    assert events == ["greet", "drain", "resume", "listen"]
    assert sum("can't talk right now" in line for line in out) == 1


def test_same_tick_expiry_and_arrival_greets_the_new_visitor():
    quiet = ticks(VISIT_TIMEOUT)
    events, out, _ = run_door(quiet + [None], polls=[[]] * len(quiet) + [[Presence.HERE]])
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert events.count("greet") == 2


def test_gone_ends_the_visit_and_the_next_arrival_is_greeted():
    polls = [[Presence.GONE]] + [[]] * 40 + [[Presence.HERE]]  # 41 ticks = 10.25 s > GONE_GRACE
    events, out, _ = run_door(ticks(11), polls=polls)
    assert out.count("-- visit over --") == 1
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert events.count("greet") == 2


def test_talking_that_began_before_the_visit_ran_out_keeps_the_visit():
    # the evening's logs: a kid got candy, talked on 8 s later, finished after AFTER_CANDY_QUIET,
    # and the visit ended under them: a new visit, a fresh allowance, a second candy
    _, out, brain = run_door(ticks(8) + [4.0], ["Can I have another?"], rules=StubRules(attempted=True))
    assert "-- visit over --" not in out and "-- new visitor --" not in out
    assert brain.visits == 0  # the same visit: no fresh allowance, and Hazel remembers them
    assert brain.replies == ["Can I have another?"]


def test_long_turn_that_began_after_the_visit_ran_out_starts_a_new_one():
    _, out, brain = run_door(ticks(AFTER_CANDY_QUIET) + [4.0], ["Trick or treat"], rules=StubRules(attempted=True))
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert brain.visits == 1
    assert brain.replies == ["Trick or treat"]


def test_arrival_heard_during_a_long_turn_is_answered_not_greeted():
    # the evening's logs: "Hello" -> a greeting -> an answer to the "Hello" said before it
    quiet = ticks(AFTER_CANDY_QUIET)
    polls = [[]] * (len(quiet) + 1) + [[Presence.HERE]]  # B's HERE, buffered while B spoke
    events, out, brain = run_door(quiet + [4.0], ["Trick or treat"], polls=polls, rules=StubRules(attempted=True))
    assert out.index("-- visit over --") < out.index("-- new visitor --")
    assert out.count("-- new visitor --") == 1
    assert events.count("greet") == 1  # start-up only
    assert brain.visits == 1  # B's visit starts fresh, with a fresh allowance
    assert brain.replies == ["Trick or treat"]


def test_arrival_with_a_line_after_the_last_visitor_left_is_answered_not_greeted():
    # A asked for candy and walked away; B walks up talking within GONE_GRACE
    polls = [[Presence.GONE], [], [Presence.HERE]]  # the HERE buffered while B spoke
    events, out, brain = run_door([None, TURN], ["Can we have candy?"], polls=polls, rules=StubRules(attempted=True))
    assert out.count("-- new visitor --") == 1
    assert events.count("greet") == 1  # start-up only
    assert events[-4:] == ["reply", "drain", "resume", "listen"]
    assert brain.visits == 1
    assert brain.replies == ["Can we have candy?"]


def test_door_prints_the_status_every_heartbeat_while_nothing_happens():
    _, out, _ = run_door(ticks(2 * HEARTBEAT), status="clocked")
    statuses = [line for line in out if line.startswith("status:")]
    assert len(statuses) == 3  # start-up, the visit's end at 10 s, a heartbeat at 910 s (the next is due at 1810 s)


def test_door_never_sets_visit_state():
    tree = ast.parse((Path(voice.main.__file__)).read_text())
    for node in ast.walk(tree):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
        for target in targets:
            assert not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "visits")


def test_stray_dispense_lines_do_not_touch_the_visit():
    link = FakeLink(boot=CANDY)  # a late result from an earlier dispense
    dispenser = Dispenser(link)
    rules = CandyRules(dispenser)
    events, out, _ = run_door(ticks(6), dispenser=dispenser, rules=rules)  # a misread HERE or candy line would show
    assert events == ["greet", "drain", "resume"] + ["listen"] * (len(ticks(6)) + 1)
    assert not rules.attempted
    assert "-- new visitor --" not in out and "-- visit over --" not in out
    assert link.written == []


def test_voice_mode_wires_door(monkeypatch):
    events, seen, chats = [], {}, []
    speaker = FakeSpeaker(events)
    ears = (EventListener(events), EventEars(events))
    patch_main(monkeypatch, events, speaker=speaker, ears=ears)

    def recording_door(*args, **kwargs):
        seen.update(kwargs, args=args)

    monkeypatch.setattr(voice.main, "door", recording_door)
    monkeypatch.setattr(voice.main, "chat", lambda brain, **kwargs: chats.append(brain))
    main(["--fake-dispenser", "candy"])
    brain, listener, transcriber, _, visits = seen["args"]
    assert (listener, transcriber) == ears
    assert isinstance(visits, Visits) and visits.rules is brain.rules
    seen["after_reply"]()
    assert events[-1] == "drain"  # half-duplex: listen again only once Hazel is quiet
    assert chats == []
    main(["--text", "--fake-dispenser", "candy"])
    assert len(chats) == 1


def test_unplugged_arduino_during_poll_keeps_the_door_open(monkeypatch, capsys):
    events, opened = [], []

    class UnpluggedPort(RecordingPort):
        def poll(self):
            if len(opened) == 1:
                raise DispenserError("lost the Arduino: device disconnected. Is the USB cable plugged in?")
            return []

    def open_port(*args, **kwargs):
        opened.append(1)
        return UnpluggedPort(events)

    def polling_door(brain, listener, ears, dispenser, *args, **kwargs):
        for _ in range(3):
            assert dispenser.poll() == []
        raise KeyboardInterrupt

    monkeypatch.setattr(voice.dispenser, "RECONNECT_INTERVAL", 0)
    patch_main(monkeypatch, events, open_port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", polling_door)
    main([])
    assert "lost the Arduino" in capsys.readouterr().out  # main()'s logging replaces caplog's handler
    assert len(opened) >= 2
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


def test_voice_mode_order_and_close_order(monkeypatch):
    events = []

    def open_port(*args, **kwargs):
        events.append("open")
        return RecordingPort(events)

    def interrupted_door(*args, **kwargs):
        raise KeyboardInterrupt

    patch_main(monkeypatch, events, open_port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", interrupted_door)
    main([])
    assert events == ["credentials", "voice", "ears", "open", "speaker closed", "mic closed", "port closed", "ears closed"]


@pytest.mark.parametrize("argv", [[], ["--mute"]])
def test_voice_mode_without_elevenlabs_key_exits_before_the_port(monkeypatch, argv):
    events = []
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setattr(voice.main, "check_credentials", lambda client: None)
    monkeypatch.setattr(voice.main.anthropic, "Anthropic", lambda **kwargs: object())
    monkeypatch.setattr(Dispenser, "open", lambda *a, **k: events.append("open"))
    with pytest.raises(SystemExit) as exit:
        main(argv)
    assert "--text" in str(exit.value.code)
    assert events == []


def test_mic_failure_closes_everything(monkeypatch, capsys):
    events = []

    def open_port(*args, **kwargs):
        events.append("open")
        return RecordingPort(events)

    def mic_gone(*args, **kwargs):
        raise MicError("no audio from the microphone for 2 s: is it unplugged?")

    patch_main(monkeypatch, events, open_port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", mic_gone)
    with pytest.raises(SystemExit) as exit:
        main([])
    assert exit.value.code == 1  # the supervisor restarts it
    assert "unplugged" in capsys.readouterr().out
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


def test_silence_flag_reaches_open_ears(monkeypatch):
    calls = []

    def fake_open_ears(*args, **kwargs):
        calls.append((args, kwargs))
        return EventListener([]), EventEars([])

    patch_main(monkeypatch, [])
    monkeypatch.setattr(voice.main, "open_ears", fake_open_ears)
    monkeypatch.setattr(voice.main, "door", lambda *args, **kwargs: None)
    main(["--silence", "1.2", "--fake-dispenser", "candy"])
    assert calls == [((1.2,), {"hint": " (or use --text)", "device": 1})]
    with pytest.raises(SystemExit) as exit:
        main(["--silence", "0"])
    assert exit.value.code == 2


def test_failing_port_close_still_closes_ears(monkeypatch):
    """A yanked USB cable makes the port's close raise; pending transcript deletes must still be waited for."""
    events = []

    class YankedPort(RecordingPort):
        def close(self):
            super().close()
            raise DispenserError("serial link lost")

    def interrupted_door(*args, **kwargs):
        raise KeyboardInterrupt

    patch_main(monkeypatch, events, lambda *a, **k: YankedPort(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", interrupted_door)
    main([])  # Reconnecting.close() swallows the gone link's error
    assert events[-2:] == ["port closed", "ears closed"]


def test_ears_failing_to_open_closes_the_speaker_before_the_port(monkeypatch):
    events = []

    def no_microphone(*args, **kwargs):
        events.append("ears")
        sys.exit("no microphone: Error querying device -1 (or use --text)")

    patch_main(monkeypatch, events, lambda *a, **k: events.append("open"), FakeSpeaker(events))
    monkeypatch.setattr(voice.main, "open_ears", no_microphone)
    with pytest.raises(SystemExit):
        main([])
    assert events == ["credentials", "voice", "ears", "speaker closed"]


def test_write_line_starts_a_line_of_its_own(capsys):
    console = Console()
    console.write("Hazel: ", end="")
    console.write_line("status: LLM OK")
    console.write_line("status: voice OK")
    assert capsys.readouterr().out.splitlines() == ["Hazel: ", "status: LLM OK", "status: voice OK"]


def test_a_log_line_never_lands_mid_sentence(capsys):
    console = Console()
    logger = logging.getLogger("voice.test_console")
    logger.addHandler(console)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        console.write("Hazel: ", end="")
        console.write("Heh heh,", end="")
        logger.info("dispensed: candy")
        console.write(" grab it!")
        logger.info("visit over")
    finally:
        logger.removeHandler(console)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Hazel: Heh heh,"
    assert lines[1].endswith("INFO  voice.test_console: dispensed: candy")
    assert lines[2] == " grab it!"
    assert lines[3].endswith("visit over")


@pytest.mark.parametrize("argv, level", [([], logging.INFO), (["--debug"], logging.DEBUG)])
def test_debug_flag_sets_the_terminal_log_level(monkeypatch, argv, level):
    patch_main(monkeypatch, [])
    monkeypatch.setattr(voice.main, "chat", lambda brain, **kwargs: None)
    main(["--text", "--fake-dispenser", "candy", *argv])
    (console,) = [h for h in logging.getLogger().handlers if isinstance(h, Console)]
    assert console.level == level
    assert logging.getLogger("voice").level == logging.DEBUG  # the file always gets everything
    assert logging.getLogger().level == logging.WARNING  # the SDKs' own debug logs stay quiet


def test_full_log_file_has_the_screen_and_debug_records(tmp_path, capsys):
    console, path = setup_logging(debug=False, log_dir=tmp_path)
    try:
        console.write("visitor: Trick or treat  (-33 dB)")
        console.write("Hazel: ", end="")
        console.write("Heh heh,", end="")
        logging.getLogger("voice.rules").info("dispensed: candy")
        console.write(" grab it!")
        logging.getLogger("voice.dispenser").debug("arduino: beam: CLEAR")
    finally:
        logging.getLogger().removeHandler(console)
        for handler in logging.getLogger().handlers[:]:
            if getattr(handler, "baseFilename", None) == str(path):
                handler.close()
                logging.getLogger().removeHandler(handler)
    assert path.parent == tmp_path and path.name.startswith("voice-") and path.suffix == ".log"
    lines = path.read_text().splitlines()
    assert [line.split(": ", 1)[1] for line in lines] == [
        "visitor: Trick or treat  (-33 dB)",
        "dispensed: candy",
        "Hazel: Heh heh, grab it!",  # whole, after the record that came mid-sentence
        "arduino: beam: CLEAR",
    ]
    screen = capsys.readouterr().out
    assert "arduino: beam: CLEAR" not in screen  # INFO on the terminal without --debug
    assert screen.count("Trick or treat") == 1  # the file copy isn't printed again


def test_typed_lines_go_to_the_full_log(caplog):
    caplog.set_level("INFO", logger="voice.screen")
    run_chat(FakeBrain(), ["trick or treat", "/quit"])
    assert "visitor> trick or treat" in [r.getMessage() for r in caplog.records]


def test_logs_are_git_ignored():
    ignored = subprocess.run(["git", "check-ignore", "-q", "logs/voice-x.log"], cwd=Path(voice.main.__file__).parents[1], check=False)
    assert ignored.returncode == 0  # visitors' words must never be committed


class DistanceDispenser:
    """Dispenser stand-in for SensorNote: distance() returns the next answer, or raises it."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0

    def distance(self):
        self.asked += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def hear_lines(caplog, dispenser, level=logging.DEBUG):
    hear_log = logging.getLogger("voice.hear")
    note = SensorNote(dispenser)
    hear_log.addFilter(note)
    caplog.set_level(logging.DEBUG, logger="voice.hear")
    try:
        hear_log.log(level, "dropped a turn: %s (%.2f s voiced, %.0f dB)", "too quiet", 1.31, -47.0)
    finally:
        hear_log.removeFilter(note)
    return [r.getMessage() for r in caplog.records]


@pytest.mark.parametrize(
    "answer, note",
    [(62, "sensor: 62 cm"), (None, "sensor: nothing in range"), (DispenserError("lost the Arduino: gone"), "sensor: no answer")],
)
def test_hear_debug_lines_get_the_sensor_distance(caplog, answer, note):
    lines = hear_lines(caplog, DistanceDispenser(answer))
    assert lines == [f"dropped a turn: too quiet (1.31 s voiced, -47 dB); {note}"]


@pytest.mark.parametrize(
    "answer, nobody",
    [(62, False), (149, False), (150, True), (291, True), (None, True), (DispenserError("lost the Arduino: gone"), False)],
)
def test_nobody_there_is_no_reading_under_150_cm(answer, nobody):
    assert nobody_there(DistanceDispenser(answer)) is nobody  # 150 cm: HERE_CM


def run_main_door(monkeypatch, argv, port=None, during=lambda listener, *args, **kwargs: None):
    """main(argv) in voice mode with door() replaced by during(listener, *door's args, **its kwargs),
    called while the port is open."""
    events = []
    listener = EventListener(events)
    open_port = (lambda *a, **k: port) if port else None
    patch_main(monkeypatch, events, open_port, FakeSpeaker(events), ears=(listener, EventEars(events)))
    monkeypatch.setattr(voice.main, "door", lambda *args, **kwargs: during(listener, *args, **kwargs))
    main(argv)


def test_voice_mode_is_alone_only_with_no_visit_and_nobody_in_front(monkeypatch):
    seen = []

    def during(listener, brain, _, ears, dispenser, visits, alone, **kwargs):
        assert listener.alone is alone
        seen.append((alone(), listener.in_visit()))
        visits.arrived()
        seen.append((alone(), listener.in_visit()))  # a visit is going

    run_main_door(monkeypatch, [], RecordingPort([]), during)  # RecordingPort: nothing in range
    run_main_door(monkeypatch, ["--fake-dispenser", "candy"], during=during)  # no sensor: can't tell
    assert seen == [(True, False), (False, True), (False, False), (False, True)]


def keep_some(listener, *args, keep, **kwargs):
    keep(TURN, "notext")
    listener.on_drop(TURN, "too quiet with nobody there")
    listener.on_drop(TURN, "too short")


def test_keep_turns_saves_wavs_named_with_the_distance(monkeypatch, tmp_path):
    monkeypatch.setattr(voice.hear, "KEEP_DIR", tmp_path / "turns")
    run_main_door(monkeypatch, ["--keep-turns"], RecordingPort([]), keep_some)
    ends = sorted(path.name.split("_", 3)[-1] for path in (tmp_path / "turns").iterdir())
    assert ends == ["none_alone.wav", "none_notext.wav"]  # the too-short blip isn't kept


def test_without_keep_turns_nothing_is_saved(monkeypatch, tmp_path):
    monkeypatch.setattr(voice.hear, "KEEP_DIR", tmp_path / "turns")
    run_main_door(monkeypatch, [], RecordingPort([]), keep_some)
    assert not (tmp_path / "turns").exists()


@pytest.mark.parametrize("answer, shown", [(87, "87 cm"), (None, "none"), (DispenserError("lost the Arduino: gone"), "?")])
def test_sensor_reading_for_the_status_line(answer, shown):
    assert sensor_reading(DistanceDispenser(answer)) == shown


def test_voice_mode_status_shows_the_distance(monkeypatch, capsys):
    events = []
    port = RecordingPort(events)
    patch_main(monkeypatch, events, lambda *a, **k: port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", lambda *args, status, **kwargs: status.show())
    main([])
    (line,) = status_lines(capsys.readouterr().out)
    assert "voice OK · distance none · visits 0" in line  # RecordingPort: nothing in range


def test_only_debug_lines_ask_the_sensor(caplog):
    dispenser = DistanceDispenser()
    assert hear_lines(caplog, dispenser, level=logging.WARNING) == ["dropped a turn: too quiet (1.31 s voiced, -47 dB)"]
    assert dispenser.asked == 0


def test_voice_mode_with_the_arduino_adds_the_sensor_note_and_removes_it(monkeypatch):
    events, seen = [], []
    port = RecordingPort(events)
    patch_main(monkeypatch, events, lambda *a, **k: port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))

    def recording_door(*args, **kwargs):
        seen.extend((f, f.dispenser.inner) for f in logging.getLogger("voice.hear").filters if isinstance(f, SensorNote))

    monkeypatch.setattr(voice.main, "door", recording_door)
    main([])
    assert len(seen) == 1 and seen[0][1] is port
    assert not any(isinstance(f, SensorNote) for f in logging.getLogger("voice.hear").filters)
    seen.clear()
    main(["--fake-dispenser", "candy"])  # no sensor: no note
    assert seen == []


def test_p10s_is_the_default_device(monkeypatch, devices):
    events, speakers, ears = [], [], []
    patch_main(monkeypatch, events)
    monkeypatch.setattr(voice.main, "make_speaker", lambda args, device=None: speakers.append(device) or (None, {}))

    def fake_open_ears(*args, device=None, **kwargs):
        ears.append(device)
        return EventListener([]), EventEars([])

    monkeypatch.setattr(voice.main, "open_ears", fake_open_ears)
    monkeypatch.setattr(voice.main, "door", lambda *args, **kwargs: None)
    main(["--fake-dispenser", "candy"])
    main(["--fake-dispenser", "candy", "--device", "default"])
    assert devices == ["P10S"]
    assert speakers == [2, None] and ears == [1, None]


def test_device_is_resolved_before_any_stream_opens(monkeypatch):
    events = []

    def open_port(*args, **kwargs):
        events.append("open")
        return RecordingPort(events)

    def interrupted_door(*args, **kwargs):
        raise KeyboardInterrupt

    patch_main(monkeypatch, events, open_port, FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "wait_for_devices", lambda name, **kwargs: events.append("devices") or (1, 2))
    monkeypatch.setattr(voice.main, "door", interrupted_door)
    main([])
    assert events[:5] == ["credentials", "devices", "voice", "ears", "open"]  # the re-scan needs every stream closed


def test_text_mute_skips_device_resolution(monkeypatch, devices):
    patch_main(monkeypatch, [])
    monkeypatch.setattr(voice.main, "chat", lambda brain, **kwargs: None)
    main(["--text", "--mute", "--fake-dispenser", "candy"])
    assert devices == []


def test_unknown_device_exits_with_the_names_seen(monkeypatch):
    def no_such_device(name, **kwargs):
        raise DeviceError(f"no audio input matching {name!r} after 60 s; saw: alsa_input.pci-0000_00_1f.3.analog-stereo")

    events = []
    patch_main(monkeypatch, events)
    monkeypatch.setattr(voice.main, "wait_for_devices", no_such_device)
    with pytest.raises(SystemExit) as exit:
        main(["--device", "Jabra"])
    assert "'Jabra'" in str(exit.value.code) and "saw: alsa_input" in str(exit.value.code)
    assert events == ["credentials"]  # never started on another device


def run_door_with_reopen(script, reopen=None, status=None):
    """door() with reopen_audio recording "reopen" (or running reopen); returns (events, lines)."""
    events, out, clock = [], [], FakeClock()
    if status:
        status = Status(write=out.append)

    def reopen_audio():
        events.append("reopen")
        if reopen:
            reopen()

    door(
        EventBrain(events),
        EventListener(events, script, clock),
        EventEars(events, ()),
        FakeSensorDispenser(),
        Visits(StubRules(), clock),
        after_reply=lambda: events.append("drain"),
        write=lambda *a, end="\n": out.append("".join(map(str, a))),
        reopen_audio=reopen_audio,
        status=status,
    )
    return events, out


def test_mic_loss_reopens_audio_and_keeps_listening():
    events, out = run_door_with_reopen([MicError, None])
    assert events == ["greet", "drain", "resume", "listen", "reopen", "resume", "listen", "listen"]
    assert any("reopening the audio device" in line for line in out)


def test_silent_mic_is_not_reopened():
    with pytest.raises(SilentMic):
        run_door_with_reopen([SilentMic])


def test_door_without_reopen_audio_ends_on_mic_error():
    with pytest.raises(MicError):
        run_door(script=[MicError])


def test_mic_that_never_comes_back_exits_1(monkeypatch):
    events = []

    def never_back(mic, **kwargs):
        raise MicError("the audio device didn't come back in 60 s: Device unavailable")

    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events), ears=(EventListener(events, [MicError]), EventEars(events)))
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: EventBrain(events))
    monkeypatch.setattr(voice.main, "reopen_mic", never_back)
    with pytest.raises(SystemExit) as exit:
        main([])
    assert exit.value.code == 1
    assert "reset output" in events  # the speaker was freed first
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


def test_mic_that_comes_back_keeps_the_run_going(monkeypatch, capsys):
    events, mics = [], []
    listener = EventListener(events, [MicError])
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events), ears=(listener, EventEars(events)))
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: EventBrain(events))
    monkeypatch.setattr(voice.main, "reopen_mic", lambda mic, **kwargs: mics.append(mic))
    main([])  # the script ends with EOFError: a clean end
    assert mics == [listener.mic]
    assert "audio device back" in capsys.readouterr().out


def test_voice_gone_ends_the_run(monkeypatch):
    events = []
    speaker = FakeSpeaker(events, mute_after=1)  # muted for good at the greeting's drain
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), speaker, ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: EventBrain(events))
    with pytest.raises(SystemExit) as exit:
        main([])
    assert exit.value.code == 1
    assert "listen" not in events  # ended right after the greeting
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


def test_claude_failure_calls_on_result_with_the_error():
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL))
    results, after = [], []
    lines = iter(["a", "b"])

    def read(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    chat(FakeBrain(error=error), read, lambda *a, end="\n": None, after_reply=lambda: after.append(1), on_result=results.append)
    assert results == [error, None]
    assert len(after) == 2


STATUS_RECORD = re.compile(r"\d\d:\d\d:\d\d\.\d{3} INFO  voice\.status: (status: .*)")


def status_lines(out: str) -> list[str]:
    """The status lines main() printed, each a voice.status log record (with its time and level)."""
    return [m[1] for line in out.splitlines() if (m := STATUS_RECORD.fullmatch(line))]


def run_main_typed(monkeypatch, speaker, lines, brain_error=None, typed=("trick or treat",)):
    """main(["--text"]) with typed lines, the brain failing with brain_error once; returns the events."""
    events = speaker.events if speaker else []
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), speaker, lines=lines)
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: FakeBrain(error=brain_error))
    typed = iter(typed)

    def one_line(prompt):
        try:
            return next(typed)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(voice.main, "chat", functools.partial(chat, read=one_line))
    main(["--text"])
    return events


CONNECTION_ERROR = anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL))


def test_fallback_uses_the_cache_else_tts(monkeypatch, capsys):
    run_main_typed(monkeypatch, None, {}, CONNECTION_ERROR)  # muted: the line is printed only
    assert LINES["foggy"] in capsys.readouterr().out
    events = run_main_typed(monkeypatch, FakeSpeaker([]), {"foggy": b"\x01\x00"}, CONNECTION_ERROR)
    assert "play:b'\\x01\\x00'" in events
    events = run_main_typed(monkeypatch, FakeSpeaker([]), {}, CONNECTION_ERROR)
    assert f"feed:\n{LINES['foggy']} " in events


def test_failed_tts_reply_is_followed_by_croaky_once(monkeypatch, capsys):
    speaker = FakeSpeaker([], failing_drains=2)  # the reply's voice failed, and so did the croaky line's
    events = run_main_typed(monkeypatch, speaker, {"croaky": b"\x02\x00"})
    assert events.count("play:b'\\x02\\x00'") == 1
    assert capsys.readouterr().out.count(LINES["croaky"]) == 1


def test_billing_error_is_logged_loudly(monkeypatch, capsys):
    body = {"type": "error", "error": {"type": "billing_error", "message": "Your credit balance is too low"}}
    response = httpx2.Response(400, request=httpx2.Request("POST", MESSAGES_URL))
    run_main_typed(monkeypatch, None, {}, anthropic.APIStatusError(message="x", response=response, body=body))
    out = capsys.readouterr().out  # main()'s logging replaces caplog's handler
    assert "ERROR voice.fallback: API PROBLEM (Anthropic billing)" in out
    assert LINES["foggy"] in out


def test_stt_failure_plays_the_ears_line_and_resumes():
    events, clock, results = [], FakeClock(), []
    door(
        EventBrain(events),
        EventListener(events, [TURN], clock),
        EventEars(events, [ApiError(status_code=500, body="x")]),
        FakeSensorDispenser(),
        Visits(StubRules(), clock),
        after_reply=lambda: events.append("drain"),
        write=lambda *a, end="\n": None,
        fallback=lambda name: events.append(f"fallback:{name}"),
        on_result=results.append,
    )
    assert events == ["greet", "drain", "resume", "listen", "fallback:ears", "drain", "resume", "listen"]
    assert results == [None]  # the greeting only: the ears line isn't a Claude result


def test_elevenlabs_quota_on_a_turn_is_logged_loudly(caplog):
    caplog.set_level("ERROR", logger="voice.fallback")
    run_door([TURN], [ApiError(status_code=401, body={"detail": {"status": "quota_exceeded"}})])
    assert [r.getMessage().split(":")[0] for r in caplog.records] == ["API PROBLEM (ElevenLabs account (quota or key)"]


def test_door_prints_status_at_start_and_after_each_visit():
    _, out, _ = run_door(ticks(VISIT_TIMEOUT) + [TURN], ["hi"], status=True)
    statuses = [i for i, line in enumerate(out) if line.startswith("status:")]
    assert len(statuses) == 2
    assert statuses[0] < out.index("-- visit over --") < statuses[1]
    assert out[statuses[0]].endswith("visits 1 · candies 0")  # the start-up greeting's visit
    assert "hi" not in out[statuses[1]]  # never a visitor's words


def test_new_visitors_are_counted():
    _, out, _ = run_door(ticks(VISIT_TIMEOUT) + [TURN] + ticks(VISIT_TIMEOUT) + [None], ["hi"], status=True)
    assert [line.split(" · ")[-2] for line in out if line.startswith("status:")][-1] == "visits 2"


def test_mic_loss_and_recovery_show_in_status():
    _, out = run_door_with_reopen([MicError], status=True)
    statuses = [line for line in out if line.startswith("status:")]
    assert "mic LOST" in statuses[1] and "last error" in statuses[1]
    assert "mic OK" in statuses[2]


def test_stt_failure_shows_ears_lost_then_ok():
    _, out, _ = run_door([TURN, TURN], [ApiError(status_code=500, body="x"), "hi"], status=True)
    statuses = [line for line in out if line.startswith("status:")]
    assert "ears LOST" in statuses[1] and "ears OK" in statuses[2]


def test_claude_error_marks_claude_lost_then_ok(monkeypatch, capsys):
    run_main_typed(monkeypatch, None, {}, CONNECTION_ERROR, typed=["a", "b"])
    statuses = status_lines(capsys.readouterr().out)
    assert len(statuses) == 2  # each on a line of its own, though Hazel's line was open
    assert "LLM LOST" in statuses[0] and statuses[0].endswith("LLM: Connection error.")
    assert "LLM OK" in statuses[1]


def test_pick_line_avoids_the_last_one():
    recorded = {"greeting-1": b"", "greeting-2": b"", "foggy": b"", "filler-1": b""}
    assert pick_line(GREETINGS, recorded, "greeting-1", choice=lambda names: names) == ["greeting-2"]  # never a fallback line
    assert pick_line(GREETINGS, {"greeting-3": b""}, "greeting-3") == "greeting-3"  # the only one
    assert pick_line(GREETINGS, {"foggy": b""}, None) is None
    assert pick_line(FILLERS, recorded, None) == "filler-1"


def run_main_fillers(monkeypatch, lines, speaker=True):
    """main() in voice mode with door replaced: Brain's on_slow called three times. Returns the
    events and the on_slow main() gave Brain."""
    events, slow = [], []

    def fake_brain(*args, on_slow=None, **kwargs):
        slow.append(on_slow)
        return FakeBrain()

    ears = (EventListener(events), EventEars(events))
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events) if speaker else None, ears=ears, lines=lines)
    monkeypatch.setattr(voice.main, "Brain", fake_brain)

    def filler_door(*args, **kwargs):
        for _ in range(3 if slow[0] else 0):
            slow[0]()

    monkeypatch.setattr(voice.main, "door", filler_door)
    main([] if speaker else ["--mute"])
    return events, slow[0]


def test_a_slow_reply_plays_a_recorded_filler_never_the_same_twice_in_a_row(monkeypatch, capsys):
    events, _ = run_main_fillers(monkeypatch, {"filler-1": b"\x01\x00", "filler-2": b"\x02\x00", "foggy": b"\x03\x00"})
    played = [e for e in events if e.startswith("play:")]
    assert len(played) == 3 and played[0] != played[1] != played[2]
    assert "play:b'\\x03\\x00'" not in played  # never a fallback line
    out = capsys.readouterr().out
    assert FILLERS["filler-1"] in out and FILLERS["filler-2"] in out


def test_no_recorded_filler_says_nothing(monkeypatch):
    events, _ = run_main_fillers(monkeypatch, {"foggy": b"\x03\x00"})
    assert not [e for e in events if e.startswith("play:") or e.startswith("feed:")]


def test_muted_hazel_has_no_filler(monkeypatch):
    _, on_slow = run_main_fillers(monkeypatch, {"filler-1": b"\x01\x00"}, speaker=False)
    assert on_slow is None


def run_main_greeting(monkeypatch, lines, first_result=None):
    """main() in voice mode with door replaced: on_result(first_result), then two greetings, each
    followed by on_result(None) as answer() does. Returns the events and the FakeBrain."""
    events, brains = [], []
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events), ears=(EventListener(events), EventEars(events)), lines=lines)
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: brains.append(FakeBrain()) or brains[-1])

    def greeting_door(brain, *args, greet, on_result, **kwargs):
        if first_result:
            on_result(first_result)
        for _ in range(2):
            greet()
            on_result(None)

    monkeypatch.setattr(voice.main, "door", greeting_door)
    main([])
    return events, brains[0]


def test_recorded_greetings_play_at_random_without_asking_the_model(monkeypatch, capsys):
    events, brain = run_main_greeting(monkeypatch, {"greeting-1": b"\x01\x00", "greeting-2": b"\x02\x00", "foggy": b"\x03\x00"})
    assert sorted(brain.replies) == [f"<greeted:{GREETINGS['greeting-1']}>", f"<greeted:{GREETINGS['greeting-2']}>"]  # not the same twice
    assert sorted(e for e in events if e.startswith("play:")) == ["play:b'\\x01\\x00'", "play:b'\\x02\\x00'"]
    assert GREETINGS["greeting-1"] in capsys.readouterr().out


def test_no_recorded_greeting_means_the_model_greets(monkeypatch):
    events, brain = run_main_greeting(monkeypatch, {"foggy": b"\x03\x00"})
    assert brain.replies == ["<greet>", "<greet>"]
    assert not [e for e in events if e.startswith("play:")]


def test_a_recorded_greeting_says_nothing_about_the_llm(monkeypatch, capsys):
    run_main_greeting(monkeypatch, {"greeting-1": b"\x01\x00"}, first_result=CONNECTION_ERROR)
    statuses = status_lines(capsys.readouterr().out)
    assert len(statuses) == 1 and "LLM LOST" in statuses[0]  # the greetings didn't mark it OK


def test_status_exists_before_the_port_opens(monkeypatch, capsys):
    events = []

    class FlakyReconnecting:
        def __init__(self, port, on_change):
            self.on_change = on_change

        def wait_connected(self, timeout):
            self.on_change(False, "lost the Arduino: not yet")  # a status change before the rest exists
            self.on_change(True, "")

        def distance(self):
            raise DispenserError("lost the Arduino: not yet")  # Reconnecting while gone

        def close(self):
            events.append("port closed")

    patch_main(monkeypatch, events)
    monkeypatch.setattr(voice.main, "Reconnecting", FlakyReconnecting)
    monkeypatch.setattr(voice.main, "chat", lambda brain, **kwargs: None)
    main(["--text", "--mute"])
    out = capsys.readouterr().out
    assert "INFO  voice.status: status: arduino LOST" in out and "distance ? · visits 0 · candies 0" in out
    assert events[-1] == "port closed"


def test_status_parts_follow_the_flags(monkeypatch, capsys):
    patch_main(monkeypatch, [])
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: FakeBrain(error=CONNECTION_ERROR))
    typed = iter(["a"])
    monkeypatch.setattr(voice.main, "chat", functools.partial(chat, read=lambda prompt: next(typed, "/quit")))
    main(["--text", "--mute", "--fake-dispenser", "candy"])
    (line,) = status_lines(capsys.readouterr().out)
    assert line.startswith("status: LLM LOST · visits 0 · candies 0")


def test_sigterm_runs_the_ctrl_c_cleanup(monkeypatch):
    events = []

    def stopped_door(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGTERM)  # systemctl --user stop
        time.sleep(1)  # the handler raises before this ends
        raise AssertionError("SIGTERM didn't interrupt")

    def previous(signum, frame):
        raise AssertionError("the previous handler ran")

    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events), ears=(EventListener(events), EventEars(events)))
    monkeypatch.setattr(voice.main, "door", stopped_door)
    old = signal.signal(signal.SIGTERM, previous)
    try:
        main([])  # a clean stop: no SystemExit
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, old)
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


def test_sigterm_during_a_reply_still_cleans_up(monkeypatch):
    events = []

    class StoppedBrain(EventBrain):
        def reply(self, line):
            super().reply(line)
            os.kill(os.getpid(), signal.SIGTERM)  # mid-reply to a visitor
            time.sleep(1)

    listener = EventListener(events, [TURN, TURN])
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), FakeSpeaker(events), ears=(listener, EventEars(events, ["hi", "again"])))
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: StoppedBrain(events))
    main([])
    assert events.count("reply") == 1  # stopped in the first reply; the second turn never ran
    assert events[-4:] == ["speaker closed", "mic closed", "port closed", "ears closed"]


SERVICE = Path(voice.main.__file__).resolve().parents[1] / "tools" / "candy-witch.service"


def test_service_template_restarts_and_names_the_device():
    unit = SERVICE.read_text()
    settings = dict(line.split("=", 1) for line in unit.splitlines() if "=" in line and not line.startswith("#"))
    assert settings["Restart"] == "always"
    assert settings["StartLimitIntervalSec"] == "0"  # never gives up
    assert settings["ExecStart"] == "@UV@ run --env-file .env voice/main.py"  # no --device: the P10S default
    assert settings["WorkingDirectory"] == "@REPO@"
    assert float(settings["TimeoutStopSec"]) > CLOSE_LIMIT  # pending transcript deletes finish
    assert "pipewire" in settings["After"]


class ReleasablePlayer:
    def __init__(self, events):
        self.events = events

    def release(self):
        self.events.append("release")

    def move_to(self, device):
        self.events.append(f"move to {device}")


def run_mic_loss(monkeypatch, argv, rescan=lambda name, **kwargs: (5, 6)):
    """main(argv) whose listener loses the mic once; returns the events."""
    events = []
    speaker = FakeSpeaker(events)
    listener = EventListener(events, [MicError])
    patch_main(monkeypatch, events, lambda *a, **k: RecordingPort(events), speaker, ears=(listener, EventEars(events)))
    monkeypatch.setattr(voice.main, "Brain", lambda *args, **kwargs: EventBrain(events))

    def recording_wait(name, **kwargs):
        if kwargs.get("rescan"):
            events.append("rescan")
            return rescan(name, **kwargs)
        return (1, 2)

    monkeypatch.setattr(voice.main, "wait_for_devices", recording_wait)
    monkeypatch.setattr(voice.main, "reopen_mic", lambda mic, **kwargs: events.append(f"reopen mic {mic.device}"))
    main(argv)
    return events


def test_mic_loss_rescans_before_reopening_on_the_p10s(monkeypatch):
    events = run_mic_loss(monkeypatch, [])
    start = events.index("reset output")
    assert events[start : start + 6] == ["reset output", "release", "mic closed", "rescan", "move to 6", "reopen mic 5"]


def test_mic_loss_with_the_system_default_reopens_without_rescanning(monkeypatch):
    events = run_mic_loss(monkeypatch, ["--device", "default"])
    assert "rescan" not in events and "release" not in events
    assert "reopen mic None" in events


def test_p10s_not_back_after_the_rescan_wait_exits_1(monkeypatch):
    def never_back(name, **kwargs):
        raise DeviceError(f"no audio input matching {name!r} after 60 s; saw: alsa_input.pci-0000_00_1f.3.analog-stereo")

    with pytest.raises(SystemExit) as exit:
        run_mic_loss(monkeypatch, [], rescan=never_back)
    assert exit.value.code == 1
