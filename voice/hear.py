"""Hazel's ears: 16 kHz mono 16-bit PCM in, ElevenLabs Scribe v2 text out.

`Transcriber.transcribe` returns the stripped text, or "" when there is no speech (silence and
noise: audio-event tags are off). Each transcript is deleted from the ElevenLabs account after
use, on a background daemon thread, because zero-retention mode is refused on the Starter plan;
close() waits at most CLOSE_LIMIT for them, then reports each ID still pending. A request that
times out may still leave a transcript behind: it comes back with no ID to delete.

`Listener` cuts a `Microphone`'s audio into visitor turns with TEN VAD: pre-roll, an end-of-turn
silence, and gates that drop turns too short or too quiet to be a visitor: gentler during a
visit (`VISIT_MIN_VOICED`, `VISIT_MIN_DBFS`), stricter when nobody stands in front
(`MIN_ALONE_DBFS`). It is half-duplex: after `resume()` (Hazel just
spoke), audio captured until the next `listen()` is dropped. Audio is never saved, unless
--keep-turns asks for WAVs in tmp/turns/ (`save_turn`) to find out what reaches Scribe.

Usage:
    uv run --env-file .env voice/hear.py tests/fixtures/voice/*.wav   # prints each file's text and delay
    uv run --env-file .env voice/hear.py --listen [--silence 0.7]     # live mic -> turns -> text, with levels
    uv run --env-file .env voice/hear.py --listen --device default    # the system default mic, not the P10S
    uv run --env-file .env voice/hear.py --listen --keep-turns        # also saves each turn as a WAV in tmp/turns/
"""

import argparse
import logging
import math
import os
import queue
import sys
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # voice isn't an installed package

import httpx  # the elevenlabs SDK's transport (httpx, not anthropic's httpx2)
import numpy as np
from elevenlabs.client import ElevenLabs
from elevenlabs.core.api_error import ApiError
from ten_vad import TenVad
from voice.devices import AUDIO_DEVICE, AUDIO_RETRY, AUDIO_WAIT, SYSTEM_DEFAULT, DeviceError, wait_for_devices

STT_MODEL_ID = "scribe_v2"  # beat faster-whisper on kid-like voices and noise (docs/voice.md, open decision 2)
STT_SAMPLE_RATE = 16000  # Hz; Scribe's raw-PCM input rate, and what the Microphone records
STT_FORMAT = "pcm_s16le_16"  # Scribe's name for 16-bit little-endian mono at STT_SAMPLE_RATE
STT_LANGUAGE = "en"
STT_TIMEOUT = 5.0  # s per read, like TTS_TIMEOUT; a turn takes 0.3-0.6 s
STT_KEYTERMS = ["trick or treat"]  # the magic words (voice/persona.md); fixes kid voices in noise
DELETE_RETRY = 0.25  # s between delete tries: a transcript is stored 0.2-0.6 s after the reply
DELETE_WINDOW = 5.0  # s of "not found yet" before giving up (8x the slowest seen)
STT_REQUEST_OPTIONS = {"max_retries": 0}  # one upload per turn: an SDK retry can leave a transcript we can't delete, and adds ~3 s
CLOSE_LIMIT = 8.0  # s exit waits for pending deletes: DELETE_WINDOW plus one SDK retry backoff
VAD_HOP = 256  # samples per VAD frame and per mic block: 16 ms, TEN VAD's hop
HOP_SECONDS = VAD_HOP / STT_SAMPLE_RATE
VAD_THRESHOLD = 0.5  # TEN probability for speech: splits every speech clip from every non-speech one
VAD_WARMUP = 1.0  # s ignored on the first listen(): a fresh TEN VAD fires on its first frames
MIN_VOICED = 0.45  # s of speech frames a turn needs: speech has >= 0.61, music and noise <= 0.34
MIN_TURN_DBFS = -45.0  # level of a turn's speech frames; quieter is background (TV), not a visitor
# the level a turn needs with nobody in front of the HC-SR04 and no visit going. From logs/:
# 427 of 440 such turns came back from Scribe empty; at -38 dB 41 are sent, and every lost one
# with text was a grown-up's aside at -41/-42 dB (a visitor's "trick or treat" was -30 dB or louder)
MIN_ALONE_DBFS = -38.0
# during a visit (Hazel greeted someone, or a visitor is talking) quieter, shorter answers count:
# "yes", a shy kid. logs/ with someone within 150 cm: 29 turns dropped at 0.30-0.45 s
# voiced, 12 at -50..-45 dB. Noise let through costs an empty Scribe call, which gets no reply
VISIT_MIN_VOICED = 0.30  # s; music and noise reach 0.34, so only during a visit
VISIT_MIN_DBFS = -50.0  # 12 of those dropped turns were at -50..-45 dB
KEEP_DIR = Path(__file__).resolve().parent.parent / "tmp" / "turns"  # --keep-turns; tmp/ is git-ignored
END_SILENCE = 0.7  # s of non-speech that ends a turn (docs/voice.md); --silence overrides
PRE_ROLL = 0.8  # s of audio before the trigger kept in the turn: the VAD fires up to 0.64 s late
ECHO_TAIL = 0.5  # s ignored after Hazel stops: mic latency 0.24-0.37 s (S2), no echo speech after the drain (S11)
MAX_TURN = 15.0  # s; a turn this long (pre-roll included) is sent as it is
MIC_TIMEOUT = 2.0  # s with no block (they come every 16 ms) means the mic is gone
STT_ERRORS = (ApiError, httpx.TransportError)  # what transcribe raises when Scribe fails

