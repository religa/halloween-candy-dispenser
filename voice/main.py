"""Talk to the candy witch: by voice, or by typing with --text. You play the trick-or-treater.

Usage:
    uv run --env-file .env voice/main.py                                 # by voice: the P10S's mic and speaker, real Arduino
    uv run --env-file .env voice/main.py --device default                # the system default mic and speaker (another computer)
    uv run --env-file .env voice/main.py --silence 1.0                   # longer pause before Hazel answers
    uv run --env-file .env voice/main.py --text                          # typed; real Arduino (finds the port)
    uv run --env-file .env voice/main.py --text --port /dev/ttyACM0      # Linux; /dev/cu.usbmodem14101 on macOS
    uv run --env-file .env voice/main.py --text --fake-dispenser candy   # no Arduino: pretend (candy|empty|blocked)
    uv run --env-file .env voice/main.py --text --mute                   # text only, no voice
    uv run --env-file .env voice/main.py --debug                         # also every Arduino line, turn and request timing
    uv run --env-file .env voice/main.py --keep-turns                    # also save each turn as a WAV in tmp/turns/ (git-ignored)

Needs ANTHROPIC_API_KEY, and ELEVENLABS_API_KEY (optionally ELEVENLABS_VOICE_ID) unless --text --mute
(voice mode needs it to hear even with --mute), kept in the git-ignored .env and loaded by
`uv run --env-file .env` (the code itself doesn't read .env). Ctrl-C = exit. Typed: /next = new
visitor, /quit or Ctrl-D = exit. By voice, Hazel greets at start-up and whenever the HC-SR04
(when it's wired) sees someone walk up with no visit going, and handles a stream of visitors: a
visit ends after quiet, or once the sensor sees them leave (voice/visits.py).

Hazel uses the P10S speakerphone's mic and speaker (voice/devices.py), never the laptop's: at
start-up it waits up to 60 s for it, and a P10S lost mid-session is reopened for up to 60 s, then
the program exits with status 1 for its supervisor (tools/candy-witch.service) to restart it. A
lost Arduino is reopened without ending the run.

What happens is logged to the terminal, between Hazel's lines: the sensor's HERE/GONE, visits
starting and ending (and why), tool calls and candy. --debug adds every Arduino line, each heard
or dropped turn (with the HC-SR04's distance at that moment) and each request's timing. Every run also writes a full log to
logs/voice-<date>-<time>.log (git-ignored): everything the terminal shows, visitors' words and
Hazel's replies included, plus the --debug records.

During a visit, quieter and shorter turns reach Scribe (`VISIT_MIN_VOICED`, `VISIT_MIN_DBFS`). With
no visit going and nobody within the HC-SR04's HERE_CM, a turn must be louder (`MIN_ALONE_DBFS`), and a Scribe failure isn't answered with "Eh?": there is nobody to
hear it. --keep-turns saves every turn sent to Scribe, and each dropped as too quiet, as a WAV
named after its level, the sensor's distance and what Scribe made of it, to find out what the
mic hears. Those are visitors' voices: listen, then delete them.
"""

import argparse
import logging
import os
import random
import signal
import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # voice isn't an installed package

import anthropic
import httpx2
from elevenlabs.client import ElevenLabs
from voice.brain import MODEL, Brain
from voice.devices import AUDIO_DEVICE, SYSTEM_DEFAULT, DeviceError, wait_for_devices
from voice.dispenser import HERE_CM, STARTUP_WAIT, DispenserError, Outcome, Presence, Reconnecting
from voice.fallback import FILLERS, GREETINGS, LINES, load_lines, report_api_error
from voice.hear import END_SILENCE, MicError, SilentMic, keep_drop, log_drop, open_ears, positive_seconds, reopen_mic, save_turn, transcribe_turn
from voice.rules import CandyRules
from voice.speak import TTS_TIMEOUT, VOICE_ID, SoundPlayer, Speaker, check_voice, elevenlabs_tts
from voice.status import PARTS, Status
from voice.visits import Visits

