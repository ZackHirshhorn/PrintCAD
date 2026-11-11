"""P0 web UI flows: UI-01, UI-02, UI-03, UI-04, UI-06.

Runs the real server and a headless Chromium with software WebGL. Rendering is checked
through viewer screenshots: background, model grey, build-volume blue and overhang red pixels.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from urllib.parse import urlparse

import httpx
import pytest

from printcad.analysis import signed_volume
from printcad.mesh import parse_3mf, parse_stl
from qa_helpers import BOX_PARAM, CUBE20, EXAMPLE_NAMES, MUSHROOM, pixel_counts

pytestmark = [pytest.mark.p0, pytest.mark.ui]

BOOL_STR_SCRIPT = (
    "solid = param('solid', True)\n"
    "label = param('label', 'qa')\n"
    "count = param('count', 2, min=1, max=5)\n"
    "result = cq.Workplane('XY').box(10 * count, 10, 10)"
)


def _api(ui, path, payload=None):
    if payload is None:
        return httpx.get(ui.base + path, timeout=60).json()
    return httpx.post(ui.base + path, json=payload, timeout=120).json()


# ------------------------------------------------------------------ UI-01


@pytest.mark.qa("UI-01")
def test_first_load(ui):
    page = ui.page
    assert page.title() == "PrintCAD"
    printers = page.locator("#printer option")
    materials = page.locator("#material option")
    examples = page.locator("#example option")
    assert printers.count() == len(_api(ui, "/api/printers")) == 7
    assert materials.count() == len(_api(ui, "/api/materials")) == 7
    assert examples.count() == 3
    assert [examples.nth(i).get_attribute("value") for i in range(3)] == list(EXAMPLE_NAMES)
    assert page.locator("#printer").input_value() == "prusa_mk4"
    first = _api(ui, "/api/examples")[0]
    assert page.locator("#example").input_value() == first["name"]
    assert page.locator("#editor").input_value() == first["script"]
    assert page.locator("#viewer canvas").count() == 1
    box = page.locator("#viewer canvas").bounding_box()
    assert box["width"] > 200 and box["height"] > 200

    # The initial example ran automatically and succeeded.
    assert ui.wait_ok() == "OK"
    assert ui.analysis()["Watertight"] == "yes"
    assert ui.console_errors == [] and ui.page_errors == []
    origin = urlparse(ui.base).netloc
    foreign = [u for u in ui.requests if urlparse(u).netloc not in (origin, "") and not u.startswith(("data:", "blob:"))]
    assert foreign == [], f"the UI must work offline, but requested: {foreign}"


@pytest.mark.qa("UI-01")
def test_webgl_viewer_renders_model_and_build_volume(ui):
    ui.wait_ok()
    px = pixel_counts(ui.viewer_png())
    assert px["background"] > 0.3 * px["total"], px
    assert px["model"] > 500, f"no model pixels rendered: {px}"
    assert px["blue"] > 50, f"build volume outline not rendered: {px}"


# ------------------------------------------------------------------ UI-02


@pytest.mark.qa("UI-02")
@pytest.mark.parametrize("name", EXAMPLE_NAMES)
def test_run_each_example_via_select(ui, name):
    ui.wait_ok()
    page = ui.page
    page.locator("#example").select_option(name)
    ex = next(e for e in _api(ui, "/api/examples") if e["name"] == name)
    assert page.locator("#editor").input_value() == ex["script"]
    ui.wait_ok()
    expected = _api(ui, "/api/run", {"script": ex["script"], "params": {}, "printer": "prusa_mk4", "material": "pla", "overhang_angle": 45, "infill": 0.2})
    a = expected["analysis"]
    shown = ui.analysis()
    s = a["bounding_box"]["size"]
    assert shown["Size (mm)"] == f"{s[0]:.1f} x {s[1]:.1f} x {s[2]:.1f}"
    assert shown["Volume"] == f"{a['volume'] / 1000:.2f} cm3"
    assert shown["Triangles"] == str(a["triangle_count"])
    assert shown["Best orientation"] == a["orientation"]["best"]
    inputs = page.locator("#params label.param")
    assert inputs.count() == len(expected["params"])
    assert [inputs.nth(i).locator("span").inner_text() for i in range(inputs.count())] == [p["name"] for p in expected["params"]]
    px = pixel_counts(ui.viewer_png())
    assert px["model"] > 500, px
    assert px["blue"] > 50, f"build volume outline not rendered: {px}"


@pytest.mark.qa("UI-02")
def test_run_button_and_ctrl_enter(ui):
    ui.wait_ok()
    ui.set_editor(CUBE20)
    ui.click_run()
    ui.wait_ok()
    assert ui.analysis()["Size (mm)"] == "20.0 x 20.0 x 20.0"

    ui.set_editor(CUBE20.replace("box(20, 20, 20", "box(30, 10, 5"))
    ui.page.locator("#editor").press("Control+Enter")
    ui.wait_status(lambda t: True)
    ui.page.wait_for_function("document.querySelector('#analysis td + td')?.textContent === '30.0 x 10.0 x 5.0'", timeout=60000)
    assert ui.status() == "OK"


@pytest.mark.qa("UI-02")
def test_overhang_highlight_and_legend(ui):
    ui.wait_ok()
    assert ui.page.locator("#legend").is_visible()
    assert "needs support" in ui.page.locator("#legend").inner_text()
    ui.set_editor(CUBE20)
    ui.click_run()
    ui.wait_ok()
    above = pixel_counts(ui.viewer_png())
    assert above["red"] == 0, f"a cube on the bed has no overhangs: {above}"
    ui.orbit_to_below()
    below = pixel_counts(ui.viewer_png())
    assert below["red"] == 0, f"the cube's bottom sits on the bed and must not be red: {below}"

    ui.set_editor(MUSHROOM)
    ui.click_run()
    ui.wait_ok()  # the camera keeps looking up from below, at the cap underside
    shaded = pixel_counts(ui.viewer_png())
    assert shaded["red"] > 1000, f"overhang faces are not highlighted in red: {shaded}"
    assert shaded["model"] + shaded["red"] > 2000, shaded


# ------------------------------------------------------------------ UI-03


@pytest.mark.qa("UI-03")
def test_numeric_param_in_range_rebuilds(ui):
    ui.wait_ok()
    ui.set_editor(BOX_PARAM)
    ui.click_run()
    ui.wait_ok()
    field = ui.page.locator("#params label.param input")
    assert field.get_attribute("type") == "number"
    assert field.get_attribute("min") == "5" and field.get_attribute("max") == "50"
    assert ui.analysis()["Size (mm)"] == "10.0 x 20.0 x 30.0"
    field.fill("25")
    field.dispatch_event("change")
    ui.page.wait_for_function("document.querySelector('#analysis td + td')?.textContent === '25.0 x 20.0 x 30.0'", timeout=60000)
    assert ui.wait_ok() == "OK"
    assert ui.page.locator("#params label.param input").input_value() == "25"


@pytest.mark.qa("UI-03")
@pytest.mark.parametrize("value,message", [("1", "below the minimum"), ("99", "above the maximum")])
def test_numeric_param_out_of_range_shows_error_and_keeps_model(ui, value, message):
    ui.wait_ok()
    ui.set_editor(BOX_PARAM)
    ui.click_run()
    ui.wait_ok()
    before = ui.analysis()
    field = ui.page.locator("#params label.param input")
    field.fill(value)
    field.dispatch_event("change")
    text = ui.wait_error()
    assert message in text
    assert ui.analysis() == before, "the last good analysis must stay on screen"
    assert pixel_counts(ui.viewer_png())["model"] > 500, "the last good model must stay in the viewer"


@pytest.mark.qa("UI-03")
def test_bool_str_and_int_param_controls(ui):
    ui.wait_ok()
    ui.set_editor(BOOL_STR_SCRIPT)
    ui.click_run()
    ui.wait_ok()
    fields = ui.page.locator("#params label.param")
    by_name = {fields.nth(i).locator("span").inner_text(): fields.nth(i).locator("input") for i in range(fields.count())}
    assert set(by_name) == {"solid", "label", "count"}
    assert by_name["solid"].get_attribute("type") == "checkbox" and by_name["solid"].is_checked()
    assert by_name["label"].get_attribute("type") == "text" and by_name["label"].input_value() == "qa"
    assert by_name["count"].get_attribute("type") == "number" and by_name["count"].get_attribute("step") == "1"

    with ui.page.expect_request(lambda r: r.url.endswith("/api/run")) as req:
        by_name["solid"].uncheck()
    assert json.loads(req.value.post_data)["params"]["solid"] is False
    ui.wait_ok()

    by_name = {fields.nth(i).locator("span").inner_text(): fields.nth(i).locator("input") for i in range(fields.count())}
    with ui.page.expect_request(lambda r: r.url.endswith("/api/run")) as req:
        by_name["label"].fill("changed")
        by_name["label"].dispatch_event("change")
    assert json.loads(req.value.post_data)["params"]["label"] == "changed"
    ui.wait_ok()

    by_name = {fields.nth(i).locator("span").inner_text(): fields.nth(i).locator("input") for i in range(fields.count())}
    by_name["count"].fill("3")
    by_name["count"].dispatch_event("change")
    ui.page.wait_for_function("document.querySelector('#analysis td + td')?.textContent === '30.0 x 10.0 x 10.0'", timeout=60000)


# ------------------------------------------------------------------ UI-04


@pytest.mark.qa("UI-04")
def test_syntax_error_then_recovery(ui):
    ui.wait_ok()
    ui.set_editor("result = (")
    ui.click_run()
    text = ui.wait_error()
    assert re.search(r"Syntax error on line \d+", text), text
    assert ui.page.locator("#run").is_enabled() and ui.page.locator("#editor").is_editable()
    assert ui.page_errors == []

    ui.set_editor(CUBE20)
    ui.click_run()
    assert ui.wait_ok() == "OK"
    assert ui.analysis()["Size (mm)"] == "20.0 x 20.0 x 20.0"
    assert not ui.status_is_error()


@pytest.mark.qa("UI-04")
@pytest.mark.parametrize(
    "source,message",
    [
        ("import os\n" + CUBE20, "not allowed"),
        ("", "variable named 'result'"),
        ("x = 1\nresult = 1 / 0", "ZeroDivisionError"),
    ],
    ids=["forbidden-import", "empty-editor", "runtime-error"],
)
def test_script_errors_are_shown(ui, source, message):
    ui.wait_ok()
    ui.set_editor(source)
    ui.click_run()
    assert message in ui.wait_error()
    assert ui.page_errors == []


# ------------------------------------------------------------------ UI-06


def _download(ui, fmt):
    with ui.page.expect_download(timeout=120000) as info:
        ui.page.locator(f"[data-export='{fmt}']").click()
    download = info.value
    assert download.failure() is None, download.failure()
    with open(download.path(), "rb") as fh:
        return download.suggested_filename, fh.read()


@pytest.mark.qa("UI-06")
def test_export_downloads_match_the_model(ui):
    ui.wait_ok()
    ui.set_editor(BOX_PARAM)
    ui.click_run()
    ui.wait_ok()
    expected_volume = 10 * 20 * 30

    name, data = _download(ui, "stl")
    assert name == "model.stl"
    assert signed_volume(parse_stl(data)) == pytest.approx(expected_volume, rel=1e-6)
    assert ui.wait_ok() == "Exported model.stl"

    name, data = _download(ui, "3mf")
    assert name == "model.3mf"
    assert zipfile.ZipFile(io.BytesIO(data)).testzip() is None
    assert signed_volume(parse_3mf(data)) == pytest.approx(expected_volume, rel=1e-4)
    assert ui.wait_ok() == "Exported model.3mf"

    name, data = _download(ui, "step")
    assert name == "model.step"
    assert data.startswith(b"ISO-10303-21")
    assert ui.wait_ok() == "Exported model.step"


@pytest.mark.qa("UI-06")
def test_export_uses_current_params(ui):
    ui.wait_ok()
    ui.set_editor(BOX_PARAM)
    ui.click_run()
    ui.wait_ok()
    field = ui.page.locator("#params label.param input")
    field.fill("40")
    field.dispatch_event("change")
    ui.page.wait_for_function("document.querySelector('#analysis td + td')?.textContent === '40.0 x 20.0 x 30.0'", timeout=60000)
    ui.wait_ok()
    _, data = _download(ui, "stl")
    assert signed_volume(parse_stl(data)) == pytest.approx(40 * 20 * 30, rel=1e-6)


@pytest.mark.qa("UI-06")
@pytest.mark.parametrize("fmt", ["stl", "3mf", "step"])
def test_export_with_broken_script_shows_error_and_no_download(ui, fmt):
    ui.wait_ok()
    downloads = []
    ui.page.on("download", lambda d: downloads.append(d))
    ui.set_editor("result = (")
    ui.page.locator(f"[data-export='{fmt}']").click()
    assert "Syntax error" in ui.wait_error()
    ui.page.wait_for_timeout(500)
    assert downloads == []
