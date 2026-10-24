"""Hazel's voice, offline: a fake TTS and a fake player record what would be heard."""

import inspect
import threading
import time
import typing

import httpx
import pytest
import sounddevice
import voice.speak
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from test_brain import GRAB_TURN, TOOL_TURN, FakeClient, StubDispenser
from voice.brain import Brain
from voice.rules import CandyRules
from voice.speak import OUTPUT_FORMAT, VOICE_ID, SoundPlayer, Speaker, check_voice, elevenlabs_tts, speakable, split_sentences


class FakeTTS:
    """TTS stand-in: records each sentence it is asked to say, then yields its bytes."""

    def __init__(self, events, fail_on=None, error=None, chunks=None, delay=0):
        self.events = events
        self.fail_on = fail_on
        self.error = error
        self.chunks = chunks
        self.delay = delay

    def __call__(self, sentence):
        self.events.append(f"say:{sentence}")
        time.sleep(self.delay)
        if sentence == self.fail_on:
            raise self.error
        yield from self.chunks or [sentence.encode()]


class FakePlayer:
    """Player stand-in: records written bytes; like the real stream, writes fail once aborted, until
    reopen() (which records "reopen", or raises the next of reopen_errors)."""

    def __init__(self, events, write_error=None, abort_error=None, wait_delay=0, reopen_errors=()):
        self.events = events
        self.write_error = write_error
        self.wait_delay = wait_delay
        self.abort_error = abort_error
        self.reopen_errors = list(reopen_errors)
        self.aborted = False
        self.written = []

    def write(self, data):
        if self.aborted:
            raise RuntimeError("Stream is stopped")
        if self.write_error:
            raise self.write_error
        self.written.append(data)

    def wait(self):
        time.sleep(self.wait_delay)
        self.events.append("<heard>")

    def abort(self):
        self.aborted = True
        if self.abort_error:
            raise self.abort_error

    def reopen(self):
        if self.reopen_errors:
            raise self.reopen_errors.pop(0)
        self.aborted = False
        self.events.append("reopen")


def make_speaker(**tts):
    events, errors = [], []
    player = FakePlayer(events)
    speaker = Speaker(FakeTTS(events, **tts), player, on_error=errors.append)
    return speaker, player, events, errors


def drains(speaker):
    """drain() returns within 2 s (so a hang fails the test instead of freezing the suite)."""
    t = threading.Thread(target=speaker.drain, daemon=True)
    t.start()
    t.join(2)
    assert not t.is_alive()


SPLITS = [
    ("Heh heh! Come closer. ", ["Heh heh!", "Come closer."], "", ["Heh heh!", "Come closer."]),
    ("Ask Dr. Hazel. ", ["Ask Dr. Hazel."], "", ["Ask Dr. Hazel."]),
    ("Well... let me see. ", ["Well... let me see."], "", ["Well... let me see."]),
    ("Wait... Boo! ", ["Wait...", "Boo!"], "", ["Wait...", "Boo!"]),
    ("Really?! Yes. ", ["Really?!", "Yes."], "", ["Really?!", "Yes."]),
    ('She said "Boo!" Then left. ', ['She said "Boo!"', "Then left."], "", ['She said "Boo!"', "Then left."]),
    ("line one\nline two", ["line one"], "line two", ["line one", "line two"]),
    ("Done.", [], "Done.", ["Done."]),
    ("Wait... ", [], "Wait... ", ["Wait..."]),
    ("J. R. R. Tolkien wrote it. ", ["J. R. R. Tolkien wrote it."], "", ["J. R. R. Tolkien wrote it."]),
    ("Ask Dr", [], "Ask Dr", ["Ask Dr"]),
    ("I won't. Go away! ", ["I won't.", "Go away!"], "", ["I won't.", "Go away!"]),
    ("It’s Hazel’s. Boo! ", ["It’s Hazel’s.", "Boo!"], "", ["It’s Hazel’s.", "Boo!"]),
    ("Ask Dr.\nHazel", ["Ask Dr."], "Hazel", ["Ask Dr.", "Hazel"]),
    ("Well...\nlet me see", ["Well..."], "let me see", ["Well...", "let me see"]),
]


