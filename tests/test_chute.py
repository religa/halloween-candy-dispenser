"""Chute frame, ramp and spigot, checked in the assembly frame (turntable underside z 0, chute on -Y).

"ramp" and "spigot" are in chute_ramp's reference mount; "*_mounted" are placed by chute_frame.RAMP_MOUNT.
"""

import math

import chute_frame as cf
import chute_ramp as cr
import chute_spigot as cs
import numpy as np
import pytest
import shapely
import trimesh
import turntable_quarter as tq
from common import CLEARANCE
from hardware import (
    BEAM_BODY_HEIGHT,
    BEAM_LED,
    BEAM_LED_HEIGHT,
    BEAM_LED_TO_HOLE,
    BUCKET_TAPER,
    BUCKET_TURNTABLE_DIAMETER,
    BUCKET_WALL,
    DRAIN_PIPE_ID,
    M2_5_SELF_TAP_PILOT,
    M4_CLEARANCE,
    M4_SELF_TAP_PILOT,
)
from mesh_checks import export_mesh, overlap_volume, section

TOL = 0.05
INCH = 25.4
Y_TO_Z = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=float)  # (x, y, z) -> (x, z, -y)
X_TO_Z = np.array([[0, 1, 0, 0], [0, 0, 1, 0], [1, 0, 0, 0], [0, 0, 0, 1]], dtype=float)  # (x, y, z) -> (y, z, x)


def bucket_outside(z: float) -> float:
    """Independent of the part: the bucket's outside radius from hardware.py."""
    return BUCKET_TURNTABLE_DIAMETER / 2 + BUCKET_TAPER * z + BUCKET_WALL


