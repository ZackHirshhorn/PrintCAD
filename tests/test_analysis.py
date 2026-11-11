import cadquery as cq
import numpy as np
import pytest

from printcad import analysis as an
from printcad.materials import get_material
from printcad.mesh import Mesh, tessellate_shape
from printcad.printers import Printer, get_printer


def test_watertight_box(box_mesh):
    r = an.edge_report(box_mesh)
    assert r["watertight"] and r["manifold"]
    assert r["open_edges"] == r["non_manifold_edges"] == r["inconsistent_edges"] == 0


def test_open_mesh_detected(box_mesh):
    open_mesh = Mesh(box_mesh.vertices, box_mesh.faces[:-1])
    r = an.edge_report(open_mesh)
    assert not r["watertight"]
    assert r["open_edges"] == 3


def test_flipped_face_inconsistent(box_mesh):
    faces = box_mesh.faces.copy()
    faces[0] = faces[0][::-1]
    r = an.edge_report(Mesh(box_mesh.vertices, faces))
    assert r["watertight"] and not r["manifold"]
    assert r["inconsistent_edges"] == 3


def test_non_manifold_edge():
    v = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1]]
    f = [[0, 1, 2], [1, 0, 3], [0, 1, 4]]  # three faces share edge 0-1
    r = an.edge_report(Mesh(v, f))
    assert r["non_manifold_edges"] == 1
    assert not r["watertight"]


def test_empty_mesh_report():
    empty = Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=int))
    assert an.edge_report(empty)["watertight"] is False
    assert an.min_wall_thickness(empty) is None
    assert an.overhang_mask(empty).size == 0
    assert an.overhang_stats(empty)["fraction"] == 0.0


def test_volume_and_bbox(box_mesh):
    assert an.signed_volume(box_mesh) == pytest.approx(6000)
    bb = an.bounding_box(box_mesh)
    assert bb["size"] == [10, 20, 30]


def test_overhang_box_has_none(box_mesh):
    assert not an.overhang_mask(box_mesh).any()  # bottom face sits on the bed


def test_overhang_elevated_ceiling():
    # T shape: a plate on a post; the underside of the plate overhangs.
    post = cq.Workplane("XY").box(4, 4, 10, centered=(True, True, False))
    plate = cq.Workplane("XY").box(30, 30, 3, centered=(True, True, False)).translate((0, 0, 10))
    m = tessellate_shape(post.union(plate).val())
    mask = an.overhang_mask(m)
    normals = m.face_normals()
    assert mask.any()
    assert np.all(normals[mask][:, 2] < -0.7)
    stats = an.overhang_stats(m)
    assert stats["area"] == pytest.approx(30 * 30 - 4 * 4, rel=1e-6)


def test_overhang_angle_threshold(pyramid_mesh):
    # Inverted cone side faces are ~ 42 degrees from horizontal-down, depends on angle.
    strict = an.overhang_stats(pyramid_mesh, 10)["area"]
    lenient = an.overhang_stats(pyramid_mesh, 80)["area"]
    assert strict >= lenient


def test_overhang_45_exact_boundary():
    # Sloped triangle with normal (0, 1, -1)/sqrt2 floating above a bed triangle.
    v = np.array([[0, 0, 5], [0, 1, 6], [1, 0, 5], [10, 0, 0], [11, 0, 0], [10, 1, 0.0]])
    m = Mesh(v, [[0, 1, 2], [3, 4, 5]])
    assert m.face_normals()[0][2] == pytest.approx(-np.sqrt(0.5))
    assert not an.overhang_mask(m, 45)[0]  # exactly at the limit is allowed
    assert an.overhang_mask(m, 44)[0]
    assert not an.overhang_mask(m, 45)[1]  # bed contact never needs support


def test_min_wall_hollow(hollow_mesh):
    wall = an.min_wall_thickness(hollow_mesh)
    assert wall == pytest.approx(2.0, abs=0.01)


def test_min_wall_solid_box(box_mesh):
    assert an.min_wall_thickness(box_mesh) == pytest.approx(10.0, abs=0.01)


def test_min_wall_sampling_path(hollow_mesh):
    wall = an.min_wall_thickness(hollow_mesh, max_samples=5)
    assert wall is not None and wall >= 2.0 - 0.01


def test_orient_names(box_mesh):
    for name in ("z_up", "z_down", "x_down", "x_up", "y_down", "y_up"):
        o = an.orient(box_mesh, name)
        lo, hi = o.bounds()
        assert lo[2] == pytest.approx(0)
        assert (lo[0] + hi[0]) / 2 == pytest.approx(0)
        assert an.signed_volume(o) == pytest.approx(6000)
    # +X face down means the 10 mm x-extent becomes the height
    assert an.orient(box_mesh, "x_down").bounds()[1][2] == pytest.approx(10)
    assert an.orient(box_mesh, "y_up").bounds()[1][2] == pytest.approx(20)
    with pytest.raises(ValueError):
        an.orient(box_mesh, "sideways")


def test_orient_x_down_puts_plus_x_face_on_bed(box_mesh):
    o = an.orient(box_mesh, "x_down")
    n = o.face_normals()
    bed = o.triangles[:, :, 2].max(axis=1) < 1e-6
    assert bed.sum() == 2
    assert np.allclose(n[bed], [0, 0, -1])
    # originally these were the +X faces
    orig_plus_x = np.isclose(box_mesh.face_normals()[:, 0], 1)
    assert orig_plus_x.sum() == 2


