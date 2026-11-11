import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from printcad.analysis import signed_volume
from printcad.api import app
from printcad.mesh import parse_3mf, parse_stl

BOX = "w = param('w', 10.0)\nresult = cq.Workplane('XY').box(w, 20, 30, centered=False)"


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "PrintCAD" in r.text and "app.js" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    three = client.get("/static/vendor/three.module.min.js")
    assert three.status_code == 200 and len(three.content) > 100_000
    assert client.get("/static/vendor/OrbitControls.js").status_code == 200


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_printers_materials_examples(client):
    printers = client.get("/api/printers").json()
    assert any(p["key"] == "ender3" and p["volume"] == [220, 220, 250] for p in printers)
    mats = client.get("/api/materials").json()
    assert any(m["key"] == "pla" and m["density"] == 1.24 for m in mats)
    ex = client.get("/api/examples").json()
    assert {e["name"] for e in ex} == {"bracket", "enclosure", "gear"}


def test_run(client):
    r = client.post("/api/run", json={"script": BOX, "params": {"w": 5}})
    assert r.status_code == 200
    d = r.json()
    assert len(d["mesh"]["vertices"]) == 8 * 3
    assert len(d["mesh"]["indices"]) == 12 * 3
    assert d["analysis"]["volume"] == pytest.approx(5 * 20 * 30)
    assert d["analysis"]["watertight"] is True
    assert d["params"][0]["name"] == "w" and d["params"][0]["value"] == 5.0
    assert d["overhang_faces"] == []
    assert d["stdout"] == ""


def test_run_options(client):
    r = client.post("/api/run", json={"script": BOX, "printer": "ender3", "material": "petg", "infill": 1.0})
    d = r.json()["analysis"]
    assert d["build_volume"]["printer"] == "ender3"
    assert d["weight"]["material"] == "petg"
    assert d["weight"]["estimated_grams"] == pytest.approx(d["weight"]["solid_grams"])


@pytest.mark.parametrize(
    "payload,msg",
    [
        ({"script": "x = 1"}, "result"),
        ({"script": "result = ("}, "Syntax"),
        ({"script": "import os\nresult=1"}, "not allowed"),
        ({"script": BOX, "printer": "nope"}, "Unknown printer"),
        ({"script": BOX, "material": "nope"}, "Unknown material"),
        ({"script": BOX, "overhang_angle": 120}, "overhang_angle"),
        ({"script": BOX, "params": {"w": "abc"}}, "invalid value"),
    ],
)
def test_run_errors(client, payload, msg):
    r = client.post("/api/run", json=payload)
    assert r.status_code == 400
    assert msg in r.json()["detail"]


def test_run_validation_422(client):
    assert client.post("/api/run", json={}).status_code == 422


def test_export_stl(client):
    r = client.post("/api/export/stl", json={"script": BOX})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("model/stl")
    assert 'filename="model.stl"' in r.headers["content-disposition"]
    assert signed_volume(parse_stl(r.content)) == pytest.approx(6000)


def test_export_3mf(client):
    r = client.post("/api/export/3mf", json={"script": BOX, "params": {"w": 20}})
    assert r.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(r.content)).testzip() is None
    assert signed_volume(parse_3mf(r.content)) == pytest.approx(12000, rel=1e-4)


def test_export_step(client):
    r = client.post("/api/export/STEP", json={"script": BOX})
    assert r.status_code == 200
    assert b"ISO-10303-21" in r.content[:100]


def test_export_errors(client):
    r = client.post("/api/export/obj", json={"script": BOX})
    assert r.status_code == 400 and "Unsupported" in r.json()["detail"]
    r = client.post("/api/export/stl", json={"script": "x=1"})
    assert r.status_code == 400


def test_run_example_through_api(client):
    ex = client.get("/api/examples").json()[0]
    r = client.post("/api/run", json={"script": ex["script"]})
    assert r.status_code == 200 and r.json()["analysis"]["watertight"]
