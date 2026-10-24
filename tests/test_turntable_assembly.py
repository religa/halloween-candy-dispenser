"""Four quarters rotated into a disc, with the unmodified reference connector at every seam."""

import itertools
import math
from pathlib import Path

import hardware
import pytest
import trimesh
import turntable_connector as tc
import turntable_quarter as tq
from mesh_checks import export_mesh, hole_centres, overlap_volume, rotated

TOL = 0.05
SEAMS = (0.0, 90.0, 180.0, 270.0)
REF_CONNECTOR = Path(__file__).resolve().parents[1] / "ref" / "automatic-candy-dispenser" / "turntable connector.stl"
CONNECTOR_MID_Z = -2.0  # the ref connector spans z -4..0 and straddles the +X seam


def connector_fit(connector, plate_holes, skew=0.0) -> list[tuple[float, float, float]]:
    """For each connector hole at every seam: (offset to nearest plate hole, its diameter, plate hole diameter)."""
    fit = []
    for seam in SEAMS:
        for x, y, d in hole_centres(rotated(connector, seam + skew), CONNECTOR_MID_Z):
            nearest = min(plate_holes, key=lambda h: math.dist(h[:2], (x, y)))
            fit.append((math.dist(nearest[:2], (x, y)), d, nearest[2]))
    return fit


@pytest.fixture(scope="module")
def quarters(tmp_path_factory):
    quarter = export_mesh(tq.build(), "turntable_quarter", tmp_path_factory.mktemp("out"))
    return [rotated(quarter, seam) for seam in SEAMS]


@pytest.fixture(scope="module")
def plate_holes(quarters):
    return [h for q in quarters for h in hole_centres(q, tq.BASE / 2)]


@pytest.fixture(scope="module", params=["ours", "brankly"])
def connector(request, tmp_path_factory):
    """Both connectors in the assembly frame: under the +X seam, z -4..0."""
    if request.param == "ours":
        mesh = export_mesh(tc.build(), "turntable_connector", tmp_path_factory.mktemp("connector"))
        mesh.apply_translation([0, 0, -tc.THICKNESS])
        return mesh
    if not REF_CONNECTOR.exists():
        pytest.skip("ref/ not cloned (git-ignored); see CLAUDE.md")
    mesh = trimesh.load_mesh(REF_CONNECTOR, force="mesh")
    assert mesh.is_watertight, "ref connector changed: no longer watertight"
    return mesh


def test_connectors_align_at_every_seam(connector, plate_holes):
    fit = connector_fit(connector, plate_holes)
    assert len(fit) == 2 * len(SEAMS)
    assert max(offset for offset, _, _ in fit) < TOL


def test_connector_holes_same_diameter(connector, plate_holes):
    for _, connector_d, plate_d in connector_fit(connector, plate_holes):
        assert connector_d == pytest.approx(plate_d, abs=TOL)


def test_misaligned_connector_detected(connector, plate_holes):
    # Control: proves the alignment check can fail.
    assert max(offset for offset, _, _ in connector_fit(connector, plate_holes, skew=5.0)) > 1.0


def test_connector_inside_rim(connector):
    for seam in SEAMS:
        radii = (rotated(connector, seam).vertices[:, :2] ** 2).sum(axis=1) ** 0.5
        assert radii.max() <= tq.RADIUS + 0.01


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_quarters_do_not_overlap(quarters):
    assert overlap_volume(quarters) < 1e-6


def test_overlap_detected(quarters):
    # Control: the second quarter turned 2 degrees into the first must register as overlap.
    assert overlap_volume([quarters[0], rotated(quarters[1], -2.0)]) > 1.0


def test_bearing_holes_form_square(plate_holes):
    bearing = [h[:2] for h in plate_holes if h[2] == pytest.approx(hardware.BEARING_HOLE, abs=TOL)]
    assert len(bearing) == len(SEAMS)
    distances = sorted(math.dist(a, b) for a, b in itertools.combinations(bearing, 2))
    assert distances[:4] == pytest.approx([hardware.BEARING_SPACING] * 4, abs=TOL)
    assert distances[4:] == pytest.approx([hardware.BEARING_SPACING * math.sqrt(2)] * 2, abs=TOL)