API_TIMEOUT = 30.0  # s; the SDK default (600 s read) would freeze the chat on a stalled stream
# Brain.reply's errors: the SDK wraps transport errors only while opening a request, not mid-stream
REPLY_ERRORS = (anthropic.APIError, httpx2.TransportError)
TYPED_GREETING = "Hazel the witch is ready. Type as the visitor; /next = new visitor, /quit = exit."
VOICE_GREETING = "Hazel the witch is listening. Talk to her; Ctrl-C = exit."
TICK = 0.25  # s of audio per listen() while nobody speaks: how often the sensor and the clock are checked
LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s"
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"  # git-ignored: it holds visitors' words
SCREEN = "voice.screen"  # the logger for lines the terminal already shows: they go to the log file only

log = logging.getLogger("voice.main")
screen = logging.getLogger(SCREEN)


class Console(logging.Handler):
    """stdout, shared by Hazel's streamed words, the loop's lines and log records: a record that
    comes while Hazel is mid-sentence starts on a new line."""

    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter(LOG_FORMAT, "%H:%M:%S"))
        self.addFilter(lambda record: record.name != SCREEN)
        self._mid_line = False
        self._line = ""  # the screen line so far, for the log file

    def write(self, *parts, end="\n") -> None:
        """print() for everything that isn't a log record; each finished line also goes to the log file."""
        text = " ".join(map(str, parts)) + end
        with self.lock:
            print(text, end="", flush=True)
            if text:
                self._mid_line = not text.endswith("\n")
            *done, self._line = (self._line + text).split("\n")
        for line in done:
            if line.strip():
                screen.info(line)

    def write_line(self, text: str) -> None:
        """A line of its own, even while Hazel is mid-sentence (like a log record)."""
        self.write(("\n" if self._mid_line else "") + text)

    def emit(self, record) -> None:
        try:
            line = self.format(record)
            print("\n" + line if self._mid_line else line, flush=True)  # called with self.lock held
            self._mid_line = False
        except Exception:
            self.handleError(record)


def pick_line(texts, recorded, last: str | None, choice=random.choice) -> str | None:
    """A recorded line's name from texts (GREETINGS, FILLERS), never the one said last if there's
    another; None if none is recorded."""
    names = [name for name in texts if name in recorded]
    return choice([name for name in names if name != last] or names) if names else None


def sensor_reading(dispenser) -> str:
    """The HC-SR04's distance now, for the status line: "87 cm", "none" (nothing in range) or
    "?" (the Arduino isn't answering; its own status field says why)."""
    try:
        cm = dispenser.distance()
    except DispenserError:
        return "?"
    return f"{cm} cm" if cm else "none"


def nobody_there(dispenser) -> bool:
    """True when the HC-SR04 sees nobody within HERE_CM (or nothing in range); False when it sees
    someone, or the Arduino isn't answering: then nobody can tell, and a visitor gets the benefit."""
    try:
        cm = dispenser.distance()
    except DispenserError:
        return False
    return not cm or cm >= HERE_CM


def turn_note(dispenser) -> str:
    """--keep-turns: the sensor's distance for a WAV's name: "87cm", "none" or "noanswer"."""
    reading = sensor_reading(dispenser)
    return "noanswer" if reading == "?" else reading.replace(" ", "")


class SensorNote(logging.Filter):
    """Adds the HC-SR04's distance to voice.hear's debug lines (a heard or a dropped turn), so the
    log shows whether someone stood in front when the mic heard something."""

    def __init__(self, dispenser):
        super().__init__()
        self.dispenser = dispenser

    def filter(self, record) -> bool:
        if record.levelno == logging.DEBUG:
            try:
                cm = self.dispenser.distance()
            except DispenserError:
                note = "no answer"
            else:
                note = f"{cm} cm" if cm else "nothing in range"
            record.msg = f"{record.msg}; sensor: {note}"
        return True


