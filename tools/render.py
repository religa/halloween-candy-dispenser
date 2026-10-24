"""Render an STL to a PNG with isometric, front, top and side views.

Works headless (matplotlib only), so it runs anywhere without a GPU or window.

Usage:
    uv run tools/render.py "ref/automatic-candy-dispenser/motor gear.stl"
    uv run tools/render.py part.stl -o preview.png
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import trimesh
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

VIEWS = [  # (title, elevation, azimuth, axis pointing at the viewer)
    ("iso", 30, -60, None),
    ("front (-Y)", 0, -90, "y"),
    ("top (+Z)", 90, -90, "z"),
    ("right (+X)", 0, 0, "x"),
]
BASE_COLOR = np.array([0.95, 0.55, 0.15])
LIGHT = np.array([0.4, -0.6, 0.7]) / np.linalg.norm([0.4, -0.6, 0.7])


def shaded_colors(mesh: trimesh.Trimesh) -> np.ndarray:
    brightness = 0.35 + 0.65 * np.clip(mesh.face_normals @ LIGHT, 0, 1)
    return np.clip(brightness[:, None] * BASE_COLOR, 0, 1)


def eye_direction(elev: float, azim: float) -> np.ndarray:
    e, a = np.radians(elev), np.radians(azim)
    return np.array([np.cos(e) * np.cos(a), np.cos(e) * np.sin(a), np.sin(e)])


def render(mesh: trimesh.Trimesh, out: Path, title: str):
    colors = shaded_colors(mesh)
    lo, hi = mesh.bounds
    center, half = (lo + hi) / 2, (hi - lo).max() / 2

    fig = plt.figure(figsize=(12, 12))
    for i, (name, elev, azim, depth_axis) in enumerate(VIEWS, start=1):
        ax = fig.add_subplot(2, 2, i, projection="3d")
        # Drop faces pointing away from the camera; matplotlib's depth sorting
        # would otherwise paint some of them over the visible surface.
        front = mesh.face_normals @ eye_direction(elev, azim) > 1e-6
        # Edges in the face color hide anti-aliasing seams between triangles.
        faces = Poly3DCollection(mesh.triangles[front], facecolors=colors[front], edgecolors=colors[front], linewidths=0.3)
        ax.add_collection3d(faces)
        for set_lim, c in zip((ax.set_xlim, ax.set_ylim, ax.set_zlim), center, strict=True):
            set_lim(c - half, c + half)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_proj_type("ortho")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")
        ax.set_zlabel("Z")
        ax.set_title(name)
        if depth_axis:  # its ticks all collapse onto one spot in a flat view
            getattr(ax, f"set_{depth_axis}ticks")([])
            getattr(ax, f"set_{depth_axis}label")("")

    x, y, z = mesh.extents
    fig.suptitle(f"{title}  —  {x:.1f} × {y:.1f} × {z:.1f} mm", fontsize=14)
    fig.tight_layout()
    fig.savefig(out, dpi=100)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stl", type=Path)
    parser.add_argument("-o", "--out", type=Path, help="output PNG (default: next to the STL)")
    args = parser.parse_args()

    out = args.out or args.stl.with_suffix(".png")
    render(trimesh.load_mesh(args.stl, force="mesh"), out, args.stl.stem)
    print(out)


if __name__ == "__main__":
    main()
