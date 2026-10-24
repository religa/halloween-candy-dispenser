"""Driver case: open-top tray for the TB6600, the RJ45 screw-terminal adapter and the 24 V C14 inlet.

The TB6600 lies flat on the floor, label face up, its slotted base plate against the -X wall
and its terminals facing the +X wall, which carries the connectors: the C14 inlet (flange
outside, two M3 screws and nuts) in front of the driver's power terminals and the RJ45 adapter
(the same mount as the electronics case) in front of its signal terminals. The motor cable
leaves through a notch in the +X wall top between them; two more notches in each Y wall
take any other cables.

Two M4 self-tapping screws go through the U-slots in the plate's ends into bosses on the
outside of the -X wall. A screwdriver reaches them from the +X side, past the ends of the
driver: through the C14 cut-out (screw the driver in before fitting the C14) and through an
access hole beyond the RJ45. A grid of M4 holes in the floor screws the case to the bucket:
use whichever line up best; the ones under the driver are covered once it's in.

Print floor down; no supports. build(test=True) is only the connector wall.
"""

from build123d import BuildPart, Cylinder, Location, Locations, Mode, Part, Rot
from common import CLEARANCE, WALL, export
from electronics_case import ON_BED, box, rj45_mount
from hardware import (
    C14_BODY_HEIGHT,
    C14_BODY_WIDTH,
    C14_DEPTH,
    C14_FLANGE_WIDTH,
    C14_HOLE_SPACING,
    M3_CLEARANCE,
    M3_NUT_FLATS,
    M4_CLEARANCE,
    M4_SELF_TAP_PILOT,
    RJ45_BODY_LENGTH,
    RJ45_BODY_WIDTH,
    RJ45_TERMINAL_LENGTH,
    TB6600_LENGTH,
    TB6600_SLOT_HEIGHT,
    TB6600_SLOT_INSET,
    TB6600_TERMINALS,
    TB6600_WIDTH,
)

FLOOR = WALL
WALL_HEIGHT = 28.0  # above the floor; the driver's top (hardware TB6600_HEIGHT), over the C14 flange
BOSS = (10.0, 6.0)  # slot screw bosses on the outside of the -X wall: diameter, wall + boss depth
C14_GAP = 6.0  # TB6600's terminal face to the C14's tabs: room for the spade connectors
RJ45_GAP = 12.0  # TB6600's terminals to the RJ45 terminal block: wires bend here
FRONT_GAP = 14.0  # -Y wall to the driver: the C14 flange stays on the case
BACK_GAP = 8.0  # driver to the +Y wall
ACCESS_HOLE = 8.0  # through the +X wall, in line with the far slot screw
C14_SCREW_OFFSET = 6.0  # C14 centre past the near slot screw; the screwdriver goes through its cut-out
SIGNAL_OFFSET = 15.0  # RJ45 past the driver's centre: in front of the signal terminals (PUL/DIR/ENA end)
MOTOR_OFFSET = -6.5  # motor cable notch from the driver's centre: in front of A+/A-/B+/B-
CABLE_NOTCH = (8.0, 10.0)  # in the wall tops: width, depth
SIDE_NOTCHES_X = (30.0, 80.0)  # in both Y walls: beside the driver, and between its terminals and the connectors
MOUNT_COLUMNS = 4
MOUNT_ROWS = 6
NUT_ROOM = M3_NUT_FLATS / 2 + 1.0  # C14 screw hole centre to the RJ45 body, inside

TB_X0 = WALL  # base plate
TB_X1 = TB_X0 + TB6600_WIDTH + CLEARANCE  # terminal face
END_INSIDE = TB_X1 + TB6600_TERMINALS + max(C14_GAP + C14_DEPTH - WALL - TB6600_TERMINALS, RJ45_GAP + RJ45_TERMINAL_LENGTH + RJ45_BODY_LENGTH + CLEARANCE)
LENGTH = END_INSIDE + WALL
HEIGHT = FLOOR + WALL_HEIGHT
TB_Y0 = WALL + FRONT_GAP
TB_Y1 = TB_Y0 + TB6600_LENGTH + 2 * CLEARANCE
TB_MID_Y = (TB_Y0 + TB_Y1) / 2
WIDTH = TB_Y1 + BACK_GAP + WALL
SLOT_Z = FLOOR + TB6600_SLOT_HEIGHT
SLOT_SCREWS_Y = (TB_Y0 + CLEARANCE + TB6600_SLOT_INSET, TB_Y1 - CLEARANCE - TB6600_SLOT_INSET)
C14_Y = SLOT_SCREWS_Y[0] + C14_SCREW_OFFSET  # power terminals (VCC/GND) are at the -Y end
C14_Z = FLOOR + C14_BODY_HEIGHT / 2 + 1.0  # centre: the body clears the floor inside
RJ45_Y = TB_MID_Y + SIGNAL_OFFSET
MOTOR_NOTCH_Y = TB_MID_Y + MOTOR_OFFSET
MOUNT_X = tuple(
    TB_X0 + 8.0 + i * (TB_X1 + TB6600_TERMINALS + RJ45_GAP / 2 - TB_X0 - 8.0) / (MOUNT_COLUMNS - 1) for i in range(MOUNT_COLUMNS)
)  # last column: between the terminals and the connectors
MOUNT_Y = tuple(
    WALL + FRONT_GAP / 2 + i * (TB_Y1 - TB_Y0 + (FRONT_GAP + BACK_GAP) / 2) / (MOUNT_ROWS - 1) for i in range(MOUNT_ROWS)
)  # first and last rows: in the strips beside the driver
MOUNT_HOLES = tuple((x, y) for y in MOUNT_Y for x in MOUNT_X)

