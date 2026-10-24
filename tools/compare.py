"""Compare two STL meshes, e.g. a rebuilt part against the reference original.

Aligns the candidate onto the reference (ICP), then reports size differences and
how much volume differs between them.

Usage:
    uv run tools/compare.py "ref/automatic-candy-dispenser/distance ring.stl" out/distance_ring.stl
"""

import argparse
from pathlib import Path

import numpy as np
import trimesh


def align(candidate: trimesh.Trimesh, reference: trimesh.Trimesh) -> tuple[trimesh.Trimesh, float]:
    """Rigidly move candidate onto reference; returns moved mesh and mean surface distance (mm)."""
    matrix, cost = trimesh.registration.mesh_other(candidate, reference, samples=3000, scale=False, icp_first=10, icp_final=50)
    return candidate.copy().apply_transform(matrix), cost


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--no-align", action="store_true", help="compare in the files' own coordinates")
    args = parser.parse_args()

    ref = trimesh.load_mesh(args.reference, force="mesh")
    cand = trimesh.load_mesh(args.candidate, force="mesh")

    if args.no_align:
        moved = cand
    else:
        moved, cost = align(cand, ref)
        print(f"alignment: mean surface distance {cost:.3f} mm")

    # Extents are compared sorted so a part modelled lying on another axis still matches.
    for label, a, b in [
        ("extents (sorted, mm)", np.sort(ref.extents), np.sort(cand.extents)),
        ("volume (cm3)", ref.volume / 1000, cand.volume / 1000),
        ("surface area (cm2)", ref.area / 100, cand.area / 100),
    ]:
        print(f"{label:<22} ref {np.round(a, 2)}  cand {np.round(b, 2)}  diff {np.round(np.subtract(b, a), 2)}")

    if ref.is_volume and moved.is_volume:
        only_ref = ref.difference(moved, engine="manifold").volume / 1000
        only_cand = moved.difference(ref, engine="manifold").volume / 1000
        print(f"{'missing from cand':<22} {only_ref:.3f} cm3")
        print(f"{'extra in cand':<22} {only_cand:.3f} cm3")
        print(f"{'match':<22} {100 * (1 - (only_ref + only_cand) / (ref.volume / 1000)):.1f}%")
    else:
        print("boolean comparison skipped: one of the meshes is not watertight")


if __name__ == "__main__":
    main()
