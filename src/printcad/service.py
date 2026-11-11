"""High-level pipeline: script -> shape -> mesh -> analysis."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .analysis import analyze_mesh, overhang_mask
from .materials import get_material
from .mesh import Mesh, tessellate_shape
from .printers import get_printer
from .runner import run_script


@dataclass
class BuildResult:
    shape: Any
    mesh: Mesh
    analysis: dict[str, Any]
    params: list[dict[str, Any]]
    stdout: str
    overhang_faces: list[int]


def build(
    script: str,
    params: dict[str, Any] | None = None,
    printer: str = "prusa_mk4",
    material: str = "pla",
    overhang_angle: float = 45.0,
    infill: float = 0.2,
    tolerance: float = 0.05,
) -> BuildResult:
    if not 0 < overhang_angle < 90:
        raise ValueError("overhang_angle must be between 0 and 90 degrees")
    if not 0 <= infill <= 1:
        raise ValueError("infill must be between 0 and 1")
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    prn = get_printer(printer)
    mat = get_material(material)
    run = run_script(script, params)
    mesh = tessellate_shape(run.shape, tolerance=tolerance)
    if len(mesh.faces) == 0:
        raise ValueError("Model produced an empty mesh")
    analysis = analyze_mesh(mesh, prn, mat, overhang_angle, infill)
    mask = overhang_mask(mesh, overhang_angle)
    return BuildResult(
        shape=run.shape,
        mesh=mesh,
        analysis=analysis,
        params=[p.to_dict() for p in run.params],
        stdout=run.stdout,
        overhang_faces=[int(i) for i in mask.nonzero()[0]],
    )
