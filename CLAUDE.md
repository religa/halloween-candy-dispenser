# CLAUDE.md

Automatic candy dispenser, adapted from `ref/automatic-candy-dispenser/` for a
**Bambu Lab A1 mini**. Parts are parametric Python scripts (build123d) that export
STL for printing and STEP for CAD.

This repository is public (Apache 2.0, see `LICENSE` and `NOTICE`).

- Build progress, measurements and next steps: **README.md → Status**. Update it when parts
  are printed or measured.
- How to build it: **docs/build-guide.md**. Update it when a part, a fastener, an assembly
  step or a purchased part changes.

## Commands

```sh
uv sync                                   # install exact env from uv.lock (Python 3.13)
uv run parts/<part>.py                    # build a part -> out/<part>.stl + .step
uv run pytest                             # all tests (tests/): part geometry, assembly, voice program with fakes; same as make test
make format | make lint | make verify     # ruff fix + format | ruff check + format check | lint + pytest + compile; run make verify before calling a change done
make compile                              # build arduino/main.ino for the Uno (arduino-cli, installs the AVR core if missing)
make upload [PORT=...] | make monitor     # flash arduino/main.ino to the Uno | read its serial output (stop the service first)
make start [ARGS="--text ..."]            # run voice/main.py in the terminal (Ctrl-C stops it; refuses while the service runs)
make service | make stop | make logs      # voice/main.py under systemd --user (tools/candy-witch.service), restarted if it stops | stop it | follow its output
make help                                 # list the make targets
uv run tools/inspect_stl.py <stl|dir>     # size, watertight, bodies, volume, PLA grams
uv run tools/render.py <stl> -o <png>     # iso/front/top/side preview PNG
uv run tools/compare.py <ref.stl> <new.stl>  # align + diff against a reference part
uv run tools/package_parts.py [part ...]  # every part as STL + 3MF + STEP -> out/halloween-candy-dispenser-parts.zip (release.yml runs it on v* tags)
uv run tools/dispense.py [--count N] [--port P]  # dispense candy over USB (Arduino running arduino/main.ino; port found automatically)
uv run --env-file .env voice/main.py --text [--mute] [--fake-dispenser candy]  # chat with the candy witch by typing; she speaks unless --mute (ANTHROPIC_API_KEY, ELEVENLABS_API_KEY in .env)
uv run --env-file .env voice/main.py [--mute] [--fake-dispenser candy] [--silence 0.7] [--debug] [--keep-turns]   # talk to the candy witch with the mic (half-duplex; needs both keys); --debug logs every Arduino line and timing; --keep-turns saves each turn as a WAV in tmp/turns/
# voice/main.py and hear.py --listen use the P10S speakerphone's mic and speaker unless --device NAME says otherwise (--device default = the system default); voice/main.py --port P picks the Arduino's port
# make start ARGS="..." runs voice/main.py with these flags and .env, and refuses while the service holds the port
uv run --env-file .env voice/hear.py <wav>...   # speech-to-text on 16 kHz mono WAVs, prints text and delay
uv run --env-file .env voice/hear.py --listen [--silence S] [--keep-turns]   # live mic -> turns -> text with levels, for tuning
uv run --env-file .env tools/make_voice_fixtures.py   # regenerate tests/fixtures/voice/ (spends TTS credits)
```

Add packages with `uv add <pkg>` (dev-only: `uv add --dev <pkg>`); commit `pyproject.toml` and `uv.lock` together.

## Hard constraints

- **Build volume: 180 × 180 × 180 mm** (A1 mini). Every printed part must fit with
  margin; keep the X/Y footprint ≤ 170 mm. Parts too big for the plate get split
  into segments joined by connectors or screws. Don't scale them down.
- Units are **millimetres**, Z up, the print-bed face at z = 0 (the part as it prints),
  unless a part's docstring says otherwise.

## Public repo rules

- Nothing personal in tracked files or commit messages: no home address or neighbourhood,
  no `/Users/...` or session scratchpad paths, no account details, keys or visitor words.
  Keys live in `.env`, visitor logs in `logs/`, recordings in `tmp/`, Hazel's generated
  fallback audio in `cache/`; all git-ignored.
