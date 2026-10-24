"""The printed gear and pinion mesh at CENTER_DISTANCE without their teeth colliding."""

import motor_gear as mg
import numpy as np
import pytest
import turntable_gear as tg
from gearing import CENTER_DISTANCE, MOTOR_TEETH, TURNTABLE_TEETH
from mesh_checks import export_mesh, overlap_volume, rotated

SWEEP_STEPS = 25


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    out = tmp_path_factory.mktemp("out")
    gear = export_mesh(tg.build(), "turntable_gear", out)
    pinion = export_mesh(mg.build(), "motor_gear", out)
    teeth = pinion.slice_plane(plane_origin=[0, 0, mg.TOOTH_LENGTH], plane_normal=[0, 0, -1], cap=True)
    # gear print frame: turntable face at z 0, so the teeth start TURNTABLE_GAP above it
    teeth.apply_translation([0, 0, mg.TURNTABLE_GAP])
    return gear, teeth


def worst_overlap(gear, teeth, center_distance: float) -> float:
    worst = 0.0
    for angle in np.linspace(0, 360 / TURNTABLE_TEETH, SWEEP_STEPS):
        phase = 180 + 180 / MOTOR_TEETH - angle * TURNTABLE_TEETH / MOTOR_TEETH
        pinion = rotated(teeth, phase)
        pinion.apply_translation([center_distance, 0, 0])
        worst = max(worst, overlap_volume([rotated(gear, angle), pinion]))
    return worst


@pytest.mark.filterwarnings("ignore:invalid value encountered in divide:RuntimeWarning")
def test_mesh_no_interference(pair):
    assert worst_overlap(*pair, CENTER_DISTANCE) < 1e-6


def test_mesh_interference_detected(pair):
    # Control: 1 mm closer the teeth must collide.
    assert worst_overlap(*pair, CENTER_DISTANCE - 1) > 1.0
