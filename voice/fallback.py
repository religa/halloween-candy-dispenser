"""What Hazel says when an API fails, and her greetings: short lines recorded once in her voice
and kept on disk, so they play even when ElevenLabs is the thing that's down, and a visitor is
greeted at once instead of after a model reply, and a slow reply starts with a filler. Also which API failures mean the account needs
the operator (credit, limits), so they're logged loudly."""

import hashlib
import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path

import anthropic
from elevenlabs.core.api_error import ApiError
from voice.speak import MODEL_ID, OUTPUT_FORMAT

LINES = {  # name -> text; said in character, never mentions computers
    "foggy": "Heh heh, my crystal ball has gone all foggy! Give old Hazel a moment, dearie, then say it again.",  # Claude failed
    "ears": "Eh? My old ears missed that, dearie. Say it once more?",  # speech-to-text failed
    "croaky": "Ahem! My voice went all croaky there. Say that again, dearie?",  # TTS failed during a reply
}
GREETINGS = {  # name -> text; one is picked at random for each arrival (voice/main.py), like persona.md's arrival line
    "greeting-1": "Heh heh heh, well hello there, dearie! Do you know the magic words that make my cauldron share its candy?",
    "greeting-2": "Ooh, a visitor on Halloween night! Say the magic words, and maybe my cauldron will bubble up a treat.",
    "greeting-3": "Welcome, welcome to old Hazel's porch! My candy only comes out for the magic words, you know.",
    "greeting-4": "Well now, what a marvelous costume! Heh heh, do you know what to say to a witch on Halloween?",
    "greeting-5": "Who goes there? Heh heh, a brave little visitor! Say the magic words, dearie, and see what my cauldron does.",
    "greeting-6": "Ah, good evening, my little friend! My cauldron is full of candy, but it only listens to the magic words.",
    "greeting-7": "Heh heh, step right up, dearie! Old Hazel has candy for anyone who knows the magic words.",
    "greeting-8": "Oh my, my crystal ball said you'd be coming! Now, say the magic words, and a treat may tumble down.",
    "greeting-9": "Happy Halloween, dearie! My cauldron is bubbling and ready, if you know the magic words.",
    "greeting-10": "Heh heh heh, hello, hello! A witch's candy needs the magic words. Can you guess them?",
}
FILLERS = {  # name -> text; one at random while Claude is slow to answer (voice/brain.py FILLER_AFTER), before any reply
    "filler-1": "Hmmm, let me see...",
    "filler-2": "Ooh, now then...",
    "filler-3": "Well, well, well...",
    "filler-4": "Now, let old Hazel think...",
}
CACHE_DIR = Path(__file__).resolve().parent.parent / "cache" / "voice"  # git-ignored

log = logging.getLogger(__name__)


def cache_path(cache_dir: Path, name: str, text: str, voice_id: str) -> Path:
    """Where a line's audio is kept: the hash changes with anything that changes the sound."""
    digest = hashlib.sha256(f"{voice_id}|{MODEL_ID}|{OUTPUT_FORMAT}|{text}".encode()).hexdigest()[:12]
    return cache_dir / f"{name}-{digest}.pcm"


def load_lines(
    tts: Callable[[str], Iterable[bytes]],
    voice_id: str,
    cache_dir: Path = CACHE_DIR,
    on_error: Callable[[str], None] = log.warning,
    texts: dict[str, str] | None = None,
) -> dict[str, bytes]:
    """name -> raw PCM (int16) for each texts entry (default: LINES, GREETINGS and FILLERS): from the cache,
    else recorded with tts and cached. A line that can't be had is skipped with one on_error line."""
    lines = {}
    for name, text in (LINES | GREETINGS | FILLERS if texts is None else texts).items():
        path = cache_path(cache_dir, name, text, voice_id)
        try:
            if not path.exists():
                pcm = b"".join(tts(text))
                if not pcm:
                    raise ValueError("no audio")
                cache_dir.mkdir(parents=True, exist_ok=True)
                partial = path.with_name(path.name + ".partial")
                partial.write_bytes(pcm)
                os.replace(partial, path)  # atomic: a crash never leaves half a line
            pcm = path.read_bytes()
            lines[name] = pcm[: len(pcm) - len(pcm) % 2]  # whole int16 samples
        except Exception as e:
            on_error(f"(no recorded {name!r} line, it will be spoken live: {e.__class__.__name__}: {e})")
    return lines


def billing_problem(e: BaseException) -> str | None:
    """What kind of account trouble e is, or None for a passing failure (overload, network).
    Typed fields only, never message text. The keys passed the start-up checks, so a
    later auth-type failure means the account, not a typo."""
    if isinstance(e, anthropic.APIStatusError):
        error = e.body.get("error") if isinstance(e.body, dict) else None
        if (isinstance(error, dict) and error.get("type") == "billing_error") or e.status_code == 402:
            return "Anthropic billing"
        if isinstance(e, anthropic.RateLimitError):
            return "Anthropic rate limit"
        if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return "Anthropic account"
    elif isinstance(e, ApiError):
        if e.status_code in (401, 402):
            detail = e.body.get("detail") if isinstance(e.body, dict) else None
            status = detail.get("status") if isinstance(detail, dict) else None
            return "ElevenLabs account (quota or key)" + (f": {status}" if status else "")
        if e.status_code == 429:
            return "ElevenLabs rate limit"
    return None


def report_api_error(e: BaseException) -> None:
    """Log account trouble loudly; a passing failure is already one terminal line."""
    if kind := billing_problem(e):
        log.error("API PROBLEM (%s): %s. Check the account's credit and limits.", kind, e)
