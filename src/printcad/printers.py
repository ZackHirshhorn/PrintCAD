"""Printer profiles (build volume and process parameters)."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Printer:
    key: str
    name: str
    x: float
    y: float
    z: float
    nozzle: float = 0.4
    layer_height: float = 0.2
    xy_tolerance: float = 0.2  # typical extra clearance needed for sliding fits, mm

    @property
    def volume(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["volume"] = list(self.volume)
        return d


PRINTERS: dict[str, Printer] = {
    p.key: p
    for p in [
        Printer("ender3", "Creality Ender-3", 220, 220, 250, xy_tolerance=0.3),
        Printer("prusa_mk4", "Prusa MK4", 250, 210, 220, xy_tolerance=0.2),
        Printer("prusa_mini", "Prusa MINI+", 180, 180, 180, xy_tolerance=0.2),
        Printer("bambu_x1", "Bambu Lab X1 Carbon", 256, 256, 256, xy_tolerance=0.15),
        Printer("bambu_a1_mini", "Bambu Lab A1 mini", 180, 180, 180, xy_tolerance=0.2),
        Printer("creality_k1", "Creality K1", 220, 220, 250, xy_tolerance=0.2),
        Printer("voron_350", "Voron 2.4 350", 350, 350, 330, xy_tolerance=0.15),
    ]
}


def get_printer(key: str) -> Printer:
    try:
        return PRINTERS[key.lower()]
    except KeyError:
        raise KeyError(f"Unknown printer '{key}'. Available: {', '.join(PRINTERS)}") from None
