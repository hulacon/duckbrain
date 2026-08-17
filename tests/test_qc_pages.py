"""Interaction tests for the two QC pages: the Overview and the Inspect page.

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
from duckbrain.gui import qc_panels

#: Read from the registry rather than retyped, so a relabelled measure moves the
#: assertion with it instead of failing on prose.
TSNR = get_guidance("tsnr").label
FD_MEAN = get_guidance("fd_mean").label

from conftest import page_path

OVERVIEW = page_path("src/duckbrain/gui/pages/5_QC_Overview.py")
INSPECT = page_path("src/duckbrain/gui/pages/5a_QC_Inspect.py")
ALL_PAGES = [OVERVIEW, INSPECT]

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


def _write_anat_mriqc(derivatives: Path):
    """T1w IQMs beside the bold ones, for the anat-modality cases."""
    mriqc = derivatives / "mriqc"
    mriqc.mkdir(parents=True, exist_ok=True)
    iqms = json.loads((FIXTURES / "T1w.json").read_text())
    for sub in ("010", "011"):
        (mriqc / f"sub-{sub}_T1w.json").write_text(json.dumps(iqms))
    return mriqc


@pytest.fixture
def project(tmp_path):
    # The metrics cache is process-wide, and tmp_path keys differ per test only
    # by accident of the path. Relying on that is what hid a cache key Streamlit
    # was discarding — see tests/test_streamlit_caches.py.
    qc_panels._load_metrics.clear()
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


def _decisions_dir(project: Path) -> Path:
    """Where decisions land, asked of the code rather than restated here."""
    from duckbrain.config import load_config
    from duckbrain.core import qc

    return qc.decisions_dir(load_config(project_dir=str(project)))


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
        """The pages must agree about what is being looked at.

        The overview is cohort-level since the rework — its table is the run
        picker — so it carries the modality control only.
        """
        at = _run(page)
        assert _selectbox(at, "Modality") is not None
        if page == OVERVIEW:
            assert _selectbox(at, "Run") is None
        else:
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
        at = _run(INSPECT)
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
        seg = [t for t in at.toggle if t.label == "Show Tissue segmentation on the T1w"]
        assert seg and seg[0].value

    def test_the_fallback_says_where_the_runs_came_from(self, project):
        _write_fmriprep(project / "derivatives")
        at = _run(INSPECT)
        assert any("read from fMRIPrep's own figures" in c for c in _captions(at))

    def test_a_project_with_neither_derivative_points_at_preprocessing(self, project):
        at = _run(INSPECT)
        assert not at.exception
        assert any("Run MRIQC first" in i.value for i in at.info)

    def test_measures_survive_a_project_with_no_fmriprep(self, project):
        """MRIQC ran, fMRIPrep did not — the numbers must still be reviewable."""
        _write_mriqc(project / "derivatives")
        at = _run(INSPECT)
        assert not at.exception
        assert _selectbox(at, "Run") is not None
        assert at.dataframe, "no measure table rendered"


# ---------------------------------------------------------------------------
# Scope travel — the mechanism the navigation rests on
# ---------------------------------------------------------------------------


class TestScopeTravel:
    def test_a_url_selects_the_run_it_names(self, full):
        """A sent inspection link is query parameters, so this is the hinge."""
        at = _run(INSPECT, run="sub-011_task-rest_run-1_bold")
        assert not at.exception
        assert _selectbox(at, "Run").value == "sub-011_task-rest_run-1_bold"

    def test_a_url_selects_the_modality_it_names(self, full):
        assert _selectbox(_run(INSPECT, modality="T1w"), "Modality").value == "T1w"

    def test_a_stale_url_falls_back_rather_than_raising(self, full):
        """A link to a run that has since been deleted must not break the page."""
        at = _run(INSPECT, run="sub-999_task-gone_run-9_bold")
        assert not at.exception
        assert _selectbox(at, "Run").value == "sub-010_task-rest_run-1_bold"

    def test_the_url_is_rewritten_to_match_the_selection(self, full):
        """So the page a reviewer is looking at is the page they can send."""
        at = _run(INSPECT)

        def param(name):
            # AppTest hands back the raw multi-value form; the browser sends one.
            value = at.query_params.get(name)
            return value[0] if isinstance(value, list) else value

        assert param("run") == "sub-010_task-rest_run-1_bold"
        assert param("modality") == "bold"


# ---------------------------------------------------------------------------
# The inspector: one run, every domain at once
# ---------------------------------------------------------------------------


class TestInspection:
    def test_every_domains_measures_share_one_table(self, full):
        """The four aspect tables concatenated — tSNR and motion side by side."""
        table = _run(INSPECT).dataframe[0].value
        rendered = table["Measure"].tolist()
        assert TSNR in rendered
        assert FD_MEAN in rendered
        # A bare IQM cannot be read; where it sits among these runs can.
        assert "Position in cohort" in table.columns

    def test_each_domains_review_question_is_stated(self, full):
        assert any("distortion corrected" in m.value for m in _run(INSPECT).markdown)

    def test_a_domain_with_nothing_for_this_modality_explains_itself(self, full):
        """Temporal has no number and no figure for a T1w — and says why."""
        _write_anat_mriqc(full / "derivatives")
        at = _run(INSPECT, modality="T1w")
        assert not at.exception
        assert any("single volume" in c for c in _captions(at))

    def test_the_verdict_is_not_gated_behind_reviewing_anything(self, full):
        """A reviewer seeing a wrecked run must be able to exclude it at once."""
        at = _run(INSPECT)
        exclude = [b for b in at.button if b.label == "Exclude"]
        assert exclude and not exclude[0].disabled

    def test_the_evidence_is_open_on_arrival(self, full):
        """Looking at the figures is this page's purpose, so they start shown."""
        at = _run(INSPECT)
        figure_toggles = [t for t in at.toggle if t.label.startswith("Show ")]
        assert figure_toggles, "no evidence toggles rendered"
        assert all(t.value for t in figure_toggles)
        # An open toggle really renders its figure's reading instructions.
        assert any(m.value.startswith("*Look for:*") for m in at.markdown)

    def test_the_tools_report_stays_gated_while_figures_are_open(self, full):
        """The 80 MB report embed must not inherit the figures' default-open."""
        at = _run(INSPECT, run="sub-010_task-rest_run-1_bold")
        report_toggles = [t for t in at.toggle if t.label.startswith("Open ")]
        assert report_toggles, "the tool's own report is not offered"
        assert all(t.value is False for t in report_toggles)
        assert not at.get("iframe")

    def test_recording_a_verdict_writes_it(self, full):
        at = _run(INSPECT)
        [b for b in at.button if b.label == "Keep"][0].click().run()
        assert not at.exception
        written = list(_decisions_dir(full).glob("*_decision.json"))
        assert len(written) == 1
        record = json.loads(written[0].read_text())["decisions"][-1]
        assert record["decision"] == "keep"
        assert record["reviewer"]

    def test_a_note_alone_is_not_a_verdict(self, full):
        """#17.10, pinned again on the page that now owns the verdict."""
        at = _run(INSPECT)
        [i for i in at.text_input if i.label == "Reason"][0].set_value("just a note").run()
        assert not at.exception
        assert not list(_decisions_dir(full).glob("*_decision.json"))

    def test_no_per_aspect_sign_off_is_offered(self, full):
        """One review interface per run — the collapse the rework exists for."""
        labels = [b.label for b in _run(INSPECT).button]
        assert "Reviewed — no concerns" not in labels
        assert "Reviewed — concerns" not in labels

    def test_a_historical_aspect_review_is_shown_read_only(self, full):
        """Dogfooding-era domain entries stay visible; nothing writes new ones."""
        from duckbrain.core import qc

        qc.save_decision(
            _decisions_dir(full),
            "sub-010_task-rest_run-1_bold",
            "concerns",
            reason="ringing",
            reviewer="ben",
            domain="artifact",
        )
        at = _run(INSPECT, run="sub-010_task-rest_run-1_bold")
        assert any("per-aspect layout" in c and "concerns" in c for c in _captions(at))

    def test_reviewed_aspects_do_not_become_a_verdict(self, full):
        """Four reviewed aspects must prompt for a verdict, never stand in for one.

        The settled rule (docs/qc-review-domains.md): derived readiness may be
        displayed, never recorded, and the verdict buttons are never gated.
        """
        from duckbrain.core import qc

        decisions = _decisions_dir(full)
        for key in ("signal", "temporal", "alignment", "artifact"):
            qc.save_decision(
                decisions, "sub-010_task-rest_run-1_bold", "reviewed", reviewer="ben", domain=key
            )
        at = _run(INSPECT, run="sub-010_task-rest_run-1_bold")
        assert not at.exception
        assert any("no verdict recorded" in c for c in _captions(at))
        keep = [b for b in at.button if b.label == "Keep"]
        assert keep and not keep[0].disabled

    def test_the_glossary_leads_each_entry_with_its_bold_label(self, full):
        assert any(m.value.startswith(f"**{TSNR}**") for m in _run(INSPECT).markdown)

    def test_a_domain_caveat_rides_with_the_numbers(self, full):
        """The sentinel/-1 and noise-estimate warnings must not hide in the glossary."""
        assert any("noise estimate" in c for c in _captions(_run(INSPECT)))


