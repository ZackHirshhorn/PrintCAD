import json
import subprocess
import sys
from unittest import mock

import pytest

from printcad import cli
from printcad.analysis import signed_volume
from printcad.mesh import load_mesh

SCRIPT = "w = param('w', 10.0)\nresult = cq.Workplane('XY').box(w, 20, 30, centered=False)"


@pytest.fixture
def script(tmp_path):
    p = tmp_path / "box.py"
    p.write_text(SCRIPT)
    return p


@pytest.mark.parametrize("ext", ["stl", "3mf", "step"])
def test_run_exports(script, tmp_path, capsys, ext):
    out = tmp_path / f"out.{ext}"
    assert cli.main(["run", str(script), "-o", str(out)]) == 0
    assert out.stat().st_size > 0
    text = capsys.readouterr().out
    assert "Watertight:       yes" in text
    if ext != "step":
        assert signed_volume(load_mesh(out)) == pytest.approx(6000, rel=1e-4)


def test_run_with_params_and_json(script, tmp_path, capsys):
    out = tmp_path / "o.stl"
    assert cli.main(["run", str(script), "-o", str(out), "-p", "w=20", "--json", "--printer", "ender3", "--material", "abs"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["volume"] == pytest.approx(12000)
    assert data["weight"]["material"] == "abs"


def test_run_errors(script, tmp_path, capsys):
    assert cli.main(["run", str(script), "-o", str(tmp_path / "o.obj")]) == 1
    assert "extension" in capsys.readouterr().err
    assert cli.main(["run", str(script), "-o", str(tmp_path / "o.stl"), "-p", "bad"]) == 1
    assert "NAME=VALUE" in capsys.readouterr().err
    assert cli.main(["run", str(tmp_path / "missing.py"), "-o", str(tmp_path / "o.stl")]) == 1
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1")
    assert cli.main(["run", str(bad), "-o", str(tmp_path / "o.stl")]) == 1
    assert "result" in capsys.readouterr().err


def test_analyze(script, tmp_path, capsys):
    out = tmp_path / "o.stl"
    cli.main(["run", str(script), "-o", str(out)])
    capsys.readouterr()
    assert cli.main(["analyze", str(out)]) == 0
    text = capsys.readouterr().out
    assert "10.00 x 20.00 x 30.00" in text
    assert "Volume:           6.000 cm3" in text
    assert cli.main(["analyze", str(out), "--json", "--overhang-angle", "30", "--printer", "bambu_x1"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["overhang"]["angle"] == 30
    assert data["build_volume"]["printer"] == "bambu_x1"


def test_analyze_warnings_and_errors(tmp_path, capsys):
    other = tmp_path / "x.obj"
    other.write_text("v")
    assert cli.main(["analyze", str(other)]) == 1
    assert "Unsupported" in capsys.readouterr().err
    assert cli.main(["analyze", str(tmp_path / "none.stl")]) == 1
    big = tmp_path / "big.py"
    big.write_text("result = cq.Workplane('XY').box(400, 10, 10)")
    out = tmp_path / "big.stl"
    cli.main(["run", str(big), "-o", str(out), "--printer", "ender3"])
    text = capsys.readouterr().out
    assert "WARNING" in text and "Fits ender3: no" in text


def test_serve_invokes_uvicorn(capsys):
    with mock.patch("uvicorn.run") as run:
        assert cli.main(["serve", "--host", "0.0.0.0", "--port", "9123"]) == 0
    run.assert_called_once_with("printcad.api:app", host="0.0.0.0", port=9123, log_level="info")
    assert "http://0.0.0.0:9123" in capsys.readouterr().out


def test_no_command_and_version():
    with pytest.raises(SystemExit):
        cli.main([])
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0


def test_module_entry_point(script, tmp_path):
    out = tmp_path / "m.stl"
    r = subprocess.run([sys.executable, "-m", "printcad.cli", "run", str(script), "-o", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert out.exists()
