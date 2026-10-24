"""Guardrail: every part script follows CLAUDE.md (has build()) and fits the A1 mini plate."""

import importlib
import inspect
from pathlib import Path

import pytest
from common import BUILD_HEIGHT, PLATE_MAX
from mesh_checks import export_mesh

PARTS_DIR = Path(__file__).resolve().parents[1] / "parts"
NOT_PARTS = {"common", "gearing", "hardware"}  # helper modules, not printable parts
PART_SCRIPTS = sorted(p for p in PARTS_DIR.glob("*.py") if p.stem not in NOT_PARTS)


def check_printable(mesh, label: str):
    assert mesh.is_watertight, f"{label}: mesh is not watertight"
    assert mesh.body_count == 1, f"{label}: {mesh.body_count} separate bodies"
    x, y, z = mesh.extents
    assert max(x, y) <= PLATE_MAX, f"{label}: footprint {x:.1f} x {y:.1f} exceeds {PLATE_MAX} mm"
    assert z <= BUILD_HEIGHT, f"{label}: height {z:.1f} exceeds {BUILD_HEIGHT} mm"
    assert mesh.bounds[0][2] == pytest.approx(0.0, abs=1e-6), f"{label}: bed face is not at z = 0"


def test_part_scripts_found():
    assert PART_SCRIPTS, f"no part scripts found in {PARTS_DIR}"


def test_not_parts_exist():
    # A stale or misspelt name here would silently drop a real part from the guardrail.
    for name in NOT_PARTS:
        assert (PARTS_DIR / f"{name}.py").exists(), f"NOT_PARTS lists missing module {name}"


@pytest.mark.parametrize("script", PART_SCRIPTS, ids=lambda p: p.stem)
def test_part_builds_and_fits(script, tmp_path):
    module = importlib.import_module(script.stem)
    assert hasattr(module, "build"), f"{script.name} has no build() (CLAUDE.md: Part conventions)"
    check_printable(export_mesh(module.build(), script.stem, tmp_path), script.name)
    if "test" in inspect.signature(module.build).parameters:
        name = f"{script.stem}_test"
        check_printable(export_mesh(module.build(test=True), name, tmp_path), name)
