"""Helpers for geometry tests: export a part and measure the STL that gets printed."""

import itertools
import math
from pathlib import Path

import common
import numpy as np
import pytest
import shapely
import trimesh


def export_mesh(part, name: str, out_dir: Path) -> trimesh.Trimesh:
    """Export through common.export into out_dir (never the repo's out/) and load the STL."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(common, "OUT", out_dir)
        stl = common.export(part, name)
    return trimesh.load_mesh(stl, force="mesh")


def section(mesh: trimesh.Trimesh, z: float) -> list[shapely.Polygon]:
    """Filled polygons (with holes) where the plane at height z cuts the mesh."""
    path, _ = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1]).to_2D(to_2D=np.eye(4))
    return list(path.polygons_full)


def hole_centres(mesh: trimesh.Trimesh, z: float) -> list[tuple[float, float, float]]:
    """(x, y, diameter) of every hole in the section at height z.

    The diameter is the largest circle centred on the hole that fits inside it, i.e. the
    screw that actually passes. A slot with the same area as a round hole measures small.
    """
    holes = []
    for poly in section(mesh, z):
        for ring in poly.interiors:
            hole = shapely.Polygon(ring)
            centre = hole.centroid
            diameter = 2 * hole.exterior.distance(centre) if hole.covers(centre) else 0.0
            holes.append((centre.x, centre.y, diameter))
    return holes


def rotated(mesh: trimesh.Trimesh, deg: float) -> trimesh.Trimesh:
    return mesh.copy().apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), [0, 0, 1]))


def overlap_volume(meshes: list[trimesh.Trimesh]) -> float:
    # Non-touching pairs give an empty mesh (trimesh warns "invalid value in divide"); volume is 0.
    return sum(a.intersection(b, engine="manifold").volume for a, b in itertools.combinations(meshes, 2))


def rotated_point(xy: tuple[float, float], deg: float) -> tuple[float, float]:
    """xy turned deg degrees about the origin."""
    a = math.radians(deg)
    return (xy[0] * math.cos(a) - xy[1] * math.sin(a), xy[0] * math.sin(a) + xy[1] * math.cos(a))
