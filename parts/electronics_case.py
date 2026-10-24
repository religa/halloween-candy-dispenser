"""Electronics case: open-top tray for the Arduino Uno and the RJ45 screw-terminal adapter.

The Uno sits on four standoffs, held by M3 x 8 self-tapping screws, with its USB and barrel
jack in notches in the -X end wall. The RJ45 adapter lies on the floor at the +X end: its
nose drops into a notch in the end wall, so the socket faces out and the shoulders of its
wide body bear on the wall's inside when the plug is pulled. Two L posts behind the body
stop it when the plug is pushed in, and a zip tie over the body, through the floor slots
and along the groove underneath, holds it down. The green terminal block faces the Uno
across the wiring gap; the two M4 holes in the gap screw the case down.

Print floor down; no supports. The underside groove is a short bridge.
build(test=True) is only the RJ45 end, to check the adapter's estimated sizes first.
"""

from build123d import Align, Box, BuildPart, Cylinder, Location, Locations, Mode, Part
from common import CLEARANCE, WALL, export
from hardware import (
    M3_SELF_TAP_PILOT,
    M4_CLEARANCE,
    RJ45_BODY_LENGTH,
    RJ45_BODY_WIDTH,
    RJ45_NOSE_WIDTH,
    RJ45_TERMINAL_LENGTH,
    RJ45_TERMINAL_WIDTH,
    UNO_HOLES,
    UNO_JACK_Y,
    UNO_LENGTH,
    UNO_THICKNESS,
    UNO_UNDERSIDE,
    UNO_USB_Y,
    UNO_WIDTH,
)

FLOOR = WALL
BOARD_GAP = 1.0  # board edge to wall, all round
STANDOFF = UNO_UNDERSIDE + 2.0  # floor to the board's underside
STANDOFF_DIAMETER = 6.0
PILOT_FLOOR = 1.0  # floor left under each standoff's pilot hole
WALL_HEIGHT = 20.0  # above the floor; over the USB socket's top (hardware UNO_USB_HEIGHT)
NOTCH_MARGIN = 1.0  # each side of the USB socket and barrel jack
WIRE_GAP = 22.0  # terminal block to the board's edge: wires bend here, M4 holes for mounting
POST = 3.0  # L posts behind the RJ45 body: thickness
POST_ARM = 3.0  # along the body's sides; the zip tie goes round the rest
POST_HEIGHT = 12.0
TIE_SLOT = (5.0, 2.5)  # zip tie slot through the floor (along X, across Y), beside the body
TIE_GROOVE_DEPTH = 1.2  # under the floor, slot to slot, so the case still sits flat

INNER_WIDTH = UNO_WIDTH + 2 * BOARD_GAP
BOARD_X = WALL + BOARD_GAP  # board frame origin in the case
BOARD_Y = WALL + BOARD_GAP
BOARD_TOP = FLOOR + STANDOFF + UNO_THICKNESS
BODY_BACK = BOARD_X + UNO_LENGTH + WIRE_GAP + RJ45_TERMINAL_LENGTH  # back face of the RJ45 body
END_INSIDE = BODY_BACK + RJ45_BODY_LENGTH + CLEARANCE  # inside of the +X wall; the shoulders bear on it
LENGTH = END_INSIDE + WALL
WIDTH = INNER_WIDTH + 2 * WALL
HEIGHT = FLOOR + WALL_HEIGHT
RJ45_Y = WIDTH / 2  # adapter centre line
BODY_HALF = RJ45_BODY_WIDTH / 2 + CLEARANCE
TIE_Y = BODY_HALF + TIE_SLOT[1] / 2  # slot centres, each side of RJ45_Y
TIE_X = BODY_BACK + (POST_ARM + RJ45_BODY_LENGTH) / 2  # between the post arms and the shoulders
MOUNT_HOLES = tuple((BOARD_X + UNO_LENGTH + WIRE_GAP / 2, WIDTH / 2 + s * INNER_WIDTH / 3) for s in (-1, 1))

CORNER = (Align.MIN, Align.MIN, Align.MIN)
ON_BED = (Align.CENTER, Align.CENTER, Align.MIN)


