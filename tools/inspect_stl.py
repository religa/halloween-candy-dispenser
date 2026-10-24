"""Summarize STL meshes: size, printability and material.

Usage:
    uv run tools/inspect_stl.py ref/automatic-candy-dispenser
    uv run tools/inspect_stl.py out/turntable_gear.stl other.stl
"""

import argparse
from pathlib import Path

import trimesh

PLA_DENSITY = 1.24  # g/cm^3


def collect(paths: list[str]) -> list[Path]:
    files = []
    for p in map(Path, paths):
        files.extend(sorted(p.glob("*.stl")) if p.is_dir() else [p])
    return files


def load(path: Path) -> trimesh.Trimesh:
    return trimesh.load_mesh(path, force="mesh")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="STL files or directories")
    args = parser.parse_args()

    header = f"{'part':<28} {'x':>7} {'y':>7} {'z':>7}  {'tris':>7} {'bodies':>6} {'watertight':>10} {'cm3':>7} {'g PLA':>6}"
    print(header)
    print("-" * len(header))
    for path in collect(args.paths):
        mesh = load(path)
        x, y, z = mesh.extents
        cm3 = mesh.volume / 1000 if mesh.is_volume else float("nan")
        print(
            f"{path.stem[:28]:<28} {x:7.1f} {y:7.1f} {z:7.1f}  {len(mesh.faces):7d} "
            f"{mesh.body_count:6d} {str(mesh.is_watertight):>10} {cm3:7.1f} {cm3 * PLA_DENSITY:6.0f}"
        )
    print("\nDimensions in mm. Mass is solid PLA (100% infill), so an upper bound.")


if __name__ == "__main__":
    main()