log = logging.getLogger(__name__)


def read_wav(path) -> bytes:
    """The PCM frames of a 16 kHz mono 16-bit WAV. Other formats raise ValueError; non-WAVs wave.Error."""
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if (rate, channels, width) != (STT_SAMPLE_RATE, 1, 2):
            raise ValueError(
                f"{path}: need 16 kHz mono 16-bit WAV, got {rate} Hz, {channels} ch, {8 * width}-bit (convert: ffmpeg -i in -ar 16000 -ac 1 -sample_fmt s16 out.wav)"
            )
        return w.readframes(w.getnframes())


class Transcriber:
    def __init__(self, client, on_error: Callable[[str], None] = print):
        """client: an elevenlabs.client.ElevenLabs. on_error receives one line per transcript
        that couldn't be deleted."""
        self.client = client
        self.on_error = on_error
        self.closed = False
        # one daemon worker deletes in order; a daemon never holds interpreter exit
        self._queue = queue.Queue()
        self._pending: list[str] = []
        self._changed = threading.Condition()  # guards closed and _pending
        threading.Thread(target=self._work, daemon=True).start()

    def transcribe(self, pcm: bytes) -> str:
        """Text heard in pcm, "" if none. Raises ApiError or httpx.TransportError if Scribe fails,
        RuntimeError after close() (before sending: an upload whose transcript can't be deleted)."""
        if self.closed:
            raise RuntimeError("Transcriber is closed")
        if not pcm:
            return ""  # an empty upload is a 400
        response = self.client.speech_to_text.convert(
            model_id=STT_MODEL_ID,
            file=pcm,
            file_format=STT_FORMAT,
            language_code=STT_LANGUAGE,
            tag_audio_events=False,  # with tags, noise comes back as "[static]"
            keyterms=STT_KEYTERMS,
            request_options=STT_REQUEST_OPTIONS,
        )
        transcription_id = response.transcription_id
        if transcription_id:
            with self._changed:
                queued = not self.closed
                if queued:
                    self._pending.append(transcription_id)
                    self._queue.put(transcription_id)
            if not queued:  # close() ran during the upload: delete here instead
                self._forget(transcription_id)
        return response.text.strip()

    def close(self) -> None:
        """Wait at most CLOSE_LIMIT for pending deletes, then report each ID still pending."""
        with self._changed:
            if self.closed:
                return  # the first close() already waited and reported
            self.closed = True
        try:
            with self._changed:
                self._changed.wait_for(lambda: not self._pending, timeout=CLOSE_LIMIT)
        finally:  # also on a second Ctrl-C: the IDs left on the account must be known
            with self._changed:
                left = list(self._pending)
            for transcription_id in left:
                try:  # the ID only: the transcript text is a child's words
                    self.on_error(f"(couldn't delete transcript {transcription_id}: still pending after {CLOSE_LIMIT:g} s at exit)")
                except Exception:
                    pass

    def _work(self) -> None:
        while True:
            transcription_id = self._queue.get()
            try:
                self._forget(transcription_id)
            except Exception:  # on_error raised: keep the worker alive for the next deletes
                pass
            with self._changed:
                self._pending.remove(transcription_id)
                self._changed.notify_all()

    def _forget(self, transcription_id: str) -> None:
        """Delete the transcript, retrying while it isn't stored yet. Reports, never raises."""
        deadline = time.monotonic() + DELETE_WINDOW
        while True:
            try:
                self.client.speech_to_text.transcripts.delete(transcription_id)
                return
            except Exception as e:
                if isinstance(e, ApiError) and e.status_code == 404 and time.monotonic() < deadline:
                    time.sleep(DELETE_RETRY)
                    continue
                # the ID only: the transcript text is a child's words
                self.on_error(f"(couldn't delete transcript {transcription_id}: {e.__class__.__name__}: {e})")
                return


