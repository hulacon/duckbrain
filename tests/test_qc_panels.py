"""Tests for duckbrain.gui.qc_panels — the reusable QC review panels.

Driven with ``AppTest.from_function`` rather than through a page, the same way
``tests/test_gui_components.py`` drives ``directory_picker``. That is the whole
reason these panels live in a module instead of in a page script: a page is not
imported by any test, so logic put there is logic nothing covers.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.core.qc_domains import get_domain
from duckbrain.gui import qc_panels

FIGURE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    "<style>@keyframes flicker { 0% {opacity:1} 100% {opacity:0} }"
    ".f { animation: flicker 2s infinite; }</style>"
    '<rect class="f" width="10" height="10"/></svg>'
)


@pytest.fixture
def fmriprep(tmp_path):
    figures = tmp_path / "fmriprep" / "sub-010" / "figures"
    figures.mkdir(parents=True)
    for name in (
        "sub-010_task-rest_run-1_desc-sdc_bold.svg",
        "sub-010_task-rest_run-1_desc-coreg_bold.svg",
        "sub-010_dseg.svg",
    ):
        (figures / name).write_text(FIGURE_SVG)
    return tmp_path / "fmriprep"


def _script(root, run_key):
    """Run in a fresh module by AppTest, so it closes over nothing and imports its own."""
    from duckbrain.core.qc_domains import get_domain
    from duckbrain.gui import qc_panels

    qc_panels.evidence_viewer(root, get_domain("alignment"), run_key)


def _viewer(root: str, run_key: str = "sub-010_task-rest_run-1_bold"):
    return AppTest.from_function(
        _script, kwargs={"root": root, "run_key": run_key}, default_timeout=30
    ).run()


class TestEvidenceViewer:
    def test_nothing_is_loaded_on_arrival(self, fmriprep):
        """Megabyte-scale figures are a cost the reviewer chooses to spend."""
        at = _viewer(str(fmriprep))
        assert not at.exception
        assert at.toggle, "no figures were offered"
        assert all(t.value is False for t in at.toggle)

    def test_the_size_is_named_before_it_is_spent(self, fmriprep):
        at = _viewer(str(fmriprep))
        assert any("MB" in c.value for c in at.caption)

    def test_a_present_figure_is_offered_and_an_absent_one_is_explained(self, fmriprep):
        at = _viewer(str(fmriprep))
        captions = " ".join(c.value for c in at.caption)
        assert "Susceptibility distortion correction" in captions
        # No fieldmap-estimation figure was written, so the panel must say so
        # rather than quietly listing one fewer figure than the domain declares.
        assert "Fieldmap estimation" in captions
        assert "not on disk" in captions

    def test_showing_a_figure_states_what_to_look_for(self, fmriprep):
        at = _viewer(str(fmriprep))
        at.toggle[0].set_value(True).run()
        assert not at.exception
        assert any("Look for:" in m.value for m in at.markdown)

    def test_a_missing_tree_explains_every_figure_rather_than_rendering_nothing(self, tmp_path):
        at = _viewer(str(tmp_path / "absent"))
        assert not at.exception
        assert not at.toggle
        declared = get_domain("alignment").evidence_for("bold")
        captions = " ".join(c.value for c in at.caption)
        assert captions.count("not on disk") == len(declared)

    def test_the_animation_reaches_the_browser_intact(self, fmriprep):
        """The claim the whole per-figure viewer rests on, checked at the exit.

        Serving one figure instead of the 80 MB report is only worth doing if the
        before/after flicker survives, and the flicker is CSS *inside* the SVG.
        Streamlit inlines a local SVG as a base64 data URI, so this decodes what
        would actually be sent and looks for the animation in it — the earlier
        tests check the file on disk, which would still pass if the render path
        started stripping styles.
        """
        import base64

        at = _viewer(str(fmriprep))
        at.toggle[0].set_value(True).run()
        assert not at.exception

        images = [e for e in at._tree if e.type == "image"]
        assert images, "the figure was toggled on but no image was emitted"
        url = images[0].proto.imgs[0].url
        assert url.startswith("data:image/svg+xml"), (
            "the figure is no longer self-contained — a URL has to resolve, and "
            "under OnDemand's /node/<host>/<port>/ prefix that is the bug this "
            "avoided by construction"
        )
        payload = base64.b64decode(url.split(",", 1)[1]).decode("utf-8", "replace")
        assert "@keyframes" in payload and "animation:" in payload

    def test_it_reports_how_many_figures_it_found(self, fmriprep):
        """The return value is what a caller uses to decide whether to say more."""
        assert (
            qc_panels.evidence_viewer.__doc__
            and "Returns how many" in qc_panels.evidence_viewer.__doc__
        )

    def test_a_domain_with_no_figures_renders_nothing(self, fmriprep):
        def script():
            from duckbrain.core.qc_domains import get_domain
            from duckbrain.gui import qc_panels

            shown = qc_panels.evidence_viewer(
                "/nonexistent", get_domain("signal"), "sub-010_task-rest_bold"
            )
            import streamlit as st

            st.write(f"shown={shown}")

        at = AppTest.from_function(script, default_timeout=30).run()
        assert not at.exception
        assert not at.caption
        assert not at.toggle


@pytest.fixture
def reports(tmp_path):
    """An MRIQC report for one run and an fMRIPrep report for its subject.

    Both name a figure beside them, because the size the panel promises is the
    document *plus* what it draws on — a report counted at its own file size
    would understate the spend by an order of magnitude.
    """
    mriqc = tmp_path / "mriqc"
    (mriqc / "figures").mkdir(parents=True)
    (mriqc / "figures" / "carpet.svg").write_text(FIGURE_SVG)
    (mriqc / "sub-010_task-rest_run-1_bold.html").write_text(
        '<html><body><img src="./figures/carpet.svg"/></body></html>'
    )

    fmriprep = tmp_path / "fmriprep"
    (fmriprep / "sub-010" / "figures").mkdir(parents=True)
    (fmriprep / "sub-010" / "figures" / "dseg.svg").write_text(FIGURE_SVG)
    (fmriprep / "sub-010.html").write_text(
        '<html><body><object data="./sub-010/figures/dseg.svg"></object></body></html>'
    )
    return mriqc, fmriprep


def _reports_script(mriqc_dir, fmriprep_dir, run_key):
    import streamlit as st

    from duckbrain.gui import qc_panels

    st.write(f"offered={qc_panels.full_report_panel(mriqc_dir, fmriprep_dir, run_key)}")


def _report_panel(mriqc_dir, fmriprep_dir, run_key="sub-010_task-rest_run-1_bold"):
    return AppTest.from_function(
        _reports_script,
        kwargs={
            "mriqc_dir": str(mriqc_dir),
            "fmriprep_dir": str(fmriprep_dir),
            "run_key": run_key,
        },
        default_timeout=30,
    ).run()


class TestFullReportPanel:
    def test_nothing_is_loaded_on_arrival(self, reports):
        """~80 MB read into the server's RAM is a cost the reviewer chooses."""
        at = _report_panel(*reports)
        assert not at.exception
        assert at.toggle, "no report was offered"
        assert all(t.value is False for t in at.toggle)
        assert not at.get("iframe")

    def test_the_size_is_named_before_it_is_spent(self, reports):
        at = _report_panel(*reports)
        assert all("MB" in c.value for c in at.caption)

    def test_the_size_counts_the_figures_not_just_the_document(self, reports):
        """A report is small; what it draws on is not. Naming the file's own size
        would promise 0.0 MB and then spend fifteen."""
        mriqc, _ = reports
        report = mriqc / "sub-010_task-rest_run-1_bold.html"
        assert qc_panels._payload_bytes_cached.__wrapped__(str(report), (0.0, 0)) == (
            report.stat().st_size + len(FIGURE_SVG)
        )

    def test_both_tools_are_offered_for_one_run(self, reports):
        at = _report_panel(*reports)
        assert at.markdown[-1].value == "offered=2"
        labels = " ".join(t.label for t in at.toggle)
        assert "MRIQC" in labels and "fMRIPrep" in labels

    def test_the_session_report_beats_the_subject_one(self, reports):
        """fMRIPrep keys by subject *or* by subject and session. Matching the
        looser key when the tighter file exists hands over another session."""
        mriqc, fmriprep = reports
        (fmriprep / "sub-010_ses-02.html").write_text("<html><body>ses 2</body></html>")
        at = _report_panel(mriqc, fmriprep, run_key="sub-010_ses-02_task-rest_run-1_bold")
        assert any("sub-010_ses-02" in t.label for t in at.toggle)
        assert not any(t.label.endswith("sub-010") for t in at.toggle)

    def test_a_run_with_no_report_is_told_so(self, tmp_path):
        at = _report_panel(tmp_path / "mriqc", tmp_path / "fmriprep")
        assert not at.exception
        assert at.markdown[-1].value == "offered=0"
        assert not at.toggle
        assert any("Neither tool has written" in c.value for c in at.caption)

    def test_opening_one_embeds_the_report_with_its_figure_served(self, reports):
        """The point of the panel, end to end: the document reaches the browser
        and the figure it names is a URL the app really serves."""
        at = _report_panel(*reports)
        at.toggle[0].set_value(True).run()
        assert not at.exception
        (frame,) = at.get("iframe")
        assert "./figures/carpet.svg" not in frame.proto.srcdoc
        assert "/media/" in frame.proto.srcdoc


