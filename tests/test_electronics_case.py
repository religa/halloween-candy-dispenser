"""Electronics case: the Uno and the RJ45 adapter (hardware.py) fit, measured on the STL."""

import itertools
import math

import electronics_case as ec
import pytest
import shapely
from common import CLEARANCE
from hardware import (
    M3_SELF_TAP_PILOT,
    M4_CLEARANCE,
    RJ45_BODY_LENGTH,
    RJ45_BODY_WIDTH,
    RJ45_NOSE_WIDTH,
    RJ45_TERMINAL_LENGTH,
    RJ45_TERMINAL_WIDTH,
    UNO_HOLES,
    UNO_JACK_Y,
    UNO_LENGTH,
    UNO_THICKNESS,
    UNO_UNDERSIDE,
    UNO_USB_Y,
    UNO_WIDTH,
)
from mesh_checks import export_mesh, hole_centres, section

TOL = 0.05


@pytest.fixture(scope="module")
def mesh(tmp_path_factory):
    return export_mesh(ec.build(), "electronics_case", tmp_path_factory.mktemp("out"))


def solid(mesh, z: float) -> shapely.Geometry:
    return shapely.union_all(section(mesh, z))


def gaps(mesh, z: float, a: tuple[float, float], b: tuple[float, float]) -> list[tuple[float, float]]:
    """Open stretches (start, end), as distances from a, along the line a -> b at height z."""
    line = shapely.LineString([a, b]).difference(solid(mesh, z))
    start = shapely.Point(a)
    ends = [(g.coords[0], g.coords[-1]) for g in getattr(line, "geoms", [line])]
    return sorted(tuple(sorted(start.distance(shapely.Point(p)) for p in pair)) for pair in ends)


def board_holes(mesh) -> list[tuple[float, float]]:
    """Pilot holes in the standoffs."""
    found = [h[:2] for h in hole_centres(mesh, ec.FLOOR + 1) if h[2] == pytest.approx(M3_SELF_TAP_PILOT, abs=TOL)]
    assert len(found) == len(UNO_HOLES)
    return found


def board_origin(mesh) -> tuple[float, float]:
    """Where the Uno's corner sits, from the hole pattern's centre."""
    found, expected = board_holes(mesh), UNO_HOLES
    return tuple(sum(p[i] for p in found) / len(found) - sum(p[i] for p in expected) / len(expected) for i in (0, 1))


def test_standoff_holes_match_uno(mesh):
    ox, oy = board_origin(mesh)
    for x, y in UNO_HOLES:
        assert min(math.dist((ox + x, oy + y), h) for h in board_holes(mesh)) < TOL
    # Pilots stop short of the bed, so the bottom stays flat and closed.
    assert not [h for h in hole_centres(mesh, 0.5) if h[2] == pytest.approx(M3_SELF_TAP_PILOT, abs=TOL)]


def board_outline(mesh) -> shapely.Polygon:
    ox, oy = board_origin(mesh)
    return shapely.box(ox, oy, ox + UNO_LENGTH, oy + UNO_WIDTH)


def standoff_top(mesh) -> float:
    x, y = board_holes(mesh)[0]
    ring = shapely.Point(x + M3_SELF_TAP_PILOT / 2 + 0.5, y)
    return max(z / 10 for z in range(int(mesh.bounds[1][2] * 10)) if solid(mesh, z / 10).contains(ring))


def test_board_fits_inside(mesh):
    # Pins under the board clear the floor.
    assert standoff_top(mesh) - ec.FLOOR >= UNO_UNDERSIDE - TOL
    board = board_outline(mesh)
    walls = solid(mesh, standoff_top(mesh) + UNO_THICKNESS / 2)
    assert board.distance(walls) >= CLEARANCE, "board touches a wall"
    assert walls.envelope.contains(board)


