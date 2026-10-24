import math

import numpy as np
import pytest
import shapely
import turntable_quarter as tq
from common import PLATE_MAX, WALL
from mesh_checks import export_mesh, hole_centres, section

TOL = 0.05
# Independent oracles, deliberately not imported from turntable_quarter:
USER_MEASURED_SPACING = 82.0  # neighbouring bearing holes, confirmed with the printed bearing_fit_check
HEAD_CLEARANCE = 6.0  # M5 screw head radius 4.25 mm + margin, so heads clear the ribs

EXPECTED_HOLES = [(tq.polar(tq.BEARING_RADIUS, tq.BEARING_ANGLE), tq.BEARING_HOLE)] + [(tq.polar(tq.CONNECTOR_RADIUS, a), tq.CONNECTOR_HOLE) for a in tq.CONNECTOR_ANGLES]


@pytest.fixture(scope="module")
def mesh(tmp_path_factory):
    return export_mesh(tq.build(), "turntable_quarter", tmp_path_factory.mktemp("out"))


@pytest.fixture(scope="module")
def holes(mesh):
    return hole_centres(mesh, tq.BASE / 2)


@pytest.fixture(scope="module")
def ribs(mesh):
    return section(mesh, tq.BASE + tq.RIB_HEIGHT / 2)


def test_printable(mesh):
    assert mesh.is_watertight
    assert mesh.body_count == 1
    x, y, z = mesh.extents
    assert max(x, y) <= PLATE_MAX
    assert z == pytest.approx(tq.BASE + tq.RIB_HEIGHT, abs=1e-6)


@pytest.mark.parametrize("centre,diameter", EXPECTED_HOLES)
def test_hole(holes, centre, diameter):
    near = [h for h in holes if math.dist(h[:2], centre) < TOL]
    assert len(near) == 1, f"no hole at {centre}; found {holes}"
    assert near[0][2] == pytest.approx(diameter, abs=TOL)


def test_hole_count(holes):
    assert len(holes) == len(EXPECTED_HOLES)


def test_bearing_square(holes):
    ((x, y, _),) = [h for h in holes if h[2] == pytest.approx(tq.BEARING_HOLE, abs=TOL)]
    neighbour = (-y, x)  # the next quarter's bearing hole, 90 degrees round
    assert math.dist((x, y), neighbour) == pytest.approx(USER_MEASURED_SPACING, abs=TOL)


def test_ribs(ribs):
    assert len(ribs) == len(tq.RIB_ANGLES)
    angles = sorted(math.degrees(math.atan2(r.centroid.y, r.centroid.x)) for r in ribs)
    assert angles == pytest.approx(sorted(tq.RIB_ANGLES), abs=0.1)
    for rib in ribs:
        corners = np.array(rib.minimum_rotated_rectangle.exterior.coords)
        width = min(math.dist(corners[0], corners[1]), math.dist(corners[1], corners[2]))
        assert width == pytest.approx(tq.RIB_WIDTH, abs=TOL)


def test_ribs_span_hub_to_rim(ribs):
    for rib in ribs:
        assert shapely.Point(0, 0).distance(rib) == pytest.approx(tq.HUB_RADIUS, abs=TOL)
        radii = np.linalg.norm(np.array(rib.exterior.coords), axis=1)
        # Upper bound is tight on purpose: untrimmed rib corners would reach r = 130.004.
        assert tq.RADIUS - TOL <= radii.max() <= tq.RADIUS + 1e-3


def test_seam_gap(mesh):
    assert mesh.bounds[0][:2] == pytest.approx((tq.SEAM_GAP, tq.SEAM_GAP), abs=0.01)


def test_rim_and_hub(mesh):
    radii = np.linalg.norm(mesh.vertices[:, :2], axis=1)
    assert radii.min() >= tq.HUB_RADIUS - 0.01
    assert radii.max() <= tq.RADIUS + 0.01
    # The base itself must reach the rim and the hub, not just the ribs on top of it.
    (base,) = section(mesh, tq.BASE / 2)
    base_radii = np.linalg.norm(np.array(base.exterior.coords), axis=1)
    assert base_radii.min() == pytest.approx(tq.HUB_RADIUS, abs=TOL)
    assert base_radii.max() == pytest.approx(tq.RADIUS, abs=TOL)


def test_hole_wall(mesh, holes):
    (base,) = section(mesh, tq.BASE / 2)
    for x, y, d in holes:
        assert base.exterior.distance(shapely.Point(x, y).buffer(d / 2)) >= WALL


def test_holes_clear_ribs(holes, ribs):
    for x, y, _ in holes:
        for rib in ribs:
            assert shapely.Point(x, y).distance(rib) >= HEAD_CLEARANCE
