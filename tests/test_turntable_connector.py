"""Our connector: its own geometry, the quarters' holes, and a match against Brankly's original."""

import math
from pathlib import Path

import numpy as np
import pytest
import shapely
import trimesh
import turntable_connector as tc
import turntable_quarter as tq
from common import WALL
from mesh_checks import export_mesh, hole_centres, rotated, section

TOL = 0.05
REF_CONNECTOR = Path(__file__).resolve().parents[1] / "ref" / "automatic-candy-dispenser" / "turntable connector.stl"
# Measured from the ref STL (independent of our constants): r 110..130, +-30 deg, 4 mm, Ø6 at r 120 +-15 deg.
REF_INNER, REF_OUTER, REF_HALF_SPAN, REF_THICKNESS = 110.0, 130.0, 30.0, 4.0


@pytest.fixture(scope="module")
def connector(tmp_path_factory):
    return export_mesh(tc.build(), "turntable_connector", tmp_path_factory.mktemp("out"))


def test_printable(connector):
    assert connector.is_watertight
    assert connector.body_count == 1
    assert connector.extents[2] == pytest.approx(REF_THICKNESS, abs=1e-4)
    assert connector.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_shape(connector):
    xy = connector.vertices[:, :2]
    radii = np.linalg.norm(xy, axis=1)
    angles = np.degrees(np.arctan2(xy[:, 1], xy[:, 0]))
    assert radii.min() == pytest.approx(REF_INNER, abs=TOL)
    assert radii.max() == pytest.approx(REF_OUTER, abs=TOL)
    assert angles.min() == pytest.approx(-REF_HALF_SPAN, abs=0.05)
    assert angles.max() == pytest.approx(REF_HALF_SPAN, abs=0.05)


def test_holes_match_quarters(connector, tmp_path_factory):
    # Both holes must sit on a quarter's connector hole: one quarter on each side of the +X seam.
    quarter = export_mesh(tq.build(), "turntable_quarter", tmp_path_factory.mktemp("quarter"))
    quarter_holes = [h for h in hole_centres(quarter, tq.BASE / 2) if h[2] == pytest.approx(tq.CONNECTOR_HOLE, abs=TOL)]
    nearest_seam = min(quarter_holes, key=lambda h: math.atan2(h[1], h[0]))  # the quarter spans 0..90 deg
    x, y = nearest_seam[:2]
    targets = [(x, y), (x, -y)]  # and its neighbour across the +X seam (quarters are mirror-symmetric)
    holes = hole_centres(connector, REF_THICKNESS / 2)
    assert len(holes) == 2
    for x, y, d in holes:
        assert min(math.dist((x, y), t) for t in targets) < TOL
        assert d == pytest.approx(tq.CONNECTOR_HOLE, abs=TOL)


def test_hole_walls(connector):
    (outline,) = section(connector, REF_THICKNESS / 2)
    for x, y, d in hole_centres(connector, REF_THICKNESS / 2):
        hole = shapely.Point(x, y).buffer(d / 2)
        assert outline.exterior.distance(hole) >= WALL


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_matches_brankly_original(connector):
    if not REF_CONNECTOR.exists():
        pytest.skip("ref/ not cloned (git-ignored); see CLAUDE.md")
    ref = trimesh.load_mesh(REF_CONNECTOR, force="mesh")
    ref.apply_translation([0, 0, -ref.bounds[0][2]])  # the ref sits at z -4..0 (assembly); ours prints at 0..4
    assert difference_volume(ref, connector) < 0.01 * ref.volume
    # Control: the same connector turned 2 degrees must register as different.
    assert difference_volume(ref, rotated(connector, 2.0)) > 0.02 * ref.volume


def difference_volume(a, b) -> float:
    """Volume in one mesh but not the other."""
    return a.difference(b, engine="manifold").volume + b.difference(a, engine="manifold").volume