@pytest.mark.parametrize("text, sentences, remainder, final", SPLITS)
def test_split_sentences(text, sentences, remainder, final):
    assert split_sentences(text) == (sentences, remainder)
    assert split_sentences(text, final=True) == (final, "")


@pytest.mark.parametrize("text", [s[0] for s in SPLITS])
def test_streaming_one_character_at_a_time_says_the_same_sentences(text):
    speaker, _, events, _ = make_speaker()
    for c in text:
        speaker.feed(c)
    speaker.drain()
    said = [e.removeprefix("say:") for e in events if e.startswith("say:")]
    assert said == split_sentences(text, final=True)[0]


@pytest.mark.parametrize(
    "sentence, spoken",
    [("Boo! 🎃", "Boo!"), ("🎃👻", ""), ("Hi 👋🏽 there", "Hi there"), ("Hi 👨‍👩‍👧 all", "Hi all"), ("...", ""), ("1️⃣ wish", "1 wish")],
)
def test_speakable(sentence, spoken):
    assert speakable(sentence) == spoken


def test_sentences_are_said_in_order_then_heard():
    speaker, _, events, _ = make_speaker()
    speaker.feed("Heh heh! Abraca")
    speaker.feed("dabra")
    speaker.drain()
    assert events == ["say:Heh heh!", "say:Abracadabra", "<heard>"]


def test_drain_blocks_until_heard():
    events = []
    speaker = Speaker(FakeTTS(events, delay=0.2), FakePlayer(events, wait_delay=0.2))
    speaker.feed("One. Two. ")
    speaker.drain()
    assert events == ["say:One.", "say:Two.", "<heard>"]


def test_drain_returns_even_if_reporting_the_error_fails():
    def broken_pipe(line):
        raise BrokenPipeError

    events = []
    speaker = Speaker(FakeTTS(events), FakePlayer(events, write_error=RuntimeError("x")), on_error=broken_pipe)
    speaker.feed("One. ")
    drains(speaker)
    drains(speaker)


def test_tts_failure_is_reported_once_and_skips_the_rest_of_the_reply():
    speaker, _, events, errors = make_speaker(fail_on="One.", error=ApiError(status_code=401, body="x"))
    speaker.feed("One. Two. ")
    drains(speaker)
    assert len(errors) == 1 and "lost her voice" in errors[0]
    assert "say:Two." not in events
    speaker.feed("Again.")
    drains(speaker)
    assert "say:Again." in events
    assert len(errors) == 1


def test_player_failure_is_reported_once_and_drain_returns():
    events, errors = [], []
    speaker = Speaker(FakeTTS(events), FakePlayer(events, write_error=RuntimeError("x")), on_error=errors.append)
    speaker.feed("One. Two. ")
    drains(speaker)
    assert len(errors) == 1 and "RuntimeError" in errors[0]
    assert "say:Two." not in events


def test_play_writes_raw_audio_in_order_with_sentences():
    speaker, player, events, _ = make_speaker()
    speaker.feed("One. ")
    speaker.play(b"\x10\x11")
    speaker.feed("Two. ")
    speaker.drain()
    assert player.written == [b"One.", b"\x10\x11", b"Two."]
    speaker.close()
    speaker.play(b"\x12\x13")  # ignored once closed
    drains(speaker)
    assert player.written == [b"One.", b"\x10\x11", b"Two."]


def test_reply_failed_is_reported_per_reply():
    speaker, _, _, _ = make_speaker(fail_on="Bad.", error=ApiError(status_code=500, body="x"))
    speaker.feed("Bad. ")
    drains(speaker)
    assert speaker.take_reply_failed()
    speaker.feed("Good. ")
    drains(speaker)
    assert not speaker.take_reply_failed()


def test_a_recording_plays_after_tts_failed_in_the_same_reply():
    speaker, player, _, _ = make_speaker(fail_on="Well dearie.", error=ApiError(status_code=500, body="x"))
    speaker.feed("Well dearie. ")  # the network went: TTS fails, then Claude
    speaker.play(b"\x10\x11")  # the foggy line, from the cache
    drains(speaker)
    assert player.written == [b"\x10\x11"]


