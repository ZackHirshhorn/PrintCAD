"""Exporters: binary STL, 3MF (written by hand) and STEP."""
from __future__ import annotations

import io
import os
import struct
import tempfile
import zipfile

import numpy as np

from .mesh import Mesh

FORMATS = ("stl", "3mf", "step")
MEDIA_TYPES = {
    "stl": "model/stl",
    "3mf": "model/3mf",
    "step": "application/step",
}


def to_stl(mesh: Mesh, name: str = "printcad") -> bytes:
    """Serialize to binary STL."""
    tris = mesh.triangles.astype("<f4")
    normals = mesh.face_normals().astype("<f4")
    dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    arr = np.zeros(len(tris), dtype=dt)
    arr["n"] = normals
    arr["v"] = tris
    header = f"PrintCAD {name}".encode("ascii", "replace")[:80].ljust(80, b" ")
    return header + struct.pack("<I", len(tris)) + arr.tobytes()


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)


def to_3mf(mesh: Mesh, name: str = "printcad") -> bytes:
    """Serialize to a 3MF package (millimeter units)."""
    vert_xml = "".join(f'<vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}"/>' for x, y, z in mesh.vertices)
    tri_xml = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces)
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ") or "printcad"
    model = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
        f'<metadata name="Title">{safe}</metadata>'
        '<metadata name="Application">PrintCAD</metadata>'
        "<resources>"
        f'<object id="1" name="{safe}" type="model"><mesh>'
        f"<vertices>{vert_xml}</vertices><triangles>{tri_xml}</triangles>"
        "</mesh></object></resources>"
        '<build><item objectid="1"/></build></model>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("_rels/.rels", _RELS)
        zf.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def to_step(shape) -> bytes:
    """Serialize a CadQuery shape to STEP."""
    import cadquery as cq

    fd, path = tempfile.mkstemp(suffix=".step")
    os.close(fd)
    try:
        cq.exporters.export(cq.Workplane("XY").newObject([shape]), path, exportType="STEP")
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.unlink(path)


def export_bytes(fmt: str, shape, mesh: Mesh, name: str = "printcad") -> bytes:
    fmt = fmt.lower()
    if fmt == "stl":
        return to_stl(mesh, name)
    if fmt == "3mf":
        return to_3mf(mesh, name)
    if fmt == "step":
        return to_step(shape)
    raise ValueError(f"Unsupported export format '{fmt}'. Use one of: {', '.join(FORMATS)}")
