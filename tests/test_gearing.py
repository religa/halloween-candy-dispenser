"""Involute outline maths, checked in 2D (no CAD): radii, tooth count, validity, meshing."""

import math

import numpy as np
import pytest
import shapely
from gearing import (
    BACKLASH,
    CENTER_DISTANCE,
    MOTOR_TEETH,
    TURNTABLE_TEETH,
    gear_outline,
    pitch_radius,
    root_radius,
    tip_radius,
)
from shapely import affinity

TEETH = [TURNTABLE_TEETH, MOTOR_TEETH]
SWEEP_STEPS = 25


def radii(teeth: int) -> np.ndarray:
    return np.linalg.norm(np.array(gear_outline(teeth)), axis=1)


def mesh_sweep(center_distance: float) -> tuple[float, float, float]:
    """(max overlap area, min gap, max gap) of the pair across one turntable-gear tooth pitch."""
    gear = shapely.Polygon(gear_outline(TURNTABLE_TEETH))
    pinion = shapely.Polygon(gear_outline(MOTOR_TEETH))
    worst, gap, widest = 0.0, math.inf, 0.0
    for angle in np.linspace(0, 360 / TURNTABLE_TEETH, SWEEP_STEPS):
        g = affinity.rotate(gear, angle, origin=(0, 0))
        # pinion on +X: a tooth gap faces the gear, then it counter-rotates by the ratio
        phase = 180 + 180 / MOTOR_TEETH - angle * TURNTABLE_TEETH / MOTOR_TEETH
        p = affinity.translate(affinity.rotate(pinion, phase, origin=(0, 0)), center_distance, 0)
        worst = max(worst, g.intersection(p).area)
        separation = g.distance(p)  # closest approach of the two outlines at this angle
        gap = min(gap, separation)
        widest = max(widest, separation)
    return worst, gap, widest


def test_center_distance():
    assert CENTER_DISTANCE == pytest.approx(80.0)


@pytest.mark.parametrize("teeth", TEETH)
def test_outline_radii(teeth):
    r = radii(teeth)
    assert r.max() == pytest.approx(tip_radius(teeth), abs=1e-6)
    assert r.min() == pytest.approx(root_radius(teeth), abs=1e-6)


@pytest.mark.parametrize("teeth", TEETH)
def test_tooth_count(teeth):
    outside = radii(teeth) >= pitch_radius(teeth)
    rising = outside & ~np.roll(outside, 1)
    assert rising.sum() == teeth


@pytest.mark.parametrize("teeth", TEETH)
def test_outline_is_valid_polygon(teeth):
    outline = shapely.Polygon(gear_outline(teeth))
    assert outline.is_valid
    assert (outline.centroid.x, outline.centroid.y) == pytest.approx((0, 0), abs=0.01)


def test_pair_meshes_without_interference():
    worst, gap, widest = mesh_sweep(CENTER_DISTANCE)
    assert worst == 0
    assert gap > BACKLASH / 2  # teeth never touch: measured gap is ~0.9 x BACKLASH
    assert widest < 2 * BACKLASH  # and stay engaged: no extra slop at any angle


def test_interference_detected():
    # Control: pushing the gears 1 mm together must register as overlap.
    worst, _, _ = mesh_sweep(CENTER_DISTANCE - 1)
    assert worst > 1.0