assert C14_Y - C14_FLANGE_WIDTH / 2 >= 0
assert RJ45_Y - RJ45_BODY_WIDTH / 2 - CLEARANCE - NUT_ROOM >= C14_Y + C14_HOLE_SPACING / 2
assert abs(SLOT_SCREWS_Y[0] - C14_Y) + ACCESS_HOLE / 2 < C14_BODY_WIDTH / 2  # the screw head passes the cut-out


def build(test: bool = False) -> Part:
    with BuildPart() as case:
        box(0, LENGTH, 0, WIDTH, 0, HEIGHT)
        box(WALL, END_INSIDE, WALL, WIDTH - WALL, FLOOR, HEIGHT, mode=Mode.SUBTRACT)

        # TB6600: bosses and pilots for the slot screws in the -X wall, access hole in the +X wall
        with Locations(*[Location((0, y, SLOT_Z)) * Rot(0, -90, 0) for y in SLOT_SCREWS_Y]):
            Cylinder(BOSS[0] / 2, BOSS[1] - WALL, align=ON_BED)
        with Locations(*[Location((WALL, y, SLOT_Z)) * Rot(0, -90, 0) for y in SLOT_SCREWS_Y]):
            Cylinder(M4_SELF_TAP_PILOT / 2, BOSS[1], align=ON_BED, mode=Mode.SUBTRACT)
        with Locations(Location((END_INSIDE, SLOT_SCREWS_Y[1], SLOT_Z)) * Rot(0, 90, 0)):
            Cylinder(ACCESS_HOLE / 2, WALL, align=ON_BED, mode=Mode.SUBTRACT)

        rj45_mount(END_INSIDE, RJ45_Y, HEIGHT)

        # C14: body cut-out and two M3 holes in the +X wall
        box(
            END_INSIDE,
            LENGTH,
            C14_Y - C14_BODY_WIDTH / 2 - CLEARANCE,
            C14_Y + C14_BODY_WIDTH / 2 + CLEARANCE,
            C14_Z - C14_BODY_HEIGHT / 2 - CLEARANCE,
            C14_Z + C14_BODY_HEIGHT / 2 + CLEARANCE,
            Mode.SUBTRACT,
        )
        with Locations(*[Location((END_INSIDE, C14_Y + s * C14_HOLE_SPACING / 2, C14_Z)) * Rot(0, 90, 0) for s in (-1, 1)]):
            Cylinder(M3_CLEARANCE / 2, WALL, align=ON_BED, mode=Mode.SUBTRACT)

        box(END_INSIDE, LENGTH, MOTOR_NOTCH_Y - CABLE_NOTCH[0] / 2, MOTOR_NOTCH_Y + CABLE_NOTCH[0] / 2, HEIGHT - CABLE_NOTCH[1], HEIGHT, Mode.SUBTRACT)
        for x in SIDE_NOTCHES_X:
            for y0 in (0, WIDTH - WALL):
                box(x - CABLE_NOTCH[0] / 2, x + CABLE_NOTCH[0] / 2, y0, y0 + WALL, HEIGHT - CABLE_NOTCH[1], HEIGHT, Mode.SUBTRACT)

        with Locations(*[(x, y, 0) for x, y in MOUNT_HOLES]):
            Cylinder(M4_CLEARANCE / 2, FLOOR, align=ON_BED, mode=Mode.SUBTRACT)

        if test:
            box(-BOSS[1], END_INSIDE - C14_DEPTH + WALL - 2.0, 0, WIDTH, 0, HEIGHT, Mode.SUBTRACT)
    part = case.part
    if test:
        part = part.moved(Location((-part.bounding_box().min.X, 0, 0)))
    return part


if __name__ == "__main__":
    export(build(), "driver_case")
    export(build(test=True), "driver_case_test")