def positive_seconds(text: str) -> float:
    """argparse type: a number of seconds > 0."""
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not (value > 0 and math.isfinite(value)):  # also rejects nan and inf
        raise argparse.ArgumentTypeError("must be a number of seconds > 0")
    return value


class MicError(Exception):
    """The microphone gives no usable audio."""


class SilentMic(MicError):
    """The microphone gives only digital silence: muted or not allowed, which reopening won't fix."""


@dataclass
class Turn:
    """One visitor turn. start and end are seconds of audio this Listener has read (flushed audio
    isn't counted); start includes the pre-roll."""

    pcm: bytes
    start: float
    end: float
    voiced: float  # s of speech frames
    level: float  # dBFS of the speech frames


def ten_vad() -> Callable[[bytes], float]:
    """The speech probability of one VAD_HOP frame of int16 PCM."""
    vad = TenVad(VAD_HOP, VAD_THRESHOLD)
    return lambda frame: float(vad.process(np.frombuffer(frame, np.int16))[0])


def dbfs(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, np.int16) / 32768
    return 20 * math.log10(math.sqrt(np.mean(samples**2)) + 1e-9)


def frames(seconds: float) -> int:
    return math.ceil(seconds / HOP_SECONDS)


class Listener:
    """Cuts a mic's audio into visitor turns with a VAD: pre-roll, end silence and gates (voiced
    length, then level; gentler in a visit, stricter with nobody there). Half-duplex: after resume(), listen() only hears audio from after
    it was called."""

    def __init__(self, mic, vad, end_silence=END_SILENCE, on_drop=lambda turn, why: None, alone=lambda: False, in_visit=lambda: False):
        """mic: read() -> one VAD_HOP block (EOFError at the end of a source, MicError when the
        device is gone) and flush(). vad: frame -> speech probability. on_drop(turn, why) sees
        each turn the gates drop. alone() is True when nobody is there to talk (no visit, and the
        sensor sees nobody): such a turn needs MIN_ALONE_DBFS. It is asked only for a turn between
        the two levels. in_visit() is True while a visit is going: a turn then needs only
        VISIT_MIN_VOICED and VISIT_MIN_DBFS, and alone() isn't asked."""
        self.mic = mic
        self.vad = vad
        self.end_silence = end_silence
        self.on_drop = on_drop
        self.alone = alone
        self.in_visit = in_visit
        self._warmup = frames(VAD_WARMUP)
        self._echo = frames(ECHO_TAIL)
        self._end = frames(end_silence)
        self._min_voiced = frames(MIN_VOICED)
        self._visit_min_voiced = frames(VISIT_MIN_VOICED)
        self._max_turn = frames(MAX_TURN)
        self._ring = deque(maxlen=frames(PRE_ROLL))  # the last PRE_ROLL of audio, kept through dropped turns
        self._read = 0  # frames read since the first listen()
        self._started = False
        self._eof = False
        self._resume = True  # the first listen() flushes too
        self._skip = 0  # frames still to ignore: the warm-up, or the echo tail
        self._all_zero = True  # every warm-up frame so far was digital silence

    def resume(self) -> None:
        """Hazel just spoke: the next listen() drops what the mic captured until then, and the first
        ECHO_TAIL after it."""
        self._resume = True

    def listen(self, timeout: float | None = None) -> Turn | None:
        """The next turn that passes the gates, or None if no turn was open after `timeout` s of audio
        (never cuts a turn short). Audio from before the last resume() (Hazel talking) is dropped,
        and so is the first ECHO_TAIL after it (VAD_WARMUP on the first call)."""
        if self._eof:
            raise EOFError
        if self._resume:
            self.mic.flush()
            self._ring.clear()
            self._resume = False
            if not self._started:
                self._started = True
                self._skip = self._warmup
            else:
                self._skip = max(self._skip, self._echo)
        limit = frames(timeout) if timeout is not None else None
        read = 0  # frames read in this call
        body, voiced, start = None, [], 0  # the open turn: its frames (pre-roll included), speech frames, first frame
        while True:
            if body is None and limit is not None and read >= limit:
                return None
            try:
                frame = self.mic.read()
            except EOFError:
                self._eof = True
                if body is not None and (passed := self._gate(body, voiced, start)):
                    return passed
                raise
            self._read += 1
            read += 1
            p = self.vad(frame)  # every frame read, skipped ones too: the VAD's state follows the audio
            if self._skip > 0:
                self._skip -= 1
                self._all_zero = self._all_zero and not any(frame)
                if self._skip == 0 and self._all_zero:  # a working mic never gives this
                    raise SilentMic(
                        "the microphone gives only digital silence: check its input volume (Linux: `wpctl status` or pavucontrol;"
                        " macOS: System Settings → Sound → Input) and that this program may use the microphone"
                    )
                continue
            speech = p >= VAD_THRESHOLD
            if body is None:
                if speech:
                    start = self._read - len(self._ring) - 1
                    body, voiced, silence = [*self._ring, frame], [frame], 0
                self._ring.append(frame)
                continue
            body.append(frame)
            self._ring.append(frame)  # so a dropped blip doesn't eat the next turn's lead-in
            if speech:
                voiced.append(frame)
                silence = 0
            else:
                silence += 1
            if silence == self._end or len(body) >= self._max_turn:
                passed = self._gate(body, voiced, start)
                body = None
                if passed:
                    return passed

    def _gate(self, body, voiced, start) -> Turn | None:
        turn = Turn(
            b"".join(body),
            start * HOP_SECONDS,
            (start + len(body)) * HOP_SECONDS,
            len(voiced) * HOP_SECONDS,
            dbfs(b"".join(voiced)),
        )
        visit = self.in_visit()
        if len(voiced) < (self._visit_min_voiced if visit else self._min_voiced):
            self.on_drop(turn, "too short")
        elif turn.level < (VISIT_MIN_DBFS if visit else MIN_TURN_DBFS):
            self.on_drop(turn, "too quiet")
        elif not visit and turn.level < MIN_ALONE_DBFS and self.alone():
            self.on_drop(turn, "too quiet with nobody there")
        else:
            return turn
        return None