def box(x0: float, x1: float, y0: float, y1: float, z0: float, z1: float, mode: Mode = Mode.ADD):
    """Axis-aligned box between the given coordinates."""
    with Locations((x0, y0, z0)):
        Box(x1 - x0, y1 - y0, z1 - z0, align=CORNER, mode=mode)


def rj45_mount(end_inside: float, y: float, top: float, floor: float = FLOOR):
    """RJ45 adapter in the +X end wall, inside an active BuildPart: nose notch from the floor
    up to `top`, L posts behind the body, zip tie slots and the groove under the floor."""
    body_back = end_inside - CLEARANCE - RJ45_BODY_LENGTH
    nose_half = RJ45_NOSE_WIDTH / 2 + CLEARANCE
    box(end_inside, end_inside + WALL, y - nose_half, y + nose_half, floor, top, Mode.SUBTRACT)
    stop = RJ45_TERMINAL_WIDTH / 2 + CLEARANCE  # posts stay clear of the terminal block
    for s in (-1, 1):
        y_in, y_out = sorted((y + s * stop, y + s * (BODY_HALF + POST)))
        box(body_back - POST, body_back, y_in, y_out, floor, floor + POST_HEIGHT)
        y_in, y_out = sorted((y + s * BODY_HALF, y + s * (BODY_HALF + POST)))
        box(body_back, body_back + POST_ARM, y_in, y_out, floor, floor + POST_HEIGHT)
    tie_x = body_back + (POST_ARM + RJ45_BODY_LENGTH) / 2  # between the post arms and the shoulders
    with Locations(*[(tie_x, y + s * TIE_Y, 0) for s in (-1, 1)]):
        Box(*TIE_SLOT, floor, align=ON_BED, mode=Mode.SUBTRACT)
    with Locations((tie_x, y, 0)):
        Box(TIE_SLOT[0], 2 * TIE_Y + TIE_SLOT[1], TIE_GROOVE_DEPTH, align=ON_BED, mode=Mode.SUBTRACT)


def build(test: bool = False) -> Part:
    with BuildPart() as case:
        box(0, LENGTH, 0, WIDTH, 0, HEIGHT)
        box(WALL, END_INSIDE, WALL, WIDTH - WALL, FLOOR, HEIGHT, mode=Mode.SUBTRACT)

        # Uno: standoffs with pilot holes, notches for the USB socket and barrel jack
        holes = [(BOARD_X + x, BOARD_Y + y) for x, y in UNO_HOLES]
        with Locations(*[(x, y, FLOOR) for x, y in holes]):
            Cylinder(STANDOFF_DIAMETER / 2, STANDOFF, align=ON_BED)
        with Locations(*[(x, y, PILOT_FLOOR) for x, y in holes]):
            Cylinder(M3_SELF_TAP_PILOT / 2, HEIGHT, align=ON_BED, mode=Mode.SUBTRACT)
        for y0, y1 in (UNO_USB_Y, UNO_JACK_Y):
            box(0, WALL, BOARD_Y + y0 - NOTCH_MARGIN, BOARD_Y + y1 + NOTCH_MARGIN, BOARD_TOP, HEIGHT, Mode.SUBTRACT)

        rj45_mount(END_INSIDE, RJ45_Y, HEIGHT)

        with Locations(*[(x, y, 0) for x, y in MOUNT_HOLES]):
            Cylinder(M4_CLEARANCE / 2, FLOOR, align=ON_BED, mode=Mode.SUBTRACT)

        if test:
            box(0, BODY_BACK - POST - WALL, 0, WIDTH, 0, HEIGHT, Mode.SUBTRACT)
            box(0, LENGTH, 0, WIDTH, FLOOR + POST_HEIGHT, HEIGHT, Mode.SUBTRACT)
    part = case.part
    if test:
        part = part.moved(Location((-part.bounding_box().min.X, 0, 0)))
    return part


if __name__ == "__main__":
    export(build(), "electronics_case")
    export(build(test=True), "electronics_case_test")
