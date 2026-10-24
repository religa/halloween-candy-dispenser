"""Hazel's ears, offline: a fake Scribe client records each request, fake mics and a fake VAD drive the
Listener, real TEN VAD runs on the fixtures; live fixture tests need ELEVENLABS_API_KEY."""

import http.server
import inspect
import math
import os
import re
import subprocess
import sys
import threading
import time
import typing
import wave
from pathlib import Path

import httpx
import numpy as np
import pytest
import sounddevice
import voice.hear
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from elevenlabs.speech_to_text.types import SpeechToTextConvertRequestFileFormat
from elevenlabs.types import SpeechToTextChunkResponseModel
from test_rules import FakeClock
from voice.devices import AUDIO_RETRY, DeviceError
from voice.hear import (
    ECHO_TAIL,
    HOP_SECONDS,
    PRE_ROLL,
    STT_SAMPLE_RATE,
    STT_TIMEOUT,
    VAD_HOP,
    VAD_WARMUP,
    Listener,
    MicError,
    Microphone,
    SilentMic,
    Transcriber,
    Turn,
    keep_drop,
    main,
    open_ears,
    read_wav,
    reopen_mic,
    save_turn,
    ten_vad,
    transcribe_turn,
)

PCM = b"\x01\x00\x02\x00" * 800
NOT_FOUND = ApiError(status_code=404, body={"detail": {"code": "transcript_not_found"}})
REQUEST = {  # the oracle for what Scribe is asked, written out, not imported
    "model_id": "scribe_v2",
    "file": PCM,
    "file_format": "pcm_s16le_16",
    "language_code": "en",
    "tag_audio_events": False,
    "keyterms": ["trick or treat"],
    "request_options": {"max_retries": 0},  # one upload per turn
}


class FakeScribeTranscripts:
    """transcripts stand-in: each delete sleeps, then raises the next of errors, or records the ID."""

    def __init__(self, errors=(), delete_delay=0):
        self.errors = list(errors)
        self.delete_delay = delete_delay
        self.deleted = []

    def delete(self, transcription_id):
        time.sleep(self.delete_delay)
        if self.errors:
            raise self.errors.pop(0)
        self.deleted.append(transcription_id)