class Microphone:
    """An audio input (device: a PortAudio index, None = the default): 16 kHz mono int16 in VAD_HOP
    blocks. Opening it raises sounddevice.PortAudioError with no device."""

    def __init__(self, device=None):
        self.device = device
        self.blocks = queue.Queue()
        self._open()

    def _open(self) -> None:
        import sounddevice  # here, not at the top: --text must not need PortAudio

        self.stream = sounddevice.RawInputStream(samplerate=STT_SAMPLE_RATE, channels=1, dtype="int16", blocksize=VAD_HOP, device=self.device, callback=self._callback)
        self.stream.start()

    def reopen(self) -> None:
        """A new stream on the same device, e.g. after a replug (the same index works).
        Raises sounddevice.PortAudioError while the device is still gone."""
        self.close()
        self.flush()
        self._open()

    def _callback(self, indata, frames, time, status) -> None:
        self.blocks.put(bytes(indata))  # PortAudio's thread: never raises

    def read(self) -> bytes:
        try:
            return self.blocks.get(timeout=MIC_TIMEOUT)
        except queue.Empty:
            raise MicError(f"no audio from the microphone for {MIC_TIMEOUT:g} s: is it unplugged?") from None

    def flush(self) -> None:
        try:
            while True:
                self.blocks.get_nowait()
        except queue.Empty:
            pass

    def close(self) -> None:
        try:
            self.stream.close()
        except Exception:
            pass