@pytest.fixture(scope="module")
def meshes(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    return {
        "frame": export_mesh(cf.assembled(), "frame", out),
        "ramp": export_mesh(cr.assembled(), "ramp", out),
        "frame_print": export_mesh(cf.build(), "frame_print", out),
        "ramp_print": export_mesh(cr.build(), "ramp_print", out),
        "spigot": export_mesh(cs.assembled(), "spigot", out),
        "spigot_print": export_mesh(cs.build(), "spigot_print", out),
        "ramp_mounted": export_mesh(cf.RAMP_MOUNT * cr.assembled(), "ramp_mounted", out),
        "spigot_mounted": export_mesh(cf.RAMP_MOUNT * cs.assembled(), "spigot_mounted", out),
        "ramp_test": export_mesh(cr.build(test=True), "ramp_test", out),
        "turntable": export_mesh(tq.build(), "quarter", out),
    }


def holes(mesh: trimesh.Trimesh, matrix: np.ndarray, level: float) -> list[tuple[float, float, float]]:
    """(u, v, diameter) of the holes where the plane transformed to z = level cuts the mesh."""
    found = []
    for poly in section(mesh.copy().apply_transform(matrix), level):
        for ring in poly.interiors:
            hole = shapely.Polygon(ring)
            c = hole.centroid
            found.append((c.x, c.y, 2 * hole.exterior.distance(c) if hole.covers(c) else 0.0))
    return found


def has_hole(found, centre, diameter, tol=TOL) -> bool:
    return any(math.dist(h[:2], centre) < tol and h[2] == pytest.approx(diameter, abs=tol) for h in found)


def bed_area(mesh: trimesh.Trimesh) -> float:
    down = (mesh.face_normals[:, 2] < -0.999) & (mesh.triangles_center[:, 2] < 1e-4)
    return mesh.area_faces[down].sum()


def test_print_orientation(meshes):
    # Each prints flat on a large face with no supports: the frame on its outer face, the
    # ramp on its floor, the spigot on its socket mouth.
    assert bed_area(meshes["frame_print"]) > 0.4 * 2 * cf.HALF_WIDTH * (cf.TOP_Z - cf.BOTTOM_Z)  # the window takes the rest
    assert bed_area(meshes["ramp_print"]) > 0.9 * 2 * cr.RAIL_OUT * cr.CHANNEL_LENGTH
    outline = (2 * cs.SOCKET_OUT) * (cs.HOOD_TOP - cs.SOCKET_BOTTOM)
    channel = (2 * cs.SOCKET_IN) * (cs.SOCKET_TOP - cs.SOCKET_FLOOR)
    under_hood = 2 * (cr.CHANNEL + cr.STEP) * (cs.BORE - cr.STEP - cs.SOCKET_TOP)
    assert bed_area(meshes["spigot_print"]) == pytest.approx(outline - channel - under_hood, rel=0.03)
    for name in ("frame", "ramp", "spigot"):
        assert meshes[f"{name}_print"].volume == pytest.approx(meshes[name].volume, rel=1e-3)  # cones tessellate differently


@pytest.mark.parametrize("name", ("frame_print", "ramp_print", "spigot_print"))
def test_no_overhangs_past_45_degrees(meshes, name):
    # Downward faces steeper than 45 degrees, off the bed, may only be hole roofs (they bridge): small total area.
    mesh = meshes[name]
    steep = (-mesh.face_normals[:, 2] > math.sin(math.radians(46))) & (mesh.triangles_center[:, 2] > 0.2)
    assert mesh.area_faces[steep].sum() < 150


def test_window_is_4_by_4_inches_at_the_turntable_top(meshes):
    frame = meshes["frame"]
    # across: the frame's two sides, cut level at mid-window
    sides = sorted(section(frame, 50.0), key=lambda p: p.centroid.x)
    assert (sides[0].bounds[2], sides[-1].bounds[0]) == pytest.approx((-2 * INCH, 2 * INCH), abs=TOL)
    # up: at the bucket face, the window runs from the turntable's top face up 4 in
    for x in (0.0, 30.0, 2 * INCH - 0.5):
        r_out = lambda z: bucket_outside(z) + 0.3  # noqa: E731
        just_out = lambda z: (x, -math.sqrt(r_out(z) ** 2 - x**2), z)  # noqa: E731, B023 (called within the same iteration)
        assert not frame.contains([just_out(tq.BASE + 0.3), just_out(tq.BASE + 4 * INCH - 0.3)]).any()
        assert frame.contains([just_out(tq.BASE - 1.0), just_out(tq.BASE + 4 * INCH + 0.3)]).all()  # under the 45 degree floor


def test_frame_sits_on_the_bucket_outside(meshes):
    frame = meshes["frame"]
    # Just outside the bucket, the frame is there all round the hole ...
    points = []
    for x in np.linspace(-cf.HALF_WIDTH + 1, cf.HALF_WIDTH - 1, 15):
        for z in np.linspace(cf.BOTTOM_Z + 1, cf.TOP_Z - 1, 15):
            if abs(x) < 2 * INCH + 1 and tq.BASE - 1 < z < tq.BASE + 4 * INCH + 1:
                continue
            r = bucket_outside(z) + 0.3
            points.append((x, -math.sqrt(r**2 - x**2), z))
    assert frame.contains(points).all()
    # ... and nothing of it reaches into the bucket wall or the hole: no rim
    v = frame.vertices
    assert (np.hypot(v[:, 0], v[:, 1]) >= np.array([bucket_outside(z) for z in v[:, 2]]) - 1e-3).all()


def test_window_floor_has_no_ledge(meshes):
    # Every upward face of the window's floor falls at 45 degrees or more: nothing flat to stop on.
    frame = meshes["frame"]
    c, n = frame.triangles_center, frame.face_normals
    floor = (n[:, 2] > 0.01) & (np.abs(c[:, 0]) < 2 * INCH - 0.2) & (c[:, 2] < tq.BASE + 0.1)
    assert floor.any()
    slopes = np.degrees(np.arccos(n[floor, 2]))
    assert slopes.min() >= 45.0 - 0.5


def test_ramp_floor_starts_below_the_window_floor(meshes):
    # At the joint candy only drops: the ramp's floor sits at or under the frame's floor at every x.
    frame, ramp = meshes["frame"], meshes["ramp_mounted"]
    z_face = cf.RAMP_FLOOR_Z
    for x in np.linspace(-2 * INCH + 0.3, 2 * INCH - 0.3, 11):
        behind = (x, cf.face_y(z_face) + 0.4, 60.0)
        front = (x, cf.face_y(z_face) - 0.4, 60.0)
        frame_floor = frame.ray.intersects_location([behind], [(0, 0, -1)])[0][:, 2].max()
        ramp_floor = ramp.ray.intersects_location([front], [(0, 0, -1)])[0][:, 2].max()
        assert ramp_floor <= frame_floor + 0.1
        assert frame_floor - ramp_floor < 12  # a short drop, not a fall into a gap


def test_ramp_runs_steeper_than_45_degrees(meshes):
    # two points along the mounted ramp's floor line, far apart
    a = (cf.RAMP_MOUNT * cf.Pos(0, *cr.at(0, 0))).position
    b = (cf.RAMP_MOUNT * cf.Pos(0, *cr.at(cr.CHANNEL_LENGTH, 0))).position
    slope = math.degrees(math.atan2(a.Z - b.Z, abs(a.Y - b.Y)))
    assert slope == pytest.approx(cr.SLOPE + cf.TILT, abs=0.01)
    assert slope > 45


def test_frame_screw_holes_go_through(meshes):
    frame, inward = meshes["frame"], np.array(tuple(-cf.FACE_NORMAL))
    for at in [cf.Vector(x, cf.face_y(z), z) for x, z in cf.BUCKET_SCREWS] + list(cf.RAMP_SCREWS):
        start = np.array(tuple(at)) - 5 * inward
        assert not frame.ray.intersects_any([start], [inward])[0], f"hole at {tuple(at)} is blocked"
        assert has_wall_round(frame, start, inward)
    for _, z in cf.BUCKET_SCREWS:
        assert z > 50  # above the candy riding in the chamber (43 mm passage, docs/middle-wall.md)


def has_wall_round(mesh, start, axis, offset=M4_SELF_TAP_PILOT / 2 + 0.3) -> bool:
    """A ray parallel to the hole, just outside it, does hit the part: it's a hole, not open space."""
    side = np.cross(axis, (1.0, 0, 0))
    side = side / np.linalg.norm(side)
    return bool(mesh.ray.intersects_any([start + offset * side], [axis])[0])


def test_ramp_lugs_line_up_with_frame_holes(meshes):
    frame, ramp, inward = meshes["frame"], meshes["ramp_mounted"], np.array(tuple(-cf.FACE_NORMAL))
    for at in cf.RAMP_SCREWS:
        start = np.array(tuple(at)) - 20 * inward  # outside the lug
        assert not ramp.ray.intersects_any([start], [inward])[0]
        assert not frame.ray.intersects_any([start], [inward])[0]
        # the lug sits flat on the frame's face beside the hole
        up_the_face = np.cross(inward, (1.0, 0, 0))
        up_the_face *= np.sign(up_the_face[2])
        beside = np.array(tuple(at)) + 5 * up_the_face
        assert trimesh.proximity.closest_point(frame, [beside])[1][0] < 0.05
        assert trimesh.proximity.closest_point(ramp, [beside])[1][0] < 0.05


def test_parts_dont_collide(meshes):
    quarters = []
    for i in range(4):
        q = meshes["turntable"].copy()
        q.apply_transform(trimesh.transformations.rotation_matrix(math.radians(90 * i), [0, 0, 1]))
        quarters.append(q)
    # flush faces on the tilted frame face leave a rounding sliver of a few cubic microns
    assert overlap_volume([meshes["frame"], meshes["ramp_mounted"], meshes["spigot_mounted"]]) == pytest.approx(0, abs=1e-2)
    for q in quarters:
        assert overlap_volume([meshes["frame"], q]) == pytest.approx(0, abs=1e-3)


def beam_point():
    return cr.at(cr.SENSOR_AT, cr.BEAM_HEIGHT)


def test_beam_crosses_the_whole_channel(meshes):
    y, z = beam_point()
    ramp = meshes["ramp"]
    # the line between the two LEDs is clear, from one rail's outer face to the other's
    assert not ramp.ray.intersects_any([[-cr.LUG_OUT - 5, y, z]], [[1.0, 0, 0]]).any()
    # ... and it runs low over the floor, so flat candy cuts it too
    hit, _, _ = ramp.ray.intersects_location([[0, y, z]], [[0, math.sin(math.radians(cr.SLOPE)), -math.cos(math.radians(cr.SLOPE))]])
    height = min(np.linalg.norm(p - [0, y, z]) for p in hit)
    assert 4.0 <= height <= 8.0


@pytest.mark.parametrize("side", (-1, 1))
def test_sensor_mounts(meshes, side):
    ramp = meshes["ramp"]
    channel_face, outer_face = side * cr.CHANNEL, side * cr.RAIL_OUT
    # rail thick enough that the lens tip stays out of the channel
    assert abs(outer_face - channel_face) >= BEAM_LED_HEIGHT
    found = holes(ramp, X_TO_Z, outer_face - side * 0.5)
    led = [h for h in found if h[2] > 4]
    pilot = [h for h in found if h[2] == pytest.approx(M2_5_SELF_TAP_PILOT, abs=TOL)]
    assert len(led) == 1 and len(pilot) == 1
    assert led[0][2] >= 2 * (BEAM_LED + 2 * CLEARANCE) - TOL  # twice the lens's close fit, so the beam isn't clipped
    assert led[0][:2] == pytest.approx(beam_point(), abs=TOL)
    assert math.dist(led[0][:2], pilot[0][:2]) == pytest.approx(BEAM_LED_TO_HOLE, abs=TOL)
    # pilot upstream of the LED, on the same line along the floor
    assert pilot[0][1] > led[0][1]
    assert cr.at(cr.SENSOR_AT - BEAM_LED_TO_HOLE, cr.BEAM_HEIGHT) == pytest.approx(pilot[0][:2], abs=TOL)


def test_fit_check_has_the_sensor_mounts(meshes):
    test = meshes["ramp_test"]
    assert test.is_watertight and test.body_count == 1
    assert test.volume < meshes["ramp_print"].volume / 2
    # a line of sight across both rails exists only through the two LED holes
    zs = np.linspace(0.5, test.extents[2] - 0.5, 300)
    ys = np.linspace(test.bounds[0][1] + 0.5, test.bounds[1][1] - 0.5, 300)
    origins = np.array([[test.bounds[0][0] - 5, y, z] for y in ys[::10] for z in zs[::10]])
    clear = ~test.ray.intersects_any(origins, np.tile([1.0, 0, 0], (len(origins), 1)))
    assert clear.any(), "no line of sight across the test piece: LED holes missing or misaligned"


def outer_diameter(mesh: trimesh.Trimesh, z: float) -> float:
    (ring,) = section(mesh, z)
    return 2 * math.sqrt(shapely.Polygon(ring.exterior).area / math.pi)


def test_spigot_fits_the_drain_pipe(meshes):
    # print frame: the spigot axis is vertical, its tip at the top
    spigot = meshes["spigot_print"]
    top = spigot.bounds[1][2]
    tip = outer_diameter(spigot, top - 0.5)
    base = outer_diameter(spigot, top - cs.SPIGOT_LENGTH + 0.5)
    assert tip < DRAIN_PIPE_ID - 2  # starts into the pipe easily
    assert base > DRAIN_PIPE_ID + 3  # and the flexible pipe has to stretch over it before it gets there
    groove = outer_diameter(spigot, top - cs.GROOVE_AT)
    assert groove < tip + (base - tip) * cs.GROOVE_AT / cs.SPIGOT_LENGTH - 2  # zip-tie groove, ~1.2 mm deep
    # the spigot runs on in line with the ramp: its axis is the same direction as the floor
    centres = [shapely.Polygon(section(spigot, z)[0].exterior).centroid for z in (top - 1, top - cs.SPIGOT_LENGTH + 1)]
    assert math.dist((centres[0].x, centres[0].y), (centres[1].x, centres[1].y)) < 0.1


def test_ramp_screws_into_the_spigot_socket(meshes):
    for side in (-1, 1):
        rail = holes(meshes["ramp"], X_TO_Z, side * (cr.RAIL_OUT - 2))
        wall = holes(meshes["spigot"], X_TO_Z, side * (cs.SOCKET_OUT - 2))
        pilots = [h for h in rail if h[2] == pytest.approx(M4_SELF_TAP_PILOT, abs=TOL)]
        assert len(pilots) == 2
        for y, z, _ in pilots:
            assert has_hole(wall, (y, z), M4_CLEARANCE)
    # the rails' ends sit right up against the 45 degree shoulder: nearly touching, not overlapping
    for side in (-1, 1):
        rail_end = (side * (cr.RAIL_OUT - 0.5), *cr.at(cr.CHANNEL_LENGTH, cr.RAIL_HEIGHT / 2))
        assert trimesh.proximity.closest_point(meshes["spigot"], [rail_end])[1][0] < 1.0


def test_candy_runs_from_the_channel_out_of_the_spigot(meshes):
    # Rays down the slope from the open channel, anywhere inside the bore's circle (down to
    # 0.3 mm above the floor), leave through the spigot tip without touching anything: no
    # edge at the ramp-to-spigot seam, the funnel or the bore.
    r = cs.BORE / 2 - 0.3
    points = [(r * math.cos(a), cs.AXIS_H + r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)]
    points = [(x, h) for x, h in points if h >= 0.3]  # the bore dips 0.5 under the channel floor (the step down)
    points += [(0.0, cs.AXIS_H), (0.0, 0.3), (10.0, 3.0), (-10.0, 3.0)]
    origins, directions = [], []
    for x, h in points:
        y, z = cr.at(20.0, h)
        origins.append((x, y, z))
        directions.append((0.0, *cr.DOWN))
    chute = trimesh.util.concatenate([meshes["ramp"], meshes["spigot"]])
    assert not chute.ray.intersects_any(np.array(origins), np.array(directions)).any()


def test_rail_holes_go_through_but_screws_stay_out_of_the_channel(meshes):
    ramp = meshes["ramp"]
    centres = [(cr.SENSOR_AT - BEAM_LED_TO_HOLE, cr.BEAM_HEIGHT), *cr.JOINT_SCREWS]
    for sx in (-1, 1):
        for s, h in centres:  # a ray down each hole's axis, from outside into the channel, meets nothing
            y, z = cr.at(s, h)
            assert not ramp.ray.intersects_any([(sx * (cr.RAIL_OUT + 5), y, z)], [(-sx, 0.0, 0.0)])[0]
    # M2.5 x 12 through the sensor body, M4 x 10 through the socket wall: tips short of the channel
    assert 12 <= BEAM_BODY_HEIGHT + cr.RAIL
    assert 10 <= cs.SOCKET_WALL + CLEARANCE + cr.RAIL
