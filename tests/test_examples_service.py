import pytest

from printcad.examples import get_example, list_examples
from printcad.runner import ScriptError
from printcad.service import build


def test_examples_listed():
    names = {e["name"] for e in list_examples()}
    assert names == {"bracket", "enclosure", "gear"}
    for e in list_examples():
        assert e["title"] and e["description"] and "result" in e["script"]
    with pytest.raises(KeyError):
        get_example("nope")


@pytest.mark.parametrize("name", ["bracket", "enclosure", "gear"])
def test_examples_build_printable(name):
    res = build(get_example(name)["script"])
    a = res.analysis
    assert a["watertight"] and a["manifold"]
    assert a["volume"] > 1000
    assert a["build_volume"]["fits"]
    assert a["warnings"] == []
    assert res.params


def test_bracket_params_change_geometry():
    script = get_example("bracket")["script"]
    small = build(script, {"width": 20}).analysis["bounding_box"]["size"]
    big = build(script, {"width": 60}).analysis["bounding_box"]["size"]
    assert small[1] == pytest.approx(20) and big[1] == pytest.approx(60)


def test_bracket_hole_uses_tolerance():
    script = get_example("bracket")["script"]
    tight = build(script, {"fit": "tight"}).analysis["volume"]
    loose = build(script, {"fit": "loose"}).analysis["volume"]
    assert loose < tight  # bigger holes remove more material


def test_gear_teeth_scaling():
    script = get_example("gear")["script"]
    g = build(script, {"teeth": 30, "module": 1.5}).analysis["bounding_box"]["size"]
    assert g[0] == pytest.approx(2 * (1.5 * 30 / 2 + 1.5), abs=0.1)
    assert build(script, {"bore": 0}).analysis["watertight"]


def test_enclosure_has_two_bodies_and_fits_small_printer():
    res = build(get_example("enclosure")["script"], printer="prusa_mini")
    assert len(res.shape.Solids()) == 2
    assert res.analysis["build_volume"]["fits"]


def test_build_validation():
    script = get_example("bracket")["script"]
    with pytest.raises(ValueError, match="overhang_angle"):
        build(script, overhang_angle=0)
    with pytest.raises(ValueError, match="infill"):
        build(script, infill=2)
    with pytest.raises(ValueError, match="tolerance"):
        build(script, tolerance=0)
    with pytest.raises(KeyError):
        build(script, printer="nope")
    with pytest.raises(KeyError):
        build(script, material="nope")
    with pytest.raises(ScriptError):
        build("x = 1")


def test_overhang_faces_reported():
    script = "base = cq.Workplane('XY').box(4, 4, 10, centered=(True, True, False))\nplate = cq.Workplane('XY').box(30, 30, 3, centered=(True, True, False)).translate((0, 0, 10))\nresult = base.union(plate)"
    res = build(script)
    assert len(res.overhang_faces) > 0
    assert res.analysis["overhang"]["face_count"] == len(res.overhang_faces)
