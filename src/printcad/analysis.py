"""Printability analysis of triangle meshes (numpy only)."""
from __future__ import annotations

import itertools
from typing import Any

import numpy as np

from .materials import Material
from .mesh import Mesh
from .printers import Printer

BED_TOLERANCE = 1e-3  # faces this close to the lowest point count as bed contact


# ------------------------------------------------------------ topology


def edge_report(mesh: Mesh) -> dict[str, Any]:
    """Count open (boundary), non-manifold and inconsistently oriented edges.

    Expects a welded mesh. A closed, consistently oriented 2-manifold has every
    directed edge appearing exactly once and its reverse exactly once.
    """
    if len(mesh.faces) == 0:
        return {"open_edges": 0, "non_manifold_edges": 0, "inconsistent_edges": 0, "watertight": False, "manifold": False}
    f = mesh.faces
    directed = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    lo = directed.min(axis=1)
    hi = directed.max(axis=1)
    forward = directed[:, 0] < directed[:, 1]
    key = lo.astype(np.int64) * (int(mesh.faces.max()) + 1) + hi
    uniq, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    open_edges = int(np.sum(counts == 1))
    non_manifold = int(np.sum(counts > 2))
    # Orientation: each undirected edge with 2 uses must be traversed once per direction.
    fwd_counts = np.bincount(inverse, weights=forward.astype(float), minlength=len(uniq))
    two = counts == 2
    inconsistent = int(np.sum(two & (fwd_counts != 1)))
    watertight = open_edges == 0 and non_manifold == 0
    return {
        "open_edges": open_edges,
        "non_manifold_edges": non_manifold,
        "inconsistent_edges": inconsistent,
        "watertight": watertight,
        "manifold": watertight and inconsistent == 0,
    }


def signed_volume(mesh: Mesh) -> float:
    t = mesh.triangles
    return float(np.sum(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2]))) / 6.0)


# ------------------------------------------------------------ overhangs


def overhang_mask(mesh: Mesh, angle: float = 45.0, normals: np.ndarray | None = None) -> np.ndarray:
    """Boolean mask of faces that need support (print direction +Z).

    `angle` is the maximum overhang angle measured from vertical: a vertical wall
    is 0 degrees, a flat ceiling is 90. Faces steeper than `angle` need support.
    Faces lying on the bed (lowest plane) do not need support.
    """
    if len(mesh.faces) == 0:
        return np.zeros(0, dtype=bool)
    n = mesh.face_normals() if normals is None else normals
    threshold = -np.sin(np.radians(angle))
    mask = n[:, 2] < threshold - 1e-9
    zmin = mesh.vertices[:, 2].min()
    on_bed = mesh.triangles[:, :, 2].max(axis=1) <= zmin + BED_TOLERANCE
    return mask & ~on_bed


def overhang_stats(mesh: Mesh, angle: float = 45.0) -> dict[str, float]:
    areas = mesh.face_areas()
    total = float(areas.sum())
    mask = overhang_mask(mesh, angle)
    area = float(areas[mask].sum())
    return {
        "angle": angle,
        "area": area,
        "fraction": area / total if total > 0 else 0.0,
        "face_count": int(mask.sum()),
    }


# ------------------------------------------------------------ wall thickness


def min_wall_thickness(mesh: Mesh, max_samples: int = 400, seed: int = 0) -> float | None:
    """Estimate the thinnest wall by casting rays inward from sampled faces.

    From each sampled face centroid a ray is cast along the inverted normal; the
    distance to the first triangle hit approximates the local thickness. Returns
    None if no ray hit anything (e.g. an empty mesh). Sampling is deterministic
    and biased toward including all faces for small meshes.
    """
    m = len(mesh.faces)
    if m == 0:
        return None
    rng = np.random.default_rng(seed)
    idx = np.arange(m) if m <= max_samples else rng.choice(m, max_samples, replace=False)
    tris = mesh.triangles
    normals = mesh.face_normals()
    areas = mesh.face_areas()
    idx = idx[areas[idx] > 1e-9]
    if len(idx) == 0:
        return None
    centers = tris[idx].mean(axis=1)
    dirs = -normals[idx]
    origins = centers + dirs * 1e-4

    v0 = tris[:, 0]
    e1 = tris[:, 1] - v0
    e2 = tris[:, 2] - v0
    best = np.inf
    chunk = max(1, 4_000_000 // max(m, 1))
    for s in range(0, len(idx), chunk):
        o = origins[s : s + chunk][:, None, :]  # (R,1,3)
        d = dirs[s : s + chunk][:, None, :]
        p = np.cross(d, e2[None, :, :])  # (R,M,3)
        det = np.einsum("rmk,mk->rm", p, e1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tvec = o - v0[None, :, :]
        u = np.einsum("rmk,rmk->rm", tvec, p) * inv
        q = np.cross(tvec, e1[None, :, :])
        v = np.einsum("rmk,rk->rm", q, d[:, 0, :]) * inv
        t = np.einsum("mk,rmk->rm", e2, q) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        if hit.any():
            best = min(best, float(np.where(hit, t, np.inf).min()) + 1e-4)
    return None if not np.isfinite(best) else best


# ------------------------------------------------------------ fit & orientation

# Rotations that bring each axis direction to face the bed (-Z).
_ORIENTATIONS: dict[str, np.ndarray] = {
    "z_up": np.eye(3),
    "z_down": np.diag([1.0, -1.0, -1.0]),
    "x_down": np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float),  # +X face to bed
    "x_up": np.array([[0, 0, -1], [0, 1, 0], [1, 0, 0]], dtype=float),
    "y_down": np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float),
    "y_up": np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float),
}


