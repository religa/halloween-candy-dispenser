"""Chute frame: the 4 x 4 in window that screws to the outside of the bucket.

Candy leaves the turntable through a hole cut in the bucket wall, the same size as the
window, and falls down the window's floor onto the chute ramp (chute_ramp.py, screwed to
the frame's flat outer face). The face against the bucket follows the bucket's tapered
outside; nothing reaches into the hole. The window's floor starts at the hole's bottom
edge, level with the turntable top, and falls at FLOOR_FALL all along the bucket's curve,
so there is no flat ledge anywhere. Where it meets the ramp, candy can only drop: the
ramp's floor starts just under the floor's lowest point, at the window's edges.

The outer face leans with the bucket's taper (2.6 degrees), which keeps the frame thin at
the top. The ramp, made for a vertical face (its reference mount), sits on it turned by
the same angle, so it runs that much steeper than its own 45 degrees: RAMP_MOUNT.

Assembly frame (assembled()): turntable axis at the origin, z = 0 the turntable
underside, the chute on -Y. Print (build()) with the flat outer face on the bed, the
bucket face up; no supports (the floor's slope is the steepest that allows that). Fixed
with 2 x M4 x 20 self-tapping screws from inside the bucket, above the candy. All screw
holes go right through the frame, square to the outer face.
"""

import math

from build123d import (
    Align,
    Box,
    BuildPart,
    BuildSketch,
    Cone,
    Cylinder,
    Location,
    Part,
    Plane,
    Polygon,
    Pos,
    Rot,
    Vector,
    extrude,
)
from chute_ramp import FLOOR, LUG_SCREWS, REF_FACE_Y, SLOPE, STEP, TOP0, WINDOW
from common import export
from hardware import (
    BUCKET_TAPER,
    BUCKET_TURNTABLE_DIAMETER,
    BUCKET_WALL,
    M4_SELF_TAP_PILOT,
)
from turntable_quarter import BASE

SILL_Z = BASE  # the hole's bottom edge, level with the turntable's top face (pocket floor)
MIN_DEPTH = 4.0  # frame thickness at x = 0, all the way up (the outer face follows the taper)
FLOOR_FALL = 45.0  # degrees: the window floor's slope, the steepest that prints unsupported
HALF_WIDTH = 70.0  # frame reaches x +-70: room for the screws beside the hole
TOP_Z = 120.0
BOTTOM_MARGIN = 6.0  # frame below the lowest point the ramp's end touches
BUCKET_SCREWS = ((-62.0, 90.0), (62.0, 90.0))  # (x, z) on the outer face: above the 43 mm candy passage
CURVE_STEPS = 40  # points along the hole's bottom edge, which follows the bucket's curve

TILT = math.degrees(math.atan(BUCKET_TAPER))  # outer face lean, matching the bucket's taper
FACE_NORMAL = Vector(0, -math.cos(math.radians(TILT)), -math.sin(math.radians(TILT)))  # outward


def inner_radius(z: float) -> float:
    """Bucket's inside radius at height z (assembly frame)."""
    return BUCKET_TURNTABLE_DIAMETER / 2 + BUCKET_TAPER * z


def outer_radius(z: float) -> float:
    return inner_radius(z) + BUCKET_WALL


def face_y(z: float) -> float:
    """y of the outer face at height z: MIN_DEPTH outside the bucket at x = 0."""
    return -(outer_radius(z) + MIN_DEPTH)


def edge_y(x: float) -> float:
    """y of the hole's bottom edge (the bucket's outside at SILL_Z) at x."""
    return -math.sqrt(outer_radius(SILL_Z) ** 2 - x**2)


def floor_at_face(x: float) -> float:
    """z where the window floor, falling at FLOOR_FALL from the hole's edge, meets the outer face."""
    t = math.tan(math.radians(FLOOR_FALL))
    # z = SILL_Z - t * (edge_y(x) - y), with y = face_y(z) = -(outer_radius(0) + MIN_DEPTH) - BUCKET_TAPER * z
    return (SILL_Z - t * (edge_y(x) + outer_radius(0) + MIN_DEPTH)) / (1 + t * BUCKET_TAPER)


