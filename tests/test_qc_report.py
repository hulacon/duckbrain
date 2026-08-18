"""Tests for duckbrain.core.qc_report — the QC report renderer.

This is the logic that used to live inside ``5_QC_Dashboard.py``, where nothing
could import it. Moving it here is what makes these tests possible at all.
"""

import json

import pandas as pd
import pytest

from duckbrain.core import qc, qc_report


@pytest.fixture
def metrics_df():
    """Two sessionless BOLD runs, the second an outlier on tsnr."""
    return pd.DataFrame(
        [
            {
                "sub": "015",
                "task": "rest",
                "run": "1",
                "fd_mean": 0.08,
                "tsnr": 43.0,
                "is_outlier": False,
                "tsnr_outlier": False,
            },
            {
                "sub": "016",
                "task": "rest",
                "run": "1",
                "fd_mean": 0.51,
                "tsnr": 4.0,
                "is_outlier": True,
                "tsnr_outlier": True,
            },
        ]
    )


IQMS = ["fd_mean", "tsnr"]


class TestRunKey:
    def test_omits_absent_entities(self):
        """A sessionless project must not produce an empty ``ses-`` segment."""
        key = qc_report.build_run_key({"sub": "015", "task": "rest", "run": "1"}, "bold")
        assert key == "sub-015_task-rest_run-1_bold"

    def test_includes_session_when_present(self):
        key = qc_report.build_run_key({"sub": "03", "ses": "05", "task": "enc", "run": "2"}, "bold")
        assert key == "sub-03_ses-05_task-enc_run-2_bold"

    def test_matches_the_key_decisions_are_stored_under(self, tmp_path, metrics_df):
        """Report and decision store must agree, or every decision reads as pending."""
        row = metrics_df.iloc[0]
        key = qc_report.build_run_key(row, "bold")
        qc.save_decision(tmp_path, key, "keep", reviewer="someone")
        assert key in qc.load_decisions(tmp_path)

    def test_nan_entity_is_dropped(self):
        key = qc_report.build_run_key({"sub": "015", "run": float("nan")}, "T1w")
        assert key == "sub-015_T1w"


class TestMriqcReportDiscovery:
    def test_finds_reports_and_keys_them_by_run(self, tmp_path):
        (tmp_path / "sub-015_task-rest_run-1_bold.html").write_text("x")
        (tmp_path / "sub-015_T1w.html").write_text("x")
        found = qc_report.find_mriqc_reports(tmp_path, "bold")
        assert found == {"sub-015_task-rest_run-1_bold": "sub-015_task-rest_run-1_bold.html"}

    def test_missing_directory_yields_no_links(self, tmp_path):
        assert qc_report.find_mriqc_reports(tmp_path / "nope", "bold") == {}


