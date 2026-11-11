# PrintCAD QA Flows

Manual and semi-automated QA flows for PrintCAD v0.1.0. Each flow has an ID, preconditions, steps and expected results.
Policy: **no flow or automated test may be skipped.** A failing flow is a defect to fix before continuing (design stage, not production).

Priority: **P0** = release blocker, **P1** = important, **P2** = polish.

## 0. Environment setup

| Item | Value |
| --- | --- |
| Python | 3.10, 3.11, 3.12 (run the full suite on each) |
| OS | Linux (headless, needs `libgl1`), macOS, Windows |
| Browsers (web UI) | Latest Chrome, Firefox, Safari/Edge (WebGL required) |
| Install | `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"` |
| Baseline | `pytest` passes with 0 skipped, 0 xfail, 0 deselected |

**QA-00 (P0) Baseline gate**
1. Fresh venv, `pip install -e ".[dev]"`.
2. `pytest -rs` and check the summary.
3. Expected: all tests pass, summary shows no `skipped`, `xfailed` or `deselected`.
4. `printcad --version` prints `printcad 0.1.0`.

---

## 1. CLI flows

**CLI-01 (P0) Run an example to STL**
1. `printcad run src/printcad/examples/bracket.py -o /tmp/bracket.stl`
2. Expected: exit 0, file exists, non-empty, binary STL (80-byte header, triangle count matches file size: `84 + 50*n`), a human-readable analysis summary is printed.

**CLI-02 (P0) Run to each output format**
1. Run `gear.py` with `-o out.stl`, `out.3mf`, `out.step`.
2. Expected: all three are written. `3mf` is a valid zip containing `3D/3dmodel.model`. `step` starts with `ISO-10303-21`. STL and 3MF re-import via `printcad analyze` with matching volume (within 0.1%).

**CLI-03 (P0) Parameter override**
1. `printcad run gear.py -o g.stl -p teeth=24 -p module=1.5 --json`
2. Expected: JSON parses. Bounding box and volume differ from defaults. Larger `teeth` gives a larger bounding box.

**CLI-04 (P1) Parameter validation**
| Input | Expected |
| --- | --- |
| `-p teeth=abc` (int param) | non-zero exit, message `Parameter 'teeth' has invalid value` |
| `-p teeth=12.5` (int param) | non-zero exit, "not an integer" |
| value below `min` / above `max` | non-zero exit naming the parameter and the limit |
| `-p noequals` | non-zero exit with a clear usage/format message |
| `-p unknown=1` (undeclared) | defined behavior, no traceback (record actual behavior and confirm it is intentional) |
| bool param `-p flag=true/1/yes/on/false` | parsed as bool |

**CLI-05 (P1) Printer and material selection**
1. Run the same script with each printer (`--printer`) and each material (`--material`) from `--help` choices.
2. Expected: build-volume-fit result changes with the printer (for example a 350 mm part fits Voron 350 but not Ender-3); weight scales with material density; invalid names rejected by argparse with the list of choices.

**CLI-06 (P0) Error handling**
| Case | Expected |
| --- | --- |
| Script path does not exist | non-zero exit, readable message, no traceback |
| Script has a syntax error | message with line number |
| Script runtime error | message `ExceptionType: msg (line N)` |
| Script never assigns `result` | message about `result` |
| `result` is not Workplane/Shape/Assembly | message naming the actual type |
| Output extension unsupported (`.obj`) | non-zero exit, message lists supported formats |
| Output directory not writable / missing | non-zero exit, readable message |

**CLI-07 (P0) Analyze STL and 3MF**
1. Export a known box (for example 20x20x20) to STL and 3MF.
2. `printcad analyze box.stl --printer prusa_mk4` and the same for `.3mf`.
3. Expected: volume 8000 mm³ (±0.5%), watertight and manifold true, overhang area about 0 for a box sitting on the bed, min wall about 20 mm.
4. `--overhang-angle 50` changes the overhang result on a part with sloped faces (use a 45° chamfer or cone).
5. `--json` output is valid JSON with the same fields as the human-readable output.
6. A `.step` or unknown extension is rejected with a clear message. A corrupt or empty STL gives a clear error, not a traceback.

**CLI-08 (P2) Help and usage**
`printcad`, `printcad -h`, `printcad run -h`, `printcad analyze -h`, `printcad serve -h` all work. No subcommand prints usage and exits non-zero.

