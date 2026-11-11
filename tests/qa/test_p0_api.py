"""P0 HTTP API flows: API-01, API-02, API-03, API-05."""
from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile

import pytest

from printcad import __version__
from printcad.analysis import signed_volume
from printcad.mesh import parse_3mf, parse_stl
from qa_helpers import BOX_PARAM, EXAMPLE_NAMES, MUSHROOM, read_binary_stl

pytestmark = pytest.mark.p0

PRINTER_KEYS = {"ender3", "prusa_mk4", "prusa_mini", "bambu_x1", "bambu_a1_mini", "creality_k1", "voron_350"}
MATERIAL_KEYS = {"pla", "petg", "abs", "asa", "tpu", "nylon", "pc"}


@pytest.mark.qa("API-01")
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": __version__}


@pytest.mark.qa("API-01")
def test_printers_have_build_volumes(client):
    printers = client.get("/api/printers").json()
    assert {p["key"] for p in printers} == PRINTER_KEYS
    for p in printers:
        assert p["name"]
        assert p["volume"] == [p["x"], p["y"], p["z"]]
        assert all(v > 0 for v in p["volume"])


@pytest.mark.qa("API-01")
def test_materials_have_densities(client):
    mats = client.get("/api/materials").json()
    assert {m["key"] for m in mats} == MATERIAL_KEYS
    for m in mats:
        assert m["name"] and 0.5 < m["density"] < 2.5


@pytest.mark.qa("API-01")
def test_examples_have_title_and_script(client):
    examples = client.get("/api/examples").json()
    assert {e["name"] for e in examples} == set(EXAMPLE_NAMES)
    for e in examples:
        assert e["title"] and e["title"] != e["name"], "examples should declare a '# title:' header"
        assert "result" in e["script"] and "param(" in e["script"]


@pytest.mark.qa("API-01")
def test_docs_and_openapi(client):
    docs = client.get("/docs")
    assert docs.status_code == 200 and "swagger" in docs.text.lower()
    spec = client.get("/openapi.json").json()
    for path in ("/api/health", "/api/printers", "/api/materials", "/api/examples", "/api/run", "/api/export/{fmt}"):
        assert path in spec["paths"], path


def _check_run_payload(d: dict) -> None:
    verts, idx = d["mesh"]["vertices"], d["mesh"]["indices"]
    assert len(verts) > 0 and len(verts) % 3 == 0
    assert len(idx) > 0 and len(idx) % 3 == 0
    n_vertices, n_faces = len(verts) // 3, len(idx) // 3
    assert all(isinstance(i, int) and 0 <= i < n_vertices for i in idx)
    assert all(isinstance(f, int) and 0 <= f < n_faces for f in d["overhang_faces"])
    assert len(set(d["overhang_faces"])) == len(d["overhang_faces"])
    assert d["analysis"]["triangle_count"] == n_faces
    assert d["analysis"]["vertex_count"] == n_vertices
    assert isinstance(d["params"], list)
    assert isinstance(d["stdout"], str)


@pytest.mark.qa("API-02")
@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_run_each_example(client, name):
    ex = next(e for e in client.get("/api/examples").json() if e["name"] == name)
    r = client.post("/api/run", json={"script": ex["script"], "params": {}, "printer": "prusa_mk4", "material": "pla", "overhang_angle": 45, "infill": 0.2})
    assert r.status_code == 200, r.text
    d = r.json()
    _check_run_payload(d)
    assert d["analysis"]["watertight"] is True
    declared = {p["name"] for p in d["params"]}
    assert declared and all(f'param("{n}"' in ex["script"] for n in declared)


@pytest.mark.qa("API-02")
def test_run_overhang_faces_and_stdout(client):
    r = client.post("/api/run", json={"script": MUSHROOM + "\nprint('hello', 42)"})
    assert r.status_code == 200, r.text
    d = r.json()
    _check_run_payload(d)
    assert d["overhang_faces"], "the cap underside must be reported as overhang"
    assert d["stdout"] == "hello 42"


@pytest.mark.qa("API-02")
def test_run_params_round_trip(client):
    d = client.post("/api/run", json={"script": BOX_PARAM, "params": {"w": 25}}).json()
    assert d["params"] == [{"name": "w", "default": 10.0, "value": 25.0, "type": "float", "min": 5, "max": 50}]
    assert d["analysis"]["bounding_box"]["size"] == pytest.approx([25, 20, 30])