def setup_logging(debug: bool, log_dir: Path) -> tuple[Console, Path]:
    """Log records from voice.* go to a Console at INFO (DEBUG with debug), and all of them, with the
    screen's lines, to a new file in log_dir; other libraries' only from WARNING up."""
    log_dir.mkdir(exist_ok=True)
    path = log_dir / time.strftime("voice-%Y%m%d-%H%M%S.log")
    console = Console()
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    file = logging.FileHandler(path, encoding="utf-8")
    file.setFormatter(logging.Formatter(LOG_FORMAT, "%Y-%m-%d %H:%M:%S"))
    logging.basicConfig(level=logging.WARNING, handlers=[console, file], force=True)
    logging.getLogger("voice").setLevel(logging.DEBUG)
    return console, path


class FakeDispenser:
    """Pretend dispenser for trying the conversation without the Arduino."""

    def __init__(self, outcome: Outcome):
        self.outcome = outcome

    def dispense(self) -> Outcome:
        log.info("fake dispenser: %s", self.outcome)
        return self.outcome

    def poll(self) -> list[Presence]:
        return []  # no sensor

    def close(self) -> None:
        pass


def check_credentials(client) -> None:
    """Exit with a one-line message unless the key works and can use MODEL (free, no tokens)."""
    try:
        client.models.retrieve(MODEL)
    except TypeError:  # no credentials at all: the SDK raises this at the first request
        sys.exit("no Anthropic credentials: set ANTHROPIC_API_KEY (in .env, then run with uv run --env-file .env)")
    except anthropic.AuthenticationError:
        sys.exit("Anthropic credentials were rejected: check ANTHROPIC_API_KEY")
    except anthropic.NotFoundError:
        sys.exit(f"model {MODEL} not available to this key")
    except anthropic.APIError as e:
        sys.exit(f"Anthropic API check failed: {e}")


def make_speaker(args, device=None) -> tuple[Speaker | None, dict[str, bytes]]:
    """Hazel's voice (device: a PortAudio output index, None = the default) and her recorded
    fallback lines and greetings (voice/fallback.py), or (None, {}) with --mute. Exits with a one-line message
    if it can't work."""
    if args.mute:
        return None, {}
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("no ElevenLabs key: set ELEVENLABS_API_KEY (in .env), or run with --text --mute")
    voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or VOICE_ID
    client = ElevenLabs(timeout=TTS_TIMEOUT)
    check_voice(client, voice_id)
    lines = load_lines(elevenlabs_tts(client, voice_id), voice_id)  # recorded now, while ElevenLabs works
    import sounddevice  # here, not at the top: --mute must not need PortAudio

    try:
        player = SoundPlayer(device=device)
    except sounddevice.PortAudioError as e:
        sys.exit(f"no audio output: {e} (or run with --mute)")
    return Speaker(elevenlabs_tts(client, voice_id), player, on_error=log.warning), lines


def answer(say, write=print, after_reply=lambda: None, on_result=lambda error: None) -> None:
    """One reply from Hazel: say() streams it; a REPLY_ERRORS failure is one line; on_result gets
    the error (None for a good reply), then after_reply runs either way."""
    write("Hazel: ", end="")
    try:
        say()
    except REPLY_ERRORS as e:
        write(f"\n(Hazel can't talk right now: {e.__class__.__name__}: {e})")
        on_result(e)
    else:
        on_result(None)
    after_reply()
    write("")


def chat(brain, read=input, write=print, after_reply=lambda: None, on_result=lambda error: None) -> None:
    """Typed visitor lines in, Hazel's replies out (streamed by the brain's on_text).
    after_reply runs after every reply, error or not (the speaker finishes talking); on_result
    gets each reply's error or None."""
    write(TYPED_GREETING)
    brain.new_visit()
    while True:
        try:
            line = read("visitor> ").strip()
        except EOFError:
            break
        if line == "/quit":
            break
        if line == "/next":
            brain.new_visit()
            write("-- new visitor --")
            continue
        if not line:
            continue
        screen.info("visitor> %s", line)  # the terminal shows it already: typed
        answer(partial(brain.reply, line), write, after_reply, on_result)