def reopen_mic(mic, wait=AUDIO_WAIT, sleep=time.sleep, clock=time.monotonic) -> None:
    """Reopen mic until a block arrives (audio flows again), trying every AUDIO_RETRY s; MicError
    after `wait` s."""
    import sounddevice  # PortAudio is loaded already: the mic is open

    deadline = clock() + wait
    while True:
        try:
            mic.reopen()
            mic.read()  # MicError after MIC_TIMEOUT while the device is gone
            return
        except (MicError, sounddevice.PortAudioError) as e:
            if clock() >= deadline:
                raise MicError(f"the audio device didn't come back in {wait:g} s: {e}") from e
        sleep(AUDIO_RETRY)


def transcribe_turn(ears, turn: Turn, write=print, on_error=lambda e: None, keep=lambda turn, outcome: None) -> str:
    """The turn's text, or "" when Scribe hears nothing or fails (one line is written for a
    failure, and on_error gets the exception). Prints `visitor: <text>  (<level> dB)` for a heard
    turn. keep(turn, outcome) sees every turn: "text", "notext" or "failed"."""
    start = time.monotonic()
    try:
        text = ears.transcribe(turn.pcm)
    except STT_ERRORS as e:
        write(f"(Hazel didn't catch that: {e.__class__.__name__}: {e})")
        on_error(e)
        keep(turn, "failed")
        return ""
    keep(turn, "text" if text else "notext")
    log.debug(  # never the words: they're a child's
        "turn: %.1f s, %.2f s voiced, %.0f dB; Scribe %.2f s, %s",
        turn.end - turn.start,
        turn.voiced,
        turn.level,
        time.monotonic() - start,
        "text" if text else "no text",
    )
    if text:
        write(f"visitor: {text}  ({turn.level:.0f} dB)")
    return text


def log_drop(turn: Turn, why: str) -> None:
    log.debug("dropped a turn: %s (%.2f s voiced, %.0f dB)", why, turn.voiced, turn.level)


def save_turn(turn: Turn, outcome: str, note: str = "", directory: Path | None = None, now=time.time) -> Path:
    """--keep-turns: the turn as a 16 kHz mono WAV (what `voice/hear.py <wav>` reads) in directory,
    named <date>-<time>.<ms>_<level>dB_<voiced>s[_<note>]_<outcome>.wav, so a night's turns sort
    by time and can be listened to by what Scribe made of them. directory defaults to KEEP_DIR."""
    directory = directory or KEEP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    t = now()
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + f".{int(t * 1000) % 1000:03d}"
    parts = [stamp, f"{turn.level:.0f}dB", f"{turn.voiced:.2f}s", note, outcome]
    path = directory / ("_".join(part for part in parts if part) + ".wav")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(STT_SAMPLE_RATE)
        w.writeframes(turn.pcm)
    return path