def orient(mesh: Mesh, name: str) -> Mesh:
    """Rotate `mesh` by a named orientation and drop it onto Z=0, centered in XY."""
    if name not in _ORIENTATIONS:
        raise ValueError(f"Unknown orientation '{name}'. Use one of: {', '.join(_ORIENTATIONS)}")
    rotated = mesh.transformed(_ORIENTATIONS[name])
    lo, hi = rotated.bounds()
    shift = np.array([-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]])
    return Mesh(rotated.vertices + shift, rotated.faces)


def bounding_box(mesh: Mesh) -> dict[str, Any]:
    lo, hi = mesh.bounds()
    return {"min": lo.tolist(), "max": hi.tolist(), "size": (hi - lo).tolist()}


def fits_build_volume(size, printer: Printer) -> bool:
    return all(s <= v + 1e-9 for s, v in zip(size, printer.volume))


def fits_any_rotation(size, printer: Printer) -> bool:
    """True if some axis permutation of `size` fits (90 degree rotations)."""
    return any(fits_build_volume(p, printer) for p in itertools.permutations(size))


def suggest_orientation(mesh: Mesh, angle: float = 45.0, printer: Printer | None = None) -> dict[str, Any]:
    """Rank the six axis-aligned orientations by support need.

    Score is the overhang area (needs support), with smaller print height and larger
    bed contact area as tie-breakers. Orientations that exceed the printer's build
    volume are rejected when a printer is given.
    """
    candidates = []
    for name in _ORIENTATIONS:
        o = orient(mesh, name)
        size = (o.bounds()[1] - o.bounds()[0]).tolist()
        areas = o.face_areas()
        mask = overhang_mask(o, angle)
        normals = o.face_normals()
        on_bed = (o.triangles[:, :, 2].max(axis=1) <= BED_TOLERANCE) & (normals[:, 2] < -0.99)
        entry = {
            "orientation": name,
            "overhang_area": float(areas[mask].sum()),
            "bed_contact_area": float(areas[on_bed].sum()),
            "height": size[2],
            "fits": True if printer is None else fits_build_volume(size, printer),
        }
        candidates.append(entry)
    usable = [c for c in candidates if c["fits"]] or candidates
    ranked = sorted(usable, key=lambda c: (round(c["overhang_area"], 3), c["height"], -c["bed_contact_area"]))
    best = ranked[0]
    return {"best": best["orientation"], "candidates": ranked}


# ------------------------------------------------------------ top level


def analyze_mesh(
    mesh: Mesh,
    printer: Printer,
    material: Material,
    overhang_angle: float = 45.0,
    infill: float = 0.2,
    wall_samples: int = 400,
) -> dict[str, Any]:
    """Full printability report for a welded mesh."""
    topo = edge_report(mesh)
    volume = abs(signed_volume(mesh)) if topo["watertight"] else max(signed_volume(mesh), 0.0)
    bbox = bounding_box(mesh)
    size = bbox["size"]
    wall = min_wall_thickness(mesh, max_samples=wall_samples) if topo["watertight"] else None
    areas = mesh.face_areas()
    warnings: list[str] = []
    if not topo["watertight"]:
        warnings.append("Mesh is not watertight; slicers may fail or produce gaps.")
    elif not topo["manifold"]:
        warnings.append("Mesh has inconsistent face orientation.")
    fits = fits_build_volume(size, printer)
    if not fits:
        if fits_any_rotation(size, printer):
            warnings.append(f"Part exceeds the {printer.name} build volume in this orientation but fits if rotated.")
        else:
            warnings.append(f"Part does not fit the {printer.name} build volume.")
    over = overhang_stats(mesh, overhang_angle)
    if over["fraction"] > 0.05:
        warnings.append(f"{over['fraction'] * 100:.0f}% of the surface overhangs more than {overhang_angle:g} degrees; supports likely needed.")
    if wall is not None and wall < material.min_wall:
        warnings.append(f"Thinnest wall ~{wall:.2f} mm is below the {material.min_wall} mm recommended for {material.name}.")
    solid_weight = volume / 1000.0 * material.density
    # Rough slicer model: two ~0.4 mm perimeters plus top/bottom skin (0.8 mm shell), sparse infill inside.
    shell_volume = min(volume, float(areas.sum()) * 0.8)
    estimated_grams = (shell_volume + (volume - shell_volume) * infill) / 1000.0 * material.density
    return {
        "vertex_count": int(len(mesh.vertices)),
        "triangle_count": int(len(mesh.faces)),
        "surface_area": float(areas.sum()),
        "volume": volume,
        "bounding_box": bbox,
        "topology": topo,
        "watertight": topo["watertight"],
        "manifold": topo["manifold"],
        "weight": {
            "material": material.key,
            "density": material.density,
            "solid_grams": solid_weight,
            "infill": infill,
            "estimated_grams": estimated_grams,
        },
        "build_volume": {
            "printer": printer.key,
            "volume": list(printer.volume),
            "fits": fits,
            "fits_rotated": fits or fits_any_rotation(size, printer),
        },
        "overhang": over,
        "min_wall_thickness": wall,
        "orientation": suggest_orientation(mesh, overhang_angle, printer),
        "warnings": warnings,
    }
