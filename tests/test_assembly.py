"""The stack in the bucket: stand, bearing, gears and motor placed together."""

import math

import motor_gear as mg
import numpy as np
import pytest
import shapely
import stand
import turntable_quarter as tq
from assembly import (
    BEARING_BOTTOM,
    FLOOR,
    GEAR_BOTTOM,
    MOTOR_FACE,
    PINION_TOP,
    TOP_PLATE_SWEEP,
    motor_proxy,
    placed_gear,
    placed_pinion,
    placed_stand,
    top_plate_sweep,
)
from gearing import CENTER_DISTANCE
from hardware import (
    BEARING_HOLE,
    BEARING_PLATE_GAP,
    BEARING_RADIUS,
    BEARING_SPACING,
    BUCKET_FLOOR_DIAMETER,
    BUCKET_TURNTABLE_DIAMETER,
    M4_BUTTON_HEAD_HEIGHT,
    NEMA23_FLANGE,
    SHAFT_LENGTH,
)
from mesh_checks import export_mesh, hole_centres, overlap_volume
from turntable_quarter import polar

TOL = 0.05
BUCKET_FLOOR_LIMIT = BUCKET_FLOOR_DIAMETER / 2 - 3  # mm from the axis, leaving 3 mm to the wall
BUCKET_TURNTABLE_LIMIT = BUCKET_TURNTABLE_DIAMETER / 2 - 0.5
NO_OVERLAP_WARNING = "ignore:invalid value encountered in divide:RuntimeWarning"


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    return tmp_path_factory.mktemp("out")


@pytest.fixture(scope="module")
def stand_mesh(out):
    return placed_stand(out)


@pytest.fixture(scope="module")
def pinion_print(out):
    return export_mesh(mg.build(), "motor_gear", out)


def max_radius(mesh) -> float:
    return np.linalg.norm(mesh.vertices[:, :2], axis=1).max()


def test_stand_fits_bucket_floor(stand_mesh):
    assert max_radius(stand_mesh) <= BUCKET_FLOOR_LIMIT


def test_bucket_check_detects_wide_stand(stand_mesh):
    # Control: a stand 10 % wider must break the bucket limit.
    wide = stand_mesh.copy().apply_scale([1.1, 1.1, 1.0])
    assert max_radius(wide) > BUCKET_FLOOR_LIMIT


SLOT_ENDS = [-stand.MOTOR_ADJUST, 0.0, stand.MOTOR_ADJUST]  # the motor slides in its slots


@pytest.mark.filterwarnings(NO_OVERLAP_WARNING)
@pytest.mark.parametrize("offset", SLOT_ENDS)
def test_motor_clear_of_stand(stand_mesh, offset):
    assert overlap_volume([stand_mesh, motor_proxy(inflate=2, offset_x=offset)]) < 1e-6


def test_motor_detected_in_leg(stand_mesh):
    # Control: a motor moved 15 mm sideways runs into the +X legs.
    assert overlap_volume([stand_mesh, motor_proxy(offset_y=15)]) > 1.0


def test_motor_clear_of_floor():
    assert motor_proxy().bounds[0][2] >= FLOOR + 5


@pytest.mark.filterwarnings(NO_OVERLAP_WARNING)
@pytest.mark.parametrize("offset", SLOT_ENDS)
def test_pinion_clears_top_plate(pinion_print, offset):
    sweep = top_plate_sweep()
    for angle in np.linspace(0, 360, 6, endpoint=False):
        pinion = placed_pinion(pinion_print, angle, offset_x=offset)
        assert overlap_volume([pinion, sweep]) < 1e-6
        near_axis = np.linalg.norm(pinion.vertices[:, :2], axis=1) < TOP_PLATE_SWEEP + 1
        assert (pinion.vertices[near_axis, 2] >= GEAR_BOTTOM + 0.5 - 1e-6).all()


def test_pinion_between_stand_and_turntable(pinion_print):
    low, high = placed_pinion(pinion_print, 0).bounds[:, 2]
    assert low >= BEARING_BOTTOM + 0.5
    assert high == pytest.approx(PINION_TOP, abs=1e-4)


def test_gear_on_bearing(out):
    gear = placed_gear(out)
    assert gear.bounds[:, 2] == pytest.approx([GEAR_BOTTOM, 0.0], abs=1e-4)
    holes = [h for h in hole_centres(gear, GEAR_BOTTOM / 2) if h[2] == pytest.approx(BEARING_HOLE, abs=TOL)]
    for k in range(4):
        expected = polar(BEARING_RADIUS, tq.BEARING_ANGLE + 90 * k)
        assert min(math.dist(h[:2], expected) for h in holes) < TOL


def test_shaft_engages_pinion():
    shaft_top = MOTOR_FACE + SHAFT_LENGTH
    hub_top = PINION_TOP - mg.TOOTH_LENGTH  # where the hub meets the teeth
    assert shaft_top >= hub_top + 3
    assert shaft_top <= PINION_TOP - 1  # and stays under the turntable


def test_turntable_fits_bucket():
    assert tq.RADIUS <= BUCKET_TURNTABLE_LIMIT
    # Control: a turntable 2 mm larger in radius would not fit.
    assert tq.RADIUS + 2 > BUCKET_TURNTABLE_LIMIT


def test_bearing_nuts_clear_motor_flange():
    # The bottom-plate nuts under the stand plate must not sit where the motor flange goes.
    half = NEMA23_FLANGE / 2
    flange = shapely.box(CENTER_DISTANCE - half, -half, CENTER_DISTANCE + half, half)
    for sx in (-1, 1):
        for sy in (-1, 1):
            nut = shapely.Point(sx * BEARING_SPACING / 2, sy * BEARING_SPACING / 2).buffer(stand.NUT_KEEPOUT)
            assert not nut.intersects(flange)


def test_screw_heads_pass_between_bearing_plates():
    # Top-plate and bottom-plate M4 button heads sit at the same radius and pass each other as it turns.
    assert 2 * M4_BUTTON_HEAD_HEIGHT + 1.0 <= BEARING_PLATE_GAP
