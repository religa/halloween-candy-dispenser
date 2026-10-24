"""66-tooth turntable gear: bolts under the turntable quarters and onto the bearing.

Print with the turntable face on the bed and the recess up; no supports. In the
assembly it is flipped: turntable face at z = 0, recess down over the bearing's raised
race. Its 4 holes take the same M4 screws as the quarters' bearing holes.

Test variant (build(test=True)): 4 mm thick, to check the bolt holes, the recess and
the mesh with the pinion before printing the full gear.
"""

from build123d import (
    Align,
    BuildPart,
    BuildSketch,
    Circle,
    Cylinder,
    Locations,
    Mode,
    Part,
    Polygon,
    extrude,
)
from common import export
from gearing import FACE_WIDTH, TURNTABLE_TEETH, gear_outline
from hardware import BEARING_HOLE, BEARING_RADIUS
from turntable_quarter import BEARING_ANGLE, polar

TEST_FACE_WIDTH = 4.0
CENTER_HOLE = 16.0  # matches ref turntable gear.stl; cable pass-through
RACE_RECESS_DIAMETER = 100.0  # clears the bearing race (~83 mm from the photo) inside the corner screw pads
RACE_RECESS_DEPTH = 2.0


def build(test: bool = False) -> Part:
    thickness = TEST_FACE_WIDTH if test else FACE_WIDTH
    with BuildPart() as gear:
        with BuildSketch():
            Polygon(*gear_outline(TURNTABLE_TEETH), align=None)
            Circle(CENTER_HOLE / 2, mode=Mode.SUBTRACT)
            with Locations(*[polar(BEARING_RADIUS, BEARING_ANGLE + 90 * k) for k in range(4)]):
                Circle(BEARING_HOLE / 2, mode=Mode.SUBTRACT)
        extrude(amount=thickness)
        with Locations((0, 0, thickness - RACE_RECESS_DEPTH)):
            Cylinder(
                RACE_RECESS_DIAMETER / 2,
                RACE_RECESS_DEPTH,
                align=(Align.CENTER, Align.CENTER, Align.MIN),
                mode=Mode.SUBTRACT,
            )
    return gear.part


if __name__ == "__main__":
    export(build(), "turntable_gear")
    export(build(test=True), "turntable_gear_test")