---

## 2. Script runner flows

**RUN-01 (P0) Valid script variants**
Verify `result` as a `Workplane`, a `cq.Shape` (for example `cq.Solid.makeBox`), a multi-solid Workplane (compound) and a `cq.Assembly`. All export and analyze.

**RUN-02 (P0) Parameters**
1. Declare int, float, bool and str params with min/max.
2. Expected: panel/`params` list reports `name, default, value, type, min, max`. Calling `param` twice with the same name returns the same value and does not duplicate the entry. Overrides are coerced to the declared type.

**RUN-03 (P0) Restricted environment**
| Script content | Expected |
| --- | --- |
| `import os` / `import subprocess` / `import sys` | `ImportError ... not allowed` |
| `from printcad.runner import x` | not allowed (only `printcad` and `printcad.tolerances`) |
| `import numpy`, `import math`, `import cadquery`, `import typing` | allowed |
| `open("/etc/passwd")` | `NameError` (builtin removed) |
| `__import__("os")` | not allowed |
| `eval`, `exec`, `compile` | `NameError` |
| relative import | not allowed |

Note: this is a guardrail, not a sandbox (see README Security). Do not log bypasses as P0 unless the README claim changes. Record any bypass found (for example via `type`, `getattr`, `object.__subclasses__`) as a P1 documentation or hardening item.

**RUN-04 (P1) print capture**
`print("a", 1)` in a script shows up in `stdout` (API) and is not written to the server console.

**RUN-05 (P1) Geometry failure modes**
Zero-size box, a fillet larger than the geometry, empty Workplane, a boolean that yields nothing. Expected: a `ScriptError`/HTTP 400 with a message, never a 500 or a server crash.

**RUN-06 (P1) Runaway scripts**
`while True: pass` and a very large geometry. Record behavior (no timeout is implemented per the code). File a defect or an explicit documented limitation. Do not leave this unrecorded.

---

## 3. HTTP API flows

Start the server with `printcad serve` (or use the FastAPI `TestClient`).

**API-01 (P0) Read endpoints**
- `GET /api/health` returns `{"status":"ok","version":"0.1.0"}`.
- `GET /api/printers` returns all 7 printers (Ender-3, Prusa MK4, MINI+, Bambu X1, A1 mini, Creality K1, Voron 2.4 350) with build volume.
- `GET /api/materials` returns PLA, PETG, ABS, ASA, TPU, Nylon, PC with density.
- `GET /api/examples` returns bracket, enclosure, gear, each with a script and a title.
- `GET /docs` and `/openapi.json` load.

**API-02 (P0) POST /api/run happy path**
Body `{script, params, printer, material, overhang_angle, infill}`.
Expected: `mesh.vertices` length divisible by 3 and `mesh.indices` by 3, all indices < vertex count, `overhang_faces` indexes valid triangles, `analysis` present, `params` lists declared params, `stdout` is a string.

**API-03 (P0) POST /api/run errors**
| Case | Expected |
| --- | --- |
| Missing `script` | 422 |
| Unknown printer or material | 400 with a readable detail |
| Script syntax/runtime error | 400 with `detail` text |
| Param below min / invalid type | 400 |
| `overhang_angle` out of range (0, 90, negative) | 400 or documented behavior, never a 500 |
| `infill` out of range (-1, 1.5) | 400 or documented behavior |
| Invalid JSON | 422 |

**API-04 (P1) Units contract: infill**
API `infill` is a fraction (0.2 default). The web UI shows percent (20). Verify the UI converts, and that the API handling of `infill=20` (user error) is deliberate (rejected or clamped) and not silently wrong.

**API-05 (P0) POST /api/export/{fmt}**
- `stl`, `3mf`, `step` return 200 with the right `Content-Type`, `Content-Disposition: attachment; filename="model.<fmt>"` and valid file content (see CLI-02).
- Upper case (`/api/export/STL`) works.
- `/api/export/obj` returns 400 listing supported formats.
- A script error returns 400, not 500.

**API-06 (P2) Static assets and root**
`GET /` returns index.html. `/static/app.js`, `/static/style.css`, `/static/vendor/three.module.min.js` return 200 with correct MIME types. Unknown static path returns 404. Server works with no network access (vendored three.js).

