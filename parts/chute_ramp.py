"""Chute ramp: the steep channel from the frame's window to the spigot, with the IR break beam.

Screws onto chute_frame's flat outer face with 4 x M4 x 20 self-tapping screws through
the two lugs beside the rails. Its lower end slides into chute_spigot's socket and is
held by 4 x M4 x 10 self-tapping screws through the socket walls into the rails.

The beam crosses the whole channel 6 mm above the floor, so every candy sliding down cuts
it, wherever it is across the width. The emitter and receiver (hardware BEAM_*) sit flat
on the rails' outer faces with the LED looking through a 6.8 mm hole (twice the lens's
close fit), each held by one M2.5 x 12 self-tapping screw through its own hole. The 6 mm
rails keep the lens tips back from the channel, out of the candy's way. All holes go right through the rails; keep the
screws to the stated lengths so their tips stay out of the channel.

assembled() is in the reference mount (REF_*); chute_frame.RAMP_MOUNT places it in the
assembly frame, where it runs at 45 degrees plus the bucket's taper. Print (build()) with the floor's
underside on the bed, rails up; no supports. Layers then run along the ramp, the strong
way for a part that hangs off the frame.

Test variant (build(test=True)): a 32 mm slice of the channel round the sensors, to
check the sensor fit and the beam across the real width.
"""

import math

from build123d import (
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Location,
    Locations,
    Part,
    Plane,
    Polygon,
    Rot,
    extrude,
)
from common import CLEARANCE, export
from hardware import (
    BEAM_LED,
    BEAM_LED_TO_HOLE,
    M2_5_SELF_TAP_PILOT,
    M4_CLEARANCE,
    M4_SELF_TAP_PILOT,
)

WINDOW = 4 * 25.4  # 4 x 4 in opening, shared with chute_frame; the original was 85 x 85
# The ramp is modelled on its first mount, kept so the printed ramp stays valid: end face in
# the plane y = REF_FACE_Y, floor top 0.5 mm under z = REF_SILL_Z there. chute_frame.RAMP_MOUNT
# moves it to where it really sits.
REF_FACE_Y = -144.0
REF_SILL_Z = 5.0
LUG_SCREWS = tuple((sx * 62.6, z) for sx in (-1, 1) for z in (10.0, 30.0))  # (x, z) on the end face
SLOPE = 45.0  # degrees, on the reference mount (user: at least 45; the original was 30)
FLOOR = 3.0
RAIL = 6.0  # thick enough that the LED lens (BEAM_LED_HEIGHT) stays out of the channel
RAIL_HEIGHT = 30.0  # above the floor, square to it
STEP = 0.5  # floor below the sill and channel wider than the window, so nothing catches at the joint
LUG_DEPTH = 10.0  # lugs along Y, square to the frame face; the screws' grip
LUG_MARGIN = 5.4  # lug material outside the screw centre
SENSOR_AT = 45.0  # LED centre, along the floor from the frame
BEAM_HEIGHT = 6.0  # LED centre above the floor
LED_HOLE = 2 * (BEAM_LED + 2 * CLEARANCE)  # twice the lens's close fit, so the beam isn't clipped; clears the collar too
TEST_SPAN = (SENSOR_AT - BEAM_LED_TO_HOLE - 12.0, SENSOR_AT + 11.0)  # along the floor

CHANNEL_LENGTH = 65.0  # along the floor from the frame; the sensor body ends at 50, the socket starts at 53
JOINT_OVERLAP = 12.0  # how far the channel's end sits inside chute_spigot's socket
JOINT_SCREWS = tuple((CHANNEL_LENGTH - JOINT_OVERLAP / 2, h) for h in (8.0, 22.0))  # (s, h) on each rail

COS = math.cos(math.radians(SLOPE))
SIN = math.sin(math.radians(SLOPE))
DOWN = (-COS, -SIN)  # (y, z) along the floor, away from the bucket
UP_NORMAL = (-SIN, COS)  # (y, z) square to the floor, into the channel
TOP0 = (REF_FACE_Y, REF_SILL_Z - STEP)  # floor top at the end face
CHANNEL = WINDOW / 2 + STEP  # half width
RAIL_OUT = CHANNEL + RAIL
LUG_OUT = max(abs(x) for x, _ in LUG_SCREWS) + LUG_MARGIN


