"""Hazel's voice: reply text in, sentences out to ElevenLabs, PCM played as it arrives.

`flush()` starts the unfinished sentence too, without waiting, so Brain calls it before the candy
tool runs: the spell is spoken while the turntable spins. `drain()` returns once everything fed
so far has been played. A voice failure is reported and skipped, never raised: the candy and the chat
don't wait on it. A stalled audio device (a write blocked on an unplugged speaker) is reopened
once; still stuck at the next drain, the Speaker goes quiet for good (`closed`).
"""

import queue
import re
import sys
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator

import httpx  # the elevenlabs SDK's transport (httpx, not anthropic's httpx2)
from elevenlabs.core.api_error import ApiError

VOICE_ID = "KtpLOh8Pat0RmfxZcmDJ"  # The Ancient Crone, elevenlabs.io/voice-library/witch
MODEL_ID = "eleven_flash_v2_5"  # ElevenLabs' lowest-latency model (first byte 0.17 s, measured)
SAMPLE_RATE = 24000  # Hz
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"  # raw 16-bit signed little-endian mono
TTS_TIMEOUT = 5.0  # s per read; the SDK default (240 s) would hold the candy that long
DRAIN_LIMIT = 30.0  # s; the most the voice may hold the candy, e.g. on a hung audio device (replies are 1-3 sentences)
STALL_GRACE = 1.0  # s a drain after a stall waits for the aborted worker to come free (it raises at once)
ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "vs", "etc"}  # "e.g."/"i.e.": single-letter rule
SHARE_LINK = "https://elevenlabs.io/voice-library/witch"  # where The Ancient Crone is added from

# a terminator run (+ closing quotes) followed by whitespace, or a newline
BOUNDARY = re.compile(r"(?P<end>[.!?…]+)[\"')”’]*(?P<space>\s+)|\n\s*")
LAST_WORD = re.compile(r"(?<![\w'’])[^\W\d_]+$")  # the word before a terminator ("won't." isn't "t.")
UNSPEAKABLE = {"So", "Sk", "Cs", "Co", "Me"}  # emoji, skin tones, surrogates, private use, keycaps
INVISIBLE = {"\u200d", "\ufe0f"}  # zero-width joiner, emoji variation selector


def _is_boundary(text: str, m: re.Match, final: bool) -> bool:
    if "\n" in m["space"]:
        return True  # a newline always ends a sentence
    end = m["end"]
    if end == ".":
        word = LAST_WORD.search(text, 0, m.start())
        if word and (len(word[0]) == 1 or word[0].lower() in ABBREVIATIONS):
            return False  # initials, "Dr.", ...
    if set(end) <= {".", "…"} and end != ".":  # an ellipsis: the next letter's case decides
        if m.end() == len(text):
            return final
        return not text[m.end()].islower()
    return True


def split_sentences(text: str, final: bool = False) -> tuple[list[str], str]:
    """Complete sentences (stripped) and the unfinished remainder (unstripped, to append to).
    final=True also returns the remainder as a last sentence."""
    sentences = []
    start = 0
    for m in BOUNDARY.finditer(text):
        if m["end"] and not _is_boundary(text, m, final):
            continue
        sentence = text[start : m.start("space") if m["end"] else m.start()].strip()
        if sentence:
            sentences.append(sentence)
        start = m.end()
    remainder = text[start:]
    if final:
        if remainder.strip():
            sentences.append(remainder.strip())
        remainder = ""
    return sentences, remainder


def speakable(sentence: str) -> str:
    """The sentence without emoji and other symbols TTS would mangle; "" if no word is left."""
    kept = "".join(c for c in sentence if unicodedata.category(c) not in UNSPEAKABLE and c not in INVISIBLE)
    kept = " ".join(kept.split())
    return kept if any(c.isalnum() for c in kept) else ""