def test_flush_starts_the_unfinished_sentence_without_waiting():
    speaker, _, events, _ = make_speaker(delay=0.5)
    speaker.feed("Heh heh, abracadabra, candy come down!")  # no space after: not a sentence yet
    start = time.monotonic()
    speaker.flush()  # Brain's before_tool: the candy spins while she says it
    assert time.monotonic() - start < 0.25
    speaker.feed("Reach in, dearie. ")
    drains(speaker)
    assert events == ["say:Heh heh, abracadabra, candy come down!", "say:Reach in, dearie.", "<heard>"]


def test_reply_failed_survives_a_drain_in_the_middle_of_a_reply():
    speaker, _, _, _ = make_speaker(fail_on="Bad.", error=ApiError(status_code=500, body="x"))
    speaker.feed("Bad. ")
    drains(speaker)
    speaker.feed("Here you go, dearie. ")
    drains(speaker)  # after the reply
    assert speaker.take_reply_failed()
    assert not speaker.take_reply_failed()


def test_play_finishes_the_unfinished_sentence_first():
    speaker, player, _, _ = make_speaker()
    speaker.feed("Well dearie, let m")  # the reply broke off here
    speaker.play(b"\x10\x11")
    speaker.drain()
    assert player.written == [b"Well dearie, let m", b"\x10\x11"]


def test_a_newline_keeps_a_live_fallback_line_apart_from_the_unfinished_sentence():
    speaker, _, events, _ = make_speaker()
    speaker.feed("Well dearie, let m")
    speaker.feed("\nHeh heh! ")  # what main()'s fallback feeds when the line isn't recorded
    speaker.drain()
    assert [e for e in events if e.startswith("say:")] == ["say:Well dearie, let m", "say:Heh heh!"]


def test_drain_twice_and_drain_with_nothing_fed_return():
    speaker, _, events, _ = make_speaker()
    drains(speaker)
    drains(speaker)
    assert events == ["<heard>", "<heard>"]


def test_stalled_tts_is_bounded_by_its_timeout():
    speaker, _, _, errors = make_speaker(delay=0.3, fail_on="Slow.", error=TimeoutError())
    speaker.feed("Slow. ")
    drains(speaker)
    assert len(errors) == 1


def test_odd_chunks_carry_a_byte_and_the_last_odd_byte_is_dropped():
    speaker, player, _, _ = make_speaker(chunks=[b"\x01\x02\x03", b"\x04\x05\x06"])
    speaker.feed("Boo. ")
    speaker.drain()
    assert player.written == [b"\x01\x02", b"\x03\x04\x05\x06"]
    assert all(len(w) % 2 == 0 for w in player.written)


def test_emoji_only_sentence_never_reaches_tts():
    speaker, _, events, _ = make_speaker()
    speaker.feed("🎃 ")
    speaker.drain()
    assert not [e for e in events if e.startswith("say:")]


def test_close_aborts_and_later_drain_returns_at_once():
    speaker, player, _, _ = make_speaker()
    speaker.close()
    assert player.aborted
    speaker.feed("Boo. ")
    drains(speaker)


def test_close_while_tts_stalls_lets_drain_return_at_once_and_says_nothing_more():
    speaker, _, events, _ = make_speaker(delay=1.0)
    speaker.feed("Slow. Next. ")
    time.sleep(0.05)
    speaker.close()
    start = time.monotonic()
    speaker.drain()
    assert time.monotonic() - start < 0.1
    speaker.feed("Later. ")
    time.sleep(1.2)
    assert [e for e in events if e.startswith("say:")] == ["say:Slow."]


class StuckPlayer(FakePlayer):
    """An audio device that hangs: write() only returns (raising) once the stream is aborted."""

    def write(self, data):
        while not self.aborted:
            time.sleep(0.01)
        raise RuntimeError("Stream is stopped")


class HungPlayer(FakePlayer):
    """An audio device that hangs for good: write() never returns, not even when aborted."""

    def __init__(self, events):
        super().__init__(events)
        self.release = threading.Event()

    def write(self, data):
        self.release.wait()


