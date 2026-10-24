"""Make the speech-to-text fixtures in tests/fixtures/voice/: 16 kHz mono 16-bit WAVs.

Speech comes from ElevenLabs premade voices and macOS `say` kid-like voices (Junior, Bubbles),
some mixed with pink noise at 5 dB SNR (over the padded clip, as in the spikes); the rest is
silence and noise with no speech. Real child voices can't be synthesised (ElevenLabs refuses
child Voice Design), so these are stand-ins.

Usage:
    uv run --env-file .env tools/make_voice_fixtures.py

Needs ELEVENLABS_API_KEY and macOS `say`, and spends about 200 TTS characters. The audio differs
on every run, so re-run the live tests afterwards: uv run --env-file .env pytest tests/test_hear.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # voice isn't an installed package

from elevenlabs.client import ElevenLabs
from voice.hear import STT_SAMPLE_RATE

OUT = Path(__file__).resolve().parent.parent / "tests/fixtures/voice"
TTS_MODEL_ID = "eleven_flash_v2_5"  # fixed for provenance: changing Hazel's voice model doesn't remake these
PAD = 0.5  # s of silence before and after speech
SNR = 5.0  # dB over pink noise, measured on the padded clip (about 8 dB over the speech alone)
TRICK_OR_TREAT = "Trick or treat!"
VAMPIRE = "I'm a vampire."

# name -> (source, voice, text); source is "elevenlabs" (premade voice ID) or "say" (macOS voice)
SPEECH = {
    "trick_or_treat-adult": ("elevenlabs", "cgSgspJ2msm6clMCkdW9", TRICK_OR_TREAT),  # Jessica
    "trick_or_treat-kid": ("say", "Junior", TRICK_OR_TREAT),
    "trick_or_treat-kid_noisy": ("say", "Junior", TRICK_OR_TREAT),
    "trick_or_treat-kid2_noisy": ("say", "Bubbles", TRICK_OR_TREAT),  # heard only with the keyterm
    "rhyme-kid": ("say", "Bubbles", "Trick or treat, smell my feet, give me something good to eat!"),
    "vampire-adult": ("elevenlabs", "TX3LPaxmHKxFdv7VOQHJ", VAMPIRE),  # Liam
    "vampire-kid_noisy": ("say", "Junior", VAMPIRE),
    "costume-adult": ("elevenlabs", "FGY2WhTYpPnrIDTdsKH5", "I'm a princess and my brother is a dinosaur."),  # Laura
}


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)))


def pink(rng, n: int) -> np.ndarray:
    """White noise with each FFT bin divided by sqrt(index + 1), normalised to peak 1."""
    f = np.fft.rfft(rng.standard_normal(n))
    f /= np.sqrt(np.arange(1, len(f) + 1))
    x = np.fft.irfft(f, n)
    return x / np.abs(x).max()


def brown(rng, n: int) -> np.ndarray:
    """Integrated white noise minus its 2000-sample moving average (no DC drift), normalised."""
    x = np.cumsum(rng.standard_normal(n))
    x -= np.convolve(x, np.ones(2000) / 2000, "same")
    return x / np.abs(x).max()


def quiet() -> dict[str, np.ndarray]:
    """No-speech clips, each from its own seeded generator so none depends on another."""
    n = 3 * STT_SAMPLE_RATE
    t = np.arange(n) / STT_SAMPLE_RATE

    def rng():
        return np.random.default_rng(1)

    clicks_rng = rng()
    clicks = np.zeros(n)
    clicks[clicks_rng.integers(0, n, 12)] = 0.9
    wind_rng = rng()
    return {
        "silence-room": rng().standard_normal(n) * 10 ** (-55 / 20),  # about -55 dBFS RMS
        "noise-pink": pink(rng(), n) * 0.3,
        "noise-wind": brown(wind_rng, 4 * STT_SAMPLE_RATE) * 0.8 + pink(wind_rng, 4 * STT_SAMPLE_RATE) * 0.05,
        "noise-hum": 0.2 * np.sin(2 * np.pi * 60 * t) + 0.05 * np.sin(2 * np.pi * 120 * t) + rng().standard_normal(n) * 0.01,
        "noise-clicks": clicks + clicks_rng.standard_normal(n) * 0.003,
    }


def from_int16(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, np.int16) / 32768


def elevenlabs_speech(client, voice_id: str, text: str) -> np.ndarray:
    chunks = client.text_to_speech.convert(voice_id, text=text, model_id=TTS_MODEL_ID, output_format=f"pcm_{STT_SAMPLE_RATE}")
    return from_int16(b"".join(chunks))


def say_speech(voice: str, text: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "say.wav"
        subprocess.run(
            ["say", "-v", voice, "--file-format=WAVE", f"--data-format=LEI16@{STT_SAMPLE_RATE}", "-o", str(path), text],
            check=True,
        )
        with wave.open(str(path), "rb") as w:
            return from_int16(w.readframes(w.getnframes()))


def save(name: str, x: np.ndarray) -> None:
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(STT_SAMPLE_RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def main() -> None:
    if not os.environ.get("ELEVENLABS_API_KEY"):
        sys.exit("no ElevenLabs key: set ELEVENLABS_API_KEY (in .env, then run with uv run --env-file .env)")
    if not shutil.which("say"):
        sys.exit("no `say` command: the kid-like voices need macOS")
    OUT.mkdir(parents=True, exist_ok=True)
    client = ElevenLabs()
    silence = np.zeros(int(PAD * STT_SAMPLE_RATE))
    for name, (source, voice, text) in SPEECH.items():
        x = elevenlabs_speech(client, voice, text) if source == "elevenlabs" else say_speech(voice, text)
        x = np.concatenate([silence, x, silence])
        if name.endswith("_noisy"):
            noise = pink(np.random.default_rng(1), len(x))
            x = x + noise * rms(x) / rms(noise) / 10 ** (SNR / 20)
        save(name, x)
        print(f"{name}.wav  {len(x) / STT_SAMPLE_RATE:.1f} s  {text!r}")
    for name, x in quiet().items():
        save(name, x)
        print(f"{name}.wav  {len(x) / STT_SAMPLE_RATE:.1f} s  (no speech)")


if __name__ == "__main__":
    main()