# ---------------------------------------------------------------------------
# The overview
# ---------------------------------------------------------------------------


class TestOverview:
    def test_it_lists_every_run(self, full):
        at = _run(OVERVIEW)
        assert not at.exception
        assert len(at.dataframe[0].value) == 2

    def test_the_at_a_glance_columns_are_here(self, full):
        """Group-level scanning wants the eye-catchers in the table itself.

        The comma-joined flagged-names column is gone deliberately: with the
        full measure set loaded it wrecked row height, and the names are one
        click away on the Inspect page — the count is the eye-catcher.
        """
        columns = list(_run(OVERVIEW).dataframe[0].value.columns)
        for col in ("Mean FD", "% high motion", "tSNR", "Flags"):
            assert col in columns, col
        assert "Flagged" not in columns

    def test_an_anat_table_carries_no_motion_columns(self, full):
        """Mean FD and tSNR are BOLD facts; an anat row must not show blanks."""
        _write_anat_mriqc(full / "derivatives")
        columns = list(_run(OVERVIEW, modality="T1w").dataframe[0].value.columns)
        assert "Flags" in columns
        assert "Mean FD" not in columns
        assert "tSNR" not in columns

    def test_no_per_run_interface_remains(self, full):
        """Verdicts, the report embed and the run picker all moved to Inspect."""
        at = _run(OVERVIEW)
        labels = [b.label for b in at.button]
        assert not {"Keep", "Exclude", "Investigate"} & set(labels)
        assert not any("tool's own report" in e.label for e in at.expander)
        assert _selectbox(at, "Run") is None

    def test_the_table_click_invites_the_inspector(self, full):
        """AppTest cannot click a dataframe row, so the invitation is what is
        testable here; the click itself is in TODO.md #30's eyeball queue and
        clicked_run_key is unit-tested in tests/test_qc_panels.py."""
        assert any("Click a row" in c for c in _captions(_run(OVERVIEW)))

    def test_the_outlier_slider_is_here_and_only_here(self, full):
        assert [s for s in _run(OVERVIEW).slider if "IQR" in s.label]
        assert not [s for s in _run(INSPECT).slider if "IQR" in s.label]

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
