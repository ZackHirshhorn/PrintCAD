# PrintCAD

Open source, code-first parametric CAD focused on 3D printing. PrintCAD wraps the
[CadQuery](https://github.com/CadQuery/cadquery) kernel (OpenCASCADE) with a local web UI,
a CLI, and printability checks that answer the questions you have before slicing:
will it fit, will it print, how heavy is it, and which way should it lie on the bed?

## Features

- **Parametric scripts**: write CadQuery in the browser or in a `.py` file, declare knobs with `param("width", 30.0, min=10, max=100)` and get a live parameter panel.
- **3D viewer** (three.js, vendored so it works offline): orbit/zoom, printer build volume box, overhang faces highlighted in red.
- **Printability analysis**: watertight and manifold checks, volume, weight by material and infill, bounding box, build volume fit (also if rotated), overhang area for a configurable angle, minimum wall thickness estimate (ray casting), and a suggested print orientation.
- **Printer and material profiles**: Ender-3, Prusa MK4 / MINI+, Bambu X1 / A1 mini, Creality K1, Voron 2.4 350; PLA, PETG, ABS, ASA, TPU, Nylon, PC.
- **Tolerance helpers** for printed fits: clearance holes, press fits, cantilever snap fit math and a snap hook shape.
- **Export** STL (binary), 3MF (written without extra dependencies) and STEP.
- **Examples**: L bracket, electronics enclosure with lid, involute spur gear.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .          # use ".[dev]" to also get the test dependencies
```

Python 3.10+ is required. CadQuery ships large wheels (OpenCASCADE), so the first install takes a while.

## Usage

### Web UI

```bash
printcad serve                 # http://127.0.0.1:8000
printcad serve --host 0.0.0.0 --port 8080
```

Pick an example, edit the script, press **Run** (or Ctrl+Enter). Changing a parameter re-runs the model.
Use the STL / 3MF / STEP buttons to download the current model.

### CLI

```bash
printcad run src/printcad/examples/gear.py -o gear.stl -p teeth=24 -p module=1.5 --printer ender3 --material petg
printcad run bracket.py -o bracket.3mf --json         # analysis as JSON
printcad analyze part.stl --printer prusa_mk4 --overhang-angle 50
```

`run` accepts `.stl`, `.3mf` and `.step` output. `analyze` reads `.stl` and `.3mf`.

### Script format

```python
width = param("width", 30.0, min=10, max=100)   # appears in the parameter panel
hole = tolerances.clearance_hole(4.0, "normal") # 4.2 mm hole for an M4 screw
result = cq.Workplane("XY").box(width, 20, 5).faces(">Z").workplane().hole(hole)
```

Available names: `cq` (CadQuery), `math`, `np` (numpy), `tolerances`, `param`, `params`. The script must assign the final
`Workplane`, `Shape` or `Assembly` to `result`. See `src/printcad/examples/`.

### HTTP API

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/printers`, `/api/materials`, `/api/examples` | Profiles and example scripts |
| POST | `/api/run` | `{script, params, printer, material, overhang_angle, infill}` returns mesh, analysis, declared params |
| POST | `/api/export/{stl,3mf,step}` | Same body, returns the file |
| GET | `/api/health` | Liveness |

Interactive docs are served at `/docs`.

## How the analysis works

- **Watertight / manifold**: vertices are welded, then every edge must be shared by exactly two triangles, traversed once in each direction.
- **Overhangs**: a face needs support when its normal points down more steeply than the threshold angle measured from vertical (default 45). Faces on the bed are exempt.
- **Wall thickness**: rays are cast inward from sampled faces and the shortest hit distance is reported. It is an estimate, not a guarantee.
- **Weight**: solid weight is volume times density. The estimate adds a 0.8 mm shell plus sparse infill, a rough stand-in for a slicer.

## Security

Scripts are Python code. The runner restricts builtins and imports to catch mistakes, but it is **not** a security sandbox.
`printcad serve` binds to `127.0.0.1` by default; do not expose it to untrusted users.

## Troubleshooting

- `ImportError: libGL.so.1: cannot open shared object file` on headless Linux: CadQuery's OpenCASCADE bindings need the GL library even though nothing is rendered. Install it, for example `sudo apt install libgl1` (Debian/Ubuntu) or `sudo dnf install mesa-libGL` (Fedora/RHEL).
- The 3D view needs a browser with WebGL.

## Development

```bash
pip install -e ".[dev]"
playwright install chromium   # browser for the web UI tests
pytest                        # everything
pytest -m p0                  # only the automated P0 QA flows (tests/qa/)
pytest -m "p0 and not ui"     # P0 flows without the browser
```

No test may be skipped: `tests/conftest.py` turns any skip or xfail into a failure. The UI tests drive
the real server in headless Chromium with software WebGL; set `PRINTCAD_CHROMIUM=/path/to/chrome` to use
a specific browser binary. QA flows are described in [docs/qa/qa-flows.md](docs/qa/qa-flows.md).

The vendored three.js (r160, MIT) lives in `src/printcad/web/vendor/`.

## License

MIT, see [LICENSE](LICENSE).
