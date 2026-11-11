"""Triangle mesh container, tessellation of CadQuery shapes, and STL/3MF readers."""
from __future__ import annotations

import io
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Mesh:
    """Indexed triangle mesh. vertices: (N,3) float64, faces: (M,3) int64."""

    vertices: np.ndarray
    faces: np.ndarray

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=np.float64).reshape(-1, 3)
        self.faces = np.asarray(self.faces, dtype=np.int64).reshape(-1, 3)

    @property
    def triangles(self) -> np.ndarray:
        """(M,3,3) array of triangle corner coordinates."""
        return self.vertices[self.faces]

    def face_normals(self) -> np.ndarray:
        t = self.triangles
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        length = np.linalg.norm(n, axis=1, keepdims=True)
        length[length == 0] = 1.0
        return n / length

    def face_areas(self) -> np.ndarray:
        t = self.triangles
        return 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        if len(self.vertices) == 0:
            return np.zeros(3), np.zeros(3)
        return self.vertices.min(axis=0), self.vertices.max(axis=0)

    def transformed(self, matrix: np.ndarray) -> "Mesh":
        """Return a copy transformed by a 3x3 rotation/scale matrix."""
        m = np.asarray(matrix, dtype=np.float64)
        verts = self.vertices @ m.T
        faces = self.faces.copy()
        if np.linalg.det(m) < 0:
            faces = faces[:, ::-1]
        return Mesh(verts, faces)

    def weld(self, decimals: int = 5) -> "Mesh":
        """Merge vertices that coincide (to `decimals` places) and drop degenerate faces."""
        if len(self.vertices) == 0:
            return Mesh(self.vertices, self.faces)
        rounded = np.round(self.vertices, decimals) + 0.0  # +0.0 folds -0.0 into 0.0
        unique, inverse = np.unique(rounded, axis=0, return_inverse=True)
        faces = inverse.reshape(-1)[self.faces]
        keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
        return Mesh(unique, faces[keep])


def tessellate_shape(shape, tolerance: float = 0.05, angular_tolerance: float = 0.1) -> Mesh:
    """Tessellate a CadQuery Shape into a welded Mesh."""
    verts, tris = shape.tessellate(tolerance, angular_tolerance)
    v = np.array([[p.x, p.y, p.z] for p in verts], dtype=np.float64)
    return Mesh(v, np.array(tris, dtype=np.int64)).weld()


# ---------------------------------------------------------------- readers


def _from_triangle_soup(tris: np.ndarray) -> Mesh:
    verts = tris.reshape(-1, 3)
    return Mesh(verts, np.arange(len(verts)).reshape(-1, 3)).weld()


def parse_stl(data: bytes) -> Mesh:
    """Parse binary or ASCII STL bytes."""
    if len(data) >= 84:
        count = struct.unpack("<I", data[80:84])[0]
        if 84 + count * 50 == len(data):
            dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
            arr = np.frombuffer(data, dtype=dt, count=count, offset=84)
            return _from_triangle_soup(arr["v"].astype(np.float64))
    text = data.decode("ascii", errors="ignore")
    if "facet" not in text:
        raise ValueError("Not a valid STL file")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums or len(nums) % 3:
        raise ValueError("Not a valid STL file")
    return _from_triangle_soup(np.array(nums, dtype=np.float64))


def parse_3mf(data: bytes) -> Mesh:
    """Parse the first mesh object of a 3MF package (all objects are merged)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            model = zf.read("3D/3dmodel.model")
        root = ET.fromstring(model)
    except zipfile.BadZipFile:
        raise ValueError("Not a valid 3MF file (not a zip archive)") from None
    except KeyError:
        raise ValueError("Not a valid 3MF file (missing 3D/3dmodel.model)") from None
    except ET.ParseError as exc:
        raise ValueError(f"Not a valid 3MF file (malformed model XML: {exc})") from None
    verts: list[list[float]] = []
    faces: list[list[int]] = []
    for mesh in root.iter():
        if not mesh.tag.endswith("}mesh") and mesh.tag != "mesh":
            continue
        offset = len(verts)
        for el in mesh.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "vertex":
                verts.append([float(el.get("x")), float(el.get("y")), float(el.get("z"))])
            elif tag == "triangle":
                faces.append([offset + int(el.get(k)) for k in ("v1", "v2", "v3")])
    if not verts or not faces:
        raise ValueError("3MF contains no mesh")
    return Mesh(np.array(verts), np.array(faces)).weld()


def load_mesh(path: str | Path) -> Mesh:
    """Load a mesh from a .stl or .3mf file."""
    p = Path(path)
    ext = p.suffix.lower()
    data = p.read_bytes()
    if ext == ".stl":
        return parse_stl(data)
    if ext == ".3mf":
        return parse_3mf(data)
    raise ValueError(f"Unsupported mesh format '{ext}' (use .stl or .3mf)")
