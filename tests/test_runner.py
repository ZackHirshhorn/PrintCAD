import cadquery as cq
import pytest

from printcad.runner import ScriptError, run_script


def test_basic_script():
    r = run_script("result = cq.Workplane('XY').box(1, 2, 3)")
    assert isinstance(r.shape, cq.Shape)
    assert r.shape.Volume() == pytest.approx(6)
    assert r.params == []


def test_params_declared_and_overridden():
    script = "w = param('w', 10.0, min=1, max=50)\nn = param('n', 2)\nresult = cq.Workplane('XY').box(w, 1, n)"
    r = run_script(script)
    assert [p.name for p in r.params] == ["w", "n"]
    assert r.shape.Volume() == pytest.approx(20)
    r = run_script(script, {"w": "5", "n": 4})
    assert r.shape.Volume() == pytest.approx(20)
    spec = {p.name: p for p in r.params}["w"]
    assert spec.value == 5.0 and spec.default == 10.0 and spec.type == "float"
    assert spec.min == 1 and spec.max == 50
    assert spec.to_dict()["type"] == "float"


def test_param_types_and_bool():
    script = "b = param('b', True)\ns = param('s', 'abc')\nresult = cq.Workplane('XY').box(1, 1, 1 if b else 2)"
    assert run_script(script, {"b": "false"}).shape.Volume() == pytest.approx(2)
    assert run_script(script, {"b": False}).shape.Volume() == pytest.approx(2)
    r = run_script(script, {"s": 5})
    assert {p.name: p.value for p in r.params}["s"] == "5"


def test_param_repeated_returns_same():
    script = "a = param('a', 3.0)\nb = param('a', 99.0)\nresult = cq.Workplane('XY').box(a, b, 1)"
    assert run_script(script).shape.Volume() == pytest.approx(9)


@pytest.mark.parametrize(
    "script,params,msg",
    [
        ("param('w', 5, min=10)\nresult = cq.Workplane().box(1,1,1)", {}, "below the minimum"),
        ("param('w', 5, max=10)\nresult = cq.Workplane().box(1,1,1)", {"w": 11}, "above the maximum"),
        ("param('w', 5)\nresult = cq.Workplane().box(1,1,1)", {"w": "abc"}, "invalid value"),
        ("param('w', 5)\nresult = cq.Workplane().box(1,1,1)", {"w": 2.5}, "invalid value"),
        ("x = 1", {}, "named 'result'"),
        ("result = 5", {}, "must be a CadQuery"),
        ("result = cq.Workplane('XY')", {}, "no solids"),
        ("result = (", {}, "Syntax error"),
        ("1/0\nresult = None", {}, "ZeroDivisionError"),
    ],
)
def test_errors(script, params, msg):
    with pytest.raises(ScriptError, match=msg):
        run_script(script, params)


def test_error_reports_line_number():
    with pytest.raises(ScriptError, match=r"line 2"):
        run_script("x = 1\ny = undefined_name\nresult = None")


@pytest.mark.parametrize(
    "stmt",
    ["import os", "import subprocess", "from os import path", "import printcad.cli", "open('/etc/passwd')", "__import__('os')", "eval('1')", "exec('x=1')"],
)
def test_sandbox_blocks_dangerous(stmt):
    with pytest.raises(ScriptError):
        run_script(stmt + "\nresult = cq.Workplane().box(1,1,1)")


def test_allowed_imports_and_helpers():
    script = (
        "import math\nimport cadquery as cq2\nfrom printcad import tolerances as t\nimport numpy\n"
        "d = tolerances.clearance_hole(4)\n"
        "result = cq2.Workplane('XY').circle(d / 2).extrude(math.floor(2.9))"
    )
    r = run_script(script)
    assert r.shape.Volume() == pytest.approx(3.14159265 * 2.1**2 * 2, rel=1e-4)


def test_classes_and_functions_work():
    script = "class A:\n    def v(self):\n        return 3\ndef f(x):\n    return x * A().v()\nresult = cq.Workplane('XY').box(f(1), 1, 1)"
    assert run_script(script).shape.Volume() == pytest.approx(3)


def test_print_captured():
    r = run_script("print('hello', 3)\nresult = cq.Workplane().box(1,1,1)")
    assert r.stdout == "hello 3"


def test_shape_and_assembly_results():
    r = run_script("result = cq.Solid.makeBox(1, 2, 3)")
    assert r.shape.Volume() == pytest.approx(6)
    r = run_script(
        "a = cq.Assembly()\na.add(cq.Workplane().box(1, 1, 1), name='a')\n"
        "a.add(cq.Workplane().box(1, 1, 1), name='b', loc=cq.Location(cq.Vector(5, 0, 0)))\nresult = a"
    )
    assert r.shape.Volume() == pytest.approx(2)


def test_multiple_solids_compound():
    r = run_script(
        "result = cq.Workplane('XY').box(1, 1, 1).translate((0, 0, 0)).add(cq.Workplane('XY').box(1, 1, 1).translate((5, 0, 0)).vals())"
    )
    assert r.shape.Volume() == pytest.approx(2)