def test_usb_and_jack_notches(mesh):
    board = board_outline(mesh)
    y0 = board.bounds[1]
    board_top = standoff_top(mesh) + UNO_THICKNESS
    for lo, hi in (UNO_USB_Y, UNO_JACK_Y):
        # Open from the board's top face (where the sockets sit) to the top of the wall.
        for z in (board_top + 0.2, mesh.bounds[1][2] - 0.2):
            open_ = gaps(mesh, z, (0.5, y0 + lo), (0.5, y0 + hi))
            assert open_ and open_[0][1] - open_[0][0] == pytest.approx(hi - lo, abs=TOL), "socket blocked by the -X wall"


def test_rj45_pocket(mesh):
    z = ec.FLOOR + 1
    y_mid = (mesh.bounds[0][1] + mesh.bounds[1][1]) / 2
    x_end = mesh.bounds[1][0]
    # Nose notch: the nose passes, the body's shoulders don't.
    notch = [g for g in gaps(mesh, z, (x_end - 0.5, 0), (x_end - 0.5, mesh.bounds[1][1])) if g[0] > 0]
    width = notch[0][1] - notch[0][0]
    assert RJ45_NOSE_WIDTH + 2 * CLEARANCE <= width + TOL < RJ45_BODY_WIDTH
    # Along the centre line: the end wall's inside, then back to the posts' faces just off the terminal block.
    probe_y = y_mid + RJ45_TERMINAL_WIDTH / 2 + 0.6  # behind a shoulder, off the terminal block
    end_wall, post = gaps(mesh, ec.FLOOR + 1, (x_end, probe_y), (0, probe_y))[0]
    assert post - end_wall == pytest.approx(RJ45_BODY_LENGTH + CLEARANCE, abs=TOL), "posts don't meet the body's back"
    # The terminal block passes between the posts; the body between the post arms.
    behind = gaps(mesh, z, (x_end - end_wall - RJ45_BODY_LENGTH - 1, 0), (x_end - end_wall - RJ45_BODY_LENGTH - 1, 99))
    between = [g for g in behind if g[0] < y_mid < g[1]][0]
    assert RJ45_TERMINAL_WIDTH + 2 * CLEARANCE == pytest.approx(between[1] - between[0], abs=TOL)
    beside = gaps(mesh, z, (x_end - end_wall - RJ45_BODY_LENGTH + 2, 0), (x_end - end_wall - RJ45_BODY_LENGTH + 2, 99))
    arms = [g for g in beside if g[0] < y_mid < g[1]][0]
    assert RJ45_BODY_WIDTH + 2 * CLEARANCE == pytest.approx(arms[1] - arms[0], abs=TOL)
    # The zip tie slots run beside the body, between the posts and the shoulders.
    body = (x_end - end_wall - RJ45_BODY_LENGTH, x_end - end_wall)
    slots = [shapely.Polygon(r) for p in section(mesh, 1.8) for r in p.interiors if shapely.Polygon(r).bounds[0] > body[0] - 5]
    assert len(slots) == 2
    for slot in slots:
        assert body[0] < slot.bounds[0] and slot.bounds[2] < body[1], "zip tie slot past the body's ends"
        assert slot.distance(shapely.box(body[0], y_mid - RJ45_BODY_WIDTH / 2, body[1], y_mid + RJ45_BODY_WIDTH / 2)) < 1.0
    # The terminal block clears the board with room for the wires.
    terminal_end = x_end - end_wall - RJ45_BODY_LENGTH - RJ45_TERMINAL_LENGTH
    assert terminal_end - board_outline(mesh).bounds[2] >= 15


def test_mount_and_tie_holes(mesh):
    m4 = [h for h in hole_centres(mesh, 1.5) if h[2] == pytest.approx(M4_CLEARANCE, abs=TOL)]
    assert len(m4) == 2
    for a, b in itertools.combinations(m4, 2):
        assert math.dist(a[:2], b[:2]) > 15
    # Zip tie: two slots beside the body, joined by the groove under the floor.
    standoffs = board_holes(mesh)
    slots = [h for h in hole_centres(mesh, 1.8) if h[2] < M4_CLEARANCE - TOL and min(math.dist(h[:2], s) for s in standoffs) > 1]
    assert len(slots) == 2
    assert len([h for h in hole_centres(mesh, 0.5) if h[2] != pytest.approx(M4_CLEARANCE, abs=TOL)]) == 1
