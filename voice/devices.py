"""Audio devices by name (--device), so Hazel uses the P10S speakerphone rather than whatever
PipeWire made the default. On Linux, matching goes through PortAudio's PulseAudio host API only:
PipeWire resamples there, and its device names and indexes survive a replug (ALSA's hw:N don't)."""

import logging
import time

AUDIO_DEVICE = "P10S"  # the door speakerphone; never the laptop's own mic/speaker: the laptop is far from the witch
SYSTEM_DEFAULT = "default"  # --device value meaning "whatever PipeWire's default is" (another computer, no P10S)
AUDIO_WAIT = 60.0  # s an audio device is waited for: at start-up, and after it's lost mid-session
AUDIO_RETRY = 2.0  # s between tries while waiting
PREFERRED_HOST_API = "PulseAudio"  # PipeWire's PulseAudio server on Linux; absent on macOS
KINDS = ("input", "output")

log = logging.getLogger(__name__)


class DeviceError(Exception):
    """No audio device matches the name; the message is for the operator."""


def _searched(sd) -> list[tuple[int, dict]]:
    """(index, device) for every device in the preferred host API, or in all of them without it."""
    apis = [i for i, api in enumerate(sd.query_hostapis()) if api["name"] == PREFERRED_HOST_API]
    return [(i, d) for i, d in enumerate(sd.query_devices()) if not apis or d["hostapi"] in apis]


def find_device(name: str, kind: str, sd) -> int | None:
    """The index of the first `kind` ("input" or "output") device whose name contains `name`
    (case-insensitive), skipping PulseAudio's .monitor sources; None if there's none."""
    for i, d in _searched(sd):
        if d[f"max_{kind}_channels"] > 0 and name.lower() in d["name"].lower() and not d["name"].endswith(".monitor"):
            return i
    return None


def wait_for_devices(name: str, wait=AUDIO_WAIT, sleep=time.sleep, clock=time.monotonic, sd=None, rescan=False) -> tuple[int, int]:
    """(input index, output index) of the device named `name`, waiting up to `wait` s for it to
    appear. Between tries PortAudio is re-initialised, as it only lists the devices present at
    init: call this only while no stream is open. rescan=True re-initialises before
    the first look too: after a loss, the old list still shows the device that's gone."""
    if sd is None:
        import sounddevice as sd  # here, not at the top: --text --mute must not need PortAudio
    if rescan:
        _rescan(sd)
    deadline = clock() + wait
    first = True
    while True:
        found = {kind: find_device(name, kind, sd) for kind in KINDS}
        if None not in found.values():
            return found["input"], found["output"]
        if clock() >= deadline:
            missing = next(kind for kind in KINDS if found[kind] is None)
            seen = ", ".join(d["name"] for _, d in _searched(sd))
            raise DeviceError(f"no audio {missing} matching {name!r} after {wait:g} s; saw: {seen}")
        if first:
            log.warning("waiting up to %g s for the audio device %r", wait, name)
            first = False
        sleep(AUDIO_RETRY)
        _rescan(sd)


def _rescan(sd) -> None:
    try:
        sd._terminate()  # private in sounddevice 0.5.6, but the only way to re-scan
        sd._initialize()
    except sd.PortAudioError as e:  # e.g. PipeWire restarting
        raise DeviceError(f"PortAudio couldn't re-scan the audio devices: {e}") from e
