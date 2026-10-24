<div align="center">

# 🎃 Hazel: a Talking AI Halloween Candy Dispenser (3D-printed, Arduino)

**A talking, AI-powered Halloween candy dispenser you can 3D print.**
Kids say "trick or treat", the witch answers in her own voice, and a candy drops down her sleeve.

[![tests](https://github.com/religa/halloween-candy-dispenser/actions/workflows/tests.yml/badge.svg)](https://github.com/religa/halloween-candy-dispenser/actions/workflows/tests.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![YouTube](https://img.shields.io/badge/YouTube-watch_Hazel-FF0000?logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=f7yGwlmqU8s)
[![GitHub stars](https://img.shields.io/github/stars/religa/halloween-candy-dispenser?style=social)](https://github.com/religa/halloween-candy-dispenser/stargazers)

https://github.com/user-attachments/assets/e6556676-e8ea-44c1-a313-09fb70a67dca

▶️ On YouTube: [Hazel the Candy Witch: a Talking Halloween Candy Dispenser (LLM + Arduino)](https://www.youtube.com/watch?v=f7yGwlmqU8s)
· [Build a Talking Candy Witch: 3D-Printed Halloween Candy Dispenser (Arduino + LLM)](https://www.youtube.com/watch?v=n9rjkIQ5XzI)

**[⬇️ Download STLs](https://github.com/religa/halloween-candy-dispenser/releases/latest/download/halloween-candy-dispenser-parts.zip)** · **[Build guide](docs/build-guide.md)** · [How it works](#how-it-works) · [Parts](#parts) ·
[Wiring](docs/wiring.md) · [Voice program](docs/voice.md) · [FAQ](#faq)

</div>

## What it is

An automatic Halloween candy dispenser in a 5-gallon bucket, with a 6 ft witch prop that talks
to trick-or-treaters. Everything printed fits the **Bambu Lab A1 mini** (180 × 180 mm plate), so
it prints on almost any 3D printer.

- **Talking witch:** Hazel listens through a USB speakerphone, answers in character with
  Claude, and speaks with an ElevenLabs voice. A sonar sees each visitor walk up, so she
  greets them first.
- **Candy on cue:** say "trick or treat" and she asks the dispenser for candy. Code, not
  the model, enforces the limits: one candy per kid, three per group, and a cooldown.
- **Reliable dispensing:** a NEMA 23 stepper turns a slotted turntable until a candy cuts an
  IR break beam on the chute, then backs off. The candy slides down a drain pipe hidden in
  the witch's sleeve into her cauldron.
- **Parametric, tested CAD:** every printed part is a Python script
  ([build123d](https://build123d.readthedocs.io)) that exports STL and STEP, with geometry
  tests on every part ([trimesh](https://trimesh.org)). Change a hardware size in one file
  and the mating parts follow.
- **Runs all evening:** a `systemd` service with reconnects, a watchdog, in-character
  fallback lines when the network drops, and a status line in the log.

Based on Brankly's
[Automatic Halloween Candy Dispenser](https://brankly.com/automatic-halloween-candy-dispenser/);
full credit to [Brankly](https://brankly.com/) for the original idea and design. This
version:
- is remodelled from scratch as parametric Python, with tests;
- fits a ~4 in (95 mm) lazy susan bearing, with a new gear pair (66/14) and a compact stand;
- splits the turntable into quarters to fit the small plate, and replaces the 270 mm middle
  wall with a cut 2×4;
- adds a new chute into a drain pipe, cases for the electronics, and an RJ45 link between
  them;
- adds Hazel, the talking witch (`voice/`).

## How it works

A sonar on the witch sees a visitor walk up, and the program on the computer has Hazel greet
them. She listens through a USB speakerphone: ElevenLabs turns the speech into text, Claude
answers in character, and ElevenLabs speaks the reply in her voice. When a kid says "trick or
treat", Claude asks for candy and the code checks the limits before sending a `d` over USB to
the Arduino Uno. The Uno drives a NEMA 23 stepper through a TB6600, turning a slotted
turntable in the bucket until a candy falls onto the chute and cuts an IR beam. The candy
slides down a drain pipe in the witch's sleeve into her cauldron.

The computer, the Arduino and the 24 V supply stay indoors; the bucket, the witch and the
speakerphone are outside, joined by an Ethernet cable, a 110 V power cord carrying the 24 V,
and the speakerphone's USB. The [demo video](https://www.youtube.com/watch?v=f7yGwlmqU8s) shows it at work and the
[build video](https://www.youtube.com/watch?v=n9rjkIQ5XzI) shows each part; the details are in [wiring](docs/wiring.md) and the
[voice program](docs/voice.md).

## Build your own

**[docs/build-guide.md](docs/build-guide.md)** goes step by step from the parts list
(bucket, bearing, motor and driver, Arduino, sensors, witch prop, 2×4) to the first
dispense and a full evening on the porch. Prefer to watch first? The
[build video](https://www.youtube.com/watch?v=n9rjkIQ5XzI) walks through the same steps.

## Parts

Every part as STL, 3MF and STEP, ready to slice: **[⬇️ halloween-candy-dispenser-parts.zip](https://github.com/religa/halloween-candy-dispenser/releases/latest/download/halloween-candy-dispenser-parts.zip)**
(from the [latest release](https://github.com/religa/halloween-candy-dispenser/releases/latest)). Or build
them yourself from `parts/`, as in [Quick start](#quick-start).

| Part | Print | Notes |
|---|---|---|
| `bearing_fit_check` | 1×, **first** | ~8 g. All 4 bearing screws must drop through |
| `turntable_quarter` | 4× | Four make the 260 mm turntable with 8 candy pockets |
| `turntable_connector` | 4× | One under each seam, 2 × M5. Same shape as Brankly's (checked against `ref/` to 0.03 %) |
| `turntable_gear` (+ `_test`) | 1× | 66 teeth, Ø136, module 2. Bolts under the quarters onto the bearing |
| `motor_gear` | 1× | 14-tooth pinion for the 23HS5628's D-shaft; M3 set screw + nut |
| `stand` (+ `_test`) | 1× | 163 × 104 × 75. Bearing on top, motor underneath in ±1 mm slots to set the mesh |
| `chute_frame` | 1× | 4 × 4 in window on the outside of the bucket |
| `chute_ramp` (+ `_test`) | 1× | 45° channel with the IR break beam across it |
| `chute_spigot` | 1× | Funnel into a 4 in FLEX-Drain pipe |
| `electronics_case` (+ `_test`) | 1× | Open tray for the Uno and an RJ45 screw-terminal adapter |
| `driver_case` (+ `_test`) | 1× | Open tray for the TB6600, an RJ45 screw-terminal adapter and a C14 inlet |

The gears (66/14, 4.71:1, 80 mm apart) are slower than the original 4:1. The `_test`
variants are thin fit-check prints from the same scripts (`build(test=True)`).

## Electronics

Arduino Uno, a TB6600 stepper driver on 24 V, a 23HS5628 NEMA 23 motor, an IR break-beam
pair across the chute ramp, and an HC-SR04 sonar that tells the voice program when someone walks up.
Firmware: `arduino/main.ino`. A `d` over USB turns the turntable until a candy cuts the beam (at
most 15 s), then it reverses for 1 s. The Uno case and the bucket are linked by one Ethernet
cable between two RJ45 screw-terminal adapters, plus a 110 V power cord carrying the 24 V. Full
wiring, driver settings and a step-by-step first power-up: [docs/wiring.md](docs/wiring.md).

To dispense from the computer: `uv run tools/dispense.py` (sends `d` over USB; `--count 3` for three in a row). Typing `d` in the Arduino Serial Monitor
(115200 baud) does the same.

## Quick start

Needs [uv](https://docs.astral.sh/uv/): `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux or macOS,
or `brew install uv`. Tested on Linux and macOS; not on Windows.

```sh
uv sync                                  # Python 3.13 + locked packages into .venv/
uv run pytest                            # geometry and program tests (~1 min)
make verify                              # lint + tests + compile the firmware; `make help` for the rest
uv run parts/stand.py                    # build one part -> out/stand.stl + out/stand.step
uv run tools/inspect_stl.py out          # size, watertight, PLA grams for each built part
uv run tools/render.py out/stand.stl -o stand.png   # iso/front/top/side preview
```

The original design lives in `ref/automatic-candy-dispenser/` (git-ignored, not part of
this repo). Clone it for the one part we print unchanged (the middle wall director) and for
the tests that check our parts against it; they skip without it:

```sh
git clone https://github.com/branklyvideo/automatic-candy-dispenser ref/automatic-candy-dispenser
```

## Status

**Printed and checked against the real hardware:** every part; the assembled dispenser works.
- `bearing_fit_check`: OK, with the holes on an 82 mm square
- `motor_gear`, `turntable_gear_test`, `stand_test`, `stand`, `turntable_gear`,
  4 × `turntable_quarter`, 4 × `turntable_connector`: OK
- chute: `chute_ramp_test`, `chute_frame`, `chute_ramp`, `chute_spigot`: OK; the
  estimated bucket wall, taper, drain pipe and beam sensor sizes all fit
- `electronics_case_test`, `electronics_case`, `driver_case_test`, `driver_case`: OK

**Measured** (all in `parts/hardware.py`):
- bearing: 8.5 mm thick, 6–7 mm plate gap
- bucket: 262 mm inside at turntable height
- motor: shaft 28 mm past the flange (the datasheet's 20.6 was wrong, hence the stand's 5 mm riser pad), flange 5 mm, D-flat 5.8 mm
- RJ45 adapter and TB6600 outlines

**Still open:**
- Middle wall lid: Brankly's is 260 mm, too big for the A1 mini, and needs its own design for the 2×4 wall ([docs/middle-wall.md](docs/middle-wall.md)).
- Voice program: built, including the evening's resilience (Arduino reconnect and watchdog, P10S replug, fallback lines, status line, `make service`); the manual checks with real hardware, spending caps, cost per visit and the one-hour soak test are open: [docs/voice.md](docs/voice.md#manual-checks-still-open).

## Layout

| Path | What |
|---|---|
| `parts/` | One build123d script per printed part. Helpers: `common.py` (tolerances, `export()`), `hardware.py` (dimensions of the purchased parts), `gearing.py` (involute gears) |
| `tests/` | pytest tests: each part's STL mesh, the assembly's clearances, and the voice program (with fakes, offline) |
| `tools/` | `inspect_stl.py`, `render.py`, `compare.py` (diff against a ref part), `dispense.py` (dispense over USB), `package_parts.py` (the release zip) |
| `arduino/` | Firmware for the Uno: `main.ino` |
| `voice/` | The talking-witch program; `persona.md` is Hazel's prompt |
| `docs/` | [Build guide](docs/build-guide.md), [wiring](docs/wiring.md), [middle wall](docs/middle-wall.md), [voice design](docs/voice.md) |
| `out/` | Generated `.stl` / `.step` files. Git-ignored; rebuild from `parts/` |

## Writing a part

Follow the conventions in [CLAUDE.md](CLAUDE.md): dimensions as constants at the top, a
`build()` function, and an export when run as a script.

```python
# parts/distance_ring.py
from build123d import Align, BuildPart, Cylinder, Mode, Part
from common import export

OUTER_RADIUS = 58.5  # matches ref distance ring.stl (117 mm across)
INNER_RADIUS = 50.0  # example value; measure the ref part before relying on it
THICKNESS = 1.8  # matches ref distance ring.stl
ON_BED = (Align.CENTER, Align.CENTER, Align.MIN)  # bottom face at z = 0 (CLAUDE.md)


def build() -> Part:
    with BuildPart() as ring:
        Cylinder(radius=OUTER_RADIUS, height=THICKNESS, align=ON_BED)
        Cylinder(radius=INNER_RADIUS, height=THICKNESS, align=ON_BED, mode=Mode.SUBTRACT)
    return ring.part


if __name__ == "__main__":
    export(build(), "distance_ring")  # writes out/distance_ring.stl and .step
```

Build it with `uv run parts/distance_ring.py`, then add `tests/test_distance_ring.py`.
`tests/test_all_parts.py` picks up every part script automatically.

## FAQ

**Does it need a Bambu Lab printer?** No. The parts are sized for the A1 mini's 180 mm
plate, so any printer with a bed that size or larger works. They print in PLA.

**What accounts does the talking witch need?** An [Anthropic API key](https://console.anthropic.com/)
(Claude) and an [ElevenLabs](https://elevenlabs.io/) key (speech-to-text and her voice), in a
git-ignored `.env`. Set spending caps on both.

**Can I run the dispenser without the witch?** For testing, yes: `uv run tools/dispense.py`
drops a candy over USB. The full build is meant to run with Hazel and the sonar.

**What computer runs it?** A Linux or macOS laptop next to the Arduino, indoors. On Linux,
`make service` runs it as a `systemd --user` service for the evening. Not tested on Windows.

**What about privacy?** Visitors' voices go to ElevenLabs for speech-to-text and their words
to Anthropic. The program saves no audio and deletes each transcript from the ElevenLabs
account; its text log stays on your computer. Consider a small sign at the door.

**Do I need Brankly's original files?** Only for Brankly's printed middle wall director (we
cut ours from a 2×4 offcut) and for the tests that compare our parts with the originals;
those skip without them.

## Share your build

Built one, or changed a part for your bucket or printer? Open an issue with a photo, or send
a pull request. If Hazel scared up some smiles on your porch, a ⭐ helps other makers find
the project.

## License

[Apache License 2.0](LICENSE), copyright 2026 religa; see [NOTICE](NOTICE). This covers
the code and documents in this repository only. Brankly's original design isn't included
and isn't covered by it.