**API-07 (P1) Concurrency**
Fire 10 parallel `/api/run` calls with different params. Expected: each response matches its own params, no cross-talk, no crash.

---

## 4. Web UI flows

Run `printcad serve`, open http://127.0.0.1:8000.

**UI-01 (P0) First load**
Expected: no console errors, example/printer/material dropdowns populated, editor holds the first example script, viewer canvas present, status "Ready". Network tab shows only same-origin requests.

**UI-02 (P0) Run an example**
Pick each example (bracket, enclosure, gear) and click **Run**, then repeat with Ctrl+Enter.
Expected: status shows progress then success; model appears in the viewer; the build volume box is drawn; analysis panel is filled; parameter panel shows sliders/inputs for declared params; red overhang faces visible where applicable and legend matches.

**UI-03 (P0) Parameter panel**
Change a numeric param within and outside the min/max. Expected: in range re-runs the model and updates the geometry and analysis; out of range shows the server error in the status area and keeps the last good model (or clearly indicates none). Bool and str params render as appropriate controls.

**UI-04 (P0) Editing and errors**
1. Introduce a syntax error, Run: error with line number is displayed, no blank screen, UI still usable.
2. Fix it, Run: recovers.
3. Script with `import os`: error shown.
4. Empty editor: clear message.

**UI-05 (P1) Printer/material/angle/infill controls**
Change the printer: build volume box resizes and the fit result changes. Change the material: weight changes. Change the angle (1 to 89): overhang highlight changes. Infill 0 to 100: weight changes. Type out-of-range values (0, 90, -5, 150, empty) and check for a graceful result.

**UI-06 (P0) Export downloads**
Click STL, 3MF, STEP. Expected: a file `model.<ext>` downloads, opens in an external viewer or slicer, and matches the model on screen. Click export with a broken script: error shown, no corrupt download.

**UI-07 (P1) Viewer interaction**
Orbit, zoom, pan with mouse and trackpad. Window resize keeps aspect ratio. Switching examples resets or refits the camera. No memory growth over 50 consecutive runs (check for leaked geometries/materials).

**UI-08 (P2) Analysis panel content**
Shows watertight, manifold, volume, weight, bounding box, fits-build-volume (and rotated), overhang area, min wall, suggested orientation. Warnings are visually distinct from passes. Numbers match `printcad analyze` on the exported STL.

**UI-09 (P2) Cross-browser and layout**
Repeat UI-01 to UI-06 on Chrome, Firefox and Safari. Check a 1280x720 window, a narrow window, and a browser with WebGL disabled (expect a clear message rather than a blank page; README says WebGL is required).

**UI-10 (P2) Accessibility basics**
Tab order reaches all controls; buttons and inputs have visible focus and labels; contrast of muted text and red/green legend is acceptable (the legend should not rely on colour alone).

---

## 5. Analysis correctness flows (golden models)

Use analytic shapes and compare to known values.

| ID | Model | Expected |
| --- | --- | --- |
| AN-01 (P0) | Box 20x20x20 | volume 8000 mm³, watertight, manifold, no overhang, min wall about 20 |
| AN-02 (P0) | Cylinder r=10 h=20 | volume about 6283 mm³ (tessellation error under 1%) |
| AN-03 (P0) | Box with through-hole | volume reduced by hole volume, manifold true |
| AN-04 (P0) | Two disjoint boxes (compound) | valid result, volume is the sum |
| AN-05 (P0) | Open mesh (delete one triangle of a STL) | watertight false, manifold false, clear warning |
| AN-06 (P1) | Cone / 45° chamfer / flat underside | overhang area at angles 30, 45, 60 behaves monotonically; faces on the bed are exempt |
| AN-07 (P1) | Thin wall 0.4 mm box shell | min wall estimate about 0.4 and a thin-wall warning |
| AN-08 (P1) | Part bigger than the bed in one axis | does not fit; fits when rotated if the rotated bounding box fits |
| AN-09 (P1) | Weight | solid weight = volume × density; estimate with infill 0 < infill 100 solid; ordering by material density holds |
| AN-10 (P1) | Orientation suggestion | an L bracket lying on its flat face yields fewer overhangs than on its edge; suggestion is stable between runs |
| AN-11 (P2) | Units | all lengths mm, volume mm³ or cm³ stated consistently in CLI, API and UI |

