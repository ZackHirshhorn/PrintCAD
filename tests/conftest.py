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


# ------------------------------------------------------------------ no-skip policy
# Project rule: no test may be skipped or expected to fail. Any skip/xfail, whether by
# marker, pytest.skip(), pytest.importorskip() or pytest.xfail(), is reported as a failure.

_FORBIDDEN_MARKERS = ("skip", "skipif", "xfail")


def pytest_collection_modifyitems(config, items):
    offenders = [
        f"{item.nodeid} (@pytest.mark.{name})"
        for item in items
        for name in _FORBIDDEN_MARKERS
        if item.get_closest_marker(name)
    ]
    if offenders:
        raise pytest.UsageError("Skipping tests is not allowed:\n  " + "\n  ".join(offenders))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.skipped or hasattr(report, "wasxfail"):
        reason = getattr(report, "wasxfail", None) or report.longrepr
        if hasattr(report, "wasxfail"):
            del report.wasxfail  # otherwise pytest does not count the failure in the exit status
        report.outcome = "failed"
        report.longrepr = f"Skipping tests is not allowed (no-skip policy): {reason}"


@pytest.hookimpl(hookwrapper=True)
def pytest_make_collect_report(collector):
    outcome = yield
    report = outcome.get_result()
    if report.skipped:
        report.outcome = "failed"
        report.longrepr = f"Skipping tests is not allowed (no-skip policy): {report.longrepr}"
