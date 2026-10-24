# Middle wall from a 2×4: what to cut and why

Instead of 3D printing the middle wall (270 mm long, too big for the A1 mini plate), make
it from a Home Depot 2×4 stud. A 2×4 actually measures **1.5 × 3.5 in = 38 × 89 mm**.

Directions used below: stand **outside the bucket at the chute**, looking in. The wall runs
**away from you**, from the chute hole straight across the bucket through its centre. The
hole sits just to the right of the wall's near end.
- The **right half** of the bucket (under the lid, with the chute hole) is the **dispensing chamber**.
- The **left half** (open top) is **candy storage**.
- The wall's **near half** (by the chute) is closed; its **far half** has the candy passage.

In our build the director is a wedge cut from a 2×4 offcut, on the wall's chamber face by
the chute, instead of Brankly's printed one.

## 1. The current shape (Brankly's 3D-printed `middle wall.stl`)

Measured from `ref/automatic-candy-dispenser/` in our assembly frame, with heights measured
up from the turntable's underside (the rib tops are at 7 mm):

```
                 near half (closed, by the chute)            far half (gate)
 69 ┌──────────────────────────────────────┬──────────────────────────────────────┐ top
    │  o            o          o           │            o          o              │
    │                                      │      ●                   ●           │ 43
    │   ▯ ◯                    ▯ ◯         ├──────────────────────────────────────┘
    │                                      │   ↑ candy passage: open from the
 11 └───────────────┐ ┌──────────────────┘     turntable up to 43 (36 mm clear)
    -135          -47 -35                  0                                    +135
 ═══════════════════ turntable (ribs at 7) ════════════════════════════════════════
```

- **Size:** 270 long × 12 thick, standing 11 → 73 mm above the turntable's underside. It spans the whole bucket, so its ends press against the bucket wall.
- **Left half, the closed side:** comes down to **4 mm above the rib tops**. Candy can't ride back from the chamber into storage under it. A small 12 × 8 mm gap at the bottom (x −47…−35) matches a gap in the director. It probably lets crumbs through, and is optional.
- **Right half, the gate:** the bottom is cut away up to 43 mm, a **36 mm-tall passage** above the ribs. The turntable carries candy from storage, through this passage, into the chamber.
- **Director mounting:** the separate `middle wall director` (a wedge 130 × 19 × 37 mm on the chamber face of the near half) is held by **2 bolts** at x −25 and −105, 18.5 mm above the wall's bottom edge. The wall's Ø15.4 holes and vertical slots there are pockets for the nuts.
- **Bucket fixing:** pilot holes (Ø3) in each end take screws through the bucket wall: 3 in the near end, 2 in the far end above the passage.
- **Lid fixing:** 4 small holes near the top (Ø3.2) and a thin ledge for the lid. The lid is 260 mm, too big to print as is, so it needs its own design (see Open points).

**How it works (inferred from the shapes):** the turntable turns clockwise seen from above.
Candy rides from storage through the passage at the far end into the chamber, then round to
the chute hole by the wall's near end. The closed near half stops it riding on into storage,
and the director steers it into the hole. The firmware's reverse spin after each candy keeps
the next one from following it out.

## 2. What to cut

**One piece of 2×4, standing on its narrow edge**: 38 mm thick, **89 mm tall**, cut to the
bucket's width. Then cut **one notch** (the candy passage), drill **2 bolt holes** (director)
and **5 screw pilot holes** (bucket).

```
                         chamber face (right, seen from the chute)
 89 ┌──────────────────────────────────────┬──────────────────────────────────────┐  ← miter ~2.6°
    │                                      │                                      │    on each end
    │                                      │                                      │    (longer at top)
    │       ⊙ bolt              ⊙ bolt     ├──────────────────────────────────────┤ 32
    │      (−105)              (−25)       │   candy passage, 32 mm tall          │
  0 └──────────────────────────────────────┘   from the wall's bottom edge
   near end (chute)                     centre                              far end
   (wall's bottom edge sits 4 mm above the turntable ribs)
```

### Cut list (measured on the board; 0 = the board's bottom edge, x = 0 at its centre)

| # | Cut | Size | Tool |
|---|---|---|---|
| 1 | Crosscut a blank | ~300 mm, from a straight, knot-free part of the stud | miter saw or handsaw |
| 2 | Trim both ends to fit the bucket | bottom length **L₁**, top length **L₂**, about a 2.6° miter (see §4) | miter saw |
| 3 | Candy-passage notch on the **far** half | from x = 0 to the far end, **32 mm** up from the bottom edge | jigsaw, or handsaw + chisel |
| 4 | Director bolt holes | **Ø6 mm** through, at x = **−25** and **−105**, **18.5 mm** up | drill |
| 5 | Nut recesses for those bolts | **Ø16 mm (5/8″)**, ~8 mm deep, on the **storage** face | spade or Forstner bit |
| 6 | Bucket screw pilot holes in the ends | **Ø3 mm**, 30 mm deep, centred in the 38 mm thickness. Near end at **9, 27, 46 mm** up; far end at **42 and 70 mm** up (above the notch) | drill |
| 7 | Ease the edges | 1–2 mm chamfer on the passage edges and the bottom edge | sandpaper or block plane |

Before cutting the notch, drill a **Ø10 mm hole at its inside corner** (x = 0, 32 mm up).
That rounds the corner so the wood doesn't split there, and gives a jigsaw a start.

## 3. Why these choices

