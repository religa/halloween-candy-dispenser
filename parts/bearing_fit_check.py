"""Bearing hole-pattern test frame: print this once, before the turntable quarters.

Lay it on the lazy susan bearing; all 4 screws must drop through the holes. If they
don't, fix BEARING_SPACING / BEARING_HOLE in hardware.py (they live there only)
and reprint this frame.
"""

from build123d import (
    BuildPart,
    BuildSketch,
    Circle,
    Locations,
    Mode,
    Part,
    Rectangle,
    extrude,
)
from common import export
from hardware import BEARING_HOLE, BEARING_SPACING

FRAME = 95.0  # outer square, just over the 3.7" (94 mm) bearing plate
WINDOW = 70.0  # square cut-out to save filament
THICKNESS = 1.6


def build() -> Part:
    half = BEARING_SPACING / 2
    with BuildPart() as frame:
        with BuildSketch():
            Rectangle(FRAME, FRAME)
            Rectangle(WINDOW, WINDOW, mode=Mode.SUBTRACT)
            with Locations(*[(x, y) for x in (-half, half) for y in (-half, half)]):
                Circle(BEARING_HOLE / 2, mode=Mode.SUBTRACT)
        extrude(amount=THICKNESS)
    return frame.part


if __name__ == "__main__":
    export(build(), "bearing_fit_check")
