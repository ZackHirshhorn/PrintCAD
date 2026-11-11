"""P0 CLI flows: CLI-01, CLI-02, CLI-03, CLI-06, CLI-07."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from qa_helpers import CUBE20, EXAMPLES_DIR, INVERTED_CONE, read_binary_stl

pytestmark = pytest.mark.p0

GEAR = EXAMPLES_DIR / "gear.py"
BRACKET = EXAMPLES_DIR / "bracket.py"

REPORT_LABELS = (
    "Triangles:", "Size (mm):", "Volume:", "Surface area:", "Watertight:", "Manifold:",
    "Weight (solid):", "Weight (est.):", "Fits prusa_mk4:", "Overhang:", "Min wall (est.):", "Best orientation:",
)


def _json(result) -> dict:
    assert result.code == 0, result.err
    return json.loads(result.out)


@pytest.mark.qa("CLI-01")
def test_run_example_to_stl(run_cli, tmp_path):
    out = tmp_path / "bracket.stl"
    r = run_cli("run", BRACKET, "-o", out)
    assert r.code == 0, r.err
    data = out.read_bytes()
    count, _ = read_binary_stl(data)
    assert count > 0
    assert len(data) == 84 + 50 * count
    for label in REPORT_LABELS:
        assert label in r.out, f"summary is missing {label!r}:\n{r.out}"
    assert "Watertight:       yes" in r.out
    assert f"Wrote {out}" in r.err


@pytest.mark.qa("CLI-02")
def test_run_to_each_format_and_reimport(run_cli, tmp_path):
    reference = _json(run_cli("run", GEAR, "-o", tmp_path / "ref.stl", "--json"))["volume"]
    for ext in ("stl", "3mf", "step"):
        out = tmp_path / f"gear.{ext}"
        r = run_cli("run", GEAR, "-o", out)
        assert r.code == 0, f"{ext}: {r.err}"
        assert out.stat().st_size > 0
    with zipfile.ZipFile(io.BytesIO((tmp_path / "gear.3mf").read_bytes())) as zf:
        assert "3D/3dmodel.model" in zf.namelist()
    assert (tmp_path / "gear.step").read_bytes().startswith(b"ISO-10303-21")
    for ext in ("stl", "3mf"):
        volume = _json(run_cli("analyze", tmp_path / f"gear.{ext}", "--json"))["volume"]
        assert volume == pytest.approx(reference, rel=1e-3), ext


@pytest.mark.qa("CLI-03")
def test_parameter_overrides_change_the_model(run_cli, tmp_path):
    default = _json(run_cli("run", GEAR, "-o", tmp_path / "d.stl", "--json"))
    custom = _json(run_cli("run", GEAR, "-o", tmp_path / "c.stl", "-p", "teeth=24", "-p", "module=1.5", "--json"))
    assert custom["bounding_box"]["size"] != pytest.approx(default["bounding_box"]["size"])
    assert custom["volume"] != pytest.approx(default["volume"])

    small = _json(run_cli("run", GEAR, "-o", tmp_path / "s.stl", "-p", "teeth=16", "--json"))
    large = _json(run_cli("run", GEAR, "-o", tmp_path / "l.stl", "-p", "teeth=40", "--json"))
    assert large["bounding_box"]["size"][0] > small["bounding_box"]["size"][0]
    assert large["bounding_box"]["size"][1] > small["bounding_box"]["size"][1]


@pytest.mark.qa("CLI-06")
@pytest.mark.parametrize(
    "source,expected",
    [
        ("result = (", "Syntax error on line 1"),
        ("x = 1\nresult = 1 / 0", "ZeroDivisionError: division by zero (line 2)"),
        ("x = 1", "variable named 'result'"),
        ("result = 42", "got int"),
    ],
    ids=["syntax", "runtime", "no-result", "wrong-type"],
)
def test_script_errors_are_reported_cleanly(run_cli, script_file, tmp_path, source, expected):
    r = run_cli("run", script_file(source), "-o", tmp_path / "o.stl")
    assert r.code == 1
    assert expected in r.err
    assert r.err.startswith("error: ")
    assert "Traceback" not in r.err + r.out
    assert not (tmp_path / "o.stl").exists()


@pytest.mark.qa("CLI-06")
def test_missing_script_file(run_cli, tmp_path):
    r = run_cli("run", tmp_path / "missing.py", "-o", tmp_path / "o.stl")
    assert r.code == 1
    assert "missing.py" in r.err and "Traceback" not in r.err


@pytest.mark.qa("CLI-06")
def test_unsupported_output_extension(run_cli, script_file, tmp_path):
    r = run_cli("run", script_file(CUBE20), "-o", tmp_path / "o.obj")
    assert r.code == 1
    for ext in (".stl", ".3mf", ".step"):
        assert ext in r.err


@pytest.mark.qa("CLI-06")
def test_output_directory_missing(run_cli, script_file, tmp_path):
    r = run_cli("run", script_file(CUBE20), "-o", tmp_path / "no" / "such" / "dir" / "o.stl")
    assert r.code == 1
    assert "error:" in r.err and "Traceback" not in r.err


@pytest.mark.qa("CLI-06")
def test_output_directory_not_writable(run_cli, script_file, tmp_path):
    target = tmp_path / "is_a_directory.stl"
    target.mkdir()  # writing to a directory path fails regardless of the user's privileges
    r = run_cli("run", script_file(CUBE20), "-o", target)
    assert r.code == 1
    assert "error:" in r.err and "Traceback" not in r.err


@pytest.fixture
def cube_files(run_cli, script_file, tmp_path):
    src = script_file(CUBE20)
    paths = {}
    for ext in ("stl", "3mf"):
        paths[ext] = tmp_path / f"cube.{ext}"
        assert run_cli("run", src, "-o", paths[ext]).code == 0
    return paths


@pytest.mark.qa("CLI-07")
@pytest.mark.parametrize("ext", ["stl", "3mf"])
def test_analyze_known_cube(run_cli, cube_files, ext):
    data = _json(run_cli("analyze", cube_files[ext], "--printer", "prusa_mk4", "--json"))
    assert data["volume"] == pytest.approx(8000, rel=5e-3)
    assert data["watertight"] is True and data["manifold"] is True
    assert data["overhang"]["area"] == pytest.approx(0, abs=1e-6)
    assert data["min_wall_thickness"] == pytest.approx(20, abs=0.05)
    assert data["bounding_box"]["size"] == pytest.approx([20, 20, 20])


@pytest.mark.qa("CLI-07")
def test_analyze_overhang_angle_changes_result(run_cli, script_file, tmp_path):
    stl = tmp_path / "cone.stl"
    assert run_cli("run", script_file(INVERTED_CONE), "-o", stl).code == 0
    steep = _json(run_cli("analyze", stl, "--overhang-angle", "30", "--json"))["overhang"]
    loose = _json(run_cli("analyze", stl, "--overhang-angle", "50", "--json"))["overhang"]
    assert steep["angle"] == 30 and loose["angle"] == 50
    assert steep["area"] > 0
    assert loose["area"] < steep["area"]


@pytest.mark.qa("CLI-07")
def test_analyze_json_matches_human_report(run_cli, cube_files):
    data = _json(run_cli("analyze", cube_files["stl"], "--json"))
    text = run_cli("analyze", cube_files["stl"])
    assert text.code == 0
    for label in REPORT_LABELS:
        assert label in text.out
    assert f"Triangles:        {data['triangle_count']}" in text.out
    assert f"Volume:           {data['volume'] / 1000:.3f} cm3" in text.out
    size = data["bounding_box"]["size"]
    assert f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f}" in text.out
    assert f"Best orientation: {data['orientation']['best']}" in text.out


@pytest.mark.qa("CLI-07")
@pytest.mark.parametrize(
    "name,content",
    [
        ("part.step", b"ISO-10303-21;"),
        ("part.obj", b"v 0 0 0"),
        ("empty.stl", b""),
        ("garbage.stl", bytes(range(256)) * 3),
        ("garbage.3mf", b"this is not a zip archive"),
        ("nomodel.3mf", None),
    ],
)
def test_analyze_rejects_bad_input_cleanly(run_cli, tmp_path, name, content):
    path = tmp_path / name
    if content is None:  # a valid zip without 3D/3dmodel.model
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("readme.txt", "no model here")
        content = buf.getvalue()
    path.write_bytes(content)
    r = run_cli("analyze", path)
    assert r.code == 1, r.out
    assert r.err.startswith("error: ")
    assert "Traceback" not in r.err + r.out