class TestFmriprepReportKeys:
    def test_a_sessionless_run_asks_only_for_the_subject(self):
        assert qc_panels._fmriprep_report_keys("sub-015_task-rest_run-1_bold") == ["sub-015"]

    def test_a_session_run_asks_for_both_most_specific_first(self):
        assert qc_panels._fmriprep_report_keys("sub-015_ses-01_task-rest_bold") == [
            "sub-015_ses-01",
            "sub-015",
        ]

    def test_a_key_with_no_subject_asks_for_nothing(self):
        """Rather than building ``sub-None`` and globbing for it."""
        assert qc_panels._fmriprep_report_keys("bold") == []


class TestDomainIntro:
    def test_it_states_the_review_question(self):
        def script():
            from duckbrain.core.qc_domains import get_domain
            from duckbrain.gui import qc_panels

            qc_panels.domain_intro(get_domain("temporal"), "bold", n_measures=3)

        at = AppTest.from_function(script, default_timeout=30).run()
        assert not at.exception
        assert any("hold still" in m.value for m in at.markdown)

    def test_an_empty_domain_explains_itself_rather_than_going_blank(self):
        """The silent-degradation rule, at the panel boundary this time."""

        def script():
            from duckbrain.core.qc_domains import get_domain
            from duckbrain.gui import qc_panels

            qc_panels.domain_intro(get_domain("temporal"), "T1w", n_measures=0)

        at = AppTest.from_function(script, default_timeout=30).run()
        assert not at.exception
        assert any("single volume" in i.value for i in at.info)

    def test_a_domain_caveat_is_shown(self):
        def script():
            from duckbrain.core.qc_domains import get_domain
            from duckbrain.gui import qc_panels

            qc_panels.domain_intro(get_domain("alignment"), "bold", n_measures=0)

        at = AppTest.from_function(script, default_timeout=30).run()
        assert not at.exception
        assert any("MRIQC's own" in c.value for c in at.caption)


