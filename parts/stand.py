"""Compact stand: holds the bearing on top and the motor hanging below, inside the bucket.

Print upside down: the plate's top face on the bed, legs up; no supports. In the
assembly it is flipped, with the plate's top face under the bearing (z -18) and the legs
on the bucket floor. The motor (23HS5628) bolts under the plate at +X; the bearing's
bottom plate screws on top with the nuts underneath, where the legs leave room for them.
Top-plate screws go in from below past the plate edge at (0, +-58).

Test variant (build(test=True)): the plate only, 4 mm thick, to check the bearing and
motor holes against the real parts.
"""

import motor_gear
from build123d import (
    Align,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Locations,
    Mode,
    Part,
    Plane,
    Rectangle,
    SlotCenterToCenter,
    extrude,
)
from common import CLEARANCE, export
from gearing import CENTER_DISTANCE, FACE_WIDTH
from hardware import (
    BEARING_HOLE,
    BEARING_SPACING,
    BEARING_THICKNESS,
    M4_SELF_TAP_PILOT,
    M5_CLEARANCE,
    M5_CSK_HEAD,
    NEMA23_FLANGE,
    NEMA23_HOLE_SPACING,
    NEMA23_PILOT,
    SHAFT_LENGTH,
)

PLATE_X = (-50.0, 113.0)  # past the bearing at -X; at +X, WALL around the slotted countersinks
PLATE_HALF_Y = 52.0  # leaves the top-plate screw path at y +-58 open
PLATE_THICKNESS = 6.0
STAND_HEIGHT = 75.0  # matches ref stand.stl; the 56 mm motor ends 13 mm above the floor
LEG = 20.0
MINUS_X_LEG_Y = 12.0  # -X legs sit inboard, clear of the bearing nuts at y +-41
LEGS = (  # (x0, y0, x1, y1): +X pair flanks the motor, -X pair inboard of the bearing nuts
    (PLATE_X[1] - LEG, PLATE_HALF_Y - LEG, PLATE_X[1], PLATE_HALF_Y),
    (PLATE_X[1] - LEG, -PLATE_HALF_Y, PLATE_X[1], -PLATE_HALF_Y + LEG),
    (PLATE_X[0], MINUS_X_LEG_Y, PLATE_X[0] + LEG, MINUS_X_LEG_Y + LEG),
    (PLATE_X[0], -MINUS_X_LEG_Y - LEG, PLATE_X[0] + LEG, -MINUS_X_LEG_Y),
)
LEG_PILOT_DEPTH = 20.0  # M4 x 20 self-tapping screws come up through the ~2.5 mm bucket floor
CENTER_HOLE = 50.0  # wires; inside the 54 mm bearing bore
NUT_KEEPOUT = 5.0  # radius kept free under each bearing bottom-plate nut
TEST_THICKNESS = 4.0  # deeper than the 3.05 mm countersinks
# Flat-head motor screws: the inner pair sits inside the bearing top plate's r 67.2 sweep,
# so the heads must not stand above the plate top (z 0 here, the bed face).
CSK_RADIUS = M5_CSK_HEAD / 2 + CLEARANCE
CSK_DEPTH = CSK_RADIUS - M5_CLEARANCE / 2  # 90 degree countersink
# Riser under the plate that lowers the motor, so its shaft tip ends SHAFT_CLEARANCE under
# the pinion's top instead of reaching the turntable (the 23HS5628 shaft is 28 mm, not 20.6).
SHAFT_CLEARANCE = 1.0
_PLATE_UNDERSIDE = -(FACE_WIDTH + BEARING_THICKNESS + PLATE_THICKNESS)  # assembly z, turntable underside = 0
MOTOR_PAD = max(0.0, _PLATE_UNDERSIDE + SHAFT_LENGTH - (-motor_gear.TURNTABLE_GAP - SHAFT_CLEARANCE))
MOTOR_ADJUST = 1.0  # the motor slides +-this along X in slotted holes to tune the gear mesh
UP = (Align.CENTER, Align.CENTER, Align.MIN)


def leg_centres() -> list[tuple[float, float]]:
    return [((x0 + x1) / 2, (y0 + y1) / 2) for x0, y0, x1, y1 in LEGS]


def motor_holes() -> list[tuple[float, float]]:
    h = NEMA23_HOLE_SPACING / 2
    return [(CENTER_DISTANCE + sx * h, sy * h) for sx in (-1, 1) for sy in (-1, 1)]


def motor_slots(width: float):
    """Slots along X at the motor pilot and screw positions, for the mesh adjustment."""
    with Locations((CENTER_DISTANCE, 0)):
        SlotCenterToCenter(2 * MOTOR_ADJUST, NEMA23_PILOT + 2 * CLEARANCE)
    with Locations(*motor_holes()):
        SlotCenterToCenter(2 * MOTOR_ADJUST, width)


def build(test: bool = False) -> Part:
    thickness = TEST_THICKNESS if test else PLATE_THICKNESS
    bearing = BEARING_SPACING / 2
    with BuildPart() as stand:
        with BuildSketch():
            with Locations(((PLATE_X[0] + PLATE_X[1]) / 2, 0)):
                Rectangle(PLATE_X[1] - PLATE_X[0], 2 * PLATE_HALF_Y)
            Circle(CENTER_HOLE / 2, mode=Mode.SUBTRACT)
            with Locations(*[(sx * bearing, sy * bearing) for sx in (-1, 1) for sy in (-1, 1)]):
                Circle(BEARING_HOLE / 2, mode=Mode.SUBTRACT)
        extrude(amount=thickness)

        pad = 0.0 if test else MOTOR_PAD
        if not test:
            with BuildSketch(Plane.XY.offset(thickness)):
                for x0, y0, x1, y1 in LEGS:
                    with Locations(((x0 + x1) / 2, (y0 + y1) / 2)):
                        Rectangle(x1 - x0, y1 - y0)
            extrude(amount=STAND_HEIGHT - thickness)
            if pad:
                with BuildSketch(Plane.XY.offset(thickness)), Locations((CENTER_DISTANCE, 0)):
                    Rectangle(NEMA23_FLANGE + 2 * MOTOR_ADJUST, NEMA23_FLANGE)
                extrude(amount=pad)
            with Locations(*[(x, y, STAND_HEIGHT - LEG_PILOT_DEPTH) for x, y in leg_centres()]):
                Cylinder(M4_SELF_TAP_PILOT / 2, LEG_PILOT_DEPTH, align=UP, mode=Mode.SUBTRACT)

        with BuildSketch():  # pilot and screw slots through the plate and the pad
            motor_slots(M5_CLEARANCE)
        extrude(amount=thickness + pad, mode=Mode.SUBTRACT)
        with BuildSketch(), Locations(*motor_holes()):  # 90 degree countersinks for the flat heads, slotted too
            SlotCenterToCenter(2 * MOTOR_ADJUST, 2 * CSK_RADIUS)
        extrude(amount=CSK_DEPTH, taper=45, mode=Mode.SUBTRACT)
    return stand.part


if __name__ == "__main__":
    export(build(), "stand")
    export(build(test=True), "stand_test")
