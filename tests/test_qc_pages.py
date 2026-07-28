"""Interaction tests for the five QC pages.

The load-bearing case is :func:`test_evidence_survives_a_project_with_no_mriqc`,
carried forward from when QC was one page. fMRIPrep's figures must stay reachable
on a project where fMRIPrep ran and MRIQC did not. The old page guarded this by
ordering its fMRIPrep panel *above* its own ``st.stop()``; the domain pages guard
it by falling back to the run list in fMRIPrep's own figures. Nothing about the
viewer's code fails if that fallback goes — it just goes quiet on exactly the
projects that have a derivative to review, which is a failure this surface has
already shipped twice.

The pages themselves are near-empty declarations, so what is really under test
here is ``gui.qc_panels`` wired up the way the app wires it — including the parts
``AppTest.from_function`` cannot reach, like whether a page in the nav runs at all.
"""

import json
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project
from duckbrain.core.qc_guidance import get_guidance

#: Read from the registry rather than retyped, so a relabelled measure moves the
#: assertion with it instead of failing on prose.
TSNR = get_guidance("tsnr").label
FD_MEAN = get_guidance("fd_mean").label

OVERVIEW = "src/duckbrain/gui/pages/5_QC_Overview.py"
SIGNAL = "src/duckbrain/gui/pages/5a_QC_Signal.py"
TEMPORAL = "src/duckbrain/gui/pages/5b_QC_Temporal.py"
ALIGNMENT = "src/duckbrain/gui/pages/5c_QC_Alignment.py"
ARTIFACTS = "src/duckbrain/gui/pages/5d_QC_Artifacts.py"
ALL_PAGES = [OVERVIEW, SIGNAL, TEMPORAL, ALIGNMENT, ARTIFACTS]

FIXTURES = Path(__file__).parent / "fixtures" / "mriqc"

#: Shaped like fMRIPrep's animated reportlets — the before/after flicker is CSS
#: carried inside the file. Written as a *valid* SVG on purpose: a malformed one
#: does not match Streamlit's SVG detection, so the figure would never take the
#: rendering path the viewer exists to exercise.
FIGURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    "<style>@keyframes flicker { 0% {opacity:1} 100% {opacity:0} }"
    ".f { animation: flicker 2s infinite; }</style>"
    '<rect class="f" width="10" height="10"/></svg>'
)

