"""tools/package_parts.py: the release zip holds every part as STL, 3MF and STEP."""

import locale
import zipfile

import common
import pytest
from build123d import Mesher
from test_all_parts import PART_SCRIPTS

from tools import package_parts


def test_finds_every_part_and_no_helpers():
    assert package_parts.part_names() == [p.stem for p in PART_SCRIPTS]


def test_zip_has_each_format_and_the_3mf_matches_the_part(tmp_path):
    out, before = common.OUT, locale.setlocale(locale.LC_ALL)
    files = package_parts.package(["bearing_fit_check", "chute_ramp"], tmp_path / "parts.zip")
    assert (common.OUT, locale.setlocale(locale.LC_ALL)) == (out, before)  # put back for the other tests

    stems = ["bearing_fit_check", "chute_ramp", "chute_ramp_test"]  # chute_ramp has a build(test=True)
    assert sorted(files) == sorted(f"{package_parts.NAME}/{ext}/{s}.{ext}" for ext in package_parts.FORMATS for s in stems)

    with zipfile.ZipFile(tmp_path / "parts.zip") as zf:
        (tmp_path / "fit.3mf").write_bytes(zf.read(f"{package_parts.NAME}/3mf/bearing_fit_check.3mf"))
    mesher = Mesher()
    with package_parts.keep_locale():
        [shape] = mesher.read(tmp_path / "fit.3mf")
    assert mesher.model_unit.name == "MM"
    assert shape.volume == pytest.approx(package_parts.builds("bearing_fit_check")[0][1].volume, rel=1e-3)
    assert shape.bounding_box().min.Z == pytest.approx(0.0, abs=1e-6)