---

## 6. Export and mesh integrity flows

**EX-01 (P0) STL**: header size 80 bytes, count matches, normals unit length, re-import gives the same volume and bounding box.

**EX-02 (P0) 3MF**: valid zip, `[Content_Types].xml`, `_rels/.rels`, `3D/3dmodel.model`; XML well-formed; unit is millimeter; vertex/triangle counts match the mesh; opens in a third-party tool (PrusaSlicer/Cura/3D Builder).

**EX-03 (P1) STEP**: re-importable with CadQuery (`cq.importers.importStep`), same volume within 0.1%.

**EX-04 (P1) Round trip**: STL → analyze, 3MF → analyze, same numbers for the same model.

**EX-05 (P1) Weld/manifold**: meshes from CadQuery tessellation are watertight for every example at default and extreme params.

---

## 7. Examples regression matrix

For each example (bracket, enclosure with lid, gear), run at default and at the min and max of every declared param, via CLI and API.

Expected per run: succeeds, watertight and manifold, fits the Prusa MK4 build volume at default params, and matches the CLI and API analysis.

Gear extras: teeth 8 to 60 and module range; check tooth profile symmetry visually.
Enclosure extras: lid and base both present, wall thickness meets the minimum for a 0.4 mm nozzle.

---

## 8. Tolerance helper flows

- `clearance_hole(d, "tight"|"normal"|"loose")` is increasing in order and always greater than d. Unknown fit name gives a clear `ValueError`.
- Press fit hole is smaller than the clearance hole for the same d.
- Snap-fit cantilever math: check against a hand calculation for a sample input (deflection, strain under material limit); out-of-range strain is flagged.
- Snap hook shape builds a valid solid and is usable inside a script via `tolerances.`.
- Non-positive input (0, negative) gives a clear error.

---

## 9. Non-functional flows

| ID | Flow | Expected |
| --- | --- | --- |
| NF-01 (P1) | Performance: run each example 5 times via API | record p50 and p95; set a budget (suggested: under 5 s for examples on a laptop). Response payload size of `/api/run` for the gear recorded |
| NF-02 (P1) | Large model: a gear with 100 teeth, a box with 1000 holes | no crash; time and payload size recorded |
| NF-03 (P1) | Security posture | `serve` binds 127.0.0.1 by default; `--host 0.0.0.0` works and the README warning is present. No path traversal via `/static/..%2f..` |
| NF-04 (P2) | Install | clean install on each OS, `libgl1` troubleshooting message reproduces on a headless box without GL and the README fix works |
| NF-05 (P2) | Packaging | `pip install .` (not editable) includes `web/*`, `web/vendor/*`, `examples/*.py`; `printcad serve` UI works from the installed wheel. Note the repo has both `examples.py` and an `examples/` directory, so check that this naming overlap does not break imports in a built wheel |
| NF-06 (P2) | Logging and shutdown | Ctrl+C stops the server cleanly; errors are logged server-side |

---

## 10. Suggested execution order

1. **Smoke (about 10 min, every commit):** QA-00, CLI-01, API-01, API-02, UI-01, UI-02.
2. **Regression (every PR):** sections 1, 2, 3 and 7 plus AN-01 to AN-05.
3. **Full (before each release):** everything above including cross-browser UI and non-functional flows.

## 11. Defect reporting template

```
ID / flow:       (for example UI-04)
Severity:        P0 | P1 | P2
Environment:     OS, Python, browser, printcad version/commit
Steps:
Expected:
Actual:
Attachments:     script, exported file, console/server log, screenshot
```

## 12. Candidate gaps to verify (observed while reading the code)

These are items to confirm during QA, not confirmed bugs.
1. No execution timeout in `run_script`, so a runaway script can hang the server (RUN-06).
2. `infill` is a fraction in the API but a percent in the UI, so validate ranges server-side (API-04).
3. Undeclared `-p` params are silently accepted in `run_script` (stored in `params` but not validated) (CLI-04).
4. Both `examples.py` and an `examples/` package-style directory exist under `printcad/` (NF-05).
5. The restricted builtins include `type`, `getattr` and `object`, which weakens the guardrail (RUN-03). Documented as not a sandbox.
6. `/api/run` returns the mesh as JSON number arrays, so payload size and latency for large models should be measured (NF-01, NF-02).