FMRIPREP_HTML = (
    "<html><body>\n"
    '<img src="./{sub}/figures/{sub}_dseg.svg" />\n'
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
            (figures / name).write_text(FIGURE_SVG)
        (root / f"{sub}.html").write_text(FMRIPREP_HTML.format(sub=sub))
    return root


def _write_mriqc(derivatives: Path):
    """Enough real MRIQC output that the pages have numbers to show."""
    mriqc = derivatives / "mriqc"
    mriqc.mkdir(parents=True, exist_ok=True)
    iqms = json.loads((FIXTURES / "bold.json").read_text())
    for sub in ("010", "011"):
        payload = dict(iqms)
        payload["bids_name"] = f"sub-{sub}_task-rest_run-1_bold"
        # Vary one measure so the cohort has a spread to place a run within.
        payload["tsnr"] = float(iqms.get("tsnr", 40)) + (10 if sub == "011" else 0)
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


@pytest.fixture
def full(project):
    """A project with both derivatives — the ordinary case."""
    _write_fmriprep(project / "derivatives")
    _write_mriqc(project / "derivatives")
    return project


def _run(page, **params):
    at = AppTest.from_file(page, default_timeout=90)
    for key, value in params.items():
        at.query_params[key] = value
    return at.run()


def _captions(at):
    return [c.value for c in at.caption]


def _selectbox(at, label):
    matches = [s for s in at.selectbox if s.label == label]
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Every page, on every project shape
# ---------------------------------------------------------------------------


class TestEveryPageRenders:
    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_a_complete_project_renders(self, full, page):
        assert not _run(page).exception

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_an_empty_project_says_so_rather_than_breaking(self, project, page):
        """No derivatives at all: a message, not a traceback and not a blank."""
        at = _run(page)
        assert not at.exception
        assert at.warning or at.info or at.error

    @pytest.mark.parametrize("page", ALL_PAGES)
    def test_the_scope_bar_is_on_every_page(self, full, page):
        """The five pages must agree about what is being looked at."""
        at = _run(page)
        assert _selectbox(at, "Modality") is not None
        assert _selectbox(at, "Run") is not None


# ---------------------------------------------------------------------------
# The load-bearing case
# ---------------------------------------------------------------------------


class TestSurvivesAMissingTool:
    def test_evidence_survives_a_project_with_no_mriqc(self, project):
        """fMRIPrep ran, MRIQC did not — the figures must still be reachable.

        Carried forward from the single-page era, where it pinned the panel's
        position above the page's stop. It now pins the fallback that replaced
        that ordering.
        """
        _write_fmriprep(project / "derivatives")
        at = _run(ALIGNMENT)
        assert not at.exception
        assert any("No MRIQC metrics found" in w.value for w in at.warning), (
            "expected the page to notice MRIQC is missing — otherwise this test "
            "no longer pins what it claims to"
        )
        picker = _selectbox(at, "Run")
        assert picker is not None, "the fMRIPrep evidence was hidden by the MRIQC gap"
        assert list(picker.options) == [
            "sub-010_task-rest_run-1_bold",
            "sub-011_task-rest_run-1_bold",
        ]
        assert any(t.label == "Show Tissue segmentation on the T1w" for t in at.toggle)

    def test_the_fallback_says_where_the_runs_came_from(self, project):
        _write_fmriprep(project / "derivatives")
        at = _run(ALIGNMENT)
        assert any("read from fMRIPrep's own figures" in c for c in _captions(at))

    def test_a_project_with_neither_derivative_points_at_preprocessing(self, project):
        at = _run(ALIGNMENT)
        assert not at.exception
        assert any("Run MRIQC first" in i.value for i in at.info)

    def test_measures_survive_a_project_with_no_fmriprep(self, project):
        """MRIQC ran, fMRIPrep did not — the numbers must still be reviewable."""
        _write_mriqc(project / "derivatives")
        at = _run(SIGNAL)
        assert not at.exception
        assert _selectbox(at, "Run") is not None
        assert at.dataframe, "no measure table rendered"


# ---------------------------------------------------------------------------
# Domains: the right measures, in the right place, with their guidance
# ---------------------------------------------------------------------------


class TestDomainPages:
    def test_a_domain_page_shows_only_its_own_measures(self, full):
        """Signal shows tSNR; motion belongs to Temporal and must not appear."""
        rendered = _run(SIGNAL).dataframe[0].value["Measure"].tolist()
        assert TSNR in rendered
        assert FD_MEAN not in rendered

    def test_the_temporal_page_shows_motion(self, full):
        rendered = _run(TEMPORAL).dataframe[0].value["Measure"].tolist()
        assert FD_MEAN in rendered
        assert TSNR not in rendered

    def test_guidance_sits_with_the_measure_not_in_a_glossary(self, full):
        """The whole point of the regrouping: the reason is beside the number."""
        labels = [e.label for e in _run(SIGNAL).expander]
        assert any(TSNR in label for label in labels)

    def test_the_review_question_is_stated(self, full):
        assert any("distortion corrected" in m.value for m in _run(ALIGNMENT).markdown)

    def test_a_domain_with_no_measures_here_explains_itself(self, full):
        """Alignment has no MRIQC number for bold — and says why, not nothing."""
        assert any("no registration measure" in i.value for i in _run(ALIGNMENT).info)

    def test_a_run_is_placed_within_its_cohort(self, full):
        """A bare IQM cannot be read; where it sits among these runs can."""
        assert "Position in cohort" in _run(SIGNAL).dataframe[0].value.columns

    def test_alignment_carries_figures_and_signal_does_not(self, full):
        assert [t for t in _run(ALIGNMENT).toggle if t.label.startswith("Show ")]
        assert not [t for t in _run(SIGNAL).toggle if t.label.startswith("Show ")]


class TestDomainSignOff:
    """Reviewing one aspect is recorded, and is not a verdict on the run."""

    def _decisions(self, project):
        return project / "derivatives" / "preprocessing_qc"

    def test_each_domain_page_offers_a_sign_off(self, full):
        labels = [b.label for b in _run(SIGNAL).button]
        assert "Reviewed — no concerns" in labels
        assert "Reviewed — concerns" in labels

    def test_signing_off_records_it_against_that_domain(self, full):
        at = _run(SIGNAL)
        [b for b in at.button if b.label == "Reviewed — no concerns"][0].click().run()
        assert not at.exception
        written = list(self._decisions(full).glob("*_decision.json"))
        record = json.loads(written[0].read_text())["decisions"][-1]
        assert record["decision"] == "reviewed"
        assert record["domain"] == "signal"
        assert record["reviewer"]

    def test_signing_off_a_domain_gives_the_run_no_verdict(self, full):
        """The property the whole schema change exists to guarantee."""
        from duckbrain.core import qc

        at = _run(ALIGNMENT)
        [b for b in at.button if b.label == "Reviewed — concerns"][0].click().run()
        assert not at.exception
        loaded = qc.load_decisions(self._decisions(full))["sub-010_task-rest_run-1_bold"]
        assert loaded["latest"] == {}
        assert loaded["signed_off"] is False
        assert loaded["domains"]["alignment"]["latest"]["decision"] == "concerns"

    def test_a_note_alone_is_not_a_review(self, full):
        """#17.10 again, at the domain level this time."""
        at = _run(SIGNAL)
        [i for i in at.text_input if i.label == "Note"][0].set_value("looks odd").run()
        assert not at.exception
        assert not list(self._decisions(full).glob("*_decision.json"))

    def test_an_existing_review_is_shown_back(self, full):
        from duckbrain.core import qc

        qc.save_decision(
            self._decisions(full),
            "sub-010_task-rest_run-1_bold",
            "concerns",
            reason="ringing",
            reviewer="ben",
            domain="artifact",
        )
        at = _run(ARTIFACTS, run="sub-010_task-rest_run-1_bold")
        assert any("ringing" in c and "ben" in c for c in _captions(at))

    def test_the_verdict_is_not_gated_behind_reviewing_every_domain(self, full):
        """A reviewer seeing a wrecked run must be able to exclude it at once."""
        at = _run(OVERVIEW)
        exclude = [b for b in at.button if b.label == "Exclude"]
        assert exclude and not exclude[0].disabled


# ---------------------------------------------------------------------------
# Scope travel — the mechanism the navigation rests on
# ---------------------------------------------------------------------------


class TestScopeTravel:
    def test_a_url_selects_the_run_it_names(self, full):
        """Deep links from the overview are query parameters, so this is the hinge."""
        at = _run(ALIGNMENT, run="sub-011_task-rest_run-1_bold")
        assert not at.exception
        assert _selectbox(at, "Run").value == "sub-011_task-rest_run-1_bold"

    def test_a_url_selects_the_modality_it_names(self, full):
        assert _selectbox(_run(SIGNAL, modality="T1w"), "Modality").value == "T1w"

    def test_a_stale_url_falls_back_rather_than_raising(self, full):
        """A link to a run that has since been deleted must not break the page."""
        at = _run(ALIGNMENT, run="sub-999_task-gone_run-9_bold")
        assert not at.exception
        assert _selectbox(at, "Run").value == "sub-010_task-rest_run-1_bold"

    def test_the_url_is_rewritten_to_match_the_selection(self, full):
        """So the page a reviewer is looking at is the page they can send."""
        at = _run(ALIGNMENT)

        def param(name):
            # AppTest hands back the raw multi-value form; the browser sends one.
            value = at.query_params.get(name)
            return value[0] if isinstance(value, list) else value

        assert param("run") == "sub-010_task-rest_run-1_bold"
        assert param("modality") == "bold"


# ---------------------------------------------------------------------------
# The overview
# ---------------------------------------------------------------------------


class TestOverview:
    def test_it_lists_every_run(self, full):
        at = _run(OVERVIEW)
        assert not at.exception
        assert len(at.dataframe[0].value) == 2

    def test_the_verdict_buttons_are_here(self, full):
        labels = [b.label for b in _run(OVERVIEW).button]
        assert {"Keep", "Exclude", "Investigate"} <= set(labels)

    def test_recording_a_verdict_writes_it(self, full):
        at = _run(OVERVIEW)
        [b for b in at.button if b.label == "Keep"][0].click().run()
        assert not at.exception
        written = list((full / "derivatives" / "preprocessing_qc").glob("*_decision.json"))
        assert len(written) == 1
        record = json.loads(written[0].read_text())
        assert record["decisions"][-1]["decision"] == "keep"
        assert record["decisions"][-1]["reviewer"]

    def test_a_note_alone_is_not_a_verdict(self, full):
        """TODO #17.10, re-pinned: typing a reason must record nothing by itself."""
        at = _run(OVERVIEW)
        [i for i in at.text_input if i.label == "Reason"][0].set_value("just a note").run()
        assert not at.exception
        assert not list((full / "derivatives" / "preprocessing_qc").glob("*_decision.json"))

    def test_the_outlier_slider_is_here_and_only_here(self, full):
        assert [s for s in _run(OVERVIEW).slider if "IQR" in s.label]
        assert not [s for s in _run(SIGNAL).slider if "IQR" in s.label]

    def test_domain_progress_is_shown_but_no_verdict_is_derived(self, full):
        """Four reviewed aspects must prompt for a verdict, never stand in for one."""
        from duckbrain.core import qc

        decisions = full / "derivatives" / "preprocessing_qc"
        for key in ("signal", "temporal", "alignment", "artifact"):
            qc.save_decision(
                decisions, "sub-010_task-rest_run-1_bold", "reviewed", reviewer="ben", domain=key
            )
        at = _run(OVERVIEW, run="sub-010_task-rest_run-1_bold")
        assert not at.exception
        captions = " ".join(_captions(at))
        assert "4/4 aspects reviewed" in captions
        assert "no verdict recorded" in captions

    def test_the_export_is_still_offered(self, full):
        """Slice B was dropped, not the capability — the report still exports."""
        assert any("Export" in e.label for e in _run(OVERVIEW).expander)

    def test_the_export_is_not_built_until_it_is_asked_for(self, full):
        """An expander's body runs while collapsed, so this has to be explicit.

        Rendering the report inlines a ~5 MB Plotly bundle and took the overview
        from about a second to ten on a 65-run project — paid on every visit, for
        a file almost nobody exports.
        """
        at = _run(OVERVIEW)
        assert not [b for b in at.button if b.label == "Save to derivatives"]
        assert [t for t in at.toggle if t.label == "Prepare the report"]

    def test_preparing_the_report_then_offers_it(self, full):
        at = _run(OVERVIEW)
        [t for t in at.toggle if t.label == "Prepare the report"][0].set_value(True).run()
        assert not at.exception
        assert [b for b in at.button if b.label == "Save to derivatives"]
