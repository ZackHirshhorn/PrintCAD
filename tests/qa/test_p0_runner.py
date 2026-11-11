"""P0 script runner flows: RUN-01, RUN-02, RUN-03."""
from __future__ import annotations

import cadquery as cq
import pytest

from printcad.runner import ScriptError, run_script
from printcad.service import build

pytestmark = pytest.mark.p0


@pytest.mark.qa("RUN-01")
@pytest.mark.parametrize(
    "source,volume",
    [
        ("result = cq.Workplane('XY').box(10, 10, 10)", 1000),
        ("result = cq.Solid.makeBox(10, 20, 5)", 1000),
        (
            "result = cq.Workplane('XY').pushPoints([(0, 0), (30, 0)]).box(10, 10, 10)",
            2000,
        ),
        (
            "a = cq.Assembly()\n"
            "a.add(cq.Workplane('XY').box(10, 10, 10), name='a')\n"
            "a.add(cq.Workplane('XY').box(10, 10, 10), name='b', loc=cq.Location(cq.Vector(30, 0, 0)))\n"
            "result = a",
            2000,
        ),
    ],
    ids=["workplane", "shape", "multi-solid-workplane", "assembly"],
)
def test_valid_result_types_build_export_and_analyze(source, volume):
    run = run_script(source)
    assert isinstance(run.shape, cq.Shape)
    res = build(source)
    assert res.analysis["volume"] == pytest.approx(volume, rel=1e-6)
    assert res.analysis["watertight"] is True
    from printcad.export import export_bytes

    for fmt in ("stl", "3mf", "step"):
        assert len(export_bytes(fmt, res.shape, res.mesh)) > 0


PARAM_SCRIPT = """
n = param("n", 3, min=1, max=10)
size = param("size", 12.5, min=1.0, max=100.0)
hollow = param("hollow", False)
label = param("label", "abc")
again = param("n", 999)
print(n, size, hollow, label, again)
result = cq.Workplane("XY").box(size, size, n)
"""


@pytest.mark.qa("RUN-02")
def test_param_specs_reported_with_types_and_limits():
    run = run_script(PARAM_SCRIPT)
    specs = {p.name: p.to_dict() for p in run.params}
    assert list(specs) == ["n", "size", "hollow", "label"], "repeated param('n') must not add an entry"
    assert specs["n"] == {"name": "n", "default": 3, "value": 3, "type": "int", "min": 1, "max": 10}
    assert specs["size"] == {"name": "size", "default": 12.5, "value": 12.5, "type": "float", "min": 1.0, "max": 100.0}
    assert specs["hollow"] == {"name": "hollow", "default": False, "value": False, "type": "bool", "min": None, "max": None}
    assert specs["label"] == {"name": "label", "default": "abc", "value": "abc", "type": "str", "min": None, "max": None}
    assert run.stdout == "3 12.5 False abc 3", "a repeated param() call returns the first value"


@pytest.mark.qa("RUN-02")
def test_param_overrides_are_coerced_to_declared_type():
    run = run_script(PARAM_SCRIPT, {"n": "7", "size": "20", "hollow": "yes", "label": 5})
    values = {p.name: p.value for p in run.params}
    assert values == {"n": 7, "size": 20.0, "hollow": True, "label": "5"}
    assert type(values["n"]) is int and type(values["size"]) is float and type(values["label"]) is str
    bb = run.shape.BoundingBox()
    assert (bb.xlen, bb.ylen, bb.zlen) == pytest.approx((20, 20, 7))


@pytest.mark.qa("RUN-02")
@pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("on", True), ("0", False), ("no", False), (True, True), (0, False)])
def test_bool_param_coercion(raw, expected):
    run = run_script(PARAM_SCRIPT, {"hollow": raw})
    assert next(p.value for p in run.params if p.name == "hollow") is expected


@pytest.mark.qa("RUN-02")
@pytest.mark.parametrize(
    "override,message",
    [
        ({"n": "abc"}, "Parameter 'n' has invalid value"),
        ({"n": "2.5"}, "not an integer"),
        ({"n": 0}, "below the minimum 1"),
        ({"n": 11}, "above the maximum 10"),
        ({"size": "big"}, "Parameter 'size' has invalid value"),
    ],
)
def test_param_override_validation(override, message):
    with pytest.raises(ScriptError, match=message):
        run_script(PARAM_SCRIPT, override)


BOX = "\nresult = cq.Workplane('XY').box(1, 1, 1)"


@pytest.mark.qa("RUN-03")
@pytest.mark.parametrize(
    "source",
    [
        "import os",
        "import subprocess",
        "import sys",
        "import socket",
        "from os import path",
        "import printcad.runner",
        "from printcad.runner import run_script",
        "from printcad import api",
        "__import__('os')",
        "from . import tolerances",
    ],
)
def test_forbidden_imports_are_blocked(source):
    with pytest.raises(ScriptError, match="not allowed"):
        run_script(source + BOX)


@pytest.mark.qa("RUN-03")
@pytest.mark.parametrize("call", ["open('/etc/passwd')", "eval('1')", "exec('x = 1')", "compile('1', 'f', 'eval')", "globals()", "vars()", "input()"])
def test_dangerous_builtins_are_not_available(call):
    with pytest.raises(ScriptError, match="NameError"):
        run_script(call + BOX)


@pytest.mark.qa("RUN-03")
@pytest.mark.parametrize(
    "source",
    [
        "import math\nassert math.pi > 3",
        "import numpy\nassert numpy.zeros(2).sum() == 0",
        "import cadquery\nassert cadquery.Workplane",
        "import typing\nx: typing.List[int] = []",
        "from printcad import tolerances as t\nassert t.clearance_hole(3.0) > 3",
        "import printcad.tolerances\nassert printcad.tolerances",
    ],
    ids=["math", "numpy", "cadquery", "typing", "printcad-tolerances-from", "printcad-tolerances-import"],
)
def test_allowed_imports_work(source):
    assert isinstance(run_script(source + BOX).shape, cq.Shape)
