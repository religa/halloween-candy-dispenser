"""Connector that joins two turntable quarters under their seam.

Same shape as Brankly's original (ref turntable connector.stl): a flat arc under the
rim, straddling one seam, with one M5 hole into each quarter. Print 4, flat; no
supports. In this frame the seam runs along +X and the turntable axis is the origin, so
in the assembly it sits at z -4..0 under the quarters, turned to each of the 4 seams.
"""

from build123d import (
    BuildPart,
    BuildSketch,
    Circle,
    Locations,
    Mode,
    Part,
    Polygon,
    extrude,
)
from common import export
from turntable_quarter import (
    CONNECTOR_ANGLES,
    CONNECTOR_HOLE,
    CONNECTOR_RADIUS,
    RADIUS,
    polar,
)

INNER_RADIUS = 110.0  # matches ref turntable connector.stl
HALF_SPAN = 30.0  # degrees either side of the seam, matches ref turntable connector.stl
THICKNESS = 4.0  # matches ref turntable connector.stl
ARC_STEPS = 60  # points along each arc of the outline


def outline() -> list[tuple[float, float]]:
    """Annular sector from INNER_RADIUS to the turntable RADIUS, +-HALF_SPAN around +X."""
    angles = [-HALF_SPAN + 2 * HALF_SPAN * i / ARC_STEPS for i in range(ARC_STEPS + 1)]
    return [polar(RADIUS, a) for a in angles] + [polar(INNER_RADIUS, a) for a in reversed(angles)]


def build() -> Part:
    hole_angle = CONNECTOR_ANGLES[0]  # the quarters' holes sit this far either side of each seam
    with BuildPart() as connector:
        with BuildSketch():
            Polygon(*outline(), align=None)
            with Locations(polar(CONNECTOR_RADIUS, hole_angle), polar(CONNECTOR_RADIUS, -hole_angle)):
                Circle(CONNECTOR_HOLE / 2, mode=Mode.SUBTRACT)
        extrude(amount=THICKNESS)
    return connector.part


if __name__ == "__main__":
    export(build(), "turntable_connector")