RAMP_FLOOR_Z = floor_at_face(WINDOW / 2) - STEP  # just under the floor's lowest point, at the window's edges
# Reference mount -> assembly: turn about the ramp's floor-top line by TILT, then move that line onto the face.
RAMP_MOUNT = Pos(0, face_y(RAMP_FLOOR_Z), RAMP_FLOOR_Z) * Rot(X=TILT) * Pos(0, -TOP0[0], -TOP0[1])


def on_face(x: float, z_ref: float) -> Vector:
    """Where the point (x, REF_FACE_Y, z_ref) of the ramp's end face lands on the outer face."""
    return (RAMP_MOUNT * Pos(x, REF_FACE_Y, z_ref)).position


RAMP_SCREWS = tuple(on_face(x, z) for x, z in LUG_SCREWS)
BOTTOM_Z = math.floor(on_face(0, TOP0[1] - FLOOR / math.cos(math.radians(SLOPE))).Z - BOTTOM_MARGIN)


def bucket_cone() -> Cone:
    """Solid of the bucket (to its outside) over the frame's height, to subtract."""
    z0, z1 = BOTTOM_Z - 10, TOP_Z + 10
    cone = Cone(outer_radius(z0), outer_radius(z1), z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return cone.moved(Location((0, 0, z0)))


def box(x0, x1, y0, y1, z0, z1) -> Box:
    b = Box(x1 - x0, y1 - y0, z1 - z0)
    return b.moved(Location(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)))


def behind_face() -> Part:
    """Everything on the bucket's side of the outer face."""
    slab = Box(600, 300, 600, align=(Align.CENTER, Align.MIN, Align.CENTER))  # y from 0 inward
    return Pos(0, face_y(0), 0) * Rot(X=TILT) * slab


def window_floor_cut() -> Part:
    """Space above the window floor, under SILL_Z: the hole's bottom edge swept outward and down at FLOOR_FALL."""
    w = WINDOW / 2
    xs = [-w + 2 * w * i / CURVE_STEPS for i in range(CURVE_STEPS + 1)]
    far = face_y(BOTTOM_Z) - 50  # well past the outer face
    drop = SILL_Z - BOTTOM_Z + 10
    t = math.tan(math.radians(FLOOR_FALL))
    with BuildPart() as p:
        with BuildSketch(Plane.XY.offset(SILL_Z)):
            Polygon(*[(x, edge_y(x)) for x in xs], (w, far), (-w, far), align=None)
        extrude(amount=drop * math.sqrt(1 + 1 / t**2), dir=(0, -1 / t, -1))
    return p.part


def pilot(at: Vector) -> Part:
    """M4 self-tapping pilot square to the outer face, from 5 mm outside it right through the frame."""
    cyl = Cylinder(M4_SELF_TAP_PILOT / 2, 120, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return Pos(*(at + FACE_NORMAL * 5)) * Rot(X=TILT - 90) * cyl  # the cylinder's +Z turned onto the inward normal


def assembled() -> Part:
    w = WINDOW / 2
    frame = box(-HALF_WIDTH, HALF_WIDTH, -250, -100, BOTTOM_Z, TOP_Z) & behind_face()
    frame -= bucket_cone()
    frame -= box(-w, w, -250, -90, SILL_Z, SILL_Z + WINDOW)
    frame -= window_floor_cut()
    for at in [Vector(x, face_y(z), z) for x, z in BUCKET_SCREWS] + list(RAMP_SCREWS):
        frame -= pilot(at)
    return frame


TO_PRINT = Rot(X=90 - TILT)  # outer face onto the bed


def build() -> Part:
    part = TO_PRINT * assembled()
    return part.moved(Location((0, 0, -part.bounding_box().min.Z)))


if __name__ == "__main__":
    export(build(), "chute_frame")