def test_hung_audio_device_is_reopened_then_goes_quiet(monkeypatch):
    monkeypatch.setattr(voice.speak, "DRAIN_LIMIT", 0.3)
    monkeypatch.setattr(voice.speak, "STALL_GRACE", 0.1)
    events, errors = [], []
    player = HungPlayer(events)
    speaker = Speaker(FakeTTS(events), player, on_error=errors.append)
    speaker.feed("Stuck. ")
    drains(speaker)
    assert player.aborted
    assert errors == ["(Hazel's voice stalled for 0 s: reopening the speaker)"]
    assert not speaker.closed  # one stall: reopened, not muted
    speaker.feed("Still stuck. ")
    drains(speaker)  # the worker is still in write(): mute for good
    assert speaker.closed
    assert len(errors) == 2 and "lost her voice" in errors[1]
    player.release.set()


def test_reset_output_frees_a_blocked_write(monkeypatch):
    monkeypatch.setattr(voice.speak, "DRAIN_LIMIT", 0.3)
    events, errors = [], []

    class ComesBack(StuckPlayer):  # hangs until aborted, like the real stream, then works
        def write(self, data):
            if self.events.count("reopen"):
                return FakePlayer.write(self, data)
            return super().write(data)

    player = ComesBack(events)
    speaker = Speaker(FakeTTS(events), player, on_error=errors.append)
    speaker.feed("Stuck. ")
    drains(speaker)  # stalls, reset_output() aborts: the worker's write raises
    assert errors == ["(Hazel's voice stalled for 0 s: reopening the speaker)"]  # not also the aborted write's error
    speaker.feed("Back. ")
    drains(speaker)  # the worker came free: a normal drain, reopening first
    assert not speaker.closed
    assert events[-3:] == ["reopen", "say:Back.", "<heard>"]


def test_device_that_hangs_again_after_each_reopen_goes_quiet(monkeypatch):
    """A real stream's abort frees the blocked write, so the worker is free at the next
    drain; a second stall in a row still mutes, and main() then exits for the supervisor."""
    monkeypatch.setattr(voice.speak, "DRAIN_LIMIT", 0.3)
    events, errors = [], []
    player = StuckPlayer(events)  # every write hangs until aborted; reopen() clears the abort
    speaker = Speaker(FakeTTS(events), player, on_error=errors.append)
    speaker.feed("Stuck. ")
    drains(speaker)
    speaker.feed("Again. ")
    drains(speaker)
    assert speaker.closed
    assert "reopen" in events
    assert errors[0].startswith("(Hazel's voice stalled") and "lost her voice" in errors[-1]
    assert len(errors) == 2


def test_a_drain_in_time_clears_the_stall(monkeypatch):
    monkeypatch.setattr(voice.speak, "DRAIN_LIMIT", 0.3)
    events, errors = [], []
    hangs = [True]

    class HangsOnce(StuckPlayer):
        def write(self, data):
            if hangs.pop() if hangs else False:
                return super().write(data)
            return FakePlayer.write(self, data)

    speaker = Speaker(FakeTTS(events), HangsOnce(events), on_error=errors.append)
    for text in ["Stuck. ", "Fine. ", "Fine again. "]:
        speaker.feed(text)
        drains(speaker)
    assert not speaker.closed
    assert len(errors) == 1


def test_reset_output_reopens_the_player_before_the_next_sentence():
    speaker, player, events, errors = make_speaker()
    speaker.reset_output()
    assert player.aborted
    speaker.feed("Boo. ")
    drains(speaker)
    assert events == ["reopen", "say:Boo.", "<heard>"]
    assert player.written == [b"Boo."]
    assert errors == []


def test_failed_reopen_is_retried_on_the_next_item():
    events, errors = [], []
    player = FakePlayer(events, reopen_errors=[RuntimeError("Device unavailable")])
    speaker = Speaker(FakeTTS(events), player, on_error=errors.append)
    speaker.reset_output()
    speaker.feed("One. Two. ")
    drains(speaker)
    assert len(errors) == 1 and "Device unavailable" in errors[0]
    assert player.written == []  # nothing said into a gone device
    speaker.feed("Three. ")
    drains(speaker)
    assert events[-3:] == ["reopen", "say:Three.", "<heard>"]
    assert player.written == [b"Three."]


