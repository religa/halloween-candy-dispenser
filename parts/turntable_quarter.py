"""Quarter of the 260 mm candy turntable, sized for the Bambu A1 mini plate.

Print 4x, one per plate, flat with the base on the bed and the ribs up; no supports.
The quarter spans 0-90 degrees with the full disc's centre at the origin. Four copies
rotated 90 degrees apart make the disc. The reference turntable connector
(ref/automatic-candy-dispenser/turntable connector.stl) bolts under each seam.
"""

import math

from build123d import (
    Align,
    BuildPart,
    BuildSketch,
    Circle,
    Locations,
    Mode,
    Part,
    Plane,
    PolarLocations,
    Rectangle,
    extrude,
)
from common import CLEARANCE, export
from hardware import BEARING_HOLE, BEARING_RADIUS

RADIUS = 130.0  # matches ref turntable half.stl
HUB_RADIUS = 5.0  # centre notch, matches ref turntable half.stl
BASE = 5.0  # plate thickness, matches ref turntable half.stl
RIB_HEIGHT = 2.0  # matches ref turntable half.stl
RIB_WIDTH = 2.0  # matches ref turntable half.stl
RIB_ANGLES = (22.5, 67.5)  # 8 ribs on the full disc, 45 degrees apart, none on a seam
SEAM_GAP = CLEARANCE / 2  # each straight edge set back so 4 quarters don't bind

BEARING_ANGLE = 45.0  # turntable side: bearing holes on each quarter's bisector

CONNECTOR_RADIUS = 120.0  # matches ref turntable connector.stl
CONNECTOR_ANGLES = (15.0, 75.0)  # 15 degrees from each seam, matches ref turntable connector.stl
CONNECTOR_HOLE = 6.0  # matches ref turntable connector.stl


def polar(r: float, deg: float) -> tuple[float, float]:
    return (r * math.cos(math.radians(deg)), r * math.sin(math.radians(deg)))


def keep_inside_quarter():
    """Clip the current sketch to the quarter outline: rim circle and set-back seam edges."""
    Circle(RADIUS, mode=Mode.INTERSECT)
    with Locations((SEAM_GAP, SEAM_GAP)):
        Rectangle(RADIUS, RADIUS, align=(Align.MIN, Align.MIN), mode=Mode.INTERSECT)


def build() -> Part:
    with BuildPart() as quarter:
        with BuildSketch():
            Circle(RADIUS)
            keep_inside_quarter()
            Circle(HUB_RADIUS, mode=Mode.SUBTRACT)
            with Locations(polar(BEARING_RADIUS, BEARING_ANGLE)):
                Circle(BEARING_HOLE / 2, mode=Mode.SUBTRACT)
            with Locations(*[polar(CONNECTOR_RADIUS, a) for a in CONNECTOR_ANGLES]):
                Circle(CONNECTOR_HOLE / 2, mode=Mode.SUBTRACT)
        extrude(amount=BASE)
        with BuildSketch(Plane.XY.offset(BASE)):
            for a in RIB_ANGLES:
                with PolarLocations((HUB_RADIUS + RADIUS) / 2, 1, start_angle=a):
                    Rectangle(RADIUS - HUB_RADIUS, RIB_WIDTH)
            keep_inside_quarter()  # a rib moved onto a seam must not poke into the next quarter
        extrude(amount=RIB_HEIGHT)
    return quarter.part


if __name__ == "__main__":
    export(build(), "turntable_quarter")