class FakeScribe:
    """client.speech_to_text stand-in: records each convert's kwargs, answers with a real SDK response."""

    def __init__(self, text="Trick or treat", transcription_id="tr_1", error=None, **transcripts):
        self.text = text
        self.transcription_id = transcription_id
        self.error = error
        self.requests = []
        self.transcripts = FakeScribeTranscripts(**transcripts)

    def convert(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return SpeechToTextChunkResponseModel(language_code="en", language_probability=1.0, text=self.text, words=[], transcription_id=self.transcription_id)


class FakeScribeClient:
    def __init__(self, **scribe):
        self.speech_to_text = FakeScribe(**scribe)


def make_ears(**scribe):
    client, errors = FakeScribeClient(**scribe), []
    return Transcriber(client, on_error=errors.append), client.speech_to_text, errors


def write_wav(path, rate=16000, channels=1, width=2, frames=b"\0\0" * 1600):
    with wave.open(str(path), "wb") as w:
        w.setframerate(rate)
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.writeframes(frames)
    return path


def test_transcribe_sends_pcm_with_tags_off():
    ears, scribe, _ = make_ears()
    ears.transcribe(PCM)
    ears.close()
    assert scribe.requests == [REQUEST]
    assert "enable_logging" not in scribe.requests[0]  # zero retention is refused on Starter


def test_transcribe_strips_text():
    ears, _, _ = make_ears(text="  Trick or treat! \n")
    assert ears.transcribe(PCM) == "Trick or treat!"
    ears.close()


def test_whitespace_reply_is_empty():
    ears, _, _ = make_ears(text=" ")
    assert ears.transcribe(PCM) == ""
    ears.close()


def test_empty_pcm_sends_nothing():
    ears, scribe, _ = make_ears()
    assert ears.transcribe(b"") == ""
    ears.close()
    assert scribe.requests == []
    assert scribe.transcripts.deleted == []


def test_transcript_is_deleted_after_use():
    ears, scribe, errors = make_ears()
    ears.transcribe(PCM)
    ears.close()
    assert scribe.transcripts.deleted == ["tr_1"]
    assert errors == []


def test_no_id_means_no_delete():
    ears, scribe, errors = make_ears(transcription_id=None)
    assert ears.transcribe(PCM) == "Trick or treat"
    ears.close()
    assert scribe.transcripts.deleted == []
    assert errors == []


def test_delete_retries_until_the_transcript_exists(monkeypatch):
    monkeypatch.setattr(voice.hear, "DELETE_RETRY", 0.01)
    ears, scribe, errors = make_ears(errors=[NOT_FOUND, NOT_FOUND])
    ears.transcribe(PCM)
    ears.close()
    assert scribe.transcripts.deleted == ["tr_1"]
    assert errors == []


def test_delete_gives_up_after_the_window(monkeypatch):
    monkeypatch.setattr(voice.hear, "DELETE_RETRY", 0.01)
    monkeypatch.setattr(voice.hear, "DELETE_WINDOW", 0.1)
    ears, scribe, errors = make_ears(errors=[NOT_FOUND] * 1000)
    ears.transcribe(PCM)
    start = time.monotonic()
    ears.close()
    assert time.monotonic() - start < 1
    assert scribe.transcripts.deleted == []
    assert len(errors) == 1 and "tr_1" in errors[0]


@pytest.mark.parametrize("error", [ApiError(status_code=500, body="oops"), httpx.ConnectError("x")])
def test_failed_delete_is_reported_not_raised(error):
    ears, scribe, errors = make_ears(text="Trick or treat", errors=[error])
    assert ears.transcribe(PCM) == "Trick or treat"
    ears.close()
    assert len(scribe.transcripts.errors) == 0 and scribe.transcripts.deleted == []  # tried once, no retry
    assert len(errors) == 1
    assert "tr_1" in errors[0]
    assert "Trick or treat" not in errors[0]  # never the child's words in a log line


def test_on_error_raising_is_contained():
    def broken_pipe(line):
        raise RuntimeError("stdout gone")

    client = FakeScribeClient(errors=[ApiError(status_code=500, body="oops")])
    ears = Transcriber(client, on_error=broken_pipe)
    assert ears.transcribe(PCM) == "Trick or treat"
    ears.close()
    assert client.speech_to_text.transcripts.errors == []  # the delete was tried, and its report raised


def test_on_error_raising_keeps_deleting_later_transcripts():
    """The delete worker is one daemon thread: a raising report must not end it."""

    def broken_pipe(line):
        raise RuntimeError("stdout gone")

    client = FakeScribeClient(errors=[ApiError(status_code=500, body="oops")])
    ears = Transcriber(client, on_error=broken_pipe)
    ears.transcribe(PCM)
    ears.transcribe(PCM)
    start = time.monotonic()
    ears.close()
    assert time.monotonic() - start < 1
    assert client.speech_to_text.transcripts.deleted == ["tr_1"]  # the second one


def test_transcribe_after_close_raises_without_sending():
    ears, scribe, _ = make_ears()
    ears.close()
    with pytest.raises(RuntimeError, match="closed"):
        ears.transcribe(PCM)
    assert scribe.requests == []  # no upload, so no transcript left behind that can't be deleted


def test_close_during_an_upload_still_deletes_its_transcript():
    """The mic thread may be mid-upload when the program closes the transcriber."""
    ears, scribe, errors = make_ears()
    convert = scribe.convert

    def convert_while_closing(**kwargs):
        ears.close()  # another thread closes while Scribe is answering
        return convert(**kwargs)

    scribe.convert = convert_while_closing
    assert ears.transcribe(PCM) == "Trick or treat"
    assert scribe.transcripts.deleted == ["tr_1"]
    assert errors == []


def test_text_returns_before_delete_finishes():
    ears, scribe, _ = make_ears(delete_delay=1.0)
    start = time.monotonic()
    ears.transcribe(PCM)
    assert time.monotonic() - start < 0.5
    start = time.monotonic()
    ears.close()
    assert time.monotonic() - start >= 0.5
    assert scribe.transcripts.deleted == ["tr_1"]


@pytest.mark.parametrize("error", [ApiError(status_code=401, body={"detail": {"status": "invalid_api_key"}}), httpx.ConnectError("x")])
def test_convert_errors_propagate(error):
    ears, scribe, _ = make_ears(error=error)
    with pytest.raises(type(error)):
        ears.transcribe(PCM)
    ears.close()
    assert scribe.transcripts.deleted == []


def test_read_wav_accepts_16k_mono_int16(tmp_path):
    frames = bytes(range(256)) * 10
    assert read_wav(write_wav(tmp_path / "ok.wav", frames=frames)) == frames


@pytest.mark.parametrize("rate, channels, width", [(44100, 1, 2), (16000, 2, 2), (16000, 1, 1)])
def test_read_wav_rejects_other_formats(tmp_path, rate, channels, width):
    path = write_wav(tmp_path / "odd.wav", rate, channels, width, frames=b"\0" * 400)
    with pytest.raises(ValueError, match="ffmpeg") as error:
        read_wav(path)
    assert "odd.wav" in str(error.value)


def test_sdk_accepts_our_request():
    """The SDK is the oracle: every kwarg we send exists, and so does the raw-PCM format name."""
    parameters = inspect.signature(ElevenLabs(api_key="x").speech_to_text.convert).parameters
    assert set(REQUEST) <= set(parameters)
    assert "pcm_s16le_16" in typing.get_args(typing.get_args(SpeechToTextConvertRequestFileFormat)[0])


def test_convert_uploads_once_on_a_server_error():
    """The S3 probe as a test: the server's own POST count is the oracle (the SDK default is 3)."""
    posts = []

    class AlwaysFails(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            posts.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = b'{"detail": "oops"}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AlwaysFails)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        ears = Transcriber(ElevenLabs(api_key="x", base_url=base_url, timeout=5))
        start = time.monotonic()
        with pytest.raises(ApiError) as error:
            ears.transcribe(PCM)
        assert time.monotonic() - start < 1
        assert error.value.status_code == 500
        assert len(posts) == 1
        ears.close()
    finally:
        server.shutdown()
        server.server_close()


def test_close_gives_up_after_the_limit(monkeypatch):
    monkeypatch.setattr(voice.hear, "CLOSE_LIMIT", 0.2)
    ears, _, errors = make_ears(delete_delay=5)
    ears.transcribe(PCM)
    start = time.monotonic()
    ears.close()
    assert time.monotonic() - start < 1
    assert len(errors) == 1
    assert "tr_1" in errors[0]
    assert "Trick or treat" not in errors[0]  # the ID only, never the child's words


def test_pending_delete_does_not_hold_exit():
    """S4's oracle is wall time: a ThreadPoolExecutor held exit until every delete ended."""
    code = """
import time, voice.hear
from elevenlabs.types import SpeechToTextChunkResponseModel

class Transcripts:
    def delete(self, transcription_id):
        time.sleep(30)

class Scribe:
    transcripts = Transcripts()

    def convert(self, **kwargs):
        return SpeechToTextChunkResponseModel(
            language_code="en", language_probability=1.0, text="hi", words=[], transcription_id="tr_1"
        )

class Client:
    speech_to_text = Scribe()

voice.hear.CLOSE_LIMIT = 0.2
ears = voice.hear.Transcriber(Client(), on_error=lambda line: None)
ears.transcribe(bytes(2))
ears.close()
"""
    start = time.monotonic()
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10, cwd=Path(__file__).parent.parent)
    assert time.monotonic() - start < 5


def test_ctrl_c_during_close_still_reports_pending_ids():
    """An impatient second Ctrl-C at exit must not lose the IDs of transcripts left on the account."""
    ears, _, errors = make_ears(delete_delay=5)
    ears.transcribe(PCM)

    class Interrupted(type(ears._changed)):
        def wait_for(self, predicate, timeout=None):
            raise KeyboardInterrupt

    ears._changed = Interrupted()
    with pytest.raises(KeyboardInterrupt):
        ears.close()
    assert len(errors) == 1 and "tr_1" in errors[0]


def test_close_twice_is_harmless(monkeypatch):
    monkeypatch.setattr(voice.hear, "CLOSE_LIMIT", 0.2)
    ears, _, errors = make_ears(delete_delay=5)
    ears.transcribe(PCM)
    ears.close()
    start = time.monotonic()
    ears.close()
    assert time.monotonic() - start < 0.1  # no second wait
    assert len(errors) == 1  # and no second report


def test_sdk_convert_raises_httpx_errors():
    """The oracle for 'convert errors propagate': an unroutable host raises httpx, not something else."""
    ears = Transcriber(ElevenLabs(api_key="x", base_url="http://127.0.0.1:9", timeout=2))
    with pytest.raises(httpx.TransportError):
        ears.transcribe(b"\0\0")
    ears.close()


@pytest.fixture
def cli_client(monkeypatch):
    client = FakeScribeClient()
    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    monkeypatch.setattr(voice.hear, "ElevenLabs", lambda **kwargs: client)
    return client


def test_cli_prints_text_and_delay(tmp_path, cli_client, capsys):
    main([str(write_wav(tmp_path / "name.wav"))])
    out = capsys.readouterr().out
    assert "name.wav: " in out and " s " in out
    assert "'Trick or treat'" in out
    assert cli_client.speech_to_text.transcripts.deleted == ["tr_1"]


@pytest.mark.parametrize("bad, error", [("stereo", "ValueError"), ("junk", "Error")])
def test_cli_reports_a_bad_file_and_continues(tmp_path, cli_client, capsys, bad, error):
    if bad == "stereo":
        path = write_wav(tmp_path / "stereo.wav", channels=2)
    else:
        path = tmp_path / "junk.wav"
        path.write_bytes(b"not a wav file")
    main([str(path), str(write_wav(tmp_path / "good.wav"))])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(f"{path.name}: {error}")
    assert lines[1].startswith("good.wav: ") and "'Trick or treat'" in lines[1]


def test_cli_without_key_exits(monkeypatch, tmp_path):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ELEVENLABS_API_KEY"):
        main([str(write_wav(tmp_path / "name.wav"))])


FIXTURES = Path(__file__).parent / "fixtures" / "voice"
HEARD = {  # key words that must all be heard; the test's own oracle, not the generator's text
    "trick_or_treat-adult": "trick or treat",
    "trick_or_treat-kid": "trick or treat",
    "trick_or_treat-kid_noisy": "trick or treat",
    "trick_or_treat-kid2_noisy": "trick or treat",  # heard only with the keyterm
    "rhyme-kid": "trick or treat smell feet",
    "vampire-adult": "vampire",
    "vampire-kid_noisy": "vampire",
    "costume-adult": "princess dinosaur",
}
QUIET = {"silence-room", "noise-pink", "noise-wind", "noise-hum", "noise-clicks"}


def words(text):
    return re.findall(r"[a-z']+", text.lower().replace("’", "'"))


@pytest.fixture
def live():
    if not os.environ.get("ELEVENLABS_API_KEY"):
        pytest.skip("needs ELEVENLABS_API_KEY (uv run --env-file .env pytest tests/test_hear.py)")
    # the key is passed explicitly: the SDK reads its default from the environment at import time
    ears = Transcriber(ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=STT_TIMEOUT))
    yield ears
    ears.close()


