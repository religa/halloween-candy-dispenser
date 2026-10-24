"""Shared dimensions and export helper for part scripts.

Each part lives in its own script in this folder, builds a build123d Part from the
values below, and ends with `export(part, "name")`.
"""

from pathlib import Path

from build123d import Part, export_step, export_stl

OUT = Path(__file__).resolve().parent.parent / "out"

# Print tolerances (mm). Tune these after a test print, not per part.
CLEARANCE = 0.2  # gap between parts that slide or rotate against each other
PRESS_FIT = 0.05  # interference-free fit for parts pushed together
WALL = 2.4  # default wall thickness (6 perimeters of a 0.4 mm nozzle)

PLATE_MAX = 170.0  # A1 mini bed is 180 x 180 x 180 mm; keep >=5 mm margin per side
BUILD_HEIGHT = 180.0  # A1 mini maximum print height


def export(part: Part, name: str) -> Path:
    """Write out/<name>.stl for printing and out/<name>.step for opening in CAD."""
    OUT.mkdir(exist_ok=True)
    stl = OUT / f"{name}.stl"
    export_stl(part, stl, tolerance=0.01, angular_tolerance=0.1)
    export_step(part, OUT / f"{name}.step")
    print(stl)
    return stl