def keep_drop(on_drop, keep):
    """An on_drop that also hands keep(turn, outcome) the turns the level gates drop ("quiet",
    "alone"); "too short" ones are blips, too many to keep."""

    def drop(turn: Turn, why: str) -> None:
        on_drop(turn, why)
        if why != "too short":
            keep(turn, "alone" if "nobody" in why else "quiet")

    return drop


def open_ears(end_silence=END_SILENCE, on_drop=log_drop, hint="", device=None) -> tuple[Listener, Transcriber]:
    """The mic's Listener (device: a PortAudio index, None = the default) and a Transcriber, or exit
    with a one-line message (hint appended)."""
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit(f"no ElevenLabs key: set ELEVENLABS_API_KEY (in .env){hint}")
    ears = Transcriber(ElevenLabs(timeout=STT_TIMEOUT), on_error=log.warning)
    import sounddevice  # here, not at the top: --text must not need PortAudio

    try:
        mic = Microphone(device=device)
    except sounddevice.PortAudioError as e:
        ears.close()
        sys.exit(f"no microphone: {e}{hint}")
    return Listener(mic, ten_vad(), end_silence=end_silence, on_drop=on_drop), ears


def listen(end_silence: float, device: str = AUDIO_DEVICE, keep_turns: bool = False) -> None:
    """--listen: the live mic's turns as text until Ctrl-C, and the dropped turns, for tuning the gates.
    It uses the same mic as voice/main.py: the P10S unless device says otherwise. keep_turns saves
    each turn sent to Scribe, or dropped as too quiet, in KEEP_DIR. No sensor here: never alone."""

    def report(turn: Turn, why: str) -> None:
        print(f"(dropped: {why}, voiced {turn.voiced:.2f} s, {turn.level:.0f} dB)", flush=True)

    keep = save_turn if keep_turns else (lambda turn, outcome: None)

    mic = None
    if device != SYSTEM_DEFAULT:
        try:
            mic, _ = wait_for_devices(device)
        except DeviceError as e:
            sys.exit(str(e))
    listener, ears = open_ears(end_silence, on_drop=keep_drop(report, keep), device=mic)
    try:
        print(f"listening (Ctrl-C to stop){f'; keeping turns in {KEEP_DIR}' if keep_turns else ''}", flush=True)
        while True:  # no resume(): nobody speaks here
            transcribe_turn(ears, listener.listen(), keep=keep)
    except KeyboardInterrupt:
        print()
    except MicError as e:
        print(f"({e})")
    finally:
        listener.mic.close()
        ears.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="16 kHz mono 16-bit WAV files")
    parser.add_argument("--listen", action="store_true", help="live mic: print each turn's text and level")
    parser.add_argument("--silence", type=positive_seconds, default=END_SILENCE, help="--listen: seconds of quiet that end a turn")
    parser.add_argument(
        "--device", default=AUDIO_DEVICE, help=f"--listen: the mic by name (default {AUDIO_DEVICE}, as voice/main.py; {SYSTEM_DEFAULT} = the system default)"
    )
    parser.add_argument("--keep-turns", action="store_true", help=f"--listen: save each turn as a WAV in {KEEP_DIR.parent.name}/{KEEP_DIR.name}/")
    args = parser.parse_args(argv)
    if bool(args.paths) == args.listen:
        parser.error("give WAV files or --listen, not both")
    if args.listen:
        listen(args.silence, args.device, args.keep_turns)
        return
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("no ElevenLabs key: set ELEVENLABS_API_KEY (in .env, then run with uv run --env-file .env)")

    ears = Transcriber(ElevenLabs(timeout=STT_TIMEOUT))
    try:
        for path in args.paths:
            try:
                pcm = read_wav(path)
                start = time.perf_counter()
                text = ears.transcribe(pcm)
                secs = time.perf_counter() - start
            except (ValueError, wave.Error, *STT_ERRORS) as e:
                print(f"{path.name}: {e.__class__.__name__}: {e}")
                continue
            print(f"{path.name}: {secs:.2f} s  {text!r}")
    finally:
        ears.close()


if __name__ == "__main__":
    main()
