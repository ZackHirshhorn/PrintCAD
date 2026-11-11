"""QA-00 baseline gate, plus a guard that every P0 flow in the QA doc is automated."""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from printcad import __version__
from qa_helpers import QA_DOC, REPO_ROOT

pytestmark = pytest.mark.p0

TESTS_DIR = REPO_ROOT / "tests"


@pytest.mark.qa("QA-00")
def test_version_reported_by_installed_entry_point():
    r = subprocess.run([sys.executable, "-m", "printcad.cli", "--version"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"printcad {__version__}"


@pytest.mark.qa("QA-00")
def test_no_test_source_skips_or_xfails():
    pattern = re.compile(r"pytest\.(skip|xfail|importorskip)\s*\(|mark\.(skip|skipif|xfail)\b|unittest\.skip")
    offenders = []
    # These two files name the forbidden calls on purpose: the enforcement hooks and their self-test.
    enforcement = {(TESTS_DIR / "conftest.py").resolve(), Path(__file__).resolve()}
    for path in TESTS_DIR.rglob("*.py"):
        if path.resolve() in enforcement:
            continue
        for no, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{no}: {line.strip()}")
    assert not offenders, "Skips/xfails are not allowed:\n" + "\n".join(offenders)


@pytest.mark.qa("QA-00")
@pytest.mark.parametrize(
    "body",
    [
        "import pytest\n\ndef test_x():\n    pytest.skip('nope')\n",
        "import pytest\n\n@pytest.mark.skip(reason='nope')\ndef test_x():\n    pass\n",
        "import pytest\n\ndef test_x():\n    pytest.xfail('nope')\n",
        "import pytest\npytest.importorskip('module_that_does_not_exist_qa')\n\ndef test_x():\n    pass\n",
    ],
    ids=["runtime-skip", "skip-marker", "runtime-xfail", "importorskip"],
)
def test_no_skip_policy_turns_skips_into_failures(tmp_path, body):
    """Run a throwaway pytest session with the project's conftest and check a skip fails the run."""
    (tmp_path / "conftest.py").write_text((TESTS_DIR / "conftest.py").read_text())
    (tmp_path / "test_dummy.py").write_text(textwrap.dedent(body))
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path,
    )
    output = r.stdout + r.stderr
    assert r.returncode != 0, output
    assert "skipped" not in output and "xfailed" not in output, output
    assert "not allowed" in output


def _p0_flow_ids() -> set[str]:
    ids = set()
    for line in QA_DOC.read_text().splitlines():
        ids.update(re.findall(r"\*\*([A-Z]+-\d+) \(P0\)", line))  # "**CLI-01 (P0) ..." headings
        ids.update(re.findall(r"\|\s*([A-Z]+-\d+) \(P0\)\s*\|", line))  # table rows "| AN-01 (P0) |"
    return ids


def _automated_flow_ids() -> set[str]:
    ids = set()
    for path in (TESTS_DIR / "qa").glob("test_*.py"):
        ids.update(re.findall(r"mark\.qa\(\"([A-Z]+-\d+)\"\)", path.read_text()))
    return ids


@pytest.mark.qa("QA-00")
def test_every_p0_flow_in_the_qa_doc_is_automated():
    p0 = _p0_flow_ids()
    assert len(p0) >= 20, f"could not parse P0 flows from {QA_DOC}: {sorted(p0)}"
    missing = sorted(p0 - _automated_flow_ids())
    assert not missing, f"P0 flows without an automated test: {missing}"
