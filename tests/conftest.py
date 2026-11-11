import cadquery as cq
import pytest

from printcad.mesh import tessellate_shape


@pytest.fixture(scope="session")
def box_mesh():
    return tessellate_shape(cq.Workplane("XY").box(10, 20, 30, centered=False).val())


@pytest.fixture(scope="session")
def hollow_mesh():
    """Hollow box with 2 mm walls."""
    outer = cq.Workplane("XY").box(30, 30, 30, centered=False)
    inner = cq.Workplane("XY").box(26, 26, 26, centered=False).translate((2, 2, 2))
    return tessellate_shape(outer.cut(inner).val())


@pytest.fixture(scope="session")
def pyramid_mesh():
    """Inverted cone: a wide top over a narrow base, so side faces overhang strongly."""
    return tessellate_shape(cq.Solid.makeCone(2, 20, 20, pnt=cq.Vector(0, 0, 0), dir=cq.Vector(0, 0, 1)))