def test_orientation_suggestion_t_shape():
    # An upside-down T needs support when printed as modelled; flipping removes it.
    post = cq.Workplane("XY").box(4, 4, 10, centered=(True, True, False))
    plate = cq.Workplane("XY").box(30, 30, 3, centered=(True, True, False)).translate((0, 0, 10))
    m = tessellate_shape(post.union(plate).val())
    s = an.suggest_orientation(m)
    assert s["best"] == "z_down"
    assert s["candidates"][0]["overhang_area"] == pytest.approx(0, abs=1e-6)
    asis = next(c for c in s["candidates"] if c["orientation"] == "z_up")
    assert asis["overhang_area"] > 800


def test_orientation_respects_printer_fit():
    tiny = Printer("tiny", "Tiny", 100, 100, 14)
    post = cq.Workplane("XY").box(4, 4, 10, centered=(True, True, False))
    plate = cq.Workplane("XY").box(30, 30, 3, centered=(True, True, False)).translate((0, 0, 10))
    m = tessellate_shape(post.union(plate).val())
    s = an.suggest_orientation(m, printer=tiny)
    assert all(c["fits"] for c in s["candidates"])
    assert all(c["height"] <= 14 + 1e-6 for c in s["candidates"])
    assert {c["orientation"] for c in s["candidates"]} == {"z_up", "z_down"}


def test_fit_helpers():
    p = get_printer("ender3")
    assert an.fits_build_volume((220, 220, 250), p)
    assert not an.fits_build_volume((221, 10, 10), p)
    assert an.fits_any_rotation((240, 10, 10), p)
    assert not an.fits_build_volume((240, 10, 10), p)
    assert an.fits_any_rotation((10, 10, 240), p)
    assert not an.fits_any_rotation((300, 300, 300), p)


def test_analyze_mesh_report_box(box_mesh):
    rep = an.analyze_mesh(box_mesh, get_printer("prusa_mk4"), get_material("pla"))
    assert rep["watertight"] and rep["manifold"]
    assert rep["volume"] == pytest.approx(6000)
    assert rep["weight"]["solid_grams"] == pytest.approx(6.0 * 1.24)
    assert 0 < rep["weight"]["estimated_grams"] < rep["weight"]["solid_grams"]
    assert rep["build_volume"]["fits"]
    assert rep["warnings"] == []
    assert rep["min_wall_thickness"] == pytest.approx(10, abs=0.01)
    assert rep["triangle_count"] == 12


def test_analyze_mesh_warnings():
    big = tessellate_shape(cq.Workplane("XY").box(300, 10, 10).val())
    rep = an.analyze_mesh(big, get_printer("ender3"), get_material("pla"))
    assert not rep["build_volume"]["fits"]
    assert not rep["build_volume"]["fits_rotated"]
    assert any("does not fit" in w for w in rep["warnings"])

    long_ok_rotated = tessellate_shape(cq.Workplane("XY").box(10, 10, 240).val())
    rep = an.analyze_mesh(long_ok_rotated, get_printer("ender3"), get_material("pla"))
    assert rep["build_volume"]["fits"]

    tall = tessellate_shape(cq.Workplane("XY").box(10, 10, 240).val())
    rep = an.analyze_mesh(tall, get_printer("prusa_mk4"), get_material("pla"))
    assert not rep["build_volume"]["fits"] and rep["build_volume"]["fits_rotated"]
    assert any("if rotated" in w for w in rep["warnings"])

    thin = tessellate_shape(cq.Workplane("XY").box(20, 20, 0.5).val())
    rep = an.analyze_mesh(thin, get_printer("ender3"), get_material("abs"))
    assert any("Thinnest wall" in w for w in rep["warnings"])

    post = cq.Workplane("XY").box(4, 4, 10, centered=(True, True, False))
    plate = cq.Workplane("XY").box(30, 30, 3, centered=(True, True, False)).translate((0, 0, 10))
    t_shape = tessellate_shape(post.union(plate).val())
    rep = an.analyze_mesh(t_shape, get_printer("ender3"), get_material("pla"))
    assert any("supports likely" in w for w in rep["warnings"])


def test_analyze_non_watertight(box_mesh):
    m = Mesh(box_mesh.vertices, box_mesh.faces[:-2])
    rep = an.analyze_mesh(m, get_printer("ender3"), get_material("pla"))
    assert not rep["watertight"]
    assert rep["min_wall_thickness"] is None
    assert any("not watertight" in w for w in rep["warnings"])


def test_analyze_inconsistent_orientation(box_mesh):
    faces = box_mesh.faces.copy()
    faces[0] = faces[0][::-1]
    rep = an.analyze_mesh(Mesh(box_mesh.vertices, faces), get_printer("ender3"), get_material("pla"))
    assert any("inconsistent" in w for w in rep["warnings"])


def test_full_infill_weight(box_mesh):
    rep = an.analyze_mesh(box_mesh, get_printer("ender3"), get_material("pla"), infill=1.0)
    assert rep["weight"]["estimated_grams"] == pytest.approx(rep["weight"]["solid_grams"])