def test_sound_player_opens_the_given_device_and_reopens_it(monkeypatch):
    streams = []

    class FakeOutputStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            streams.append(self)

        def start(self):
            self.calls.append("start")

        def abort(self):
            self.calls.append("abort")
            raise sounddevice.PortAudioError("Stream is stopped")  # ignored

        def close(self):
            self.calls.append("close")

    monkeypatch.setattr(sounddevice, "RawOutputStream", FakeOutputStream)
    player = SoundPlayer(device=27)
    player.reopen()
    assert [s.kwargs["device"] for s in streams] == [27, 27]
    assert streams[0].calls == ["start", "abort", "close"]
    assert streams[1].calls == ["start"]
    player.release()  # while PortAudio re-scans
    assert streams[1].calls == ["start", "abort", "close"]
    with pytest.raises(RuntimeError, match="looked for again"):
        player.reopen()  # never onto the stale index
    assert len(streams) == 2
    player.move_to(31)
    player.reopen()
    assert streams[-1].kwargs["device"] == 31


def test_close_never_raises_when_abort_fails():
    events = []
    speaker = Speaker(FakeTTS(events), FakePlayer(events, abort_error=RuntimeError("unplugged")), on_error=events.append)
    speaker.close()


def test_close_mid_sentence_reports_no_error():
    speaker, _, _, errors = make_speaker(delay=0.3)
    speaker.feed("Long one. ")
    time.sleep(0.05)
    speaker.close()
    time.sleep(0.5)  # the worker's write now raises on the aborted player
    assert errors == []


class FakeVoices:
    def __init__(self, error):
        self.error = error

    def get(self, voice_id):
        if self.error:
            raise self.error


class FakeElevenLabs:
    """ElevenLabs stand-in whose voices.get() raises error (or succeeds when None)."""

    def __init__(self, error=None):
        self.voices = FakeVoices(error)


@pytest.mark.parametrize(
    "error, message",
    [
        (ApiError(status_code=401, body={"detail": {"status": "invalid_api_key"}}), "rejected"),
        (ApiError(status_code=400, body={"detail": {"code": "voice_not_found"}}), "Add to my voices"),
        (ApiError(status_code=404, body={"detail": {"code": "voice_not_found"}}), "Add to my voices"),
        (ApiError(status_code=401, body={"detail": {"status": "missing_permissions", "message": "needs voices_read"}}), "voices_read"),
        (ApiError(status_code=500, body="oops"), "check failed"),
        (httpx.ConnectError("x"), "check failed"),
    ],
)
def test_check_voice_exits_with_a_hint(error, message):
    with pytest.raises(SystemExit, match=message) as exit:
        check_voice(FakeElevenLabs(error), "abc123")
    if message == "Add to my voices":
        assert "abc123" in str(exit.value.code)


def test_check_voice_passes_when_the_voice_exists():
    assert check_voice(FakeElevenLabs(), VOICE_ID) is None


def test_sdk_stream_is_lazy_and_raises_httpx_errors():
    """The oracle for the worker's error handling: nothing is sent until iterated, then httpx raises."""
    client = ElevenLabs(api_key="x", base_url="http://127.0.0.1:9", timeout=2)
    audio = elevenlabs_tts(client, VOICE_ID)("hi")  # no request yet
    with pytest.raises(httpx.TransportError):
        next(iter(audio))


def test_voice_and_format_constants():
    assert VOICE_ID == "KtpLOh8Pat0RmfxZcmDJ"  # The Ancient Crone
    stream = ElevenLabs(api_key="x").text_to_speech.stream
    annotation = inspect.signature(stream).parameters["output_format"].annotation
    assert OUTPUT_FORMAT in typing.get_args(typing.get_args(annotation)[0])


def test_candy_drops_after_the_spell_is_heard():
    events = []
    dispenser = StubDispenser()
    dispenser.calls = events
    speaker = Speaker(FakeTTS(events), FakePlayer(events))
    brain = Brain(FakeClient(TOOL_TURN, GRAB_TURN), CandyRules(dispenser), on_text=speaker.feed, before_tool=speaker.drain)
    brain.reply("trick or treat")
    speaker.drain()
    assert events == ["say:Bubble!", "<heard>", "<candy>", "say:Grab it!", "<heard>"]
