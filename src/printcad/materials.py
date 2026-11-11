"""Filament material database."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    density: float  # g/cm^3
    min_wall: float  # recommended minimum wall thickness in mm
    nozzle_temp: int  # typical nozzle temperature in C
    shrinkage: float  # typical linear shrinkage fraction

    def to_dict(self) -> dict:
        return asdict(self)


MATERIALS: dict[str, Material] = {
    m.key: m
    for m in [
        Material("pla", "PLA", 1.24, 0.8, 210, 0.002),
        Material("petg", "PETG", 1.27, 1.0, 235, 0.004),
        Material("abs", "ABS", 1.04, 1.2, 245, 0.008),
        Material("asa", "ASA", 1.07, 1.2, 250, 0.007),
        Material("tpu", "TPU", 1.21, 1.2, 225, 0.005),
        Material("nylon", "Nylon (PA12)", 1.01, 1.2, 255, 0.012),
        Material("pc", "Polycarbonate", 1.20, 1.2, 270, 0.007),
    ]
}


def get_material(key: str) -> Material:
    try:
        return MATERIALS[key.lower()]
    except KeyError:
        raise KeyError(f"Unknown material '{key}'. Available: {', '.join(MATERIALS)}") from None