def test_fixtures_are_registered():
    assert {p.stem for p in FIXTURES.glob("*.wav")} == HEARD.keys() | QUIET
    assert not HEARD.keys() & QUIET


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.wav")), ids=lambda p: p.stem)
def test_fixtures_are_16k_mono_int16(path):
    with wave.open(str(path), "rb") as w:  # wave directly: independent of read_wav
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        assert 1 <= w.getnframes() / 16000 <= 6


def test_quiet_fixtures_have_no_speech_level_audio():
    with wave.open(str(FIXTURES / "silence-room.wav"), "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
    assert 20 * np.log10(np.sqrt(np.mean(samples**2))) < -45  # dBFS; the noise files are loud by design


@pytest.mark.parametrize("name", HEARD)
def test_speech_fixtures_are_heard(live, name):
    heard = words(live.transcribe(read_wav(FIXTURES / f"{name}.wav")))
    assert set(words(HEARD[name])) <= set(heard), heard


@pytest.mark.parametrize("name", sorted(QUIET))
def test_quiet_fixtures_give_empty_text(live, name):
    assert live.transcribe(read_wav(FIXTURES / f"{name}.wav")) == ""


# --- Listener, mic and VAD ---


class FakeVad:
    """Speech if a block's peak is above 1000: deterministic, unlike TEN."""

    def __call__(self, frame):
        return 1.0 if np.abs(np.frombuffer(frame, np.int16).astype(np.int32)).max() > 1000 else 0.0


def block(value):
    return np.full(VAD_HOP, value, np.int16).tobytes()


def seconds(n, value):
    """n seconds of blocks of value, by Listener's own rounding rule."""
    return [block(value)] * math.ceil(n / HOP_SECONDS)


WARM = seconds(VAD_WARMUP, 1)  # not all zero (the silent-mic check passes), below FakeVad's threshold


class FakeMic:
    """queued: captured before listen() (flush() drops it); future: arrives while listening; then end."""

    def __init__(self, queued=(), future=(), end=EOFError):
        self.queued = list(queued)
        self.future = list(future)
        self.end = end
        self.closed = False

    def read(self):
        if self.queued:
            return self.queued.pop(0)
        if self.future:
            return self.future.pop(0)
        raise self.end("the end")

    def flush(self):
        self.queued.clear()

    def capture(self, blocks):
        """Audio recorded while the program was busy replying: all of it is queued at the next listen()."""
        self.queued += self.future + list(blocks)
        self.future = []

    def close(self):
        self.closed = True


FILE_TAIL = 1.5  # s of floor noise after a clip, so its last turn can end


class FileMic:
    """A WAV as a mic, as the VAD was tuned on it: VAD_WARMUP + PRE_ROLL of noise at the clip's floor
    before it (warm-up, then a full ring), FILE_TAIL after, all in VAD_HOP blocks."""

    def __init__(self, pcm):
        samples = np.frombuffer(pcm, np.int16)
        whole = samples[: len(samples) // VAD_HOP * VAD_HOP].reshape(-1, VAD_HOP) / 32768
        floor = max(np.percentile(np.sqrt(np.mean(whole**2, axis=1)), 10), 1e-4)
        rng = np.random.default_rng(0)

        def noise(secs):
            return np.clip(rng.normal(0, floor * 32768, round(secs * STT_SAMPLE_RATE)), -32768, 32767).astype(np.int16)

        self.lead = VAD_WARMUP + PRE_ROLL
        audio = np.concatenate([noise(self.lead), samples, noise(FILE_TAIL)])
        audio = audio[: len(audio) // VAD_HOP * VAD_HOP]
        self.blocks = [b.tobytes() for b in audio.reshape(-1, VAD_HOP)]

    def read(self):
        if not self.blocks:
            raise EOFError
        return self.blocks.pop(0)

    def flush(self):
        pass


def listener(mic, **kwargs):
    drops = []
    return Listener(mic, FakeVad(), on_drop=lambda turn, why: drops.append(why), **kwargs), drops


def values(turn):
    """The block values of a turn made of constant blocks."""
    samples = np.frombuffer(turn.pcm, np.int16).reshape(-1, VAD_HOP)
    return [int(b[0]) for b in samples]


def test_audio_from_before_listen_is_dropped():
    mic = FakeMic(
        queued=seconds(3, 3000),  # Hazel, captured before the first listen()
        future=WARM + seconds(1, 0) + seconds(1, 5000) + seconds(1, 0),
    )
    ears, _ = listener(mic)
    first = values(ears.listen())
    assert 5000 in first and 3000 not in first
    ears.resume()  # Hazel spoke
    mic.capture(seconds(3, 3000))  # Hazel's reply, captured while she talked
    mic.future = seconds(ECHO_TAIL, 3000) + seconds(1, 6000) + seconds(1, 0)  # her echo, the kid right after it
    second = values(ears.listen())
    assert 6000 in second and 3000 not in second  # the echo tail never enters the pre-roll
    assert 5000 not in second  # nor does audio from before she spoke


@pytest.mark.parametrize("resume", [False, True])
def test_without_resume_audio_during_an_upload_is_kept(resume):
    mic = FakeMic(future=WARM + seconds(1, 0) + seconds(1, 5000) + seconds(1, 0))
    ears, _ = listener(mic)
    assert 5000 in values(ears.listen())
    if resume:  # the control: after Hazel speaks, the same capture is dropped
        ears.resume()
    mic.capture(seconds(1, 6000) + seconds(1, 0))  # a kid talking while the last turn was uploading
    if resume:
        with pytest.raises(EOFError):
            ears.listen()
    else:
        assert 6000 in values(ears.listen())


def test_timeout_returns_none_when_nobody_speaks():
    ears, _ = listener(FakeMic(future=WARM + seconds(2, 1)))  # 63 + 125 = 188 frames, 32 per call
    assert [ears.listen(timeout=0.5) for _ in range(5)] == [None] * 5
    with pytest.raises(EOFError):
        ears.listen(timeout=0.5)


def test_timeout_never_cuts_an_open_turn():
    ears, _ = listener(FakeMic(future=WARM + seconds(1.0, 5000) + seconds(1, 0)))
    results = []
    while not results or results[-1] is None:
        results.append(ears.listen(timeout=0.1))
    assert results[:-1] == [None] * (len(results) - 1) and len(results) > 1
    assert values(results[-1]).count(5000) == len(seconds(1.0, 5000))


def test_pre_roll_survives_short_listens():
    ears, _ = listener(FakeMic(future=WARM + seconds(PRE_ROLL, 200) + seconds(1, 5000) + seconds(1, 0)))
    turn = None
    while turn is None:
        turn = ears.listen(timeout=0.1)  # the speech starts several calls after the lead-in did
    lead = math.ceil(PRE_ROLL / HOP_SECONDS)
    assert values(turn)[:lead] == [200] * lead


def test_resume_during_the_warm_up_keeps_the_rest_of_it():
    mic = FakeMic(future=seconds(0.1, 1) + seconds(0.7, 5000) + seconds(1, 1))  # a fresh VAD's false trigger
    ears, drops = listener(mic)
    assert ears.listen(timeout=0.1) is None
    ears.resume()  # Hazel greeted an arrival during the first second
    with pytest.raises(EOFError):
        ears.listen()
    assert drops == []  # the trigger fell inside the warm-up, not after a shorter echo tail


def test_silent_mic_check_spans_short_listens():
    ears, _ = listener(FakeMic(future=seconds(VAD_WARMUP, 0) + seconds(1, 0)))
    nones = 0
    with pytest.raises(MicError):
        while True:
            assert ears.listen(timeout=0.1) is None
            nones += 1
    assert nones == (len(WARM) - 1) // math.ceil(0.1 / HOP_SECONDS)  # MicError in the call that reads the warm-up's last frame


def test_pre_roll_keeps_exactly_pre_roll_before_the_trigger():
    ears, _ = listener(FakeMic(future=WARM + seconds(1.5, 200) + seconds(1, 5000) + seconds(1, 0)))
    turn = values(ears.listen())
    lead = math.ceil(PRE_ROLL / HOP_SECONDS)
    assert turn[:lead] == [200] * lead
    assert turn[lead] == 5000


def test_short_blip_is_dropped_and_keeps_the_lead_in():
    ears, drops = listener(FakeMic(future=WARM + seconds(0.1, 5000) + seconds(0.75, 0) + seconds(1, 7000) + seconds(1, 0)))
    turn = values(ears.listen())
    with pytest.raises(EOFError):
        ears.listen()
    assert drops == ["too short"]
    assert turn.index(7000) >= math.ceil(PRE_ROLL / HOP_SECONDS) - 2  # a cleared ring would leave ~3


def test_quiet_turn_is_dropped():
    quiet = np.zeros(VAD_HOP, np.int16)
    quiet[0] = 2000  # peak above FakeVad's threshold, RMS about -48 dBFS
    ears, drops = listener(FakeMic(future=WARM + [quiet.tobytes()] * math.ceil(1 / HOP_SECONDS) + seconds(1, 0)))
    with pytest.raises(EOFError):
        ears.listen()
    assert drops == ["too quiet"]


def at_level(rest):
    """1 s of blocks with a 2000 peak (speech to FakeVad) over rest: -40 dBFS for rest=300, -36 for 500."""
    frame = np.full(VAD_HOP, rest, np.int16)
    frame[0] = 2000
    return [frame.tobytes()] * math.ceil(1 / HOP_SECONDS)


@pytest.mark.parametrize(
    "rest, alone, dropped",
    [
        (300, True, ["too quiet with nobody there"]),  # -40 dB: a grown-up's aside, with nobody in front
        (300, False, []),  # the same, with a visitor there
        (500, True, []),  # -36 dB: loud enough to be talking to Hazel
    ],
)
def test_nobody_there_needs_a_louder_turn(rest, alone, dropped):
    ears, drops = listener(FakeMic(future=WARM + at_level(rest) + seconds(1, 0)), alone=lambda: alone)
    turns = []
    with pytest.raises(EOFError):
        while True:
            turns.append(ears.listen())
    assert drops == dropped
    assert len(turns) == (0 if dropped else 1)


def quiet_at(peak, secs):
    """secs of blocks with one sample at peak (speech to FakeVad when > 1000), the rest silent."""
    frame = np.zeros(VAD_HOP, np.int16)
    frame[0] = peak
    return [frame.tobytes()] * math.ceil(secs / HOP_SECONDS)


@pytest.mark.parametrize(
    "future, in_visit, dropped",
    [
        (seconds(0.35, 5000), False, ["too short"]),  # 0.35 s: a short "yes"
        (seconds(0.35, 5000), True, []),
        (quiet_at(2000, 1), False, ["too quiet"]),  # about -48 dBFS: a shy kid
        (quiet_at(2000, 1), True, []),
        (seconds(0.2, 5000), True, ["too short"]),  # a blip is still a blip
        (quiet_at(1100, 1), True, ["too quiet"]),  # about -53 dBFS
    ],
)
def test_a_visit_lets_shorter_and_quieter_turns_through(future, in_visit, dropped):
    asked = []
    ears, drops = listener(FakeMic(future=WARM + future + seconds(1, 0)), in_visit=lambda: in_visit, alone=lambda: asked.append(1) or True)
    turns = []
    with pytest.raises(EOFError):
        while True:
            turns.append(ears.listen())
    assert drops == dropped
    assert len(turns) == (0 if dropped else 1)
    if in_visit:
        assert asked == []  # in a visit the sensor isn't asked


@pytest.mark.parametrize("future", [seconds(1, 5000), seconds(1, 0)])
def test_alone_is_asked_only_between_the_two_levels(future):
    asked = []
    ears, _ = listener(FakeMic(future=WARM + future + seconds(1, 0)), alone=lambda: asked.append(1) or True)
    with pytest.raises(EOFError):
        while True:
            ears.listen()
    assert asked == []  # a loud turn, and no turn: the sensor isn't asked


@pytest.mark.parametrize("end_silence", [0.4, 1.0])
def test_end_silence_ends_the_turn(end_silence):
    speech = seconds(0.5, 5000)
    future = WARM + speech + seconds(end_silence - 0.1, 0) + speech + seconds(2, 0)
    ears, _ = listener(FakeMic(future=future), end_silence=end_silence)
    turn = ears.listen()
    assert values(turn).count(5000) == 2 * len(speech)
    last_speech_end = (len(future) - len(seconds(2, 0))) * HOP_SECONDS
    assert turn.end == pytest.approx(last_speech_end + math.ceil(end_silence / HOP_SECONDS) * HOP_SECONDS)


def test_long_turn_is_cut_at_max_turn(monkeypatch):
    monkeypatch.setattr(voice.hear, "MAX_TURN", 1.0)
    ears, _ = listener(FakeMic(future=WARM + seconds(3, 5000)))
    assert len(ears.listen().pcm) == math.ceil(1.0 / HOP_SECONDS) * VAD_HOP * 2


def test_open_turn_at_eof_is_returned_then_eof():
    ears, _ = listener(FakeMic(future=WARM + seconds(1, 5000)))
    assert 5000 in values(ears.listen())
    with pytest.raises(EOFError):
        ears.listen()


def test_warm_up_ignores_the_first_second():
    ears, drops = listener(FakeMic(future=seconds(VAD_WARMUP, 5000) + seconds(2, 1)))
    with pytest.raises(EOFError):
        ears.listen()
    assert drops == []


def test_digital_silence_raises_silent_mic_naming_linux_tools():
    ears, _ = listener(FakeMic(future=seconds(VAD_WARMUP, 0) + seconds(1, 0)))
    with pytest.raises(SilentMic) as error:
        ears.listen()
    assert "wpctl" in str(error.value) and "System Settings" in str(error.value)


class ReopeningMic:
    """A mic coming back after a replug: reopen() raises each of `failures` in turn, then works;
    read() then raises each of `silent` (MicError) before giving a block."""

    def __init__(self, failures=(), silent=()):
        self.failures = list(failures)
        self.silent = list(silent)
        self.reopens = 0

    def reopen(self):
        self.reopens += 1
        if self.failures:
            raise self.failures.pop(0)

    def read(self):
        if self.silent:
            raise self.silent.pop(0)
        return block(1)


def test_reopen_mic_retries_until_audio_flows():
    clock = FakeClock()
    gone = sounddevice.PortAudioError("Error opening RawInputStream: Device unavailable")
    mic = ReopeningMic(failures=[gone, gone], silent=[MicError("no audio")])
    reopen_mic(mic, sleep=clock.sleep, clock=clock)
    assert mic.reopens == 4
    assert clock.slept == [AUDIO_RETRY] * 3


def test_reopen_mic_gives_up_after_the_wait():
    clock = FakeClock()
    mic = ReopeningMic(failures=[sounddevice.PortAudioError("Device unavailable")] * 100)
    with pytest.raises(MicError, match="didn't come back in 60 s: Device unavailable"):
        reopen_mic(mic, wait=60, sleep=clock.sleep, clock=clock)
    assert clock.now >= 60


@pytest.fixture
def fake_devices(monkeypatch):
    """open_ears offline: a fake Scribe client, a FakeMic for the microphone, FakeVad for TEN."""
    client = FakeScribeClient()
    mics = []

    def fake_microphone(device=None):
        mics.append(FakeMic(future=WARM + seconds(1, 5000) + seconds(1, 0), end=MicError))
        return mics[-1]

    monkeypatch.setenv("ELEVENLABS_API_KEY", "x")
    monkeypatch.setattr(voice.hear, "ElevenLabs", lambda **kwargs: client)
    monkeypatch.setattr(voice.hear, "Microphone", fake_microphone)
    monkeypatch.setattr(voice.hear, "ten_vad", lambda: FakeVad())
    monkeypatch.setattr(voice.hear, "wait_for_devices", lambda name, **k: (1, 2))  # no real audio devices
    return client, mics


def test_open_ears_without_key_exits_with_the_hint(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exit:
        open_ears(hint=" (or use --text)")
    assert str(exit.value.code).endswith(" (or use --text)")


def test_open_ears_without_a_microphone_exits_and_closes_ears(monkeypatch, fake_devices):
    def no_device():
        raise sounddevice.PortAudioError("Error querying device -1")

    closed = []
    monkeypatch.setattr(voice.hear, "Microphone", lambda device=None: no_device())
    monkeypatch.setattr(voice.hear.Transcriber, "close", lambda self: closed.append(self))
    with pytest.raises(SystemExit) as exit:
        open_ears(hint=" (or use --text)")
    assert "no microphone" in str(exit.value.code) and str(exit.value.code).endswith(" (or use --text)")
    assert len(closed) == 1


def test_open_ears_passes_end_silence(fake_devices):
    listener, ears = open_ears(1.2)
    ears.close()
    assert listener.end_silence == 1.2


def read_turns(mic, vad=None):
    """Every turn a real-VAD Listener finds in mic, and the drops."""
    drops, turns = [], []
    ears = Listener(mic, vad or ten_vad(), on_drop=lambda turn, why: drops.append((why, turn)))
    while True:
        try:
            turns.append(ears.listen())
        except EOFError:
            return turns, drops


@pytest.mark.parametrize("name", HEARD)
def test_speech_fixtures_give_one_turn_around_the_speech(name):
    pcm = read_wav(FIXTURES / f"{name}.wav")
    mic = FileMic(pcm)
    turns, _ = read_turns(mic)
    assert len(turns) == 1
    duration = len(pcm) / 2 / STT_SAMPLE_RATE
    pad = 0.5  # s of quiet around the speech: PAD in tools/make_voice_fixtures.py
    assert turns[0].start - mic.lead <= pad
    assert turns[0].end - mic.lead >= duration - pad


@pytest.mark.parametrize("name", sorted(QUIET))
def test_quiet_fixtures_give_no_turn(name):
    turns, _ = read_turns(FileMic(read_wav(FIXTURES / f"{name}.wav")))
    assert turns == []


def instrumental_music(dbfs_level, secs=6.0):
    """Spike S5's "chords+beat": three-note chords that change every 0.5 s, and a noise-burst kick."""
    rng = np.random.default_rng(0)
    t = np.arange(round(secs * STT_SAMPLE_RATE)) / STT_SAMPLE_RATE
    roots = [220.0, 174.6, 196.0, 261.6]
    signal = np.zeros_like(t)
    for i, root in enumerate(roots * math.ceil(secs / 0.5 / len(roots))):
        part = (t >= i * 0.5) & (t < (i + 1) * 0.5)
        for ratio in (1, 1.26, 1.5):
            signal[part] += np.sin(2 * np.pi * root * ratio * t[part])
    beat = np.zeros_like(t)
    for start in np.arange(0, secs, 0.5):
        n = round(start * STT_SAMPLE_RATE)
        burst = rng.normal(0, 1, 800) * np.exp(-np.arange(800) / 150)
        beat[n : n + 800] += burst[: len(beat) - n]
    signal += 2 * beat
    signal *= 10 ** (dbfs_level / 20) / np.sqrt(np.mean(signal**2))
    return (signal * 32768).astype(np.int16).tobytes()


@pytest.mark.parametrize("level", [-47, -30])
def test_instrumental_music_gives_no_turn(level):
    turns, _ = read_turns(FileMic(instrumental_music(level)))
    assert turns == []


def test_level_gate_drops_quiet_real_speech():
    """Spike S8: TEN still hears speech scaled to -50 dBFS, so only the level gate can drop it."""
    pcm = read_wav(FIXTURES / "trick_or_treat-adult.wav")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(voice.hear, "MIN_TURN_DBFS", -200.0)  # measure the voiced level at unity gain
        (turn,), _ = read_turns(FileMic(pcm))
    samples = np.frombuffer(pcm, np.int16).astype(np.float64)
    for target, kept in [(-50, False), (-40, True)]:
        scaled = np.clip(samples * 10 ** ((target - turn.level) / 20), -32768, 32767).astype(np.int16).tobytes()
        turns, drops = read_turns(FileMic(scaled))
        assert len(turns) == kept, target
        assert [why for why, _ in drops if why == "too quiet"] == ([] if kept else ["too quiet"]), target


TAKES = Path(__file__).parent.parent / "tmp/candy-recordings/16k"
NOISE_TAKES = {"20261010_155249", "20261010_155256", "20261010_155306"}  # labels: noise, noise, music/TV


@pytest.fixture
def takes():
    if not TAKES.is_dir():
        pytest.skip("needs the recorded takes in tmp/candy-recordings/16k (git-ignored)")
    return {p.stem: p for p in sorted(TAKES.glob("*.wav"))}


def test_real_speech_takes_give_one_turn(takes):
    speech = {name: path for name, path in takes.items() if name not in NOISE_TAKES}
    assert len(speech) == 18
    counts = {name: len(read_turns(FileMic(read_wav(path)))[0]) for name, path in speech.items()}
    assert counts == dict.fromkeys(speech, 1)


def test_music_take_never_reaches_scribe(takes):
    turns, _ = read_turns(FileMic(read_wav(takes["20261010_155306"])))
    assert turns == []


def test_noise_takes_give_no_turn(takes):
    for name in ["20261010_155249", "20261010_155256"]:
        turns, _ = read_turns(FileMic(read_wav(takes[name])))
        assert turns == [], name


class FakeInputStream:
    """sounddevice.RawInputStream stand-in: keeps the kwargs and callback."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = self.closed = False

    def start(self):
        self.started = True

    def close(self):
        self.closed = True


def test_microphone_queues_blocks_and_times_out(monkeypatch):
    monkeypatch.setattr(sounddevice, "RawInputStream", FakeInputStream)
    monkeypatch.setattr(voice.hear, "MIC_TIMEOUT", 0.05)
    mic = Microphone()
    kwargs = mic.stream.kwargs
    assert {k: kwargs[k] for k in ["samplerate", "channels", "dtype", "blocksize"]} == {
        "samplerate": 16000,
        "channels": 1,
        "dtype": "int16",
        "blocksize": 256,
    }
    assert mic.stream.started
    callback = kwargs["callback"]
    callback(memoryview(b"ab"), 1, None, None)
    assert mic.read() == b"ab"
    callback(memoryview(b"cd"), 1, None, None)
    mic.flush()
    with pytest.raises(MicError, match="unplugged"):
        mic.read()
    mic.close()
    assert mic.stream.closed


def test_microphone_opens_the_given_device_and_reopens_it(monkeypatch):
    monkeypatch.setattr(sounddevice, "RawInputStream", FakeInputStream)
    mic = Microphone(device=32)
    first = mic.stream
    mic.stream.kwargs["callback"](memoryview(b"ab"), 1, None, None)
    mic.reopen()
    assert first.closed
    assert mic.stream is not first and mic.stream.started
    assert mic.stream.kwargs["device"] == 32
    assert mic.blocks.empty()  # audio from before the loss is dropped


def test_microphone_close_never_raises(monkeypatch):
    """main()'s finally relies on it: the port and the transcript deletes close after the mic."""

    class BrokenStream(FakeInputStream):
        def close(self):
            raise sounddevice.PortAudioError("device gone")

    monkeypatch.setattr(sounddevice, "RawInputStream", BrokenStream)
    Microphone().close()


def test_sounddevice_accepts_our_input_stream_args():
    parameters = inspect.signature(sounddevice.RawInputStream).parameters
    assert {"samplerate", "channels", "dtype", "blocksize", "device", "callback"} <= set(parameters)


class FakeEars:
    """Transcriber stand-in: each transcribe returns, or raises, the next of answers."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.closed = False

    def transcribe(self, pcm):
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        self.closed = True


def turn(level=-30.0):
    return Turn(pcm=PCM, start=0.0, end=1.0, voiced=0.8, level=level)


def test_transcribe_turn_with_no_text_writes_nothing():
    out = []
    assert transcribe_turn(FakeEars([""]), turn(), write=out.append) == ""
    assert out == []


def test_transcribe_turn_reports_a_scribe_error_in_one_line():
    out = []
    assert transcribe_turn(FakeEars([ApiError(status_code=500, body="x")]), turn(), write=out.append) == ""
    assert len(out) == 1
    assert out[0].startswith("(Hazel didn't catch that: ApiError")


def test_transcribe_turn_reports_the_error():
    error, seen = ApiError(status_code=500, body="x"), []
    assert transcribe_turn(FakeEars([error]), turn(), write=lambda line: None, on_error=seen.append) == ""
    assert seen == [error]
    transcribe_turn(FakeEars(["hi"]), turn(), write=lambda line: None, on_error=seen.append)
    assert seen == [error]


def test_transcribe_turn_hands_keep_each_outcome():
    kept = []
    ears = FakeEars(["hi", "", ApiError(status_code=500, body="x")])
    for _ in range(3):
        transcribe_turn(ears, turn(), write=lambda line: None, keep=lambda t, outcome: kept.append(outcome))
    assert kept == ["text", "notext", "failed"]


def test_transcribe_turn_prints_the_heard_text_and_level():
    out = []
    assert transcribe_turn(FakeEars(["Trick or treat"]), turn(-33.2), write=out.append) == "Trick or treat"
    assert out == ["visitor: Trick or treat  (-33 dB)"]


def test_cli_needs_paths_or_listen(tmp_path):
    for argv in [[], ["--listen", str(write_wav(tmp_path / "x.wav"))]]:
        with pytest.raises(SystemExit) as exit:
            main(argv)
        assert exit.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "soon", "nan", "inf", "1e309"])
def test_cli_silence_must_be_positive(value):
    with pytest.raises(SystemExit) as exit:
        main(["--listen", "--silence", value])
    assert exit.value.code == 2


def test_listen_uses_the_p10s_by_default(monkeypatch, fake_devices):
    names, devices = [], []
    monkeypatch.setattr(voice.hear, "wait_for_devices", lambda name, **k: names.append(name) or (7, 8))
    real_open_ears = voice.hear.open_ears

    def recording_open_ears(*args, device=None, **kwargs):
        devices.append(device)
        return real_open_ears(*args, device=device, **kwargs)

    monkeypatch.setattr(voice.hear, "open_ears", recording_open_ears)
    main(["--listen"])
    main(["--listen", "--device", "default"])
    assert names == ["P10S"]
    assert devices == [7, None]


def test_listen_with_a_missing_device_exits_before_opening_anything(monkeypatch, fake_devices):
    def missing(name, **kwargs):
        raise DeviceError(f"no audio input matching {name!r} after 60 s; saw: Default Source")

    monkeypatch.setattr(voice.hear, "wait_for_devices", missing)
    with pytest.raises(SystemExit, match="'Jabra' after 60 s"):
        main(["--listen", "--device", "Jabra"])
    assert fake_devices[1] == []  # no microphone opened


def test_cli_listen_prints_text_and_closes(fake_devices, capsys):
    client, mics = fake_devices
    main(["--listen"])
    out = capsys.readouterr().out
    assert "listening" in out
    assert "visitor: Trick or treat" in out
    assert mics[0].closed
    assert client.speech_to_text.transcripts.deleted == ["tr_1"]


def test_save_turn_writes_a_wav_hear_can_read_named_by_what_it_was(tmp_path):
    t = Turn(pcm=PCM, start=0.0, end=1.0, voiced=0.69, level=-41.4)
    path = save_turn(t, "notext", "292cm", directory=tmp_path / "turns", now=lambda: 1792386021.126)
    assert read_wav(path) == PCM  # 16 kHz mono int16: `voice/hear.py <wav>` replays it
    assert re.fullmatch(r"\d{8}-\d{6}\.126_-41dB_0\.69s_292cm_notext\.wav", path.name)
    assert save_turn(t, "text", directory=tmp_path / "turns").name.endswith("_-41dB_0.69s_text.wav")  # no note


def test_keep_drop_keeps_the_level_drops_only():
    seen, kept = [], []
    drop = keep_drop(lambda turn, why: seen.append(why), lambda turn, outcome: kept.append(outcome))
    for why in ("too short", "too quiet", "too quiet with nobody there"):
        drop(Turn(PCM, 0.0, 1.0, 0.5, -40.0), why)
    assert seen == ["too short", "too quiet", "too quiet with nobody there"]
    assert kept == ["quiet", "alone"]


def test_cli_listen_keeps_turns(fake_devices, monkeypatch, tmp_path):
    monkeypatch.setattr(voice.hear, "KEEP_DIR", tmp_path / "turns")
    main(["--listen", "--keep-turns"])
    (path,) = (tmp_path / "turns").iterdir()
    assert path.name.endswith("_text.wav")
