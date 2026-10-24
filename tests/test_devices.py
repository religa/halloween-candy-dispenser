"""Audio devices by name, offline: a fake sounddevice built from the device list PortAudio showed
on the Linux laptop with the P10S plugged in."""

import pytest
from test_rules import FakeClock
from voice.devices import AUDIO_RETRY, DeviceError, find_device, wait_for_devices

ALSA, PULSE = 0, 2
P10S_OUT = "alsa_output.usb-MV-SILICON_P10S_202403221-00.analog-stereo"
P10S_IN = "alsa_input.usb-MV-SILICON_P10S_202403221-00.analog-stereo"
LAPTOP = [  # (host API, name, inputs, outputs)
    (ALSA, "HDA Intel PCH: ALC274 Analog (hw:0,0)", 2, 2),
    (PULSE, "Default Sink", 0, 32),
    (PULSE, "Default Source", 32, 0),
    (PULSE, "alsa_output.pci-0000_00_1f.3.analog-stereo", 0, 2),
    (PULSE, "alsa_input.pci-0000_00_1f.3.analog-stereo", 2, 0),
]
P10S = [
    (ALSA, "P10S: USB Audio (hw:1,0)", 2, 2),
    (PULSE, P10S_OUT, 0, 2),
    (PULSE, P10S_OUT + ".monitor", 2, 0),
    (PULSE, P10S_IN, 2, 0),
]


class FakeSoundDevice:
    """sounddevice stand-in: query_devices() lists `devices`; after each _terminate/_initialize the
    next of `later` (a new device list) takes its place, as PortAudio only lists devices present at
    init."""

    def __init__(self, devices, later=(), apis=("ALSA", "OSS", "PulseAudio")):
        self.devices = devices
        self.later = list(later)
        self.apis = apis
        self.rescans = 0

    def query_hostapis(self):
        return [{"name": name} for name in self.apis]

    def query_devices(self):
        return [{"hostapi": api, "name": name, "max_input_channels": i, "max_output_channels": o} for api, name, i, o in self.devices]

    def _terminate(self):
        self.rescans += 1

    class PortAudioError(Exception):
        pass

    def _initialize(self):
        if self.later == ["fail"]:
            raise self.PortAudioError("PaErrorCode -9999")
        if self.later:
            self.devices = self.later.pop(0)


def index(devices, name):
    return [d[1] for d in devices].index(name)


def test_find_device_uses_pulseaudio_and_skips_monitors():
    devices = LAPTOP + P10S
    sd = FakeSoundDevice(devices)
    assert find_device("P10S", "input", sd) == index(devices, P10S_IN)
    assert find_device("p10s", "output", sd) == index(devices, P10S_OUT)  # case-insensitive
    assert find_device("hw:1,0", "input", sd) is None  # ALSA's entry: its index moves on a replug


def test_find_device_searches_every_host_api_without_pulseaudio():
    devices = [(0, "MacBook Pro Microphone", 1, 0), (0, "P10S", 1, 1)]
    sd = FakeSoundDevice(devices, apis=("Core Audio",))
    assert find_device("P10S", "input", sd) == 1
    assert find_device("P10S", "output", sd) == 1
    assert find_device("MacBook", "output", sd) is None  # no output channels


def test_only_a_monitor_is_no_input():
    sd = FakeSoundDevice(LAPTOP + [(PULSE, P10S_OUT, 0, 2), (PULSE, P10S_OUT + ".monitor", 2, 0)])
    assert find_device("P10S", "input", sd) is None


def test_wait_for_devices_finds_a_present_device_without_rescanning():
    devices = LAPTOP + P10S
    sd = FakeSoundDevice(devices)
    assert wait_for_devices("P10S", sd=sd) == (index(devices, P10S_IN), index(devices, P10S_OUT))
    assert sd.rescans == 0


def test_wait_for_devices_rescans_until_the_device_appears():
    clock = FakeClock()
    sd = FakeSoundDevice(LAPTOP, later=[LAPTOP + P10S])
    assert wait_for_devices("P10S", sleep=clock.sleep, clock=clock, sd=sd) == (index(LAPTOP + P10S, P10S_IN), index(LAPTOP + P10S, P10S_OUT))
    assert sd.rescans == 1
    assert clock.slept == [AUDIO_RETRY]


def test_wait_for_devices_gives_up_and_names_what_it_saw():
    clock = FakeClock()
    sd = FakeSoundDevice(LAPTOP)
    with pytest.raises(DeviceError) as error:
        wait_for_devices("P10S", wait=60, sleep=clock.sleep, clock=clock, sd=sd)
    message = str(error.value)
    assert "no audio input matching 'P10S' after 60 s" in message
    assert "alsa_input.pci-0000_00_1f.3.analog-stereo" in message
    assert "ALC274" not in message  # ALSA's names aren't searched, so they aren't listed
    assert clock.now >= 60


def test_a_failed_rescan_is_a_device_error():
    clock = FakeClock()
    sd = FakeSoundDevice(LAPTOP, later=["fail"])
    with pytest.raises(DeviceError, match="couldn't re-scan.*-9999"):
        wait_for_devices("P10S", sleep=clock.sleep, clock=clock, sd=sd)


def test_rescan_first_drops_a_device_that_is_gone():
    """After a loss PortAudio's old list still shows the P10S; without a re-scan a
    reopen would use it and land on the laptop's mic."""
    clock = FakeClock()
    devices = LAPTOP + P10S
    sd = FakeSoundDevice(devices, later=[LAPTOP, devices])  # gone at the first re-scan, back at the next
    assert wait_for_devices("P10S", sleep=clock.sleep, clock=clock, sd=sd, rescan=True) == (index(devices, P10S_IN), index(devices, P10S_OUT))
    assert sd.rescans == 2
    assert clock.slept == [AUDIO_RETRY]