class TestSizeNote:
    @pytest.mark.parametrize("n,expected", [(1, "1 figure"), (2, "2 figures")])
    def test_it_agrees_with_itself_about_number(self, n, expected):
        assert expected in qc_panels._size_note(1_000_000, n)

    def test_bytes_are_reported_in_megabytes(self):
        assert "1.5 MB" in qc_panels._size_note(1_500_000, 1)


def test_the_panels_module_is_importable_without_a_runtime():
    """It must be safe to import from a test or a script, not only from a page."""
    assert Path(qc_panels.__file__).exists()


# ---------------------------------------------------------------------------
# The metrics cache
# ---------------------------------------------------------------------------

import json
import os


class TestMetricsCache:
    """A second MRIQC run into the same directory must reach the page.

    Driven by calling the cached function directly rather than under ``AppTest``:
    the staleness reproduces in bare Python, and putting a page in between only
    adds ways for this to pass for the wrong reason — ``scope_bar`` turns an empty
    frame into a warning path.
    """

    def test_a_rerun_of_mriqc_is_not_served_the_previous_numbers(self, tmp_path):
        mriqc = tmp_path / "mriqc"
        mriqc.mkdir()
        metrics = mriqc / "sub-010_task-rest_run-1_bold.json"
        metrics.write_text(json.dumps({"bids_name": metrics.stem, "tsnr": 40.0}))

        # The cache is process-wide, and tmp_path keys differ per test only by
        # accident of the path. Clearing makes that independent of luck.
        qc_panels._load_metrics.clear()
        before = qc_panels._fingerprint_of(mriqc, "*_bold.json")
        first = qc_panels._load_metrics(str(mriqc), "bold", before)
        assert first["tsnr"].tolist() == [40.0]

        metrics.write_text(json.dumps({"bids_name": metrics.stem, "tsnr": 41.0}))
        # Moved explicitly rather than left to the rewrite: an overwrite inside
        # the same second can leave st_mtime exactly where it was, and with the
        # file count unchanged the mtime is the only half of the fingerprint that
        # can move at all.
        moved = metrics.stat().st_mtime + 10
        os.utime(metrics, (moved, moved))

        after = qc_panels._fingerprint_of(mriqc, "*_bold.json")
        assert after != before, "the fingerprint did not move — this tests nothing"

        # The value and not the row count: a count survives every rewrite that
        # does not add a file, which is what an ordinary MRIQC re-run is.
        second = qc_panels._load_metrics(str(mriqc), "bold", after)
        assert second["tsnr"].tolist() == [41.0], (
            "served the previous MRIQC run: the fingerprint is not reaching the cache key"
        )
