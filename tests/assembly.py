"""Parts placed in the assembly frame, for clearance tests.

Origin on the turntable axis, z = 0 the turntable underside, motor on +X. Every height is
derived from the parts' own constants.
"""

import math
from pathlib import Path

import motor_gear as mg
import numpy as np
import stand
import trimesh
import turntable_gear as tg
from gearing import CENTER_DISTANCE, FACE_WIDTH
from hardware import (
    BEARING_PLATE,
    BEARING_THICKNESS,
    MOTOR_BODY_LENGTH,
    NEMA23_FLANGE,
)
from mesh_checks import export_mesh, rotated

GEAR_BOTTOM = -FACE_WIDTH  # the gear hangs under the turntable
BEARING_BOTTOM = GEAR_BOTTOM - BEARING_THICKNESS  # = the stand plate's top face
PLATE_UNDERSIDE = BEARING_BOTTOM - stand.PLATE_THICKNESS
MOTOR_FACE = PLATE_UNDERSIDE - stand.MOTOR_PAD  # the motor flange's face, under the riser pad
FLOOR = BEARING_BOTTOM - stand.STAND_HEIGHT
PINION_TOP = -mg.TURNTABLE_GAP
TOP_PLATE_SWEEP = BEARING_PLATE / math.sqrt(2)  # radius the rotating top plate's corners reach

MIRROR_Z = np.diag([1.0, 1.0, -1.0, 1.0])


def flipped(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Mirror in z: parts are modelled in their print orientation, upside down here."""
    return mesh.copy().apply_transform(MIRROR_Z)


def placed_stand(out: Path) -> trimesh.Trimesh:
    mesh = flipped(export_mesh(stand.build(), "stand", out))
    mesh.apply_translation([0, 0, BEARING_BOTTOM])
    return mesh


def placed_gear(out: Path) -> trimesh.Trimesh:
    return flipped(export_mesh(tg.build(), "turntable_gear", out))  # turntable face stays at z 0


def placed_pinion(pinion: trimesh.Trimesh, angle: float, offset_x: float = 0.0) -> trimesh.Trimesh:
    """pinion: the motor_gear mesh in its print frame (teeth on the bed); offset_x slides it in the motor slots."""
    mesh = rotated(flipped(pinion), angle)
    mesh.apply_translation([CENTER_DISTANCE + offset_x, 0, PINION_TOP])
    return mesh


def motor_proxy(inflate: float = 0.0, offset_x: float = 0.0, offset_y: float = 0.0) -> trimesh.Trimesh:
    """The motor body as a box hanging from the riser pad, optionally grown sideways and down."""
    side = NEMA23_FLANGE + 2 * inflate
    length = MOTOR_BODY_LENGTH + inflate
    box = trimesh.creation.box(extents=[side, side, length])
    box.apply_translation([CENTER_DISTANCE + offset_x, offset_y, MOTOR_FACE - length / 2])  # body length includes the flange
    return box


def top_plate_sweep() -> trimesh.Trimesh:
    """Everything the rotating bearing top plate can reach, over the bearing's whole height."""
    cylinder = trimesh.creation.cylinder(radius=TOP_PLATE_SWEEP, height=BEARING_THICKNESS, sections=128)
    cylinder.apply_translation([0, 0, (BEARING_BOTTOM + GEAR_BOTTOM) / 2])
    return cylinder
