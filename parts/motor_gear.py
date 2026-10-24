"""14-tooth pinion for the 23HS5628 motor's 6.35 mm D-shaft.

Print teeth-down (the hub is narrower than the teeth, so nothing overhangs); no
supports. In the assembly it is flipped: teeth from z -9.5 to -0.5 under the turntable,
the hub down to -17, 1 mm above the stand. Drop an M3 nut into the slot from the hub
end, start the M3 set screw a turn so the nut can't fall out, then slide the pinion on
with the shaft's flat facing the screw.
"""

import math

from build123d import (
    Align,
    Box,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Location,
    Locations,
    Mode,
    Part,
    Polygon,
    Rectangle,
    extrude,
)
from common import CLEARANCE, export
from gearing import FACE_WIDTH, MOTOR_TEETH, gear_outline
from hardware import (
    M3_CLEARANCE,
    M3_NUT_FLATS,
    M3_NUT_THICKNESS,
    SHAFT_DIAMETER,
    SHAFT_FLAT_ACROSS,
)

TURNTABLE_GAP = 0.5  # teeth stop short of the turntable underside
BEARING_GAP = 0.5  # and of the bearing's top plate
TOOTH_LENGTH = FACE_WIDTH - TURNTABLE_GAP - BEARING_GAP
HUB_LENGTH = 7.5  # the hub ends 1 mm above the stand plate
HUB_DIAMETER = 18.0  # inner edge r 71 from the turntable axis clears the bearing top plate's r 67.2 sweep
SET_SCREW_Z = TOOTH_LENGTH + HUB_LENGTH / 2
FLAT_X = SHAFT_FLAT_ACROSS - SHAFT_DIAMETER / 2 + CLEARANCE  # the bore's flat, facing +X
NUT_WALL = 1.2  # plastic between the bore flat and the nut
NUT_WIDTH = M3_NUT_FLATS + CLEARANCE  # slot width along Y; the nut's flats face +-Y
NUT_SLOT_THICKNESS = M3_NUT_THICKNESS + CLEARANCE  # along X
NUT_CORNERS = NUT_WIDTH / math.cos(math.radians(30))  # the nut stands across-corners in Z
UP = (Align.CENTER, Align.CENTER, Align.MIN)


def build() -> Part:
    length = TOOTH_LENGTH + HUB_LENGTH
    with BuildPart() as pinion:
        with BuildSketch():
            Polygon(*gear_outline(MOTOR_TEETH), align=None)
        extrude(amount=TOOTH_LENGTH)
        with Locations((0, 0, TOOTH_LENGTH)):
            Cylinder(HUB_DIAMETER / 2, HUB_LENGTH, align=UP)

        with BuildSketch():  # D-bore
            Circle((SHAFT_DIAMETER + CLEARANCE) / 2)
            with Locations((FLAT_X, 0)):
                Rectangle(SHAFT_DIAMETER, 2 * SHAFT_DIAMETER, align=(Align.MIN, Align.CENTER), mode=Mode.SUBTRACT)
        extrude(amount=length, mode=Mode.SUBTRACT)

        with Locations(Location((0, 0, SET_SCREW_Z), (0, 90, 0))):  # set-screw hole along +X
            Cylinder(M3_CLEARANCE / 2, HUB_DIAMETER, align=UP, mode=Mode.SUBTRACT)

        slot_bottom = SET_SCREW_Z - NUT_CORNERS / 2  # nut centred on the set screw
        with Locations((FLAT_X + NUT_WALL, 0, slot_bottom)):
            Box(
                NUT_SLOT_THICKNESS,
                NUT_WIDTH,
                length - slot_bottom,
                align=(Align.MIN, Align.CENTER, Align.MIN),
                mode=Mode.SUBTRACT,
            )
    return pinion.part


if __name__ == "__main__":
    export(build(), "motor_gear")
