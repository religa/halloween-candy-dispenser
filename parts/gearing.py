"""Involute spur gears for the turntable drive: profile maths and the gear-train constants.

Hand-rolled because bd_warehouse 0.3.0's SpurGear fails on build123d 0.13.0. Outlines
are 2D point lists centred on the origin with tooth 0 on +X; parts turn them into solids
with `Polygon(*gear_outline(teeth), align=None)` (align=None keeps the centre) and extrude.
"""

import math

import numpy as np

MODULE = 2.0
PRESSURE_ANGLE = 20.0  # degrees
BACKLASH = 0.1  # mm taken off each tooth at the pitch circle, per gear
TURNTABLE_TEETH = 66  # tip diameter 136 mm, same as ref turntable gear.stl
MOTOR_TEETH = 14
CENTER_DISTANCE = MODULE * (TURNTABLE_TEETH + MOTOR_TEETH) / 2  # 80 mm, the ref motor position
FACE_WIDTH = 10.0  # matches ref turntable gear.stl


def involute(angle: float) -> float:
    return math.tan(angle) - angle


def pitch_radius(teeth: int) -> float:
    return MODULE * teeth / 2


def tip_radius(teeth: int) -> float:
    return pitch_radius(teeth) + MODULE


def root_radius(teeth: int) -> float:
    return pitch_radius(teeth) - 1.25 * MODULE


def gear_outline(teeth: int, steps: int = 12) -> list[tuple[float, float]]:
    """Closed outline (x, y) of a spur gear, centred on the origin, tooth 0 on +X."""
    pressure = math.radians(PRESSURE_ANGLE)
    pitch = pitch_radius(teeth)
    base = pitch * math.cos(pressure)
    root = root_radius(teeth)
    half_tooth = math.pi / (2 * teeth) - BACKLASH / (2 * pitch)  # half tooth angle at the pitch circle

    radii = np.linspace(max(base, root), tip_radius(teeth), steps)
    flank = [half_tooth + involute(pressure) - involute(math.acos(min(1.0, base / r))) for r in radii]
    if root < base:  # small gears: the flank runs radially below the base circle
        radii = np.concatenate([[root], radii])
        flank = [flank[0]] + flank

    points = []
    for k in range(teeth):
        centre = 2 * math.pi * k / teeth
        points += [(r, centre - f) for r, f in zip(radii, flank, strict=True)]
        points += [(r, centre + f) for r, f in zip(radii[::-1], flank[::-1], strict=True)]
    return [(r * math.cos(t), r * math.sin(t)) for r, t in points]
