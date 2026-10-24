import math

import numpy as np
import pytest
import shapely
import turntable_gear as tg
import turntable_quarter as tq
from common import WALL
from gearing import FACE_WIDTH, TURNTABLE_TEETH, root_radius, tip_radius
from hardware import BEARING_HOLE
from mesh_checks import export_mesh, hole_centres, rotated_point, section

TOL = 0.05
VARIANTS = {"default": (False, FACE_WIDTH), "test": (True, tg.TEST_FACE_WIDTH)}


@pytest.fixture(scope="module")
def gears(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return {name: (export_mesh(tg.build(test=test), f"turntable_gear_{name}", out), t) for name, (test, t) in VARIANTS.items()}


@pytest.fixture(scope="module")
def gear(gears):
    return gears["default"][0]


def bolt_holes(mesh, z):
    return [h for h in hole_centres(mesh, z) if h[2] == pytest.approx(BEARING_HOLE, abs=TOL)]


@pytest.mark.parametrize("variant", VARIANTS)
def test_printable(gears, variant):
    mesh, thickness = gears[variant]
    assert mesh.is_watertight
    assert mesh.body_count == 1
    assert mesh.extents[2] == pytest.approx(thickness, abs=1e-4)
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_tip_and_root(gear):
    assert np.linalg.norm(gear.vertices[:, :2], axis=1).max() == pytest.approx(tip_radius(TURNTABLE_TEETH), abs=0.01)
    (outline,) = section(gear, 1.0)
    radii = np.linalg.norm(np.array(outline.exterior.coords), axis=1)
    assert radii.min() == pytest.approx(root_radius(TURNTABLE_TEETH), abs=TOL)


def test_bolt_holes_match_quarter(gear, tmp_path_factory):
    quarter = export_mesh(tq.build(), "turntable_quarter", tmp_path_factory.mktemp("quarter"))
    ((qx, qy, _),) = [h for h in hole_centres(quarter, tq.BASE / 2) if h[2] == pytest.approx(BEARING_HOLE, abs=TOL)]
    holes = bolt_holes(gear, 1.0)
    assert len(holes) == 4
    for k in range(4):
        expected = rotated_point((qx, qy), 90 * k)
        assert min(math.dist(h[:2], expected) for h in holes) < TOL


def test_center_hole(gear):
    centre = [h for h in hole_centres(gear, 1.0) if math.hypot(h[0], h[1]) < TOL]
    assert len(centre) == 1
    assert centre[0][2] == pytest.approx(tg.CENTER_HOLE, abs=TOL)


@pytest.mark.parametrize("variant", VARIANTS)
def test_recess(gears, variant):
    mesh, thickness = gears[variant]
    in_recess = hole_centres(mesh, thickness - 1)
    assert max(d for _, _, d in in_recess) == pytest.approx(tg.RACE_RECESS_DIAMETER, abs=0.1)
    assert len(bolt_holes(mesh, thickness - 1)) == 4
    below_recess = hole_centres(mesh, thickness - 3)
    assert max(d for _, _, d in below_recess) < 20


def test_hole_wall_to_root(gear):
    root = shapely.Point(0, 0).buffer(root_radius(TURNTABLE_TEETH), quad_segs=256).boundary
    for x, y, d in bolt_holes(gear, 1.0):
        assert root.distance(shapely.Point(x, y).buffer(d / 2)) >= WALL
