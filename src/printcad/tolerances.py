"""Tolerance helpers for printed parts: clearance holes, press fits, snap fits."""
from __future__ import annotations

import cadquery as cq

# Extra diameter (mm) added on top of the nominal size, for a 0.4 mm nozzle FDM printer.
FIT_ALLOWANCE = {
    "tight": 0.1,
    "normal": 0.2,
    "loose": 0.4,
}


def clearance_hole(diameter: float, fit: str = "normal") -> float:
    """Return the diameter to model for a hole that must pass a shaft of `diameter`."""
    if diameter <= 0:
        raise ValueError("diameter must be positive")
    if fit not in FIT_ALLOWANCE:
        raise ValueError(f"fit must be one of {sorted(FIT_ALLOWANCE)}")
    return round(diameter + FIT_ALLOWANCE[fit], 4)


def press_fit_hole(diameter: float, interference: float = 0.1) -> float:
    """Return the hole diameter for a press fit; `interference` is the diametral interference.

    FDM holes print slightly small, so a hole equal to the shaft minus a small
    interference gives a firm press fit.
    """
    if diameter <= 0:
        raise ValueError("diameter must be positive")
    if interference < 0 or interference >= diameter:
        raise ValueError("interference must be in [0, diameter)")
    return round(diameter - interference, 4)


def snap_fit_cantilever(
    length: float,
    thickness: float,
    deflection: float,
    strain_limit: float = 0.02,
    modulus: float = 2300.0,
    width: float = 5.0,
) -> dict:
    """Design numbers for a rectangular cantilever snap fit.

    Max strain at the root: e = 1.5 * t * y / L^2 (y = deflection). Returns the
    strain, whether it is within `strain_limit`, the maximum safe deflection and
    the force needed to deflect the beam (modulus in MPa, result in N).
    """
    if min(length, thickness, deflection, width) <= 0:
        raise ValueError("length, thickness, deflection and width must be positive")
    strain = 1.5 * thickness * deflection / length**2
    max_deflection = strain_limit * length**2 / (1.5 * thickness)
    inertia = width * thickness**3 / 12.0
    force = 3.0 * modulus * inertia * deflection / length**3
    return {
        "strain": strain,
        "ok": strain <= strain_limit,
        "max_deflection": max_deflection,
        "deflection_force": force,
    }


def snap_hook(length: float, thickness: float, width: float, hook_depth: float) -> cq.Workplane:
    """Cantilever beam along +Z with a triangular hook at its tip (hook points +X)."""
    if min(length, thickness, width, hook_depth) <= 0:
        raise ValueError("all dimensions must be positive")
    beam = cq.Workplane("XY").box(thickness, width, length, centered=(False, True, False))
    hook_len = min(hook_depth * 2.0, length / 2.0)
    hook = (
        cq.Workplane("XZ")
        .polyline(
            [
                (thickness, length - hook_len),
                (thickness + hook_depth, length - hook_len),
                (thickness, length),
            ]
        )
        .close()
        .extrude(width / 2.0, both=True)
    )
    return beam.union(hook)


def min_printable_feature(nozzle: float = 0.4) -> float:
    """Smallest reliably printable wall in mm (two perimeters)."""
    return round(2.0 * nozzle, 4)