- **Full 38 mm thickness (no ripping).** A table saw is the only good way to rip a 2×4 thinner, and the wall doesn't need to be thin: the turntable pockets are ~100 mm wide at the rim, so losing 26 mm more to the wall is fine. It's also much stiffer than 12 mm of plastic.
  - Cost: the director bolts on 13 mm further out than in the original, and the future lid must be designed for a 38 mm wall. The lid needs redesigning anyway.
  - If you do have a table saw, ripping it to 19 mm (3/4″) is a fine alternative. Everything else stays the same.
- **Full 89 mm height (no ripping).** The original stands 62 mm. Taller is harmless: the bucket is much deeper, and the storage side simply holds more. It also leaves **57 mm of wood above the passage** (the original had 26), so the notched half stays strong.
- **4 mm above the ribs, near half.** This keeps the original's job: candy can't slip back to storage, but the rotating ribs (2 mm tall) never touch the wood.
- **36 mm passage height** (32 mm notch + 4 mm gap) matches the original exactly, so the same candy sizes get through.
- **Bolt holes at the original director positions,** so Brankly's director (130 × 19 × 37 mm, which fits the A1 mini) bolts on unchanged. The director is a wedge: 19 mm deep at the −25 bolt but only ~5 mm at the −105 bolt. With the nuts sunk 8 mm into the 38 mm wall, the bolts need to be **M5 × 60 at x −25** (30 + 19 + nut) and **M5 × 45 at x −105** (30 + 5 + nut). The 5/8″ recesses keep the nuts flush on the storage side, so candy doesn't catch on them.
- **Screws through the bucket into the ends,** like the original. End grain holds less well than face grain, so use **#8 × 1¼″ wood screws** in 3 mm pilots, 2–3 per end. If it ever feels loose, add a small L-bracket per end on the storage face.
- **Mitred ends.** The bucket widens going up, about 8 mm in diameter over the wall's 89 mm height. Square ends would leave a gap of up to ~4 mm per side at the top, enough for small candy to leak from storage into the chamber. A ~2.6° miter per end follows the taper.
- **Corner allowance.** The bucket is round and the board is 38 mm thick, so its end **corners** touch first. The lengths below are shortened (`√(D² − 38²)`) so the corners fit, leaving ~1.4 mm at the middle of each end.

## 4. Measure the bucket first, then compute the lengths

The wall's bottom edge sits **4 mm above the rib tops**. With our stand, bearing and gear,
the rib tops are **100.5 mm above the inside floor** of the bucket. So the wall spans
**104.5 → 193.5 mm** above the floor.

1. Measure the bucket's **inside diameter** at **105 mm** above the floor (**D₁**) and at **193 mm** (**D₂**). Expect about 263 and 271 mm; it's 262 at ~95 mm.
2. Compute, with 1 mm clearance per side:
   - **L₁ = √(D₁² − 38²) − 2** (bottom edge length)
   - **L₂ = √(D₂² − 38²) − 2** (top edge length)
   - **miter angle = atan((L₂ − L₁) / 2 / 89)**
   - Example: D₁ = 263, D₂ = 271 → L₁ ≈ **258.2**, L₂ ≈ **266.3**, angle ≈ **2.6°**.
3. Mark the board's **centre** (x = 0) and measure L₁/2 and L₂/2 out from it on the bottom and top edges. The centre must sit over the turntable's axis, so the notch starts exactly there.

On a miter saw: lay the 2×4 **flat** (wide face down) and set the miter to the computed
angle. Cut the first end, flip the board end-for-end (same face down), and cut the second.
That way both ends lean outward at the top.

## 5. Fitting it

1. With the turntable, gear and stand assembled in the bucket, lay **4 mm spacers** on the rib tops on both halves (e.g. a 4 mm drill bit, or cardboard).
2. Set the wall on the spacers, **centred** on the turntable axis, pointing **straight at the chute hole**, with the hole just on the chamber side of its near end, the **notch at the far end** and the **nut recesses facing storage**.
3. Through the bucket wall, drill Ø4.5 holes in line with the end pilot holes and drive the #8 × 1¼″ screws (use washers on the outside of the bucket).
4. Remove the spacers and **turn the turntable by hand a full turn**. Nothing should rub, and the gap should be ~4 mm all along the near half.
5. Bolt the director (printed `middle wall director.stl`) to the chamber face of the near half: M5 × 60 at x −25, M5 × 45 at x −105.

**Rotation direction:** forward must turn the turntable **clockwise seen from above**, so
candy goes storage → passage → chamber. If it runs the other way, swap one motor coil
pair, or flip `FORWARD` in the firmware.

## 6. Finish

Sand everything smooth, especially the chamber face, the passage and the bottom edge, so
there are no splinters near food. Candy is usually wrapped, but if you want a finish, use a
**food-safe** one (mineral oil or shellac) and let it cure fully before loading candy.

## Shopping / tools

- 2×4 stud, sandpaper (120 + 220 grit)
- 1 × M5 × 60 and 1 × M5 × 45 bolts + 2 washers + 2 nuts (director)
- 5 × #8 × 1¼″ wood screws + washers (bucket)
- Miter saw or handsaw + miter box; jigsaw (or handsaw + chisel); drill with Ø3, Ø6 and Ø10 mm bits and a 5/8″ (16 mm) spade or Forstner bit; tape measure or calipers; square; pencil

## Open points

- **The lid** (Brankly's is 260 mm, too big to print) needs its own design for a 38 mm-thick, 89 mm-tall wall. Plywood or a split printed lid are options.
- **The chute** goes through a 4 × 4 in hole cut in the bucket wall: see [build-guide.md](build-guide.md#7-chute).
- If your D₁ / D₂ differ a lot from 263 / 271, recompute L₁, L₂ and the angle before cutting. Cut a little long first; you can always trim.
