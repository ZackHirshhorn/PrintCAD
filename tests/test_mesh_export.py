import io
import struct
import zipfile
import xml.etree.ElementTree as ET

import cadquery as cq
import numpy as np
import pytest

from printcad import export
from printcad.analysis import signed_volume
from printcad.mesh import Mesh, load_mesh, parse_3mf, parse_stl, tessellate_shape


def test_tessellate_box(box_mesh):
    assert len(box_mesh.vertices) == 8
    assert len(box_mesh.faces) == 12
    assert signed_volume(box_mesh) == pytest.approx(6000)
    assert box_mesh.face_areas().sum() == pytest.approx(2 * (200 + 300 + 600))


def test_mesh_helpers(box_mesh):
    lo, hi = box_mesh.bounds()
    assert hi.tolist() == [10, 20, 30]
    assert box_mesh.triangles.shape == (12, 3, 3)
    assert np.allclose(np.linalg.norm(box_mesh.face_normals(), axis=1), 1)
    mirrored = box_mesh.transformed(np.diag([-1.0, 1.0, 1.0]))
    assert signed_volume(mirrored) == pytest.approx(6000)  # winding flipped back
    empty = Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=int))
    assert empty.bounds()[1].tolist() == [0, 0, 0]
    assert empty.weld().faces.shape == (0, 3)


def test_weld_merges_duplicates_and_drops_degenerate():
    v = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 0.000001], [1, 0, 0], [1, 0, 0]]
    f = [[0, 1, 2], [3, 4, 5]]
    m = Mesh(v, f).weld()
    assert len(m.vertices) == 3
    assert len(m.faces) == 1


def test_stl_roundtrip(box_mesh):
    data = export.to_stl(box_mesh)
    assert len(data) == 84 + 50 * 12
    assert struct.unpack("<I", data[80:84])[0] == 12
    back = parse_stl(data)
    assert len(back.faces) == 12
    assert signed_volume(back) == pytest.approx(6000)


def test_stl_ascii_parse():
    text = """solid t
facet normal 0 0 1
 outer loop
  vertex 0 0 0
  vertex 1 0 0
  vertex 0 1 0
 endloop
endfacet
endsolid t
"""
    m = parse_stl(text.encode())
    assert len(m.faces) == 1
    assert m.vertices.shape == (3, 3)


def test_stl_invalid():
    with pytest.raises(ValueError):
        parse_stl(b"garbage")
    with pytest.raises(ValueError):
        parse_stl(b"solid x\nfacet\nvertex 1 2 3\nendfacet")


def test_3mf_structure_and_roundtrip(box_mesh):
    data = export.to_3mf(box_mesh, "my part")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        assert set(zf.namelist()) == {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"}
        root = ET.fromstring(zf.read("3D/3dmodel.model"))
        ET.fromstring(zf.read("[Content_Types].xml"))
        ET.fromstring(zf.read("_rels/.rels"))
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    assert root.get("unit") == "millimeter"
    assert len(root.findall(".//m:vertex", ns)) == 8
    assert len(root.findall(".//m:triangle", ns)) == 12
    assert root.find(".//m:build/m:item", ns).get("objectid") == "1"
    back = parse_3mf(data)
    assert len(back.faces) == 12
    assert signed_volume(back) == pytest.approx(6000, rel=1e-4)


def test_3mf_invalid():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("3D/3dmodel.model", '<model xmlns="x"><resources/></model>')
    with pytest.raises(ValueError, match="no mesh"):
        parse_3mf(buf.getvalue())


def test_step_export_reparse():
    shape = cq.Workplane("XY").box(5, 6, 7).val()
    data = export.to_step(shape)
    assert b"ISO-10303-21" in data[:100]
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as fh:
        fh.write(data)
    try:
        back = cq.importers.importStep(fh.name).val()
    finally:
        os.unlink(fh.name)
    assert back.Volume() == pytest.approx(210, rel=1e-6)


def test_export_bytes_dispatch(box_mesh):
    shape = cq.Workplane("XY").box(1, 1, 1).val()
    assert export.export_bytes("STL", shape, box_mesh)[:7] == b"PrintCA"
    assert export.export_bytes("3mf", shape, box_mesh)[:2] == b"PK"
    assert b"ISO-10303" in export.export_bytes("step", shape, box_mesh)[:100]
    with pytest.raises(ValueError, match="Unsupported"):
        export.export_bytes("obj", shape, box_mesh)


def test_load_mesh_files(tmp_path, box_mesh):
    (tmp_path / "a.stl").write_bytes(export.to_stl(box_mesh))
    (tmp_path / "a.3mf").write_bytes(export.to_3mf(box_mesh))
    (tmp_path / "a.obj").write_text("v 0 0 0")
    assert len(load_mesh(tmp_path / "a.stl").faces) == 12
    assert len(load_mesh(tmp_path / "a.3mf").faces) == 12
    with pytest.raises(ValueError, match="Unsupported"):
        load_mesh(tmp_path / "a.obj")


def test_tessellated_cylinder_volume():
    m = tessellate_shape(cq.Workplane("XY").circle(5).extrude(10).val(), tolerance=0.01)
    assert signed_volume(m) == pytest.approx(np.pi * 25 * 10, rel=5e-3)
