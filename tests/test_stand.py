"""Stand in its print frame: plate top face on the bed (z 0), legs rising to STAND_HEIGHT."""

import itertools
import math

import pytest
import shapely
import stand
from common import CLEARANCE, WALL
from gearing import CENTER_DISTANCE
from hardware import (
    BEARING_HOLE,
    BEARING_RADIUS,
    BEARING_SPACING,
    M4_SELF_TAP_PILOT,
    M5_CLEARANCE,
    M5_CSK_HEAD,
    NEMA23_FLANGE,
    NEMA23_HOLE_SPACING,
    NEMA23_PILOT,
)
from mesh_checks import export_mesh, hole_centres, section

TOL = 0.05
VARIANTS = {"default": (False, stand.STAND_HEIGHT, stand.PLATE_THICKNESS), "test": (True, stand.TEST_THICKNESS, stand.TEST_THICKNESS)}
NUTS = [(sx * BEARING_SPACING / 2, sy * BEARING_SPACING / 2) for sx in (-1, 1) for sy in (-1, 1)]


@pytest.fixture(scope="module")
def stands(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return {name: export_mesh(stand.build(test=test), f"stand_{name}", out) for name, (test, _, _) in VARIANTS.items()}


@pytest.fixture(scope="module")
def full(stands):
    return stands["default"]


def plate(mesh, variant):
    (outline,) = section(mesh, VARIANTS[variant][2] / 2)
    return outline


def has_hole(holes, centre, diameter):
    return any(math.dist(h[:2], centre) < TOL and h[2] == pytest.approx(diameter, abs=TOL) for h in holes)


def nut_positions_blocked(legs: list[shapely.Polygon]) -> list[tuple[float, float]]:
    """Bearing-nut positions under the plate that a leg covers."""
    return [nut for nut in NUTS if any(leg.intersects(shapely.Point(nut).buffer(stand.NUT_KEEPOUT)) for leg in legs)]


@pytest.mark.parametrize("variant", VARIANTS)
def test_printable(stands, variant):
    mesh = stands[variant]
    assert mesh.is_watertight
    assert mesh.body_count == 1
    assert mesh.extents[2] == pytest.approx(VARIANTS[variant][1], abs=1e-4)
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("variant", VARIANTS)
def test_bearing_holes(stands, variant):
    holes = hole_centres(stands[variant], VARIANTS[variant][2] / 2)
    for nut in NUTS:
        assert has_hole(holes, nut, BEARING_HOLE), f"no bearing hole at {nut}"


@pytest.mark.parametrize("variant", VARIANTS)
def test_motor_mount(stands, variant):
    below_countersinks = (stand.CSK_DEPTH + VARIANTS[variant][2]) / 2
    holes = hole_centres(stands[variant], below_countersinks)
    assert has_hole(holes, (CENTER_DISTANCE, 0), NEMA23_PILOT + 2 * CLEARANCE)
    h = NEMA23_HOLE_SPACING / 2
    for dx, dy in itertools.product((-h, h), repeat=2):
        assert has_hole(holes, (CENTER_DISTANCE + dx, dy), M5_CLEARANCE), f"no motor hole at {(CENTER_DISTANCE + dx, dy)}"


def test_center_hole(full):
    assert has_hole(hole_centres(full, stand.PLATE_THICKNESS / 2), (0, 0), stand.CENTER_HOLE)


@pytest.mark.parametrize("variant", VARIANTS)
def test_screw_access_open(stands, variant):
    outline = plate(stands[variant], variant)
    for y in (-BEARING_RADIUS, BEARING_RADIUS):  # top-plate screws go in from below here, turntable rotated round
        assert not outline.intersects(shapely.Point(0, y).buffer(4))


def test_nut_keepout(full):
    legs = section(full, stand.STAND_HEIGHT / 2)
    assert nut_positions_blocked(legs) == []


def test_nut_keepout_detects_corner_leg():
    # Control: the first-draft corner leg at -X sat right over a bearing nut.
    assert nut_positions_blocked([shapely.box(-50, 32, -30, 52)]) != []


def test_legs(full):
    legs = section(full, stand.STAND_HEIGHT / 2)
    assert sorted(leg.bounds for leg in legs) == pytest.approx(sorted(stand.LEGS), abs=TOL)
    near_foot = section(full, stand.STAND_HEIGHT - 5)
    for leg in near_foot:
        (hole,) = leg.interiors
        pilot = shapely.Polygon(hole)
        assert 2 * math.sqrt(pilot.area / math.pi) == pytest.approx(M4_SELF_TAP_PILOT, abs=TOL)
        assert pilot.centroid.distance(leg.centroid) < TOL
    above_pilot = section(full, stand.STAND_HEIGHT - stand.LEG_PILOT_DEPTH - 2)
    assert all(not leg.interiors for leg in above_pilot)


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("where", ["mid-plate", "top face"])
def test_hole_walls(stands, variant, where):
    # The top face (z 0, on the bed) is where the countersinks are widest.
    z = 0.1 if where == "top face" else VARIANTS[variant][2] / 2
    (outline,) = section(stands[variant], z)
    holes = [shapely.Polygon(ring) for ring in outline.interiors]
    for hole in holes:
        assert outline.exterior.distance(hole) >= WALL
    for a, b in itertools.combinations(holes, 2):
        assert a.distance(b) >= WALL


@pytest.mark.parametrize("variant", VARIANTS)
def test_motor_screws_countersunk(stands, variant):
    # The inner motor screws sit inside the bearing top plate's r 67.2 sweep, so their heads
    # must be flush with the plate top (the bed face, z 0) instead of standing above it.
    holes = hole_centres(stands[variant], 0.1)
    h = NEMA23_HOLE_SPACING / 2
    for dx, dy in itertools.product((-h, h), repeat=2):
        centre = (CENTER_DISTANCE + dx, dy)
        (d,) = [d for x, y, d in holes if math.dist((x, y), centre) < TOL]
        assert d >= M5_CSK_HEAD, f"no countersink for a flat-head M5 at {centre}"


def test_motor_pad(full):
    # Riser between the plate and the motor flange, so the long shaft ends under the pinion's top.
    polys = section(full, stand.PLATE_THICKNESS + stand.MOTOR_PAD / 2)  # the pad and the legs
    pad = min(polys, key=lambda p: math.dist((p.centroid.x, p.centroid.y), (CENTER_DISTANCE, 0)))
    half_x = NEMA23_FLANGE / 2 + stand.MOTOR_ADJUST
    half_y = NEMA23_FLANGE / 2
    assert pad.bounds == pytest.approx((CENTER_DISTANCE - half_x, -half_y, CENTER_DISTANCE + half_x, half_y), abs=TOL)
    holes = hole_centres(full, stand.PLATE_THICKNESS + stand.MOTOR_PAD / 2)
    assert has_hole(holes, (CENTER_DISTANCE, 0), NEMA23_PILOT + 2 * CLEARANCE)
    for centre in stand.motor_holes():
        assert has_hole(holes, centre, M5_CLEARANCE)


def hole_near(outline: shapely.Polygon, centre) -> shapely.Polygon:
    return min((shapely.Polygon(r) for r in outline.interiors), key=lambda h: h.centroid.distance(shapely.Point(centre)))


@pytest.mark.parametrize("variant", VARIANTS)
def test_motor_slots(stands, variant):
    # The motor slides +-MOTOR_ADJUST along X to tune the gear mesh.
    z = (stand.CSK_DEPTH + VARIANTS[variant][2]) / 2  # below the countersinks
    (outline,) = section(stands[variant], z)
    travel = 2 * stand.MOTOR_ADJUST
    for centre, width in [((CENTER_DISTANCE, 0), NEMA23_PILOT + 2 * CLEARANCE)] + [(c, M5_CLEARANCE) for c in stand.motor_holes()]:
        x0, y0, x1, y1 = hole_near(outline, centre).bounds
        assert x1 - x0 == pytest.approx(width + travel, abs=TOL), f"slot at {centre} is not {travel} mm long"
        assert y1 - y0 == pytest.approx(width, abs=TOL)
        assert (x0 + x1) / 2 == pytest.approx(centre[0], abs=TOL)


@pytest.mark.parametrize("variant", VARIANTS)
def test_countersinks_slotted(stands, variant):
    # At the plate top the countersink is as long as the slot, so a flat head seats anywhere along it.
    (outline,) = section(stands[variant], 0.1)
    for centre in stand.motor_holes():
        x0, _, x1, _ = hole_near(outline, centre).bounds
        assert x1 - x0 >= M5_CSK_HEAD + 2 * stand.MOTOR_ADJUST
