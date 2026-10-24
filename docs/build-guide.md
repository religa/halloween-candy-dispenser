# Build guide

From an empty bucket to a working candy dispenser, in order. Each step says what to check
before you go on; the details live in the linked docs.

**Videos:** [Build a Talking Candy Witch](https://www.youtube.com/watch?v=n9rjkIQ5XzI) follows this guide step by step;
[Hazel the Candy Witch](https://www.youtube.com/watch?v=f7yGwlmqU8s) shows the finished dispenser at work.

**How it works:** candy sits in the open storage half of a 5-gallon bucket on a slotted
turntable. A NEMA 23 stepper turns the turntable through a 66/14 gear pair and carries candy
under a wooden middle wall into the closed chamber. From there it drops through a hole in the
bucket wall onto a 45° chute. An IR break beam across the chute tells the Arduino a candy came
out, and the motor stops and reverses for 1 s. A `d` over USB starts a dispense.
A voice program on a computer makes the witch prop talk: Hazel greets each visitor the sonar
sees walk up, and hands out candy when kids say "trick or treat".

Status: every printed part is printed and checked, and the assembled dispenser works (see
[README → Status](../README.md#status)). Measure your own parts where this guide says
"measure": they are the values most likely to differ from ours.

1. [Gather the parts](#1-gather-the-parts)
2. [Set up the software](#2-set-up-the-software)
3. [Build the STL files](#3-build-the-stl-files)
4. [Test prints](#4-test-prints)
5. [Print the parts](#5-print-the-parts)
6. [Turntable drive](#6-turntable-drive)
7. [Chute](#7-chute)
8. [Middle wall](#8-middle-wall)
9. [Electronics](#9-electronics)
10. [First dispense](#10-first-dispense)
11. [The talking witch](#11-the-talking-witch)

## 1. Gather the parts

The exact parts we used, with links to where we bought them; their dimensions are in
[`parts/hardware.py`](../parts/hardware.py). With a different part, change its numbers
there and rebuild: every printed part that mates with it follows.

| Part | Used here | Notes |
|---|---|---|
| Bucket | [Home Depot Homer 5 gallon](https://www.homedepot.com/p/100087613) (05GLHD2) | 262 mm inside at turntable height (measured) |
| Lazy susan bearing | ~4 in / 95 mm square, [Amazon B0DDBBZZTB](https://www.amazon.com/dp/B0DDBBZZTB) | 8.5 mm thick, 4 × Ø4 holes on an 82 mm square per plate |
| Stepper motor | 23HS5628 NEMA 23, 2.8 A, 6.35 mm D-shaft; bundled with the driver, [Amazon B0H8D4RZWZ](https://www.amazon.com/dp/B0H8D4RZWZ) | shaft 28 mm past the flange (measured) |
| Stepper driver | TB6600 (a DM542 works too), in the motor bundle, [Amazon B0H8D4RZWZ](https://www.amazon.com/dp/B0H8D4RZWZ) | DIP switches: 400 pulses/rev, 2.8 A |
| Motor power | 24 V DC, 3 A or more; any you already have works. If you don't have one: [Amazon B0CRSS744F](https://www.amazon.com/dp/B0CRSS744F) | for the driver only |
| Controller | Arduino Uno R3 or R4 | powered over USB |
| Break beam | IR break-beam pair, [Amazon B0G38TCZS6](https://www.amazon.com/dp/B0G38TCZS6) | across the chute ramp |
| Presence sensor | HC-SR04 ultrasonic (sonar) | tells the voice program when someone walks up and leaves |
| Speakerphone (optional) | P10S USB speakerphone, [Amazon B0C9TCDLLN](https://www.amazon.com/dp/B0C9TCDLLN) | for the talking witch: clearer speech and hearing than a laptop's own mic and speaker; the voice program's default `--device` |
| Link cable | 2 × RJ45 screw-terminal adapter ([Amazon B0DK8ZW218](https://www.amazon.com/dp/B0DK8ZW218)) + an Ethernet patch cable | Uno case ↔ bucket; see [wiring.md → RJ45 link](wiring.md#rj45-link-uno-case--bucket) |
| Chute pipe | Amerimax FLEX-Drain 4 in ([Home Depot 202745394](https://www.homedepot.com/p/202745394)) | corrugated, flexible |
| Witch | 6-Foot Halloween Decoration Hanging Talking Witch, [Temu 601101988285461](https://www.temu.com/goods.html?goods_id=601101988285461) | the chute pipe goes in her sleeve, which is wide enough |
| Middle wall | a 2×4 stud, any lumber yard (e.g. Home Depot); an offcut of 30 cm (1 ft) or more is enough | really 38 × 89 mm (1.5 × 3.5 in); cut list in [middle-wall.md](middle-wall.md) |
| Power inlet (`driver_case`) | C14 panel inlet, screw mount, [Amazon B07PVP7XB7](https://www.amazon.com/dp/B07PVP7XB7) | for the 24 V supply's mains lead |
| Wiring | hook-up wire, 3-core cable, 2 × Wago 221-415 lever connectors | |

**Fasteners**

| Qty | Fastener | Where |
|---|---|---|
| 4 | M4 × 12 button head + nut | bearing bottom plate to stand |
| 4 | M4 × 25 button head + nut (or acorn nut) | bearing top plate, gear and quarters |
| 4 | M5 × 25 countersunk (ISO 10642) + nut | motor to stand |
| 8 | M5 × 16 (or shorter) + nut | turntable connectors |
| 1 | M3 × 8 set screw + M3 nut | pinion on the motor shaft |
| 4 | M4 × 20 self-tapping (or #8 × ¾″) | stand to bucket floor |
| 2 | M4 × 20 self-tapping | chute frame to bucket, from inside |
| 4 | M4 × 20 self-tapping | chute ramp to frame |
| 4 | M4 × 10 self-tapping | chute spigot to ramp |
| 2 | M2.5 × 12 self-tapping | beam emitter and receiver |
| 4 | M3 × 8 self-tapping | Uno in its case |
| 1 + 1 | M5 × 60, M5 × 45 + washers and nuts | director to the middle wall |
| 5 | #8 × 1¼″ wood screws + washers | middle wall to bucket |
| | zip ties | RJ45 adapter, drain pipe |

**Tools:** calipers, drill (Ø3, Ø4.5, Ø6, Ø10 mm and a 5/8″ spade bit), a jigsaw or
oscillating tool for the bucket hole, a miter saw or handsaw for the 2×4, a multimeter,
screwdrivers and hex keys.

## 2. Set up the software

Everything here is tested on Linux and macOS, not on Windows (the serial-port lookup and
`make service` assume a Unix system).

Install [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux or
macOS, or `brew install uv`), then:

```sh
git clone https://github.com/religa/halloween-candy-dispenser.git
cd halloween-candy-dispenser
uv sync                 # Python 3.13 and the locked packages, into .venv/
uv run pytest           # about a minute; everything should pass or skip
```

On Linux (Debian/Ubuntu), also install the audio libraries the voice program needs and let
your user open the Arduino's serial port (log out and back in afterwards):

```sh
sudo apt-get install -y libportaudio2 libc++1
sudo usermod -aG dialout $USER
```

Optional, but recommended: the original design, for the parts we reuse as-is and for the
tests that check our parts against it:

```sh
git clone https://github.com/branklyvideo/automatic-candy-dispenser ref/automatic-candy-dispenser
```

You also need the **Arduino IDE** or [arduino-cli](https://arduino.github.io/arduino-cli/)
(to flash the firmware) and **Bambu Studio** or another
slicer. FreeCAD or Fusion 360 can open the `.step` files if you want to look at or change a
part in CAD.

## 3. Build the STL files

**No changes to make?** Download every part instead:
[halloween-candy-dispenser-parts.zip](https://github.com/religa/halloween-candy-dispenser/releases/latest/download/halloween-candy-dispenser-parts.zip) from the latest release has
`stl/` and `3mf/` to print and `step/` for CAD. Skip to [Test prints](#4-test-prints).

To build them yourself, or after changing a measurement: each printable part is a Python script in `parts/`. Running one writes `out/<part>.stl` (to
print) and `out/<part>.step` (for CAD); parts with a fit-check version also write
`out/<part>_test.stl`.

```sh
uv run parts/stand.py                        # one part
for p in parts/*.py; do uv run "$p"; done    # every part (helpers just exit)
uv run tools/inspect_stl.py out              # size, watertight, PLA grams for each
uv run tools/render.py out/stand.stl -o stand.png   # preview, four views
```

If you changed a measurement in `parts/hardware.py`, run `uv run pytest` before printing:
the tests check that the parts still fit the plate, mesh and clear each other.

## 4. Test prints

Cheap prints that check the measured hardware before the big ones. Print in PLA; every
part prints without supports, in the orientation it's exported in.

1. **`bearing_fit_check`** (~8 g): lay it on the lazy susan bearing; all 4 screws must drop
   through. If not, fix `BEARING_SPACING` / `BEARING_HOLE` in `parts/hardware.py`.
2. **`motor_gear`** (~8 g): slides onto the shaft with the flat under the set screw.
3. **`turntable_gear_test`** (4 mm thick): its bolt holes line up with the bearing's top
   plate, it sits flat on the bearing (the recess clears the race), and it meshes with the
   pinion.
4. **`stand_test`** (4 mm plate): the bearing's bottom-plate holes, the motor's 4 holes and
   its pilot line up.
5. **`chute_ramp_test`**: screw both beam sensors on (M2.5 × 12) and check the lenses sit
   back from the channel and the receiver sees the emitter.
6. **`electronics_case_test`**: the RJ45 adapter's socket end slides into the notch, the
   shoulders sit on the wall and the posts touch the back of the body.

## 5. Print the parts

Sized for a Bambu Lab A1 mini (180 × 180 × 180 mm); anything bigger was split.

| Part | Qty | Orientation (as exported) | Size (mm) | PLA each |
|---|---|---|---|---|
| `stand` | 1 | plate on the bed, legs up | 163 × 104 × 75 | ≤ 248 g |
| `turntable_gear` | 1 | turntable face on the bed, recess up | 136 × 136 × 10 | ≤ 146 g |
| `motor_gear` | 1 | teeth down | 32 × 31 × 17 | ≤ 8 g |
| `turntable_quarter` | 4 | flat, ribs up; one per plate | 130 × 130 × 7 | ≤ 83 g |
| `turntable_connector` | 4 | flat | 35 × 130 × 4 | ≤ 12 g |
| `chute_frame` | 1 | flat outer face down | 140 × 141 × 24 | ≤ 153 g |
| `chute_ramp` | 1 | floor down | 136 × 95 × 33 | ≤ 74 g |
| `chute_spigot` | 1 | socket mouth down, spigot up | 123 × 94 × 88 | ≤ 190 g |
| `electronics_case` | 1 | floor down | 121 × 60 × 22 | ≤ 41 g |
| `driver_case` | 1 | floor down | 113 × 123 × 30 | ≤ 73 g |
| `middle wall director.stl` from `ref/` | 1 | Brankly's part, unchanged | | |

The weights are `tools/inspect_stl.py`'s solid (100 % infill) figures, so upper bounds:
about 1.3 kg for the set, much less at normal infill.

## 6. Turntable drive

1. Screw the bearing's **bottom plate** to the stand: M4 × 12 **button-head** screws down
   through the bottom plate and the stand, nuts underneath. The top plate leaves these holes
   uncovered. Both sets of M4 heads sit between the bearing plates at the same radius and
   pass over each other as it turns: two button heads (~2.2 mm each) need more than ~4.5 mm
   between the plates. Check this on your bearing first.
2. Bolt the motor under the stand plate's riser pad: 4 × M5 × 25 **countersunk** screws
   down through the plate, pad and motor flange, nuts under the flange. The heads must sit
   flush in the countersinks: the inner two are inside the circle the bearing's top plate
   sweeps. To reach them from above, turn the bearing's top plate so a straight edge faces
   the motor. Leave them just snug: the holes are ±1 mm slots along X for setting the mesh
   in step 3.
3. Put the turntable gear (recess down) on the bearing's top plate. Then fit the pinion,
   **before the quarters** (it slides down onto the shaft from above, into mesh with the
   gear). Drop an M3 nut into its slot and start the M3 × 8 set screw a turn so the nut
   can't fall out. Slide it on, teeth up and the shaft's flat facing the screw, and set its
   height **against the gear, not the stand**: lay a straightedge across the gear's top face
   and set the pinion's top 0.5 mm below it (a 0.5 mm feeler or a few layers of card), then
   tighten. That gives 0.5 mm under the turntable and 0.5 mm over the bearing's top plate,
   whatever the bearing's exact thickness. Check the hub still clears the stand plate
   (about 1.5 mm with an 8.5 mm bearing). Then slide the motor in its slots until the gears
   mesh with a hair of play (they shouldn't bind anywhere round a full turn of the
   turntable gear), and tighten the motor nuts from below.
4. Put the quarters on the gear. From below, past the stand's open edge at
   (0, ±58), push M4 × 25 **button-head** screws up through the top plate, gear and
   quarter, with a nut on top of the quarter. Turn the turntable to bring each hole round.
   The screw end stands ~5 mm proud of the nut inside a candy pocket; trim it or use an
   acorn nut. Then join each seam with a connector underneath, 2 × M5 through its holes.
   Keep these screws to 16 mm or less: longer ones sweep over the stand's corner.
5. Screw the stand to the bucket floor: 4 × M4 × 20 self-tapping screws from under the
   bucket into the legs' 20 mm pilot holes. The stand must stay 75 mm tall: the bucket
   narrows lower down, and the Ø260 turntable has only ~1 mm per side at this height.

**Check:** turn the turntable by hand a full turn. Nothing rubs, and the gears don't bind.

## 7. Chute

1. **Cut the bucket.** Hold `chute_frame` on the outside, its window just to the right of
   where the middle wall's near end will meet the bucket (seen from outside; the chamber
   side, see [middle-wall.md](middle-wall.md)), with the bottom of its window level
   with the turntable's top face. Trace inside the window and cut **on the line**: the
   frame has no rim, so the hole is exactly the window (4 × 4 in). Fix it with 2 × M4 × 20
   self-tapping screws from inside, through Ø4.5 holes in the bucket.
2. **Ramp to frame:** 4 × M4 × 20 self-tapping screws through the lugs. The frame's outer
   face leans with the bucket's taper, so the ramp runs at 47.6°.
3. **Spigot:** slide the ramp's lower end into the spigot's socket until it stops on the
   shoulder; 4 × M4 × 10 self-tapping screws through the socket walls into the rails.
4. **Pipe:** push the drain pipe over the spigot and zip-tie it over the groove. The
   spigot's low edge ends ~2 cm **below** the bucket's base, so stand the bucket 5 cm or
   more off the ground, with room for the pipe to bend away. Support the pipe: its weight
   mustn't hang on the chute. We put it inside the witch's sleeve (see the parts list),
   which is wide enough for it.
5. **Beam:** emitter and receiver on the outside of the ramp's rails, facing each other
   through the LED holes (M2.5 × 12; longer screws reach into the channel).

Some chute sizes in `parts/hardware.py` are estimates that fit our printed chute: the bucket's
wall thickness and outside taper, the drain pipe's inside diameter across the corrugation
ridges, and on the beam sensor the LED-to-hole distance and lens height. If your bucket,
pipe or sensor differ, measure them and change them before printing the frame.

## 8. Middle wall

The original printed wall is 270 mm long, too big for the A1 mini, so it's cut from a 2×4
instead. [middle-wall.md](middle-wall.md) has the measurements to take, the cut list, and
how to fit it pointing at the chute hole and bolt Brankly's director to it (we used a wedge
cut from a 2×4 offcut instead).

**Rotation direction:** forward must turn the turntable **clockwise seen from above**, so
candy goes storage → passage → chamber. You'll check this at the first power-up.

## 9. Electronics

Everything is in [wiring.md](wiring.md): the diagram, every connection, the TB6600 switch
settings, the motor coils, the RJ45 link between the Uno case and the bucket, and a
step-by-step first power-up.

1. Put the Uno in `electronics_case` (4 × M3 × 8 self-tapping screws; USB and barrel jack
   through the notches). The RJ45 adapter's socket end goes into the notch at the other
   end, held by a zip tie through the two floor slots.
2. Wire it as in [wiring.md](wiring.md). The 24 V supply only ever goes to the TB6600.
3. **Firmware:** open `arduino/main.ino` in the Arduino IDE (let it move the file into a
   `main/` folder when it asks), pick *Arduino Uno* and upload. Or, with arduino-cli,
   `make upload`: it installs the AVR core if needed, compiles and flashes the only
   USB serial port (`/dev/ttyACM0` on Linux, `/dev/cu.usbmodem*` on macOS; pick another
   with `make upload PORT=...`). `make monitor` then shows what the Uno prints.
4. Follow the [first power-up](wiring.md#9-first-power-up-one-piece-at-a-time) step by step: dispense, beam, motor
   direction, then speed.

## 10. First dispense

Fill the storage half with candy, then from the computer:

```sh
uv run tools/dispense.py             # one candy (close the Arduino IDE's Serial Monitor first)
uv run tools/dispense.py --count 3   # three in a row over one connection
```

The turntable turns until a candy cuts the beam (at most 15 s), then reverses for 1 s. If
no candy comes, the Uno's LED blinks: the bucket is empty or something's jammed. To tune
speed, timeout and back-spin, change `STEP_INTERVAL_US`, `MAX_SPIN_MS` and `BACKSPIN_MS` in
`arduino/main.ino` (see [wiring.md](wiring.md)).

## 11. The talking witch

`voice/` is a Python program for a Mac or Linux computer on the porch. It listens with the microphone,
answers in character as Hazel with Claude, speaks with an ElevenLabs voice, and asks the
dispenser for candy when a kid says "trick or treat". The code, not the model, enforces
the limits: one candy per kid, three per group, and a cooldown. Design and open checks:
[voice.md](voice.md).

1. Get an [Anthropic API key](https://console.anthropic.com/) and an
   [ElevenLabs](https://elevenlabs.io/) API key. Add Hazel's voice, *The Ancient Crone*,
   to your ElevenLabs voices (or set `ELEVENLABS_VOICE_ID` to another voice).
2. Put the keys in a `.env` file in the repo root (git-ignored):

   ```sh
   cp .env.example .env   # then fill in ANTHROPIC_API_KEY and ELEVENLABS_API_KEY
   ```

3. Try it without hardware, then with:

   ```sh
   uv run --env-file .env voice/main.py --text --fake-dispenser candy   # type as the kid
   uv run --env-file .env voice/main.py --fake-dispenser candy          # talk, fake candy
   uv run --env-file .env voice/main.py                                 # talk, real Arduino
   make start                                                           # the same, shorter (ARGS="--text" etc.)
   ```

   Hazel uses the P10S USB speakerphone's mic and speaker
   ([Amazon B0C9TCDLLN](https://www.amazon.com/dp/B0C9TCDLLN), see the parts list): her speech
   is clearer than through a laptop's own mic and speaker. With another speaker, add
   `--device default` (the system default) or `--device NAME` (part of the device's name).
   `--mute` turns her voice off; `--debug` logs every Arduino line and timing;
   `--silence 0.7` sets how long a pause ends a turn. `voice/hear.py --listen` shows the mic
   levels, to tune the turn detection for your door.
4. Mount the HC-SR04 at kid-chest height facing the porch. Hazel then greets
   each visitor as they walk up, and the visit ends when they walk away.

### Run it for the evening

On Linux, `make service` installs `tools/candy-witch.service` as a `systemd --user` unit and
starts it, so nobody has to watch the laptop. Clone the repo to a path without spaces. It isn't
enabled at login: `systemctl --user enable candy-witch` does that.

- **Watch it:** `make logs` (`journalctl --user -fu candy-witch`). Besides Hazel's lines, it prints one
  status line at start-up, at the end of each visit, whenever something breaks or comes back, and
  every 15 minutes while nothing else prints it:
  `status: arduino OK · mic OK · LLM OK · ears OK · voice OK · distance 87 cm · visits 3 · candies 2 · last error 19:16 …`.
  `distance` is the ultrasonic sensor's reading when the line was printed (`none`: nothing in range,
  `?`: the Arduino isn't answering).
- **What it survives:** the Arduino unplugged (it reconnects, and waits 60 s for it at start-up);
  a hung Uno (the firmware's 2 s watchdog reboots it); the P10S unplugged for up to 60 s (it
  reopens it; longer, the program exits and systemd restarts it 5 s later); the network or an API
  down (Hazel says an in-character line instead of going silent). The fallback lines and her ten
  greetings are recorded once into `cache/` (git-ignored) while ElevenLabs works; a visitor hears a
  random greeting at once, and Claude writes one only if none is recorded. When Claude is slow
  to answer, Hazel fills the pause with a recorded "Hmmm, let me see...".
- **Stop it** before `make start` or `make upload` (one program per serial port): `make stop`.
  Stopping runs the same clean shutdown as Ctrl-C.
- **Spending caps:** set a monthly limit in the Anthropic Console and a usage limit in
  ElevenLabs. Billing or quota trouble shows in the log as `API PROBLEM (...)`.
- Keep the lid open and suspend off for the evening.

**Privacy:** the program sends visitors' voices to ElevenLabs for speech-to-text and their
words to Anthropic. It saves no audio and deletes each transcript from the ElevenLabs
account, but both providers keep request data under their own policies. Each run writes a
text log, with visitors' words, to `logs/` (git-ignored). Consider a small sign at the door.