def door(
    brain,
    listener,
    ears,
    dispenser,
    visits,
    after_reply=lambda: None,
    write=print,
    reopen_audio=None,
    fallback=lambda name: None,
    on_result=lambda error: None,
    status=None,
    greet=None,
    alone=lambda: False,
    keep=lambda turn, outcome: None,
) -> None:
    """Voice mode: Hazel greets each arrival (and at start-up), answers each heard line, and visits
    end by time or the sensor. Every reply is followed by after_reply (the speaker drains), then
    listener.resume(): half-duplex. A lost mic (MicError) is handed to reopen_audio, which returns
    once audio flows again or raises MicError; without it, or for SilentMic, the error ends door().
    A turn speech-to-text fails on gets fallback("ears"); on_result gets each reply's error or None.
    status (a voice/status.py Status) hears about visits, the mic and speech-to-text, and prints
    its line at least every HEARTBEAT s while nothing happens. greet says
    the greeting (default brain.greet, the model's own words). alone() is True when nobody is
    there to talk to: a failed turn then gets no "ears" line. keep(turn, outcome) sees each turn
    sent to speech-to-text (--keep-turns)."""
    status = status or Status(write=lambda line: None)
    greet = greet or brain.greet

    def speak(say, on_result=on_result) -> None:
        answer(say, write, after_reply, on_result)
        listener.resume()
        visits.replied()

    def catch_up(greet_arrival: bool = True) -> None:
        """greet_arrival=False: a heard line waits, so its answer is the greeting (no greeting,
        then an answer to words said before it)."""
        if visits.expired():  # before the sensor's events: an arrival seen now starts a new visit
            write("-- visit over --")
            status.show()
        for event in dispenser.poll():
            if event is Presence.HERE and visits.arrived():
                write("-- new visitor --")
                status.visit()
                if greet_arrival:
                    speak(greet)
                else:
                    brain.new_visit()
            elif event is Presence.GONE:
                visits.left()

    write(VOICE_GREETING)
    visits.arrived()
    speak(greet)
    status.visit()
    status.show()
    while True:
        catch_up()
        status.beat()
        try:
            turn = listener.listen(timeout=TICK)
        except EOFError:
            return
        except SilentMic:
            raise  # muted or not allowed: reopening won't help
        except MicError as e:
            if reopen_audio is None:
                raise
            write(f"({e}: reopening the audio device)")
            status.set("mic", False, str(e))
            reopen_audio()
            status.set("mic", True)
            listener.resume()  # drop what came before, and the echo tail
            continue
        if turn is None:
            continue
        visits.spoke(turn.end - turn.start)  # before catch_up: their talking and speech-to-text aren't quiet
        failed = []
        text = transcribe_turn(ears, turn, write, on_error=failed.append, keep=keep)
        status.set("ears", not failed, str(failed[0]) if failed else "")
        if failed:
            report_api_error(failed[0])
            if alone():  # no visit and nobody in front: an "Eh?" would go to an empty porch
                log.info("nobody there: no ears line")
            else:
                speak(partial(fallback, "ears"), on_result=lambda error: None)  # Claude wasn't asked
            continue
        if not text:
            continue
        catch_up(greet_arrival=False)  # a turn can take seconds: the visit may have ended, or someone new walked up
        if visits.heard():
            brain.new_visit()
            write("-- new visitor --")
            status.visit()
        speak(partial(brain.reply, text))


def stop(signum, frame) -> None:
    """SIGTERM (systemctl stop): raise KeyboardInterrupt, so the Ctrl-C cleanup runs."""
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text", action="store_true", help="type instead of talking")
    parser.add_argument("--port", help="serial port (default: the only Arduino port, /dev/cu.usbmodem* or /dev/ttyACM*)")
    parser.add_argument(
        "--fake-dispenser",
        choices=[o.value for o in Outcome],
        help="pretend dispenser for trying it without the Arduino (--port is ignored)",
    )
    parser.add_argument("--mute", action="store_true", help="text only: no ElevenLabs voice")
    parser.add_argument(
        "--device",
        default=AUDIO_DEVICE,
        help=f"mic and speaker by name (default {AUDIO_DEVICE}, the door speakerphone; {SYSTEM_DEFAULT} = the system default, e.g. on another computer)",
    )
    parser.add_argument("--debug", action="store_true", help="log every Arduino line, turn and request timing too")
    parser.add_argument(
        "--silence",
        type=positive_seconds,
        default=END_SILENCE,
        help="voice mode: seconds of quiet that end a visitor's turn",
    )
    parser.add_argument("--keep-turns", action="store_true", help="voice mode: save each turn as a WAV in tmp/turns/ (git-ignored)")
    args = parser.parse_args(argv)
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        run(args)
    except KeyboardInterrupt:
        pass  # Ctrl-C or SIGTERM during a start-up wait: the cleanup has run, no traceback
    finally:
        signal.signal(signal.SIGTERM, previous)


