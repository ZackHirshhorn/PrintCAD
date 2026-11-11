"""Command line interface: printcad serve | run | analyze."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .analysis import analyze_mesh
from .export import FORMATS, export_bytes
from .materials import MATERIALS, get_material
from .mesh import load_mesh
from .printers import PRINTERS, get_printer
from .runner import ScriptError
from .service import build


def _parse_params(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise ValueError(f"Invalid --param '{item}', expected NAME=VALUE")
        out[key] = value
    return out


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="printcad", description="3D printing focused parametric CAD")
    p.add_argument("--version", action="version", version=f"printcad {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="start the web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)

    r = sub.add_parser("run", help="run a CadQuery script and export the result")
    r.add_argument("script", type=Path)
    r.add_argument("-o", "--output", type=Path, required=True, help="output file (.stl, .3mf or .step)")
    r.add_argument("-p", "--param", action="append", default=[], metavar="NAME=VALUE")
    r.add_argument("--printer", default="prusa_mk4", choices=sorted(PRINTERS))
    r.add_argument("--material", default="pla", choices=sorted(MATERIALS))
    r.add_argument("--json", action="store_true", help="print the analysis as JSON")

    a = sub.add_parser("analyze", help="analyze an STL or 3MF file")
    a.add_argument("file", type=Path)
    a.add_argument("--printer", default="prusa_mk4", choices=sorted(PRINTERS))
    a.add_argument("--material", default="pla", choices=sorted(MATERIALS))
    a.add_argument("--overhang-angle", type=float, default=45.0)
    a.add_argument("--json", action="store_true", help="print the analysis as JSON")
    return p


def format_report(an: dict) -> str:
    size = an["bounding_box"]["size"]
    wall = an["min_wall_thickness"]
    bv = an["build_volume"]
    lines = [
        f"Triangles:        {an['triangle_count']}",
        f"Size (mm):        {size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}",
        f"Volume:           {an['volume'] / 1000:.3f} cm3",
        f"Surface area:     {an['surface_area']:.1f} mm2",
        f"Watertight:       {'yes' if an['watertight'] else 'NO'}",
        f"Manifold:         {'yes' if an['manifold'] else 'NO'}",
        f"Weight (solid):   {an['weight']['solid_grams']:.1f} g {an['weight']['material']}",
        f"Weight (est.):    {an['weight']['estimated_grams']:.1f} g at {an['weight']['infill'] * 100:.0f}% infill",
        f"Fits {bv['printer']}: {'yes' if bv['fits'] else 'no'}" + ("" if bv["fits"] or not bv["fits_rotated"] else " (fits if rotated)"),
        f"Overhang:         {an['overhang']['fraction'] * 100:.1f}% of surface above {an['overhang']['angle']:g} deg",
        f"Min wall (est.):  {'n/a' if wall is None else f'{wall:.2f} mm'}",
        f"Best orientation: {an['orientation']['best']}",
    ]
    lines += [f"WARNING: {w}" for w in an["warnings"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            import uvicorn

            print(f"PrintCAD running at http://{args.host}:{args.port}")
            uvicorn.run("printcad.api:app", host=args.host, port=args.port, log_level="info")
            return 0

        if args.command == "run":
            fmt = args.output.suffix.lstrip(".").lower()
            if fmt not in FORMATS:
                raise ValueError(f"Output extension must be one of: {', '.join('.' + f for f in FORMATS)}")
            res = build(args.script.read_text(), _parse_params(args.param), args.printer, args.material)
            args.output.write_bytes(export_bytes(fmt, res.shape, res.mesh, args.output.stem))
            print(json.dumps(res.analysis, indent=2) if args.json else format_report(res.analysis))
            print(f"Wrote {args.output}", file=sys.stderr)
            return 0

        if args.command == "analyze":
            mesh = load_mesh(args.file)
            an = analyze_mesh(mesh, get_printer(args.printer), get_material(args.material), args.overhang_angle)
            print(json.dumps(an, indent=2) if args.json else format_report(an))
            return 0
    except (ScriptError, ValueError, KeyError, OSError) as exc:
        msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else exc
        print(f"error: {msg}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