- `plans/` holds local working plans (`/create-plan`) and is git-ignored. Never commit it,
  and never link to it from tracked files. When a plan's outcome matters to someone
  rebuilding this, write it into `docs/`, README or a code comment.
- Credit Brankly for anything derived from `ref/`; never copy `ref/` files into the repo.

## Part conventions

- One script per part in `parts/`, named after the part (`turntable_quarter.py`).
- Dimensions are UPPER_CASE module constants at the top of the script, with a comment
  giving the source of each value that matches another part or hardware (e.g. "matches
  ref turntable connector.stl" or "lazy susan 82 mm hole square").
- Each script exposes `build() -> Part` and ends with
  `if __name__ == "__main__": export(build(), "<name>")` so tests can import it.
- Shared print tolerances (`CLEARANCE`, `PRESS_FIT`, `WALL`) live only in
  `parts/common.py`. Import them; never redefine them per part.
- A mating dimension is defined once, in the part that owns it. Other parts and tests
  import it from there. Nominal dimensions of purchased parts (bearing, motor, fasteners,
  bucket) live only in `parts/hardware.py`; gear-train constants only in
  `parts/gearing.py`. Parts add print allowances themselves, from `common.py` tolerances.
- Slow or costly parts take `build(test: bool = False)` for a thin fit-check version;
  `__main__` exports `<name>` and `<name>_test`. `tests/test_all_parts.py` checks both.
- Helper modules in `parts/` that aren't printable (`common`, `gearing`, `hardware`) are
  listed in `NOT_PARTS` in `tests/test_all_parts.py`.
- In tests, check mating features against an independent oracle (`hardware.py` or a
  measured value), not the part's own constant, or the test can't fail.
- `out/` is generated and git-ignored. Never hand-edit or commit it.

## Verifying a part

A part isn't done until all of these pass:

1. `uv run pytest`: tests in `tests/test_<part>.py` that export the part to a temp
   dir and check the **STL mesh** with trimesh: watertight, one body, fits the plate,
   holes and features at the intended coordinates.
2. `uv run tools/inspect_stl.py out/<part>.stl` looks sane.
3. Render with `tools/render.py` and **look at the PNG** (Read it) before calling the
   shape right. Tests check numbers, the render catches wrong shapes.
4. If it replaces or mates with a `ref/` part, check the fit against the ref STL
   (hole centres within 0.05 mm).

## Layout

- `parts/`: part scripts, plus helpers `common.py` (tolerances, `export()`), `hardware.py` (purchased parts), `gearing.py` (gears)
- `tests/`: pytest tests; helpers `mesh_checks.py` (export a part, measure its STL) and `assembly.py` (parts placed in the assembly frame, for clearance tests)
- `tools/`: `inspect_stl.py` / `render.py` / `compare.py` for parts, `package_parts.py` (release zip), `dispense.py` (USB dispense), `make_voice_fixtures.py`,
  `candy-witch.service` (the unit `make service` installs)
- `Makefile`: everyday commands (`make help`); `.env.example`: the keys `.env` needs
- `docs/`: `build-guide.md` (step-by-step build), `wiring.md`, `middle-wall.md`, `voice.md`
  (voice program design and open manual checks). Markdown only: no images or other binaries
- `plans/`: local working plans, git-ignored (see Public repo rules)
- `.github/workflows/release.yml`: on a `v*` tag, runs pytest and publishes a release with the parts zip
- `.github/workflows/tests.yml`: CI runs `ruff check`, `ruff format --check` and `uv run pytest` on Ubuntu, without `ref/`, API keys or arduino-cli
- `ref/`: original design (STL, Arduino sketch, PCB), git-ignored
- `arduino/`: firmware for this build
- `voice/`: Python talking-dispenser program (docs/voice.md); `voice/dispenser.py` is the only Python copy of the Arduino serial protocol
- `logs/`: one full log per `voice/main.py` run, visitors' words included; git-ignored, never commit
- `cache/`: Hazel's fallback lines, greetings and fillers recorded by ElevenLabs (`voice/fallback.py`); git-ignored, safe to delete
- `tmp/`: recordings and `--keep-turns` WAVs (`tmp/turns/`), visitors' voices; git-ignored, delete after use