def at(s: float, h: float) -> tuple[float, float]:
    """(y, z) of the point s along the floor top from the frame and h above it."""
    return (TOP0[0] + s * DOWN[0] + h * UP_NORMAL[0], TOP0[1] + s * DOWN[1] + h * UP_NORMAL[1])


def across_plane(s: float, h: float = 0.0) -> Plane:
    """Plane square to the ramp at s along the floor: local x = X, local y = up from the floor, normal = downhill."""
    y, z = at(s, h)
    return Plane(origin=(0, y, z), x_dir=(1, 0, 0), z_dir=(0, *DOWN))


def prism(profile: list[tuple[float, float]], x0: float, x1: float) -> Part:
    """(y, z) profile extruded along X from x0 to x1."""
    with BuildPart() as p:
        with BuildSketch(Plane.YZ.offset(x0)):
            Polygon(*profile, align=None)
        extrude(amount=x1 - x0)
    return p.part


def across(y: float, z: float, diameter: float, x0: float, x1: float) -> Part:
    """Round hole along X at (y, z), from x0 to x1."""
    with BuildPart() as p:
        with BuildSketch(Plane.YZ.offset(min(x0, x1))):
            with Locations((y, z)):
                Circle(diameter / 2)
        extrude(amount=abs(x1 - x0))
    return p.part


def assembled(test: bool = False) -> Part:
    bottom_end = (REF_FACE_Y, TOP0[1] - FLOOR / COS)  # floor underside at the frame face
    rail_end = (REF_FACE_Y, TOP0[1] + RAIL_HEIGHT / COS)
    floor = [TOP0, at(CHANNEL_LENGTH, 0), at(CHANNEL_LENGTH, -FLOOR), bottom_end]
    rail = [rail_end, at(CHANNEL_LENGTH, RAIL_HEIGHT), at(CHANNEL_LENGTH, -FLOOR), bottom_end]
    lug_drop = LUG_DEPTH * math.tan(math.radians(SLOPE))
    lug = [rail_end, (REF_FACE_Y - LUG_DEPTH, rail_end[1] - lug_drop), (REF_FACE_Y - LUG_DEPTH, bottom_end[1] - lug_drop), bottom_end]

    ramp = prism(floor, -CHANNEL, CHANNEL)
    for sx in (-1, 1):
        ramp += prism(rail, *sorted((sx * CHANNEL, sx * RAIL_OUT)))
        ramp += prism(lug, *sorted((sx * (RAIL_OUT - 0.01), sx * LUG_OUT)))
    for x, z in LUG_SCREWS:  # clearance; the frame takes the self-tapping thread
        ramp -= Cylinder(M4_CLEARANCE / 2, LUG_DEPTH + 2, rotation=(90, 0, 0)).moved(Location((x, REF_FACE_Y - LUG_DEPTH / 2, z)))

    led_y, led_z = at(SENSOR_AT, BEAM_HEIGHT)
    pilot_y, pilot_z = at(SENSOR_AT - BEAM_LED_TO_HOLE, BEAM_HEIGHT)
    for sx in (-1, 1):
        ramp -= across(led_y, led_z, LED_HOLE, sx * (CHANNEL - 1), sx * (RAIL_OUT + 1))
        # screw pilots right through the rail: M2.5 x 12 ends 2 mm short of the channel, M4 x 10 ~0.2 mm
        ramp -= across(pilot_y, pilot_z, M2_5_SELF_TAP_PILOT, sx * (CHANNEL - 1), sx * (RAIL_OUT + 1))
        for js, jh in JOINT_SCREWS:
            ramp -= across(*at(js, jh), M4_SELF_TAP_PILOT, sx * (CHANNEL - 1), sx * (RAIL_OUT + 1))

    if test:
        h = RAIL_HEIGHT + 1
        slab = [at(TEST_SPAN[0], -FLOOR - 1), at(TEST_SPAN[1], -FLOOR - 1), at(TEST_SPAN[1], h), at(TEST_SPAN[0], h)]
        ramp = ramp & prism(slab, -LUG_OUT - 1, LUG_OUT + 1)
    return ramp


TO_PRINT = Rot(X=-SLOPE)  # floor underside onto the bed


def build(test: bool = False) -> Part:
    part = TO_PRINT * assembled(test)
    return part.moved(Location((0, 0, -part.bounding_box().min.Z)))


if __name__ == "__main__":
    export(build(), "chute_ramp")
    export(build(test=True), "chute_ramp_test")
