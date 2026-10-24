"""Hazel's fallback lines and the API-error classifier, offline: a counting fake TTS, files in
tmp_path, provider errors built like the SDKs build them."""

import shutil
import subprocess
from pathlib import Path

import anthropic
import httpx
import httpx2
import pytest
import voice.fallback
from elevenlabs.core.api_error import ApiError
from voice.fallback import FILLERS, GREETINGS, LINES, billing_problem, cache_path, load_lines, report_api_error

ROOT = Path(__file__).resolve().parents[1]
MESSAGES_URL = "https://api.anthropic.com/v1/messages"


class CountingTTS:
    """tts stand-in: yields each text's bytes in two chunks (odd-length unless told otherwise),
    counting calls; raises `error` for the text containing `fail_on`, after the first chunk."""

    def __init__(self, fail_on=None, error=None, odd=False):
        self.calls = []
        self.fail_on = fail_on
        self.error = error
        self.odd = odd

    def __call__(self, text):
        self.calls.append(text)
        yield b"\x01\x02"
        if self.fail_on and self.fail_on in text:
            raise self.error
        yield b"\x03\x04\x05" if self.odd else b"\x03\x04"


def test_load_lines_caches_on_first_run_and_reuses_it(tmp_path):
    tts = CountingTTS()
    lines = load_lines(tts, "voice1", cache_dir=tmp_path)
    assert set(lines) == set(LINES) | set(GREETINGS) | set(FILLERS) and all(pcm == b"\x01\x02\x03\x04" for pcm in lines.values())
    assert len(tts.calls) == len(lines)
    assert len(list(tmp_path.glob("*.pcm"))) == len(lines)
    again = CountingTTS()
    assert load_lines(again, "voice1", cache_dir=tmp_path) == lines
    assert again.calls == []


def test_load_lines_regenerates_when_the_text_or_voice_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(voice.fallback, "GREETINGS", {})
    monkeypatch.setattr(voice.fallback, "FILLERS", {})
    monkeypatch.setattr(voice.fallback, "LINES", {"foggy": "Heh heh!"})
    load_lines(CountingTTS(), "voice1", cache_dir=tmp_path)
    tts = CountingTTS()
    load_lines(tts, "voice2", cache_dir=tmp_path)
    assert tts.calls == ["Heh heh!"]
    monkeypatch.setattr(voice.fallback, "LINES", {"foggy": "Heh heh heh!"})
    tts = CountingTTS()
    load_lines(tts, "voice2", cache_dir=tmp_path)
    assert tts.calls == ["Heh heh heh!"]
    assert len(list(tmp_path.glob("foggy-*.pcm"))) == 3
    assert cache_path(tmp_path, "foggy", "a", "v1") != cache_path(tmp_path, "foggy", "a", "v2")


def test_load_lines_skips_a_failing_line_with_one_warning(tmp_path):
    errors = []
    tts = CountingTTS(fail_on="gone all foggy", error=httpx.ConnectError("no network"))
    lines = load_lines(tts, "voice1", cache_dir=tmp_path, on_error=errors.append)
    assert set(lines) == (set(LINES) | set(GREETINGS) | set(FILLERS)) - {"foggy"}
    assert len(errors) == 1 and "foggy" in errors[0] and "ConnectError" in errors[0]


def test_ten_greetings_in_hazels_voice():
    assert len(GREETINGS) == 10  # the user's number, written out
    for text in GREETINGS.values():
        assert "magic words" in text or "what to say" in text, text  # persona.md: invite the magic words
        assert "[" not in text and "trick or treat" not in text.lower(), text  # the visitor says those, not Hazel
        assert len(text) < 120, text  # one short line, like a model greeting


def test_load_lines_records_only_the_texts_given(tmp_path):
    tts = CountingTTS()
    assert set(load_lines(tts, "voice1", cache_dir=tmp_path, texts={"greeting-1": "Hello!"})) == {"greeting-1"}
    assert tts.calls == ["Hello!"]


def test_cache_writes_are_atomic(tmp_path):
    tts = CountingTTS(fail_on="crystal ball", error=httpx.ReadError("dropped mid-stream"))
    load_lines(tts, "voice1", cache_dir=tmp_path, on_error=lambda line: None)
    assert not list(tmp_path.glob("foggy-*"))  # no half-written file left to be taken as the line


def test_odd_length_audio_is_trimmed(tmp_path):
    lines = load_lines(CountingTTS(odd=True), "voice1", cache_dir=tmp_path)
    assert all(len(pcm) % 2 == 0 for pcm in lines.values())
    path = cache_path(tmp_path, "ears", LINES["ears"], "voice1")
    path.write_bytes(b"\x01\x02\x03")  # a damaged cache file
    assert load_lines(CountingTTS(), "voice1", cache_dir=tmp_path)["ears"] == b"\x01\x02"


def anthropic_error(cls, status, body=None):
    response = httpx2.Response(status, request=httpx2.Request("POST", MESSAGES_URL))
    return cls(message="x", response=response, body=body)


BILLING_BODY = {"type": "error", "error": {"type": "billing_error", "message": "Your credit balance is too low"}}


@pytest.mark.parametrize(
    "error, kind",
    [
        (anthropic_error(anthropic.APIStatusError, 400, BILLING_BODY), "Anthropic billing"),
        (anthropic_error(anthropic.APIStatusError, 402, BILLING_BODY), "Anthropic billing"),
        (anthropic_error(anthropic.APIStatusError, 402), "Anthropic billing"),
        (anthropic_error(anthropic.RateLimitError, 429), "Anthropic rate limit"),
        (anthropic_error(anthropic.AuthenticationError, 401), "Anthropic account"),
        (anthropic_error(anthropic.PermissionDeniedError, 403), "Anthropic account"),
        (anthropic_error(anthropic.InternalServerError, 529, {"type": "error", "error": {"type": "overloaded_error"}}), None),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", MESSAGES_URL)), None),
        (httpx2.ReadError("connection reset"), None),
        (ApiError(status_code=401, body={"detail": {"status": "quota_exceeded"}}), "ElevenLabs account (quota or key): quota_exceeded"),
        (ApiError(status_code=401, body=None), "ElevenLabs account (quota or key)"),
        (ApiError(status_code=402, body="x"), "ElevenLabs account (quota or key)"),
        (ApiError(status_code=429), "ElevenLabs rate limit"),
        (ApiError(status_code=500), None),
        (httpx.ReadError("dropped"), None),
    ],
)
def test_billing_problem_classifies_provider_errors(error, kind):
    assert billing_problem(error) == kind


def test_report_api_error_is_loud_only_for_account_trouble(caplog):
    caplog.set_level("WARNING", logger="voice.fallback")
    report_api_error(anthropic_error(anthropic.APIStatusError, 400, BILLING_BODY))
    report_api_error(ApiError(status_code=500))
    assert [(r.levelname, r.getMessage().split(":")[0]) for r in caplog.records] == [("ERROR", "API PROBLEM (Anthropic billing)")]
    assert "credit" in caplog.records[0].getMessage()


def test_cache_dir_is_git_ignored():
    if shutil.which("git") is None:
        pytest.skip("needs git")
    path = voice.fallback.CACHE_DIR.relative_to(ROOT) / "x.pcm"
    ignored = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=ROOT, check=False)
    assert ignored.returncode == 0  # generated audio never lands in the public repo