class Speaker:
    def __init__(self, tts: Callable[[str], Iterable[bytes]], player, on_error: Callable[[str], None] = print):
        """tts: sentence -> PCM chunks. player: write(bytes), wait() until the written audio has
        been heard, abort(), reopen(). on_error receives one line per failed reply."""
        self.tts = tts
        self.player = player
        self.on_error = on_error
        self.pending = ""
        self.queue = queue.Queue()
        self.failed = False
        self.reply_failed = False  # a drain since the last take_reply_failed() had a failure
        self.closed = False
        self._reopen = False  # reopen the player before the next sentence
        self._aborted = False  # reset_output() aborted the player: the write it frees fails quietly
        self._stalled: threading.Event | None = None  # the last drain, if it timed out (cleared by one in time)
        threading.Thread(target=self._work, daemon=True).start()

    def feed(self, chunk: str) -> None:
        """Add streamed reply text; complete sentences start being spoken. Never blocks."""
        if self.closed:
            return
        sentences, self.pending = split_sentences(self.pending + chunk)
        self._enqueue(sentences)

    def play(self, pcm: bytes) -> None:
        """Queue recorded audio (raw int16 at SAMPLE_RATE) after the text fed so far, an unfinished
        sentence included. Never blocks."""
        if not self.closed:
            sentences, self.pending = split_sentences(self.pending, final=True)
            self._enqueue(sentences)
            self.queue.put(pcm)

    def take_reply_failed(self) -> bool:
        """Whether anything fed or played failed since the last call, over every drain in between
        (a reply can be drained more than once); then forget it."""
        failed, self.reply_failed = self.reply_failed, False
        return failed

    def flush(self) -> None:
        """Start speaking the rest of the text fed so far, an unfinished sentence included. Never blocks."""
        if not self.closed:
            sentences, self.pending = split_sentences(self.pending, final=True)
            self._enqueue(sentences)

    def drain(self) -> None:
        """Speak the rest of the text fed so far and return once it has been heard."""
        if self.closed:
            return
        if self._stalled is not None and not self._stalled.wait(STALL_GRACE):
            self._give_up()  # the worker is still stuck, even after the abort
            return
        sentences, self.pending = split_sentences(self.pending, final=True)
        self._enqueue(sentences)
        heard = threading.Event()
        self.queue.put(heard)
        if heard.wait(DRAIN_LIMIT):
            self._stalled = None
        elif self._stalled is not None:
            self._give_up()  # stalled again on the reopened device
        else:
            self._stalled = heard
            self.reply_failed = True
            self.reset_output()
            self.on_error(f"(Hazel's voice stalled for {DRAIN_LIMIT:.0f} s: reopening the speaker)")

    def _give_up(self) -> None:
        self.close()  # a device that keeps hanging can't be trusted again: carry on muted
        self.on_error(f"(Hazel lost her voice: nothing heard for {DRAIN_LIMIT:.0f} s, carrying on without it)")

    def reset_output(self) -> None:
        """The audio device was lost: free a write blocked on it now, and reopen the player before
        the next sentence. Never raises."""
        self._reopen = self._aborted = True
        try:
            self.player.abort()  # a write blocked in the worker raises
        except Exception:
            pass

    def close(self) -> None:
        """Stop the audio at once. Never raises; later feed/drain calls do nothing."""
        self.closed = True
        try:
            self.player.abort()  # a write blocked in the worker raises
        except Exception:
            pass

    def _enqueue(self, sentences: list[str]) -> None:
        for s in sentences:
            if spoken := speakable(s):
                self.queue.put(spoken)

    def _work(self) -> None:
        while True:
            item = self.queue.get()
            if isinstance(item, threading.Event):
                try:
                    self._attempt(self.player.wait)
                finally:
                    self.reply_failed = self.reply_failed or self.failed
                    self.failed = False  # the next reply tries again
                    item.set()
            elif not self.closed and (isinstance(item, bytes) or not self.failed):  # recordings play when TTS failed
                if self._reopen:
                    self._attempt(self._reopen_player)
                    if self._reopen:
                        continue  # still gone: reported once; the next reply tries again
                self._attempt(self._say if isinstance(item, str) else self.player.write, item)

    def _attempt(self, step, *args) -> None:
        """Run one step of the worker; any voice failure is reported once, never raised."""
        try:
            step(*args)
        except Exception as e:  # never let a voice failure block the candy
            report = not (self.failed or self.closed or self._aborted)
            self.failed = True
            if report:
                try:
                    self.on_error(f"(Hazel lost her voice: {e.__class__.__name__}: {e})")
                except Exception:
                    pass  # e.g. stdout gone: the worker must live on to release drain()

    def _reopen_player(self) -> None:
        self._aborted = False
        self.player.reopen()
        self._reopen = False

    def _say(self, sentence: str) -> None:
        carry = b""  # int16 samples are 2 bytes; the HTTP layer doesn't promise alignment
        for chunk in self.tts(sentence):
            data = carry + chunk
            cut = len(data) - len(data) % 2
            if cut:
                self.player.write(data[:cut])
            carry = data[cut:]