class TestBuildRunRows:
    def test_merges_metrics_motion_decisions_and_reports(self, metrics_df):
        motion = pd.DataFrame(
            [{"sub": "015", "task": "rest", "run": "1", "mean_fd": 0.08, "pct_high_motion": 1.2}]
        )
        decisions = {
            "sub-015_task-rest_run-1_bold": {
                "latest": {"decision": "keep", "reviewer": "ben", "reason": "fine"}
            }
        }
        reports = {"sub-015_task-rest_run-1_bold": "sub-015_task-rest_run-1_bold.html"}

        rows = qc_report.build_run_rows(
            metrics_df, "bold", IQMS, motion_df=motion, decisions=decisions, reports=reports
        )
        assert len(rows) == 2
        first, second = rows
        assert first["motion"]["mean_fd"] == 0.08
        assert first["decision"] == "keep" and first["reviewer"] == "ben"
        assert first["report"].endswith(".html")
        assert second["motion"] is None and second["report"] == ""

    def test_flags_the_metrics_that_tripped_the_fence(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        assert rows[0]["flagged_metrics"] == []
        assert rows[1]["flagged_metrics"] == ["tsnr"]

    def test_missing_iqm_becomes_none_not_nan(self):
        df = pd.DataFrame([{"sub": "015", "task": "rest", "fd_mean": float("nan")}])
        rows = qc_report.build_run_rows(df, "bold", IQMS)
        assert rows[0]["iqms"]["fd_mean"] is None


class TestRenderReport:
    def test_never_emits_a_file_scheme_link(self, metrics_df):
        """A file:// link is silently blocked when the page is served over HTTP.

        That is the failure this whole delivery split exists to avoid: the link
        does not error, it does nothing. mmmdata's dashboard has 837 of them.
        """
        rows = qc_report.build_run_rows(
            metrics_df, "bold", IQMS, reports={"sub-015_task-rest_run-1_bold": "r.html"}
        )
        html = qc_report.render_report(rows, "bold", IQMS)
        # Plotly's own bundle mentions file:// internally; our markup must not.
        links = [seg.split('"')[0] for seg in html.split('href="')[1:]]
        assert not [link for link in links if link.startswith("file:")]

    def test_report_links_are_relative_to_the_written_location(self, metrics_df):
        rows = qc_report.build_run_rows(
            metrics_df, "bold", IQMS, reports={"sub-015_task-rest_run-1_bold": "r.html"}
        )
        html = qc_report.render_report(rows, "bold", IQMS)
        # From the constant, not retyped: the link depth follows REPORT_SUBDIR,
        # and this test exists to prove the two stay in step.
        assert f'href="{qc_report.MRIQC_REPORT_BASE}/r.html"' in html

    def test_embeds_guidance_for_every_rendered_column(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        html = qc_report.render_report(rows, "bold", IQMS)
        assert 'id="how-to-review"' in html
        assert 'id="measure-guidance"' in html
        for metric in IQMS:
            assert f'id="guidance-{metric}"' in html
            assert f'href="#guidance-{metric}"' in html

    def test_motion_guidance_appears_only_when_motion_does(self, metrics_df):
        without = qc_report.render_report(
            qc_report.build_run_rows(metrics_df, "bold", IQMS), "bold", IQMS
        )
        assert 'id="guidance-mean_fd"' not in without

        motion = pd.DataFrame([{"sub": "015", "task": "rest", "run": "1", "mean_fd": 0.08}])
        with_motion = qc_report.render_report(
            qc_report.build_run_rows(metrics_df, "bold", IQMS, motion_df=motion), "bold", IQMS
        )
        assert 'id="guidance-mean_fd"' in with_motion
        assert 'id="motion-overview"' in with_motion

    def test_outlier_detail_only_when_there_are_outliers(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        assert 'id="outlier-detail"' in qc_report.render_report(rows, "bold", IQMS)

        clean = [dict(r, is_outlier=False, flagged_metrics=[]) for r in rows]
        assert 'id="outlier-detail"' not in qc_report.render_report(clean, "bold", IQMS)

    def test_escapes_values_that_came_from_a_file(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        rows[0]["task"] = "<script>alert(1)</script>"
        html = qc_report.render_report(rows, "bold", IQMS)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_renders_with_no_runs_at_all(self):
        html = qc_report.render_report([], "bold", IQMS)
        assert "No runs." in html


class TestSignOffAccounting:
    """A decision counts only when an identifiable person made it."""

    def _rows(self, metrics_df, latest):
        return qc_report.build_run_rows(
            metrics_df,
            "bold",
            IQMS,
            decisions={"sub-015_task-rest_run-1_bold": {"latest": latest}},
        )

    def test_named_reviewer_counts_as_signed_off(self, metrics_df):
        rows = self._rows(metrics_df, {"decision": "keep", "reviewer": "ben"})
        html = qc_report.render_report(rows, "bold", IQMS)
        assert '<div class="card card-ok">1<span>Signed off</span></div>' in html
        assert ">KEEP<" in html

    def test_verdict_with_no_reviewer_reads_as_pending_and_is_surfaced(self, metrics_df):
        """Every decision duckbrain has written so far has an empty reviewer.

        They must be visible as unattributed rather than promoted to a sign-off
        they never were — the record cannot be attributed after the fact.
        """
        rows = self._rows(metrics_df, {"decision": "keep", "reviewer": ""})
        html = qc_report.render_report(rows, "bold", IQMS)
        assert '<div class="card card-ok">0<span>Signed off</span></div>' in html
        assert "unattributed: keep" in html
        assert "cannot be attributed" in html

    def test_no_record_is_simply_pending(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        html = qc_report.render_report(rows, "bold", IQMS)
        assert "unattributed" not in html
        assert ">PENDING<" in html


class TestFmriprepResolution:
    def test_one_tree_regardless_of_use_nordic(self, tmp_path):
        """duckbrain writes fMRIPrep to one directory; there is no nordic variant.

        mmmdata keeps ``fmriprep`` and ``fmriprep_nordic`` side by side, so the
        migration plan expected a path bug here. duckbrain's ``core.fmriprep``
        writes to ``<derivatives>/fmriprep`` unconditionally, so choosing a path
        by ``use_nordic`` would point at a directory that never exists.
        """
        config = {"paths": {"derivatives_dir": str(tmp_path)}, "nordic": {"use_nordic": True}}
        assert qc_report.resolve_fmriprep_dir(config) == tmp_path / "fmriprep"
        config["nordic"]["use_nordic"] = False
        assert qc_report.resolve_fmriprep_dir(config) == tmp_path / "fmriprep"

    def _config_with_raw_link(self, tmp_path, raw_link):
        root = tmp_path / "fmriprep"
        root.mkdir(parents=True, exist_ok=True)
        (root / "dataset_description.json").write_text(
            json.dumps({"Name": "f", "DatasetLinks": {"raw": raw_link}})
        )
        return {"paths": {"derivatives_dir": str(tmp_path)}}

    def test_variant_comes_from_provenance_not_config(self, tmp_path):
        config = self._config_with_raw_link(tmp_path, "../nordic/bids_format")
        # Config says raw; the artifact says NORDIC. The artifact wins.
        config["nordic"] = {"use_nordic": False}
        assert qc_report.fmriprep_input_variant(config) == "nordic"

    def test_variant_is_raw_for_a_plain_bids_link(self, tmp_path):
        config = self._config_with_raw_link(tmp_path, "../..")
        assert qc_report.fmriprep_input_variant(config) == "raw"

    def test_variant_unknown_when_there_is_no_derivative(self, tmp_path):
        assert (
            qc_report.fmriprep_input_variant({"paths": {"derivatives_dir": str(tmp_path)}})
            == "unknown"
        )

    def test_variant_is_stated_in_the_report(self, metrics_df):
        motion = pd.DataFrame([{"sub": "015", "task": "rest", "run": "1", "mean_fd": 0.08}])
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS, motion_df=motion)
        html = qc_report.render_report(rows, "bold", IQMS, fmriprep_variant="nordic")
        assert "NORDIC-denoised data" in html

    def test_a_nordic_report_says_the_iqms_are_from_raw_data(self, metrics_df):
        """The half of the table that was never labelled.

        MRIQC always reads raw BIDS, so on a NORDIC project the IQM columns and
        the motion columns describe different images. Only the motion side said
        so, and a reader who knows the project uses NORDIC will assume the IQMs
        do too — the more surprising claim was the unstated one.
        """
        motion = pd.DataFrame([{"sub": "015", "task": "rest", "run": "1", "mean_fd": 0.08}])
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS, motion_df=motion)
        html = qc_report.render_report(rows, "bold", IQMS, fmriprep_variant="nordic")
        assert "MRIQC IQMs come from the <strong>raw</strong> BIDS data" in html

    def test_a_raw_report_does_not_raise_a_distinction_that_is_not_there(self, metrics_df):
        """Both halves are raw, so saying they differ would be noise — and wrong."""
        motion = pd.DataFrame([{"sub": "015", "task": "rest", "run": "1", "mean_fd": 0.08}])
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS, motion_df=motion)
        html = qc_report.render_report(rows, "bold", IQMS, fmriprep_variant="raw")
        assert "describe different images" not in html


class TestWriteReport:
    def test_writes_beside_the_other_derivative_reports(self, tmp_path):
        path = qc_report.write_report("<p>hi</p>", tmp_path, "qc_report_all_bold.html")
        assert path == tmp_path / qc_report.REPORT_SUBDIR / "qc_report_all_bold.html"
        assert path.read_text() == "<p>hi</p>"

    def test_relative_links_resolve_from_where_it_lands(self, tmp_path):
        """The link the report emits must reach the real MRIQC report on disk.

        Resolved against the file's actual location rather than asserted as a
        string, which is what caught the report moving deeper into
        ``derivatives/duckbrain/qc/reports/``: a relative link with the wrong
        number of levels renders as ordinary text and says nothing.
        """
        mriqc = tmp_path / "mriqc"
        mriqc.mkdir()
        (mriqc / "r.html").write_text("report")
        path = qc_report.write_report("x", tmp_path, "qc.html")
        link = path.parent / f"{qc_report.MRIQC_REPORT_BASE}/r.html"
        assert link.resolve().read_text() == "report"

    def test_filename_distinguishes_scope(self):
        assert qc_report.report_filename("bold") == "qc_report_all_bold.html"
        assert qc_report.report_filename("bold", "015") == "qc_report_sub-015_bold.html"


class TestMriqcLayouts:
    """``load_mriqc_metrics`` must not depend on the dataset having sessions."""

    def _write(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))

    def test_sessionless_layout_is_found(self, tmp_path):
        """The layout of divatten_beta, on which this previously found nothing.

        Every glob required a ``ses-`` level, so a sessionless project loaded
        zero runs and the page advised running MRIQC — which had already run.
        """
        self._write(tmp_path / "sub-015/func/sub-015_task-rest_run-1_bold.json", {"tsnr": 43.0})
        df = qc.load_mriqc_metrics(tmp_path, "bold")
        assert len(df) == 1
        assert df.iloc[0]["sub"] == "015"
        assert df.iloc[0]["tsnr"] == 43.0

    def test_sessioned_layout_still_found(self, tmp_path):
        self._write(
            tmp_path / "sub-03/ses-05/func/sub-03_ses-05_task-enc_bold.json", {"tsnr": 40.0}
        )
        df = qc.load_mriqc_metrics(tmp_path, "bold")
        assert len(df) == 1
        assert df.iloc[0]["ses"] == "05"

    def test_flat_layout_still_found(self, tmp_path):
        self._write(tmp_path / "sub-015_task-rest_bold.json", {"tsnr": 41.0})
        assert len(qc.load_mriqc_metrics(tmp_path, "bold")) == 1

    def test_companion_timeseries_json_is_not_read_as_a_run(self, tmp_path):
        self._write(tmp_path / "sub-015/func/sub-015_task-rest_bold.json", {"tsnr": 43.0})
        self._write(tmp_path / "sub-015/func/sub-015_task-rest_timeseries.json", {"junk": 1})
        df = qc.load_mriqc_metrics(tmp_path, "bold")
        assert len(df) == 1
        assert "junk" not in df.columns

    def test_modalities_do_not_bleed_into_each_other(self, tmp_path):
        self._write(tmp_path / "sub-015/func/sub-015_task-rest_bold.json", {"tsnr": 43.0})
        self._write(tmp_path / "sub-015/anat/sub-015_T1w.json", {"cjv": 0.6})
        assert len(qc.load_mriqc_metrics(tmp_path, "bold")) == 1
        assert len(qc.load_mriqc_metrics(tmp_path, "T1w")) == 1

    def test_unreadable_json_is_skipped_not_fatal(self, tmp_path):
        (tmp_path / "sub-015_task-rest_bold.json").write_text("{not json")
        self._write(tmp_path / "sub-016_task-rest_bold.json", {"tsnr": 43.0})
        assert len(qc.load_mriqc_metrics(tmp_path, "bold")) == 1

    def test_file_without_a_subject_entity_is_ignored(self, tmp_path):
        self._write(tmp_path / "group_bold.json", {"tsnr": 1.0})
        assert qc.load_mriqc_metrics(tmp_path, "bold").empty


# ---------------------------------------------------------------------------
# Column attribution: which tool produced which numbers
# ---------------------------------------------------------------------------


def _rows(with_motion=True, n=2):
    """Run rows with or without fMRIPrep motion attached."""
    df = pd.DataFrame(
        [
            {"sub": f"01{i}", "task": "rest", "run": "1", "fd_mean": 0.1, "tsnr": 40.0}
            for i in range(n)
        ]
    )
    motion = None
    if with_motion:
        motion = pd.DataFrame(
            [
                {
                    "sub": f"01{i}",
                    "task": "rest",
                    "run": "1",
                    "mean_fd": 0.2,
                    "pct_high_motion": 3.0,
                }
                for i in range(n)
            ]
        )
    return qc_report.build_run_rows(df, "bold", ["fd_mean", "tsnr"], motion_df=motion)


class TestSourceAttribution:
    """MRIQC's ``fd_mean`` and fMRIPrep's ``mean_fd`` sit in the same row, are
    near-anagrams, and measure the same quantity on two different images. The
    table has to say which is which."""

    def test_both_tools_are_named_over_their_columns(self):
        html = qc_report.render_report(_rows(), "bold", ["fd_mean", "tsnr"])
        assert 'class="src src-mriqc" colspan="2"' in html
        assert 'class="src src-fmriprep" colspan="2"' in html
        assert qc_report.MRIQC_SOURCE in html and qc_report.FMRIPREP_SOURCE in html

    def test_the_two_similar_columns_both_appear_and_are_attributed(self):
        html = qc_report.render_report(_rows(), "bold", ["fd_mean", "tsnr"])
        assert "fd_mean" in html and "mean_fd" in html
        # The MRIQC span covers exactly the IQMs, so mean_fd cannot fall under it.
        assert 'colspan="2"' in html

    def test_no_fmriprep_span_when_there_is_no_motion(self):
        html = qc_report.render_report(_rows(with_motion=False), "bold", ["fd_mean", "tsnr"])
        # Assert on the header cell, not the class name — the class also appears
        # in the stylesheet, where its presence means nothing.
        assert 'class="src src-fmriprep"' not in html
        assert 'class="src src-mriqc"' in html

    def test_sorting_is_bound_to_the_column_name_row_only(self):
        """The source row's cells span columns, so their index is not a column
        index — sorting on them would sort the wrong column."""
        html = qc_report.render_report(_rows(), "bold", ["fd_mean", "tsnr"])
        assert ".qc-table thead tr:last-child th" in html
        assert "document.querySelectorAll('.qc-table th')" not in html


class TestDescribeMotionSource:
    def test_anat_says_fmriprep_contributes_nothing_here(self, tmp_path):
        state, sentence = qc_report.describe_motion_source(tmp_path, _rows(), "T1w")
        assert state == "not-applicable"
        assert "MRIQC" in sentence

    def test_no_fmriprep_directory_at_all(self, tmp_path):
        state, sentence = qc_report.describe_motion_source(
            tmp_path / "fmriprep", _rows(with_motion=False), "bold"
        )
        assert state == "absent"
        assert "has not run" in sentence

    def test_fmriprep_ran_but_wrote_no_confounds(self, tmp_path):
        """Live on divatten_beta_v2: 65 MRIQC runs, zero confounds files, and the
        dashboard showed no motion columns without saying why."""
        (tmp_path / "sub-010" / "func").mkdir(parents=True)
        (tmp_path / "sub-010" / "func" / "sub-010_desc-preproc_bold.nii.gz").touch()
        state, sentence = qc_report.describe_motion_source(
            tmp_path, _rows(with_motion=False), "bold"
        )
        assert state == "no-confounds"
        assert "absent, not zero" in sentence

    def test_confounds_exist_but_match_no_run(self, tmp_path):
        func = tmp_path / "sub-999" / "func"
        func.mkdir(parents=True)
        (func / "sub-999_task-other_run-1_desc-confounds_timeseries.tsv").touch()
        state, sentence = qc_report.describe_motion_source(
            tmp_path, _rows(with_motion=False), "bold"
        )
        assert state == "unmatched"
        assert "none matched" in sentence

    def test_some_runs_have_motion_and_some_do_not(self, tmp_path):
        func = tmp_path / "sub-010" / "func"
        func.mkdir(parents=True)
        (func / "sub-010_task-rest_run-1_desc-confounds_timeseries.tsv").touch()
        runs = _rows(n=2)
        runs[1]["motion"] = None
        state, sentence = qc_report.describe_motion_source(tmp_path, runs, "bold")
        assert state == "partial"
        assert "missing evidence, not good motion" in sentence

    def test_complete_says_nothing(self, tmp_path):
        state, sentence = qc_report.describe_motion_source(tmp_path, _rows(), "bold")
        assert state == "complete"
        assert sentence == ""


class TestMotionStatusBanner:
    def test_a_shortfall_is_stated_in_the_report(self):
        html = qc_report.render_report(
            _rows(with_motion=False),
            "bold",
            ["fd_mean", "tsnr"],
            motion_status=("no-confounds", "fMRIPrep produced output but no confounds files."),
        )
        assert "note-warn" in html
        assert "no confounds files" in html

    def test_a_complete_run_gets_no_banner(self):
        html = qc_report.render_report(
            _rows(), "bold", ["fd_mean", "tsnr"], motion_status=("complete", "")
        )
        assert '<p class="source-note' not in html

    def test_a_blank_motion_cell_reads_as_missing_not_as_zero(self):
        runs = _rows(n=2)
        runs[1]["motion"] = None
        html = qc_report.render_report(runs, "bold", ["fd_mean", "tsnr"])
        assert "cell-absent" in html
        assert "No fMRIPrep confounds for this run" in html


class TestIqmFigure:
    """The shared IQM figure both delivery paths render — build_iqm_figure."""

    def _figure(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        return qc_report.build_iqm_figure(rows, IQMS, "bold")

    def test_every_point_carries_its_run_key_for_the_click_through(self, metrics_df):
        """The live overview maps a clicked point to a run through customdata —
        a trace without it would render fine and click dead."""
        fig = self._figure(metrics_df)
        keys = {"sub-015_task-rest_run-1_bold", "sub-016_task-rest_run-1_bold"}
        scatters = [t for t in fig.data if t.type == "scatter"]
        assert scatters
        for trace in scatters:
            assert set(trace.customdata) <= keys
        # Each charted measure offers every run as a clickable point.
        assert len([t for t in scatters if set(t.customdata) == keys]) == len(IQMS)

    def test_the_flagged_marker_is_clickable_too(self, metrics_df):
        fig = self._figure(metrics_df)
        outliers = [t for t in fig.data if t.name == "outlier"]
        assert len(outliers) == 1  # only tsnr tripped the fence
        assert tuple(outliers[0].customdata) == ("sub-016_task-rest_run-1_bold",)

    def test_box_points_stay_off(self, metrics_df):
        """Box points do not emit click events in plotly.js; showing them would
        double-draw every run and leave half the dots dead to a click."""
        fig = self._figure(metrics_df)
        boxes = [t for t in fig.data if t.type == "box"]
        assert len(boxes) == len(IQMS)
        assert all(t.boxpoints is False for t in boxes)

    def test_nothing_to_chart_returns_none(self, metrics_df):
        assert qc_report.build_iqm_figure([], IQMS, "bold") is None
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        for r in rows:
            r["iqms"] = {}
        assert qc_report.build_iqm_figure(rows, IQMS, "bold") is None

    def test_the_export_still_wraps_the_same_figure(self, metrics_df):
        rows = qc_report.build_run_rows(metrics_df, "bold", IQMS)
        html = qc_report.render_report(rows, "bold", IQMS)
        # The clickable points' run keys travel into the export's chart data too.
        assert "sub-016_task-rest_run-1_bold" in html

    def test_jitter_spreads_shared_centers_inside_their_band(self):
        centers = [0.0, 0.0, 0.0, 1.0]
        jittered = qc_report._jitter_positions(centers)
        assert jittered[3] == 1.0  # a lone point stays put
        assert all(abs(j - c) <= 0.2 for j, c in zip(jittered, centers, strict=True))
        assert len(set(jittered[:3])) == 3  # points sharing a center spread out
