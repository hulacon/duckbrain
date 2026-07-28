"""Interaction tests for the QC Dashboard page.

Covers the panel that shows fMRIPrep's own per-subject report — the anatomical
checks (tissue segmentation, spatial normalization, surface reconstruction) and
SDC before/after, none of which appear anywhere in the run-shaped views the rest
of the page is built from.

The load-bearing case is :func:`test_panel_survives_a_project_with_no_mriqc`.
The page stops early when MRIQC metrics are missing, so where this panel sits
relative to that stop decides whether an fMRIPrep derivative that is present on
disk can be looked at at all. Nothing about the panel's own code would fail if
it were moved below the stop; it would just go quiet on exactly the projects
that need it, which is the failure mode this page has already shipped twice.
"""

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/5_QC_Dashboard.py"

FIXTURES = Path(__file__).parent / "fixtures" / "mriqc"

#: The shape fMRIPrep writes: one HTML per subject at the root of its output
#: directory, figures beneath it in the subject's own tree.
FMRIPREP_HTML = (
    "<html><body>\n"
    '<img src="./{sub}/figures/{sub}_dseg.svg" />\n'
    '<img src="./{sub}/figures/{sub}_space-MNI152NLin2009cAsym_T1w.svg" />\n'
    '<img src="./{sub}/figures/{sub}_task-rest_run-1_desc-sdc_bold.svg" />\n'
    "</body></html>"
)


def _write_fmriprep(derivatives: Path, subjects=("sub-010", "sub-011")):
    """A minimal fMRIPrep derivative: a report per subject, figures beside it."""
    root = derivatives / "fmriprep"
    for sub in subjects:
        figures = root / sub / "figures"
        figures.mkdir(parents=True, exist_ok=True)
        for name in (
            f"{sub}_dseg.svg",
            f"{sub}_space-MNI152NLin2009cAsym_T1w.svg",
            f"{sub}_task-rest_run-1_desc-sdc_bold.svg",
        ):
            (figures / name).write_text("<svg/>" + "x" * 1000)
        (root / f"{sub}.html").write_text(FMRIPREP_HTML.format(sub=sub))
    return root


def _write_mriqc(derivatives: Path):
    """Enough real MRIQC output that the page does not stop before the tables."""
    mriqc = derivatives / "mriqc"
    mriqc.mkdir(parents=True, exist_ok=True)
    iqms = json.loads((FIXTURES / "bold.json").read_text())
    for sub in ("010", "011"):
        payload = dict(iqms)
        payload["bids_name"] = f"sub-{sub}_task-rest_run-1_bold"
        (mriqc / f"sub-{sub}_task-rest_run-1_bold.json").write_text(json.dumps(payload))
    return mriqc


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "qc test"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def _captions(at):
    return [c.value for c in at.caption]


def _selectbox(at, label):
    matches = [s for s in at.selectbox if s.label == label]
    return matches[0] if matches else None


class TestFmriprepReportPanel:
    def test_lists_every_subject_with_a_report(self, project):
        _write_fmriprep(project / "derivatives")
        _write_mriqc(project / "derivatives")
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        picker = _selectbox(at, "Subject")
        assert picker is not None, "no subject picker rendered"
        assert list(picker.options) == ["sub-010", "sub-011"]

    def test_panel_survives_a_project_with_no_mriqc(self, project):
        """fMRIPrep ran, MRIQC did not — the report must still be reachable.

        The page stops on missing MRIQC metrics. If this panel is ever moved
        below that stop, a present derivative becomes invisible and the page
        says only that MRIQC has not run.
        """
        _write_fmriprep(project / "derivatives")
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert any("No MRIQC metrics found" in w.value for w in at.warning), (
            "expected the page to stop for missing MRIQC — otherwise this test "
            "no longer pins what it claims to"
        )
        picker = _selectbox(at, "Subject")
        assert picker is not None, "the fMRIPrep panel was hidden by the MRIQC stop"
        assert list(picker.options) == ["sub-010", "sub-011"]

    def test_states_the_cost_before_it_is_spent(self, project):
        """The figures are read into server memory, so the size is shown first."""
        _write_fmriprep(project / "derivatives")
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert any("MB of figures" in c for c in _captions(at))

    def test_report_is_behind_a_toggle_not_loaded_on_arrival(self, project):
        _write_fmriprep(project / "derivatives")
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        toggles = [t for t in at.toggle if t.label == "Show fMRIPrep report"]
        assert len(toggles) == 1
        assert toggles[0].value is False

    def test_showing_the_report_serves_every_figure(self, project):
        """Not just "does not crash": a report rendered with holes in it and no
        word said is the failure ``core.report_embed`` exists to prevent, and it
        reports one by warning. So the absence of that warning is the assertion.
        """
        _write_fmriprep(project / "derivatives")
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        [t for t in at.toggle if t.label == "Show fMRIPrep report"][0].set_value(True).run()
        assert not at.exception
        assert not [w for w in at.warning if "could not be served" in w.value]

    def test_no_derivative_says_so_and_points_somewhere(self, project):
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert _selectbox(at, "Subject") is None
        assert any("No fMRIPrep reports" in c for c in _captions(at))
