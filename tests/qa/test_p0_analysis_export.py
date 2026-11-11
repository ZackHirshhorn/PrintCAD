"""P0 analysis golden models (AN-01..AN-05) and export integrity (EX-01, EX-02)."""
from __future__ import annotations

import io
import math
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import pytest

from printcad.analysis import analyze_mesh, signed_volume
from printcad.export import to_3mf, to_stl
from printcad.materials import get_material
from printcad.mesh import Mesh, parse_3mf, parse_stl
from printcad.printers import get_printer
from printcad.service import build
from qa_helpers import CUBE20, EXAMPLE_NAMES, EXAMPLES_DIR, read_binary_stl

pytestmark = pytest.mark.p0

PRUSA = get_printer("prusa_mk4")
NS = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


@pytest.mark.qa("AN-01")
def test_cube_golden_values():
    a = build(CUBE20).analysis
    assert a["volume"] == pytest.approx(8000, rel=1e-6)
    assert a["surface_area"] == pytest.approx(2400, rel=1e-6)
    assert a["watertight"] is True and a["manifold"] is True
    assert a["topology"]["open_edges"] == 0 and a["topology"]["non_manifold_edges"] == 0
    assert a["overhang"]["area"] == 0 and a["overhang"]["face_count"] == 0
    assert a["min_wall_thickness"] == pytest.approx(20, abs=0.01)
    assert a["bounding_box"]["size"] == pytest.approx([20, 20, 20])
    assert a["build_volume"]["fits"] is True
    assert a["warnings"] == []


@pytest.mark.qa("AN-02")
def test_cylinder_volume_within_tessellation_error():
    a = build("result = cq.Workplane('XY').circle(10).extrude(20)").analysis
    exact = math.pi * 10**2 * 20
    assert a["volume"] == pytest.approx(exact, rel=0.01)
    assert a["volume"] <= exact, "an inscribed tessellation cannot exceed the true volume"
    assert a["watertight"] is True and a["manifold"] is True
    # Tessellation vertices need not land on every extreme of the circle; 0.05 mm is the build tolerance.
    assert a["bounding_box"]["size"] == pytest.approx([20, 20, 20], abs=0.05)


@pytest.mark.qa("AN-03")
def test_box_with_through_hole():
    a = build("result = cq.Workplane('XY').box(30, 30, 10).faces('>Z').workplane().hole(10)").analysis
    expected = 30 * 30 * 10 - math.pi * 5**2 * 10
    assert a["volume"] == pytest.approx(expected, rel=0.01)
    assert a["volume"] < 30 * 30 * 10
    assert a["watertight"] is True and a["manifold"] is True


@pytest.mark.qa("AN-04")
def test_two_disjoint_boxes():
    src = "result = cq.Workplane('XY').box(10, 10, 10, centered=False).union(cq.Workplane('XY').box(5, 5, 5, centered=False).translate((30, 0, 0)))"
    a = build(src).analysis
    assert a["volume"] == pytest.approx(1000 + 125, rel=1e-6)
    assert a["watertight"] is True and a["manifold"] is True
    assert a["bounding_box"]["size"] == pytest.approx([35, 10, 10])


@pytest.mark.qa("AN-05")
def test_open_mesh_is_flagged():
    res = build(CUBE20)
    stl = to_stl(res.mesh)
    count, tris = read_binary_stl(stl)
    holed = stl[:80] + (count - 1).to_bytes(4, "little") + tris[1:].tobytes()
    mesh = parse_stl(holed)
    assert len(mesh.faces) == count - 1
    a = analyze_mesh(mesh, PRUSA, get_material("pla"))
    assert a["watertight"] is False and a["manifold"] is False
    assert a["topology"]["open_edges"] == 3
    assert any("not watertight" in w for w in a["warnings"])
    assert a["min_wall_thickness"] is None, "wall thickness is meaningless for an open mesh"


@pytest.mark.qa("AN-05")
def test_inconsistent_winding_is_flagged():
    res = build(CUBE20)
    faces = res.mesh.faces.copy()
    faces[0] = faces[0][::-1]
    a = analyze_mesh(Mesh(res.mesh.vertices, faces), PRUSA, get_material("pla"))
    assert a["watertight"] is True and a["manifold"] is False
    assert any("orientation" in w for w in a["warnings"])


@pytest.fixture(scope="module", params=EXAMPLE_NAMES)
def example_build(request):
    return build((EXAMPLES_DIR / f"{request.param}.py").read_text())


@pytest.mark.qa("EX-01")
def test_stl_structure_and_round_trip(example_build):
    mesh = example_build.mesh
    data = to_stl(mesh, "qa")
    assert len(data[:80]) == 80 and data[:80].startswith(b"PrintCAD qa")
    count, tris = read_binary_stl(data)
    assert count == len(mesh.faces)
    assert len(data) == 84 + 50 * count
    lengths = np.linalg.norm(tris["n"], axis=1)
    assert np.allclose(lengths, 1.0, atol=1e-5)
    # Normals must agree with the right-hand winding of each stored triangle.
    v = tris["v"].astype(np.float64)
    cross = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    assert np.all(np.einsum("ij,ij->i", cross, tris["n"]) > 0)
    back = parse_stl(data)
    assert signed_volume(back) == pytest.approx(signed_volume(mesh), rel=1e-5)
    lo, hi = back.bounds()
    mlo, mhi = mesh.bounds()
    assert np.allclose(lo, mlo, atol=1e-4) and np.allclose(hi, mhi, atol=1e-4)


@pytest.mark.qa("EX-02")
def test_3mf_structure_and_round_trip(example_build):
    mesh = example_build.mesh
    data = to_3mf(mesh, "qa part")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        names = set(zf.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= names
        types = ET.fromstring(zf.read("[Content_Types].xml"))
        assert {d.get("Extension") for d in types} >= {"rels", "model"}
        rels = ET.fromstring(zf.read("_rels/.rels"))
        assert any(r.get("Target") == "/3D/3dmodel.model" for r in rels)
        model = ET.fromstring(zf.read("3D/3dmodel.model"))
    assert model.tag == f"{NS}model"
    assert model.get("unit") == "millimeter"
    vertices = model.findall(f".//{NS}vertex")
    triangles = model.findall(f".//{NS}triangle")
    assert len(vertices) == len(mesh.vertices)
    assert len(triangles) == len(mesh.faces)
    for t in triangles:
        assert all(0 <= int(t.get(k)) < len(vertices) for k in ("v1", "v2", "v3"))
    items = model.findall(f".//{NS}build/{NS}item")
    objects = model.findall(f".//{NS}resources/{NS}object")
    assert [i.get("objectid") for i in items] == [o.get("id") for o in objects]
    back = parse_3mf(data)
    assert signed_volume(back) == pytest.approx(signed_volume(mesh), rel=1e-5)
