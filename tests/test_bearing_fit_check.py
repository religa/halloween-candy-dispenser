import math

import bearing_fit_check as fc
import hardware
import pytest
import shapely
from common import WALL
from mesh_checks import export_mesh, hole_centres, section

TOL = 0.05
EXPECTED_CENTRES = [(sx * hardware.BEARING_SPACING / 2, sy * hardware.BEARING_SPACING / 2) for sx in (-1, 1) for sy in (-1, 1)]


@pytest.fixture(scope="module")
def mesh(tmp_path_factory):
    return export_mesh(fc.build(), "bearing_fit_check", tmp_path_factory.mktemp("out"))


@pytest.fixture(scope="module")
def screw_holes(mesh):
    # The window is also a hole in the section; screw holes are the small ones.
    return [h for h in hole_centres(mesh, fc.THICKNESS / 2) if h[2] < fc.WINDOW / 2]


def test_printable(mesh):
    assert mesh.is_watertight
    assert mesh.body_count == 1
    assert mesh.extents[2] == pytest.approx(fc.THICKNESS, abs=1e-6)


def test_screw_holes(screw_holes):
    assert len(screw_holes) == len(EXPECTED_CENTRES)
    for centre in EXPECTED_CENTRES:
        near = [h for h in screw_holes if math.dist(h[:2], centre) < TOL]
        assert len(near) == 1, f"no hole at {centre}; found {screw_holes}"
        assert near[0][2] == pytest.approx(hardware.BEARING_HOLE, abs=TOL)


def test_hole_wall(mesh, screw_holes):
    (frame,) = section(mesh, fc.THICKNESS / 2)
    window = max(frame.interiors, key=lambda ring: shapely.Polygon(ring).area)
    edges = shapely.Polygon(frame.exterior, [window]).boundary  # outer edge + window edge
    for x, y, d in screw_holes:
        assert edges.distance(shapely.Point(x, y).buffer(d / 2)) >= WALL
