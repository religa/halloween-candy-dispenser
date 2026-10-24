"""Pinion in its print frame: teeth z 0..TOOTH_LENGTH on the bed, hub above."""

import math

import motor_gear as mg
import numpy as np
import pytest
import shapely
from common import CLEARANCE
from gearing import CENTER_DISTANCE, MOTOR_TEETH, root_radius, tip_radius
from hardware import (
    BEARING_PLATE,
    M3_CLEARANCE,
    M3_NUT_FLATS,
    M3_NUT_THICKNESS,
    SHAFT_DIAMETER,
    SHAFT_FLAT_ACROSS,
)
from mesh_checks import export_mesh, section

TOL = 0.05


@pytest.fixture(scope="module")
def pinion(tmp_path_factory):
    return export_mesh(mg.build(), "motor_gear", tmp_path_factory.mktemp("out"))


def test_printable(pinion):
    assert pinion.is_watertight
    assert pinion.body_count == 1
    assert pinion.extents[2] == pytest.approx(mg.TOOTH_LENGTH + mg.HUB_LENGTH, abs=1e-4)
    assert pinion.bounds[0][2] == pytest.approx(0.0, abs=1e-6)


def test_teeth_and_hub(pinion):
    assert np.linalg.norm(pinion.vertices[:, :2], axis=1).max() == pytest.approx(tip_radius(MOTOR_TEETH), abs=0.01)
    (teeth,) = section(pinion, 3.0)
    # root lands are straight chords, so the true minimum sits a little inside root_radius
    assert np.linalg.norm(np.array(teeth.exterior.coords), axis=1).min() == pytest.approx(root_radius(MOTOR_TEETH), abs=0.1)
    (hub,) = section(pinion, mg.TOOTH_LENGTH + 1)
    assert np.linalg.norm(np.array(hub.exterior.coords), axis=1).max() == pytest.approx(mg.HUB_DIAMETER / 2, abs=TOL)


def test_d_bore(pinion):
    (teeth,) = section(pinion, 3.0)
    (bore,) = teeth.interiors
    coords = np.array(bore.coords)
    assert np.linalg.norm(coords, axis=1).max() == pytest.approx((SHAFT_DIAMETER + CLEARANCE) / 2, abs=TOL)
    # Oracle: the measured shaft. The flat sits SHAFT_FLAT_ACROSS from the far side of the shaft.
    across_flat = coords[:, 0].max() + SHAFT_DIAMETER / 2
    assert across_flat == pytest.approx(SHAFT_FLAT_ACROSS + CLEARANCE, abs=TOL)


def test_set_screw_channel(pinion):
    channel = [(x, 0.0, mg.SET_SCREW_Z) for x in np.linspace(mg.FLAT_X + 0.3, mg.HUB_DIAMETER / 2 - 0.3, 12)]
    assert not pinion.contains(channel).any(), "set-screw hole is blocked between the flat and the hub surface"
    assert pinion.contains([(8.0, 0.0, mg.SET_SCREW_Z + 3)]).all(), "hub wall above the set screw should be solid"
    # the hole is full size, not just open along its axis
    edge = M3_CLEARANCE / 2 - 0.2
    rim = [(8.0, dy, mg.SET_SCREW_Z + dz) for dy, dz in ((edge, 0), (-edge, 0), (0, edge), (0, -edge))]
    assert not pinion.contains(rim).any(), "set-screw hole is narrower than M3 clearance"


def slot_and_bore(pinion, z):
    """The nut slot and the bore, as separate holes in the hub section at height z."""
    (hub,) = section(pinion, z)
    holes = sorted((shapely.Polygon(ring) for ring in hub.interiors), key=lambda h: h.bounds[0])
    assert len(holes) == 2, f"expected bore + nut slot at z {z:.2f}, found {len(holes)} holes"
    bore, slot = holes
    return hub, slot, bore


# Above and below the set-screw hole (which opens the bore to the hub surface).
@pytest.mark.parametrize("z", [mg.SET_SCREW_Z + 2.5, mg.SET_SCREW_Z - mg.NUT_CORNERS / 2 + 0.3])
def test_nut_slot(pinion, z):
    hub, slot, bore = slot_and_bore(pinion, z)
    # Oracle is the real nut (hardware.py), not the part's own slot constants.
    assert slot.bounds[3] - slot.bounds[1] > M3_NUT_FLATS + 0.1, "slot too narrow for an M3 nut"
    assert slot.bounds[2] - slot.bounds[0] > M3_NUT_THICKNESS + 0.1, "slot too thin for an M3 nut"
    assert slot.distance(bore) >= mg.NUT_WALL - 0.01
    assert hub.exterior.distance(slot) >= mg.NUT_WALL


def test_nut_slot_floor(pinion):
    # The slot stops just below the nut's lowest corner, which keeps the nut centred on the screw.
    (low,) = section(pinion, mg.SET_SCREW_Z - mg.NUT_CORNERS / 2 - 0.5)
    assert len(low.interiors) == 1


def test_hub_clears_bearing_top_plate():
    assert mg.HUB_DIAMETER / 2 <= CENTER_DISTANCE - BEARING_PLATE / math.sqrt(2) - 2