def run(args) -> None:
    """The program, with main()'s arguments; exits 1 after the cleanup if it can't go on."""
    console, log_path = setup_logging(args.debug, LOG_DIR)
    log.info("full log: %s", log_path)
    log.info(
        "%s mode, %s, %s",
        "typed" if args.text else "voice",
        f"fake dispenser ({args.fake_dispenser})" if args.fake_dispenser else "Arduino",
        "muted" if args.mute else "speaking",
    )

    client = anthropic.Anthropic(timeout=API_TIMEOUT)
    check_credentials(client)  # before opening the port: that resets the Uno
    mic_device = out_device = None
    if args.device != SYSTEM_DEFAULT and not (args.text and args.mute):
        try:
            mic_device, out_device = wait_for_devices(args.device)  # before any stream opens: it re-scans PortAudio
        except DeviceError as e:
            sys.exit(str(e))
    speaker, lines = make_speaker(args, device=out_device)  # also before the port
    listener = ears = dispenser = rules = None
    failed = False  # an unrecoverable error: exit 1 for the supervisor
    left_out = {"arduino": args.fake_dispenser, "mic": args.text, "ears": args.text, "voice": args.mute}
    status = Status(
        candies=lambda: rules.total_given if rules else 0,  # rules exists once the port is open
        write=logging.getLogger("voice.status").info,  # a log record: the time and level on screen too
        parts=tuple(part for part in PARTS if not left_out.get(part)),
        distance=None if args.fake_dispenser else lambda: sensor_reading(dispenser) if dispenser else "?",  # dispenser exists once the port is open
    )
    try:
        if not args.text:
            listener, ears = open_ears(args.silence, hint=" (or use --text)", device=mic_device)  # also before the port
        if args.fake_dispenser:
            dispenser = FakeDispenser(Outcome(args.fake_dispenser))
        else:
            dispenser = Reconnecting(args.port, on_change=lambda ok, detail: status.set("arduino", ok, detail))  # door() never sees a lost link
            try:
                dispenser.wait_connected(STARTUP_WAIT)
            except DispenserError as e:
                sys.exit(f"{e}\n(try --fake-dispenser candy to chat without the Arduino)")

        def fallback(name: str) -> None:
            """Say a LINES line: the recording if there is one, else live TTS."""
            console.write(LINES[name], end="")
            if speaker:
                if name in lines:
                    speaker.play(lines[name])
                else:
                    speaker.feed(f"\n{LINES[name]} ")  # the newline ends a sentence cut off by the failure

        greeted = {"last": None, "recorded": False}  # the last recorded greeting; the reply just ended was one
        last_filler = {"name": None}

        def greet() -> None:
            """A recorded greeting at random, played at once; with none recorded, the model greets."""
            name = pick_line(GREETINGS, lines, greeted["last"])
            if name is None:
                brain.greet()
                return
            console.write(GREETINGS[name], end="")
            speaker.play(lines[name])
            brain.greet(said=GREETINGS[name])
            greeted.update(last=name, recorded=True)

        def filler() -> None:
            """A recorded filler at random while Claude is slow (on Brain's timer thread); without
            recordings, nothing: live TTS would arrive no sooner than the reply."""
            name = pick_line(FILLERS, lines, last_filler["name"])
            if name is None:
                return
            console.write(FILLERS[name], end=" ")
            speaker.play(lines[name])
            last_filler["name"] = name

        def on_result(error) -> None:
            if greeted["recorded"]:  # the model wasn't asked: no news about it
                greeted["recorded"] = False
                return
            status.set("LLM", error is None, str(error))
            if error:
                report_api_error(error)
                fallback("foggy")

        def pause() -> None:
            """After each reply: Hazel finishes talking. A voice gone for good ends the run; a reply
            whose voice failed is followed by the croaky line, once."""
            if speaker:
                speaker.drain()
                if speaker.closed:
                    raise MicError("Hazel's voice is gone for good")
                voice_failed = speaker.take_reply_failed()
                status.set("voice", not voice_failed, "TTS or playback failed")
                if voice_failed:
                    console.write(" ", end="")
                    fallback("croaky")
                    speaker.drain()
                    speaker.take_reply_failed()  # a croaky line that failed too isn't followed by another

        def reopen_audio() -> None:
            if speaker:
                speaker.reset_output()  # frees a write blocked on the lost device
            if args.device != SYSTEM_DEFAULT:
                # a stream opened while the P10S is gone links to the laptop's mic and speaker, with
                # no error: close both, re-scan, and reopen only once the P10S is listed again
                if speaker:
                    speaker.player.release()
                listener.mic.close()
                try:
                    listener.mic.device, out = wait_for_devices(args.device, rescan=True)
                except DeviceError as e:
                    raise MicError(str(e)) from e
                if speaker:
                    speaker.player.move_to(out)
            reopen_mic(listener.mic)
            log.info("audio device back")

        def on_text(s: str) -> None:
            console.write(s, end="")
            if speaker:
                speaker.feed(s)

        rules = CandyRules(dispenser)
        brain = Brain(
            client,
            rules,
            on_text=on_text,
            # the spell is said while the turntable spins, not before: the candy lands about as it ends
            # (0.6-3.6 s of spinning in logs/, a spell ~3 s), not ~3 s later. Never raises or blocks
            before_tool=speaker.flush if speaker else (lambda: None),
            on_slow=filler if speaker else None,
        )
        sensor_note = SensorNote(dispenser)
        if not args.text and not args.fake_dispenser:  # the fake dispenser has no sensor
            logging.getLogger("voice.hear").addFilter(sensor_note)
        visits = Visits(rules)
        sensed = not args.text and not args.fake_dispenser  # no sensor: never alone, no distance

        def alone() -> bool:
            """No visit going and nobody in front: nobody there to talk to Hazel."""
            return sensed and not visits.active and nobody_there(dispenser)

        def keep(turn, outcome: str) -> None:
            """--keep-turns: the turn as a WAV in tmp/turns/, named with the sensor's distance."""
            if args.keep_turns:
                save_turn(turn, outcome, turn_note(dispenser) if sensed else "")

        if not args.text:
            listener.alone = alone
            listener.in_visit = lambda: visits.active
            listener.on_drop = keep_drop(log_drop, keep)
            if args.keep_turns:
                log.info("keeping turns in tmp/turns/: visitors' voices, delete them after listening")
        try:
            if args.text:
                chat(brain, after_reply=pause, write=console.write, on_result=on_result)
            else:
                door(
                    brain,
                    listener,
                    ears,
                    dispenser,
                    visits,
                    after_reply=pause,
                    write=console.write,
                    reopen_audio=reopen_audio,
                    fallback=fallback,
                    on_result=on_result,
                    status=status,
                    greet=greet,
                    alone=alone,
                    keep=keep,
                )
        except KeyboardInterrupt:
            console.write("")
        except (MicError, DispenserError) as e:  # DispenserError: a safety net; Reconnecting and CandyRules catch the link's
            console.write(f"\n({e})")
            failed = True
        finally:
            logging.getLogger("voice.hear").removeFilter(sensor_note)
    finally:
        try:
            if speaker:
                speaker.close()  # stops the audio at once; never raises, so the port still closes
            if listener is not None:
                listener.mic.close()  # never raises
            if dispenser is not None:
                dispenser.close()  # never raises: Reconnecting suppresses a gone link's error
        finally:
            if ears is not None:
                ears.close()  # last: it may wait up to CLOSE_LIMIT for transcript deletes
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