@pytest.mark.qa("API-03")
@pytest.mark.parametrize(
    "payload,detail",
    [
        ({"script": BOX_PARAM, "printer": "nope"}, "Unknown printer"),
        ({"script": BOX_PARAM, "material": "nope"}, "Unknown material"),
        ({"script": "result = ("}, "Syntax error"),
        ({"script": "result = 1 / 0"}, "ZeroDivisionError"),
        ({"script": "x = 1"}, "result"),
        ({"script": BOX_PARAM, "params": {"w": 1}}, "below the minimum"),
        ({"script": BOX_PARAM, "params": {"w": "wide"}}, "invalid value"),
        ({"script": BOX_PARAM, "overhang_angle": 0}, "overhang_angle"),
        ({"script": BOX_PARAM, "overhang_angle": 90}, "overhang_angle"),
        ({"script": BOX_PARAM, "overhang_angle": -10}, "overhang_angle"),
        ({"script": BOX_PARAM, "infill": -1}, "infill"),
        ({"script": BOX_PARAM, "infill": 1.5}, "infill"),
        ({"script": BOX_PARAM, "tolerance": 0}, "tolerance"),
    ],
    ids=[
        "printer", "material", "syntax", "runtime", "no-result", "param-min", "param-type",
        "angle-0", "angle-90", "angle-negative", "infill-negative", "infill-over-1", "tolerance-0",
    ],
)
def test_run_errors_are_400_with_detail(client, payload, detail):
    r = client.post("/api/run", json=payload)
    assert r.status_code == 400, r.text
    assert detail in r.json()["detail"]


@pytest.mark.qa("API-03")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {}},
        {"json": {"params": {}}},
        {"json": {"script": BOX_PARAM, "overhang_angle": "steep"}},
        {"json": {"script": BOX_PARAM, "params": [1, 2]}},
        {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
    ],
    ids=["empty", "missing-script", "angle-not-number", "params-not-object", "invalid-json"],
)
def test_run_malformed_requests_are_422(client, kwargs):
    assert client.post("/api/run", **kwargs).status_code == 422


@pytest.mark.qa("API-05")
def test_export_stl(client):
    r = client.post("/api/export/stl", json={"script": BOX_PARAM})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("model/stl")
    assert r.headers["content-disposition"] == 'attachment; filename="model.stl"'
    count, _ = read_binary_stl(r.content)
    assert len(r.content) == 84 + 50 * count
    assert signed_volume(parse_stl(r.content)) == pytest.approx(6000, rel=1e-6)


@pytest.mark.qa("API-05")
def test_export_3mf(client):
    r = client.post("/api/export/3mf", json={"script": BOX_PARAM, "params": {"w": 20}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("model/3mf")
    assert r.headers["content-disposition"] == 'attachment; filename="model.3mf"'
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.testzip() is None
        assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(zf.namelist())
        ET.fromstring(zf.read("3D/3dmodel.model"))
    assert signed_volume(parse_3mf(r.content)) == pytest.approx(12000, rel=1e-4)


@pytest.mark.qa("API-05")
def test_export_step(client):
    r = client.post("/api/export/step", json={"script": BOX_PARAM})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/step")
    assert r.headers["content-disposition"] == 'attachment; filename="model.step"'
    assert r.content.startswith(b"ISO-10303-21")
    assert b"END-ISO-10303-21" in r.content[-200:]


@pytest.mark.qa("API-05")
@pytest.mark.parametrize("fmt", ["STL", "3Mf", "STEP"])
def test_export_format_is_case_insensitive(client, fmt):
    r = client.post(f"/api/export/{fmt}", json={"script": BOX_PARAM})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="model.{fmt.lower()}"'


@pytest.mark.qa("API-05")
def test_export_unsupported_format(client):
    r = client.post("/api/export/obj", json={"script": BOX_PARAM})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "Unsupported" in detail and all(f in detail for f in ("stl", "3mf", "step"))


@pytest.mark.qa("API-05")
@pytest.mark.parametrize("fmt", ["stl", "3mf", "step"])
def test_export_script_error_is_400(client, fmt):
    r = client.post(f"/api/export/{fmt}", json={"script": "result = ("})
    assert r.status_code == 400
    assert "Syntax error" in r.json()["detail"]
    assert "attachment" not in r.headers.get("content-disposition", "")
