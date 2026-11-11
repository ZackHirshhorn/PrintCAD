import pytest

from printcad import tolerances as t


def test_clearance_hole():
    assert t.clearance_hole(4, "tight") == 4.1
    assert t.clearance_hole(4) == 4.2
    assert t.clearance_hole(4, "loose") == 4.4
    with pytest.raises(ValueError):
        t.clearance_hole(4, "weird")
    with pytest.raises(ValueError):
        t.clearance_hole(0)


def test_press_fit():
    assert t.press_fit_hole(8, 0.1) == 7.9
    with pytest.raises(ValueError):
        t.press_fit_hole(8, 8)
    with pytest.raises(ValueError):
        t.press_fit_hole(-1)


def test_snap_fit_cantilever_math():
    r = t.snap_fit_cantilever(length=20, thickness=1.5, deflection=2.0, strain_limit=0.02, width=5)
    assert r["strain"] == pytest.approx(1.5 * 1.5 * 2.0 / 400)
    assert r["ok"] is True
    assert r["max_deflection"] == pytest.approx(0.02 * 400 / (1.5 * 1.5))
    assert r["deflection_force"] > 0
    too_much = t.snap_fit_cantilever(length=10, thickness=2, deflection=3)
    assert too_much["ok"] is False
    with pytest.raises(ValueError):
        t.snap_fit_cantilever(0, 1, 1)


def test_snap_hook_geometry():
    hook = t.snap_hook(length=15, thickness=1.5, width=6, hook_depth=1.0)
    solid = hook.val()
    assert solid.isValid()
    bb = solid.BoundingBox()
    assert bb.zlen == pytest.approx(15)
    assert bb.xlen == pytest.approx(2.5)
    assert bb.ylen == pytest.approx(6)
    with pytest.raises(ValueError):
        t.snap_hook(0, 1, 1, 1)


def test_min_feature():
    assert t.min_printable_feature(0.4) == 0.8
