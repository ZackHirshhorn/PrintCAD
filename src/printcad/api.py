"""FastAPI application."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .examples import list_examples
from .export import FORMATS, MEDIA_TYPES, export_bytes
from .materials import MATERIALS
from .printers import PRINTERS
from .runner import ScriptError
from .service import BuildResult, build

WEB_DIR = Path(__file__).parent / "web"


class RunRequest(BaseModel):
    script: str
    params: dict[str, Any] = Field(default_factory=dict)
    printer: str = "prusa_mk4"
    material: str = "pla"
    overhang_angle: float = 45.0
    infill: float = 0.2
    tolerance: float = 0.05


def _build(req: RunRequest) -> BuildResult:
    try:
        return build(
            req.script, req.params, req.printer, req.material, req.overhang_angle, req.infill, req.tolerance
        )
    except ScriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0])) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


def create_app() -> FastAPI:
    app = FastAPI(title="PrintCAD", version=__version__)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/printers")
    def printers() -> list[dict]:
        return [p.to_dict() for p in PRINTERS.values()]

    @app.get("/api/materials")
    def materials() -> list[dict]:
        return [m.to_dict() for m in MATERIALS.values()]

    @app.get("/api/examples")
    def examples() -> list[dict]:
        return list_examples()

    @app.post("/api/run")
    def run(req: RunRequest) -> dict:
        res = _build(req)
        mesh = res.mesh
        return {
            "mesh": {
                "vertices": [round(float(x), 5) for x in mesh.vertices.reshape(-1)],
                "indices": [int(i) for i in mesh.faces.reshape(-1)],
            },
            "overhang_faces": res.overhang_faces,
            "analysis": res.analysis,
            "params": res.params,
            "stdout": res.stdout,
        }

    @app.post("/api/export/{fmt}")
    def export(fmt: str, req: RunRequest) -> Response:
        fmt = fmt.lower()
        if fmt not in FORMATS:
            raise HTTPException(status_code=400, detail=f"Unsupported export format '{fmt}'. Use one of: {', '.join(FORMATS)}")
        res = _build(req)
        data = export_bytes(fmt, res.shape, res.mesh)
        return Response(
            content=data,
            media_type=MEDIA_TYPES[fmt],
            headers={"Content-Disposition": f'attachment; filename="model.{fmt}"'},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


app = create_app()
