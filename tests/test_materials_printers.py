import pytest

from printcad.materials import MATERIALS, get_material
from printcad.printers import PRINTERS, get_printer


def test_materials_have_sane_values():
    assert {"pla", "petg", "abs"} <= set(MATERIALS)
    for m in MATERIALS.values():
        assert 0.8 < m.density < 2.0
        assert m.min_wall > 0
        assert m.to_dict()["key"] == m.key


def test_get_material_case_insensitive_and_error():
    assert get_material("PLA").density == 1.24
    with pytest.raises(KeyError, match="Unknown material"):
        get_material("unobtainium")


def test_printers():
    assert {"ender3", "prusa_mk4", "bambu_x1"} <= set(PRINTERS)
    p = get_printer("Ender3")
    assert p.volume == (220, 220, 250)
    d = p.to_dict()
    assert d["volume"] == [220, 220, 250]
    with pytest.raises(KeyError, match="Unknown printer"):
        get_printer("nope")