def elevenlabs_tts(client, voice_id: str) -> Callable[[str], Iterator[bytes]]:
    """client: an elevenlabs.client.ElevenLabs. The stream is lazy: errors raise while iterating."""
    return lambda text: client.text_to_speech.stream(voice_id, text=text, model_id=MODEL_ID, output_format=OUTPUT_FORMAT)


class SoundPlayer:
    """An audio output (device: a PortAudio index, None = the default). Opening it raises
    sounddevice.PortAudioError with no device."""

    def __init__(self, device=None):
        self.device = device
        self.released = False
        self._open()

    def _open(self) -> None:
        import sounddevice  # here, not at the top: --mute must not need PortAudio

        self.stream = sounddevice.RawOutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=self.device)
        self.stream.start()

    def _close(self) -> None:
        for step in (self.stream.abort, self.stream.close):
            try:
                step()
            except Exception:
                pass

    def reopen(self) -> None:
        """A new stream on the device (the same index works after a replug). Called by
        the Speaker's worker, so nothing is inside the old stream. Raises
        sounddevice.PortAudioError while the device is still gone, RuntimeError while released."""
        if self.released:
            raise RuntimeError("the audio device is being looked for again")
        self._close()
        self._open()

    def release(self) -> None:
        """Close the stream so PortAudio can re-scan; reopen() refuses until move_to(). A stream
        opened while the device is gone links to another one (the laptop's), with no error."""
        self.released = True
        self._close()

    def move_to(self, device) -> None:
        """The device's index after the re-scan; the next reopen() opens it."""
        self.device = device
        self.released = False

    def write(self, data: bytes) -> None:
        self.stream.write(data)  # blocks while the buffer is full

    def wait(self) -> None:
        time.sleep(self.stream.latency)  # write returns once buffered, not once heard

    def abort(self) -> None:
        self.stream.abort()  # not close(): the worker may still be inside the stream


def check_voice(client, voice_id: str) -> None:
    """Exit with a one-line message unless the key works and the voice is in the account (free)."""
    try:
        client.voices.get(voice_id)
    except ApiError as e:
        if "missing_permissions" in str(e.body):
            sys.exit(f"ElevenLabs key lacks a permission: {e.body}")
        if e.status_code == 401:
            sys.exit("ElevenLabs key was rejected: check ELEVENLABS_API_KEY")
        if "voice_not_found" in str(e.body):
            sys.exit(f"voice {voice_id} is not in your ElevenLabs voices: open {SHARE_LINK}, 'Add to my voices', and set ELEVENLABS_VOICE_ID if its ID differs")
        sys.exit(f"ElevenLabs check failed: {e}")
    except httpx.TransportError as e:
        sys.exit(f"ElevenLabs check failed: {e}")
