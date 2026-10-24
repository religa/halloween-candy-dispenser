"""Build every printed part and zip the STL, 3MF and STEP files for a GitHub release.

Usage:
    uv run tools/package_parts.py                       # every part -> out/halloween-candy-dispenser-parts.zip
    uv run tools/package_parts.py motor_gear stand      # only these parts
    uv run tools/package_parts.py --zip parts.zip

Parts with a fit-check version (build(test=True)) also get <part>_test files.
.github/workflows/release.yml runs this on each v* tag and attaches the zip to the release.
"""

import argparse
import importlib
import inspect
import locale
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "parts"))  # part scripts import common, hardware, gearing

import common  # noqa: E402
from build123d import Mesher, Part  # noqa: E402

NAME = "halloween-candy-dispenser-parts"
FORMATS = ("stl", "3mf", "step")


def part_names() -> list[str]:
    """Every script in parts/ with a build(); the helpers (common, gearing, hardware) have none."""
    return [p.stem for p in sorted((ROOT / "parts").glob("*.py")) if hasattr(importlib.import_module(p.stem), "build")]


def builds(name: str) -> list[tuple[str, Part]]:
    build = importlib.import_module(name).build
    parts = [(name, build())]
    if "test" in inspect.signature(build).parameters:
        parts.append((f"{name}_test", build(test=True)))
    return parts


@contextmanager
def keep_locale():
    """Mesher.write sets the whole process to the C locale (ASCII text I/O); put it back."""
    saved = locale.setlocale(locale.LC_ALL)
    try:
        yield
    finally:
        locale.setlocale(locale.LC_ALL, saved)


def export_3mf(part: Part, path: Path) -> None:
    mesher = Mesher()
    mesher.add_shape(part, linear_deflection=0.01, angular_deflection=0.1)  # same as common.export's STL
    with keep_locale():
        mesher.write(path)


def package(names: list[str], zip_path: Path) -> list[str]:
    """Write zip_path with stl/, 3mf/ and step/ folders; return the files' names in the zip."""
    out = common.OUT
    with tempfile.TemporaryDirectory() as tmp:
        common.OUT = Path(tmp)  # export() writes .stl and .step here, never into out/
        try:
            for name in names:
                for label, part in builds(name):
                    common.export(part, label)
                    export_3mf(part, common.OUT / f"{label}.3mf")
            files = sorted(common.OUT.iterdir())
        finally:
            common.OUT = out
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f"{NAME}/{f.suffix[1:]}/{f.name}")
            return zf.namelist()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("parts", nargs="*", help="part names (default: every part in parts/)")
    parser.add_argument("--zip", type=Path, default=ROOT / "out" / f"{NAME}.zip", help="zip to write")
    args = parser.parse_args()
    names = args.parts or part_names()
    files = package(names, args.zip)
    print(f"{args.zip}: {len(files)} files from {len(names)} parts")


if __name__ == "__main__":
    main()
