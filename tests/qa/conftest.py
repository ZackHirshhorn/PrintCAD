"""Fixtures for the P0 QA suite: CLI runner, API client, live server and browser."""
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass, field

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from printcad import cli
from printcad.api import app


# ------------------------------------------------------------------ CLI


@dataclass
class CliResult:
    code: int
    out: str
    err: str


@pytest.fixture
def run_cli(capsys):
    """Run `printcad <args>` in-process and capture exit code, stdout and stderr."""

    def _run(*args) -> CliResult:
        capsys.readouterr()
        code = cli.main([str(a) for a in args])
        captured = capsys.readouterr()
        return CliResult(code, captured.out, captured.err)

    return _run


@pytest.fixture
def script_file(tmp_path):
    """Write a script to a temp .py file and return its path."""

    def _write(source: str, name: str = "script.py"):
        path = tmp_path / name
        path.write_text(source)
        return path

    return _write


# ------------------------------------------------------------------ API


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


# ------------------------------------------------------------------ live server + browser


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """Run the real uvicorn server in a background thread for browser tests."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError("live server did not start within 30 s")
        time.sleep(0.1)
    yield base
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def qa_browser():
    """Headless Chromium with software WebGL (SwiftShader), so the 3D viewer really renders.

    Set PRINTCAD_CHROMIUM to use a specific Chromium/headless-shell binary instead of the
    one installed by `playwright install chromium`.
    """
    from playwright.sync_api import sync_playwright

    args = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=os.environ.get("PRINTCAD_CHROMIUM") or None, args=args)
        yield b
        b.close()


@dataclass
class UiSession:
    page: object
    base: str
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)

    def status(self) -> str:
        return self.page.locator("#status").inner_text()

    def wait_status(self, predicate, timeout: float = 60.0) -> str:
        """Wait until the status line is not 'Running...'/'Exporting' and satisfies `predicate`."""
        deadline = time.monotonic() + timeout
        text = ""
        while time.monotonic() < deadline:
            text = self.status()
            busy = text.startswith("Running") or text.startswith("Exporting")
            if not busy and predicate(text):
                return text
            self.page.wait_for_timeout(100)
        raise AssertionError(f"status never matched, last value: {text!r}")

    def wait_ok(self, timeout: float = 60.0) -> str:
        return self.wait_status(lambda t: not self.status_is_error(), timeout)

    def wait_error(self, timeout: float = 60.0) -> str:
        return self.wait_status(lambda t: self.status_is_error(), timeout)

    def status_is_error(self) -> bool:
        return "error" in (self.page.locator("#status").get_attribute("class") or "").split()

    def set_editor(self, source: str) -> None:
        self.page.locator("#editor").fill(source)

    def click_run(self) -> None:
        self.page.locator("#run").click()

    def analysis(self) -> dict[str, str]:
        rows = self.page.locator("#analysis table tr")
        return {rows.nth(i).locator("td").nth(0).inner_text(): rows.nth(i).locator("td").nth(1).inner_text() for i in range(rows.count())}

    def orbit_to_below(self) -> None:
        """Drag the orbit controls until the camera looks up at the model from under the bed."""
        box = self.page.locator("#viewer canvas").bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        for _ in range(3):
            self.page.mouse.move(cx, cy)
            self.page.mouse.down()
            self.page.mouse.move(cx, cy - 60, steps=10)
            self.page.mouse.up()
        self.page.wait_for_timeout(500)

    def viewer_png(self) -> bytes:
        self.page.wait_for_timeout(300)  # a few animation frames so the latest mesh is drawn
        # The legend (with its red/grey swatches) and status line overlay the canvas; paint them
        # in the scene background colour so only WebGL output is measured.
        overlays = [self.page.locator("#legend"), self.page.locator("#status")]
        return self.page.locator("#viewer canvas").screenshot(mask=overlays, mask_color="#1b1e23")


@pytest.fixture
def ui(qa_browser, live_server):
    """A fresh page on the app, loaded and with the initial example run finished."""
    context = qa_browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
    page = context.new_page()
    session = UiSession(page, live_server)
    page.on("console", lambda m: session.console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: session.page_errors.append(str(e)))
    page.on("request", lambda r: session.requests.append(r.url))
    page.goto(live_server + "/")
    session.wait_status(lambda t: t not in ("Ready", ""))
    yield session
    context.close()
