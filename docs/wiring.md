# Wiring: Arduino Uno, TB6600, motor, IR break beam, HC-SR04

How the electronics connect, and how to bring them up one piece at a time. The firmware is
`arduino/main.ino`; its pin numbers and the tables here must match. The short version is in
[README → Electronics](../README.md#electronics).

What it does: send `d` over USB and the turntable turns until a candy falls through the IR beam
across the chute ramp, then the motor reverses for 1 s and stops. If no candy comes within
15 s (empty or jammed), it stops anyway, reverses the same way and blinks the Uno's LED.

## 1. Parts

| Part | Notes |
|---|---|
| Arduino Uno (R3 or R4) | powered by USB or a 7–12 V adapter, never the 24 V supply |
| TB6600 stepper driver box | DM542 works too; same terminals. Bundled with the motor: [Amazon B0H8D4RZWZ](https://www.amazon.com/dp/B0H8D4RZWZ) |
| 24 V DC supply | motor power for the TB6600 only; 3 A or more; any you already have works. If you don't have one: [Amazon B0CRSS744F](https://www.amazon.com/dp/B0CRSS744F) |
| 23HS5628 NEMA 23 motor | 2.8 A per phase, 4 wires. Ours: [Amazon B0H8D4RZWZ](https://www.amazon.com/dp/B0H8D4RZWZ) (with the TB6600) |
| IR break-beam pair ([Amazon B0G38TCZS6](https://www.amazon.com/dp/B0G38TCZS6)) | emitter (2 wires) + receiver (3 wires), 3–5 V |
| HC-SR04 ultrasonic sensor | 5 V; 4 wires; mount at kid chest height facing the porch |
| Hook-up wire | 3-core cable to extend the sensor leads (~30 cm as supplied) to the Uno |

## 2. Diagram

The TB6600 is wired **common-anode**: its PUL+ and DIR+ inputs sit at 5 V, and the Uno
switches an input on by pulling its minus side LOW, the same hookup as the motor's test
sketch.

```
                 Arduino Uno                                   TB6600
            ┌──────────────────┐                     ┌──────────────────────┐
            │              5V  ├──────┬──────────────┤ PUL+                 │
            │                  │      └──────────────┤ DIR+                 │
            │           pin 8  ├─────────────────────┤ PUL-                 │
            │           pin 9  ├─────────────────────┤ DIR-                 │
            │                  │       (not wired)   │ ENA+  ENA-           │
            │                  │                     │                      │
            │                  │                     │ A+ A- B+ B-  ├─────── motor coils
            │                  │                     │ VCC          ├─────── 24 V +
            │                  │                     │ GND          ├─────── 24 V −
            │                  │                     └──────────────────────┘
            │           pin 5  ├───────────────── signal ─┐
            │              5V  ├──┬────────────── red ────┤ RECEIVER ─┐
            │             GND  ├──│──┬─────────── black ──┘           │ beam across
            │                  │  │  │                                │ the chute
            │                  │  └──│────────── red ────┐            │ ramp
            │                  │     └────────── black ──┴ EMITTER ───┘
            │                  │
            │              5V  ├───────────────── VCC ──┐
            │           pin 6  ├───────────────── TRIG ─┤ HC-SR04
            │           pin 7  ├───────────────── ECHO ─┤ (faces the porch)
            │             GND  ├───────────────── GND ──┘
            └──────────────────┘
```

Two separate power circuits: the 24 V supply only ever touches the TB6600's VCC/GND; the
Uno's 5 V only drives the TB6600's signal inputs (through its optocouplers) and the sensors.
They don't need a common ground.

## 3. Every connection

| # | From | To | Wire |
|---|---|---|---|
| 1 | Uno **5V** | TB6600 **PUL+** | |
| 2 | Uno **5V** | TB6600 **DIR+** | jumper from PUL+ is fine |
| 3 | Uno **pin 8** | TB6600 **PUL−** | step pulses |
| 4 | Uno **pin 9** | TB6600 **DIR−** | direction |
| 5 | TB6600 **ENA+ / ENA−** | nothing | driver always on; see §8 to change |
| 6 | 24 V supply **+** | TB6600 **VCC** | |
| 7 | 24 V supply **−** | TB6600 **GND** | |
| 8 | motor coil A pair | TB6600 **A+ / A−** | see §5 |
| 9 | motor coil B pair | TB6600 **B+ / B−** | see §5 |
| 10 | Uno **5V** | emitter **red** | |
| 11 | Uno **GND** | emitter **black** | |
| 12 | Uno **5V** | receiver **red** | |
| 13 | Uno **GND** | receiver **black** | |
| 14 | Uno **pin 5** | receiver **signal** (the third wire, usually yellow or white) | no resistor: pull-up in the sketch |
| 15 | Uno **5V** | HC-SR04 **VCC** | |
| 16 | Uno **GND** | HC-SR04 **GND** | |
| 17 | Uno **pin 6** | HC-SR04 **TRIG** | |
| 18 | Uno **pin 7** | HC-SR04 **ECHO** | pull-up in the sketch: unplugged reads as "nobody there" |

The Uno's 5V and GND pins run out fast. Use a small breadboard or a terminal strip as a 5V
rail and a GND rail.

## 4. TB6600 settings

Set the DIP switches with the power off, using the table printed on the driver's case
(switch positions differ between versions):

- **Microstep: 400 pulses/rev** (half step, "2" or "2/A" on most labels). The sketch's speed
  and its 2-turn timeout assume this.
- **Current: 2.8 A** (or the nearest setting at or below it), the 23HS5628's rated phase
  current. Lower runs cooler, with less torque; drop it if the motor gets too hot to touch.

## 5. Motor coils

The motor has 4 wires in 2 pairs (coils). For the 23HS5628 the usual colours are
**black/green** (one coil) and **red/blue** (the other), but check the motor's datasheet
or label, or find the pairs with a multimeter: the two wires of a coil read about 1 Ω,
wires from different coils read open.

Put one pair on **A+ / A−** and the other on **B+ / B−**. If the turntable turns the
wrong way, either swap the two wires of *one* pair or flip `FORWARD` in the sketch.

Never connect or disconnect the motor while the TB6600 is powered; it can kill the driver.

## 6. Break-beam sensor

- **Mounting:** emitter and receiver screw to the outside of the two chute rails, facing
  each other through the LED holes, 45 mm down the ramp (`chute_ramp.py`). Either can go on
  either side. M2.5 × 12 self-tapping screws; longer ones reach into the candy channel.
- **Range:** the beam crosses 103 mm, well inside the module's rated distance.
- **Cable run:** the leads are ~30 cm. Extend them to the Uno with 3-core cable (2-core is
  enough for the emitter), soldered and heat-shrunk. Keep them away from the motor wires,
  and don't bundle them together: motor current switching can trigger false readings on a
  long signal wire. If it ever misfires, add a 10 kΩ resistor from pin 5 to 5V at the Uno
  and a 100 nF capacitor from pin 5 to GND.
- **Which level means "blocked":** these receivers come in two variants. The sketch's
  `BEAM_BLOCKED` is set to `LOW`; check it in §9, step 3, before relying on it.

## 7. Power

- **Uno:** USB from a computer or phone charger, or a 7–12 V adapter on the barrel jack.
  Don't feed it the 24 V supply: the barrel jack's regulator overheats above ~12 V.
- **5V load:** the TB6600's two inputs (~10–15 mA each) and the sensor pair (~30 mA) are
  well within what the Uno's 5V pin can supply.
- **TB6600:** 24 V only. Switch the 24 V off before touching any motor or driver wiring.

## 8. Optional: switching the motor off between candies

With ENA unconnected, the driver keeps current in the motor all the time, so it holds the
turntable firmly but gets warm, even when idle. To let the sketch switch it off:

1. Wire **ENA+ → Uno 5V** and **ENA− → Uno pin 10**.
2. In `arduino/main.ino`, set `USE_ENABLE = true`.

Pin 10 LOW then means "driver off"; the sketch turns it on only while dispensing. The
turntable can be pushed by hand while the driver is off, which is harmless here.

## 9. First power-up, one piece at a time

Do the steps in order; each checks one thing before the next depends on it.

1. **Upload with the 24 V off.** Open `arduino/main.ino` in the Arduino IDE (let it move
   the file into a `main/` folder when it asks), pick *Arduino Uno*, upload. Open the
   Serial Monitor at **115200**: it prints `ready: send 'd' to dispense`.
2. **Dispense, 24 V still off.** Type `d` + Enter: the monitor prints `dispensing`, then after
   15 s (and a 1 s reverse) `no candy after 15 s...` and the LED blinks. (The motor has no power, so
   nothing turns; that's expected.)
3. **Beam.** Put a finger between emitter and receiver: the monitor must print
   `beam: BLOCKED` and the Uno's LED (L) lights; take it out: `beam: CLEAR`, LED off.
   - Backwards (CLEAR when blocked)? Set `BEAM_BLOCKED` to `HIGH`, upload again.
   - Nothing changes either way? Check the emitter has power (a phone camera shows its
     LED glowing faintly purple) and the heads are lined up through the rail holes.
4. **Motor, turntable empty.** Switch the 24 V on and send `d`. The turntable
   must turn **clockwise seen from above** (candy goes storage → passage → chamber).
   Block the beam with a finger: it stops at once. Wrong direction: `FORWARD` to `HIGH`, or
   swap one coil pair (24 V off!).
5. **Candy.** Load the bucket and send `d`: it turns until one candy drops through the chute,
   then stops. Watch the monitor's `candy! after N steps`: N is how far it turned.
6. **Tune** if needed, in `arduino/main.ino`:
   - `STEP_INTERVAL_US`: smaller is faster (4000 µs ≈ 7.5 s per turntable turn). Each step
     is a square wave, half LOW and half HIGH; very short pulses don't get through the
     TB6600's slow input optocouplers.
   - `BACKSPIN_MS`: how long it reverses after each run (1000 ms ≈ 250 steps), candy or
     not; the original reversed 300 steps after each drop to clear the chamber.
   - `MAX_SPIN_MS`: the empty/jam timeout, 15 s from the start (~2 turntable turns).

## 10. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Motor hums or shakes, doesn't turn | coil pairs mixed up (§5), or current set too low |
| Turntable turns but never stops | beam polarity wrong (`BEAM_BLOCKED`), or heads misaligned |
| Stops at once, prints "beam already blocked" | candy stuck in the beam, misaligned heads, or polarity wrong |
| Stops at random with no candy | noise on the beam wire (§6): reroute it, add the resistor and capacitor |
| Motor very hot | lower the TB6600 current, or wire ENA (§8) |
| A fresh `ready:` line out of nowhere | the sketch hung and the 2 s watchdog rebooted the Uno (or its power dipped); it carries on by itself |

## Open points

- The beam receiver's polarity isn't stated in the listing; §9 step 3 settles it.
- Motor wire colours: confirm against the 23HS5628 datasheet or with a multimeter.
- `BACKSPIN_MS` and the speed are untuned for the 66/14 gears ([README → Status](../README.md#status)).

## HC-SR04 arrival sensor

The voice program (`voice/main.py`) uses it to greet each visitor and to end a visit when
they walk away. Dispensing and the beam work the same with or without it.

- With the Serial Monitor open (115200), `someone: HERE 85 cm` appears when you step in
  front of it, and `someone: GONE` 10 s after you leave (`HERE` needs 2 s in front: it pings once a second). Tune `HERE_CM` in
  `arduino/main.ino` (150 cm) so a kid at the door triggers it and people on the pavement don't,
  and keep `HERE_CM` in `voice/dispenser.py` the same: the voice program uses it to tell whether
  anyone is in front (a test checks the two match).
- With the sensor unplugged, neither line ever appears.
- It also prints `distance: <cm> cm` whenever the reading moves 50 cm (`REPORT_STEP_CM`), and
  `distance: none` once nothing is within 2 m (`MAX_CM`; farther counts as no echo).
- Type `p` + Enter for the distance it sees right now (`distance: 85 cm`, or `distance: none`
  for no echo): handy for setting `HERE_CM`. `voice/main.py` asks the same way, and adds it to
  each heard or dropped turn in its debug log.

## RJ45 link: Uno case ↔ bucket

One straight-through Ethernet patch cable carries every 5 V-side wire between the Uno
(`electronics_case`) and the bucket, with an RJ45 screw-terminal adapter ([Amazon
B0DK8ZW218](https://www.amazon.com/dp/B0DK8ZW218)) at each end. The 24 V runs to the TB6600 on its own cable; the two circuits
still share nothing (§7).

Dispensing comes over USB (`d`). The eighth wire is a spare, reserved for the optional ENA
(§8): leave terminal 8 empty at both ends unless you wire it.

Each pair carries related wires: DIR with the 5 V the TB6600 inputs return through, the
beam with GND, the sonar's TRIG with its ECHO, and the step pulses with the spare. Pin 8
(PUL−) is on RJ45 pin 7 and pin 9 (DIR−) on pin 2; pulses at a few kHz over a twisted pair
work fine on either pair.

```
  ELECTRONICS CASE                                                          AT THE BUCKET
  Arduino Uno   adapter A        Ethernet patch cable         adapter B
                (Uno end)       (straight-through)            (bucket end)
                ┌───────┐                                     ┌───────┐
    5V ─────────┤ 1     │  orange/white ─┐  twisted   ┌─      │     1 ├──► 5V lever nut ──┬─ TB6600 PUL+, DIR+
    pin 9 ──────┤ 2     │  orange ───────┘  pair      └─      │     2 ├──── TB6600 DIR−   ├─ beam emitter red
                │       │                                     │       │                   ├─ beam receiver red
    GND ────────┤ 3     │  green/white ──┐  twisted   ┌─      │     3 ├──► GND lever nut  └─ HC-SR04 VCC
    pin 5 ──────┤ 6     │  green ────────┘  pair      └─      │     6 ├──── beam receiver signal
                │       │                                     │       │     GND lever nut ──┬─ beam emitter black
    pin 6 ──────┤ 4     │  blue ─────────┐  twisted   ┌─      │     4 ├──── HC-SR04 TRIG    ├─ beam receiver black
    pin 7 ──────┤ 5     │  blue/white ───┘  pair      └─      │     5 ├──── HC-SR04 ECHO    └─ HC-SR04 GND
                │       │                                     │       │
    pin 8 ──────┤ 7     │  brown/white ──┐  twisted   ┌─      │     7 ├──── TB6600 PUL−
  (pin 10) ─ ─ ─┤ 8     │  brown ────────┘  pair      └─      │     8 ├ ─ ─ spare: empty (optional ENA−)
                └───[RJ45]══════════════════════════════════[RJ45]──┘

    24 V supply + / − ═══════════ separate 2-core cable ═══════════════════ TB6600 VCC / GND
```

| RJ45 pin | T568B colour | Uno end | Bucket end |
|---|---|---|---|
| 1 | orange/white | **5V** | TB6600 PUL+ and DIR+, emitter red, receiver red, HC-SR04 VCC |
| 2 | orange | pin 9 | TB6600 DIR− |
| 3 | green/white | **GND** | emitter black, receiver black, HC-SR04 GND |
| 4 | blue | pin 6 | HC-SR04 TRIG |
| 5 | blue/white | pin 7 | HC-SR04 ECHO |
| 6 | green | pin 5 | beam receiver signal |
| 7 | brown/white | pin 8 | TB6600 PUL− |
| 8 | brown | spare: leave empty (optional ENA: pin 10) | spare: leave empty (optional ENA: TB6600 ENA−) |

- **Fan-out at the bucket:** each screw terminal takes one wire, so never put the five 5V
  leads into terminal 1. Run one short wire from terminal 1 into a 5-way lever connector
  (Wago 221-415) and the loads out of it; the same for GND from terminal 3:

  ```
  adapter B          5V lever nut (221-415)              GND lever nut (221-415)
  terminal 1 ──────► ▣ in                    terminal 3 ──────► ▣ in
                     ▣ ── TB6600 PUL+ ─ jumper DIR+
                     ▣ ── beam emitter red                ▣ ── beam emitter black
                     ▣ ── beam receiver red               ▣ ── beam receiver black
                     ▣ ── HC-SR04 VCC                     ▣ ── HC-SR04 GND
  ```

  At the TB6600, jumper PUL+ → DIR+ with a short wire (two wires per screw is fine
  there), so one 5V lead serves both. Signal wires (terminals 2, 4–7) go
  straight to their device, no splitting. Lever connectors take 0.14–4 mm² (26–12 AWG)
  solid or stranded; cut the Dupont plugs off sensor leads and strip 11 mm.
- **Pin numbers, not colours:** the adapters' terminals are numbered 1–8. Wire both ends by
  number and any straight-through cable works, T568A or B. A crossover cable doesn't.
  Check each pin end to end with a multimeter before powering up.
- **Never plug either end into a network switch, router or PoE injector**: PoE puts up to
  57 V on these pins. Label both sockets "not Ethernet".
- **Voltage drop:** the 5 V load is ~0.1 A; 10 m of 24 AWG is ~1.7 Ω round trip, ~0.17 V.
  The HC-SR04 still works at 4.8 V. Over ~10 m, check 5V–GND at the bucket end (≥ 4.75 V).
- **Beam noise** (§6): if the beam misfires with the cable in place, add the 10 kΩ pull-up
  and 100 nF at the **Uno end** (pin 5 to 5V, pin 5 to GND). Keep the patch cable away from
  the motor leads; crossing them at right angles is fine.
- **Spare pin 8 / optional ENA (§8):** not connected, so the driver is always on. To let
  the sketch switch the motor off between candies, wire Uno pin 10 → terminal 8 at the Uno
  end, terminal 8 → TB6600 ENA− at the bucket, add a jumper DIR+ → ENA+ on the TB6600,
  and set `USE_ENABLE = true`.
