"""Tests for serving a tool-produced HTML report from inside the app.

The bug these pin: an MRIQC report references its figures relatively, duckbrain
served no project files at all, and the QC page embedded the report in a
sandboxed iframe with no location of its own — so every "View report" link and
every figure resolved to nothing, silently. See ``core.report_embed``.
"""

from pathlib import Path

import pandas as pd
import pytest

from duckbrain.core import qc_report
from duckbrain.core.report_embed import (
    is_local_asset,
    local_asset_paths,
    payload_bytes,
    resolve_asset,
    rewrite_asset_links,
)

#: Trimmed from a real MRIQC bold report — the CDN tags and the img tags are
#: verbatim in shape, which is what makes the "leave the CDN alone" case real.
#: Wrapped only to stay inside the line limit; the shape is what matters.
MRIQC_HTML = (
    "<html><head>\n"
    '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.2.3/dist/css/'
    'bootstrap.min.css" rel="stylesheet">\n'
    '<script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>\n'
    "</head><body>\n"
    '<a href="#summary">Summary</a>\n'
    '<img class="svg-reportlet" src="./sub-010/figures/'
    'sub-010_desc-carpet_bold.svg" style="width: 100%" />\n'
    '<img class="svg-reportlet" src="./sub-010/figures/'
    'sub-010_desc-mean_bold.svg" style="width: 100%" />\n'
    "</body></html>"
)


#: Verbatim in shape from a real fMRIPrep subject report. Every animated
#: reportlet appears exactly like this: an ``<object data=…>`` that draws it, an
#: ``<a href=…>`` to the same file that opens it in a tab, and Bootstrap's
#: ``data-bs-*`` attributes nearby, which must not be mistaken for asset
#: references.
FMRIPREP_HTML = (
    "<html><body>\n"
    '<button data-bs-toggle="collapse" data-bs-target="#sdc">SDC</button>\n'
    '<object class="svg-reportlet" type="image/svg+xml" '
    'data="./sub-010/figures/sub-010_task-rest_run-1_desc-sdc_bold.svg" style="">\n'
    "</object>\n"
    '<a href="./sub-010/figures/sub-010_task-rest_run-1_desc-sdc_bold.svg" '
    'target="_blank">Open</a>\n'
    '<img class="svg-reportlet" src="./sub-010/figures/sub-010_dseg.svg" />\n'
    "</body></html>"
)


@pytest.fixture
def report(tmp_path):
    """An MRIQC-shaped report directory: one HTML, two figures beside it."""
    figures = tmp_path / "sub-010" / "figures"
    figures.mkdir(parents=True)
    (figures / "sub-010_desc-carpet_bold.svg").write_text("<svg/>")
    (figures / "sub-010_desc-mean_bold.svg").write_text("<svg/>")
    path = tmp_path / "sub-010_task-rest_run-1_bold.html"
    path.write_text(MRIQC_HTML)
    return path


@pytest.fixture
def fmriprep_report(tmp_path):
    """An fMRIPrep-shaped report: one animated ``<object>``, one plain ``<img>``."""
    figures = tmp_path / "sub-010" / "figures"
    figures.mkdir(parents=True)
    (figures / "sub-010_task-rest_run-1_desc-sdc_bold.svg").write_text("<svg/>")
    (figures / "sub-010_dseg.svg").write_text("<svg/>")
    path = tmp_path / "sub-010.html"
    path.write_text(FMRIPREP_HTML)
    return path


class TestIsLocalAsset:
    @pytest.mark.parametrize(
        "url",
        [
            "https://cdn.jsdelivr.net/npm/bootstrap/x.css",
            "http://example.org/x.js",
            "//code.jquery.com/jquery.js",
            "data:image/png;base64,AAAA",
            "#summary",
            "/media/abc.svg",
            "",
        ],
    )
    def test_not_local(self, url):
        assert not is_local_asset(url)

    @pytest.mark.parametrize("url", ["./sub-010/figures/x.svg", "sub-010/figures/x.svg", "x.svg"])
    def test_local(self, url):
        assert is_local_asset(url)


class TestResolveAsset:
    def test_resolves_a_file_beside_the_report(self, report):
        got = resolve_asset(report.parent, "./sub-010/figures/sub-010_desc-carpet_bold.svg")
        assert got == (report.parent / "sub-010/figures/sub-010_desc-carpet_bold.svg").resolve()

    def test_missing_file_is_not_servable(self, report):
        assert resolve_asset(report.parent, "./sub-010/figures/gone.svg") is None

    def test_a_directory_is_not_servable(self, report):
        assert resolve_asset(report.parent, "./sub-010/figures") is None

    def test_query_and_fragment_are_stripped(self, report):
        got = resolve_asset(report.parent, "./sub-010/figures/sub-010_desc-mean_bold.svg?v=2#top")
        assert got is not None and got.name == "sub-010_desc-mean_bold.svg"

    def test_escaping_the_report_tree_is_refused(self, report, tmp_path):
        """A resolver turns HTML text into a file the server will read and send."""
        secret = tmp_path.parent / "secret.svg"
        secret.write_text("<svg/>")
        assert resolve_asset(report.parent, "../secret.svg") is None
        assert resolve_asset(report.parent, str(secret)) is None


class TestRewriteAssetLinks:
    def test_local_figures_are_repointed(self, report):
        html, unresolved = rewrite_asset_links(
            report.read_text(), report.parent, lambda p: f"/media/{p.name}"
        )
        assert unresolved == []
        assert 'src="/media/sub-010_desc-carpet_bold.svg"' in html
        assert 'src="/media/sub-010_desc-mean_bold.svg"' in html
        assert "./sub-010/figures/" not in html

    def test_cdn_and_anchors_are_left_alone(self, report):
        """The browser fetches these, and the browser has internet even when the
        node serving the page does not."""
        html, _ = rewrite_asset_links(
            report.read_text(), report.parent, lambda p: f"/media/{p.name}"
        )
        assert "https://cdn.jsdelivr.net/npm/bootstrap@5.2.3" in html
        assert "https://code.jquery.com/jquery-3.6.0.min.js" in html
        assert 'href="#summary"' in html

    def test_an_unservable_asset_is_reported_not_swallowed(self, report):
        """A missing figure must reach the caller — a report rendered with holes
        in it and no word said is the failure this whole module exists to fix."""
        (report.parent / "sub-010/figures/sub-010_desc-mean_bold.svg").unlink()
        html, unresolved = rewrite_asset_links(
            report.read_text(), report.parent, lambda p: f"/media/{p.name}"
        )
        assert unresolved == ["./sub-010/figures/sub-010_desc-mean_bold.svg"]
        assert "./sub-010/figures/sub-010_desc-mean_bold.svg" in html

    def test_a_resolver_declining_is_also_reported(self, report):
        _, unresolved = rewrite_asset_links(report.read_text(), report.parent, lambda p: None)
        assert len(unresolved) == 2


class TestAnimatedReportlets:
    """fMRIPrep draws its animated figures with ``<object data=…>``, not ``<img>``.

    The bug: only ``src``/``href`` were rewritten, so 41 of a subject's 95
    figures — SDC before/after, both coregistrations, spatial normalization —
    stayed relative and rendered blank. It was silent because each is *also*
    linked by an ``<a href>`` to the same file, which did get rewritten: the path
    resolved, ``unresolved`` stayed empty, and the only visible symptom was that
    the figure was missing while "open in new tab" worked.
    """

    def test_object_data_is_repointed(self, fmriprep_report):
        html, unresolved = rewrite_asset_links(
            fmriprep_report.read_text(), fmriprep_report.parent, lambda p: f"/media/{p.name}"
        )
        assert unresolved == []
        assert 'data="/media/sub-010_task-rest_run-1_desc-sdc_bold.svg"' in html
        assert "./sub-010/figures/" not in html, "a relative path survived"

    def test_bootstrap_data_attributes_are_left_alone(self, fmriprep_report):
        """``data-bs-toggle`` is not an asset reference and must not be touched."""
        html, _ = rewrite_asset_links(
            fmriprep_report.read_text(), fmriprep_report.parent, lambda p: f"/media/{p.name}"
        )
        assert 'data-bs-toggle="collapse"' in html
        assert 'data-bs-target="#sdc"' in html

    def test_a_missing_animated_figure_is_reported(self, fmriprep_report):
        """The silence is the thing being fixed: an absent one must be named.

        Its ``<a href>`` twin resolves, so this only works if ``data=`` is
        checked on its own rather than deduplicated against the link.
        """
        (
            fmriprep_report.parent
            / "sub-010"
            / "figures"
            / "sub-010_task-rest_run-1_desc-sdc_bold.svg"
        ).unlink()
        _, unresolved = rewrite_asset_links(
            fmriprep_report.read_text(), fmriprep_report.parent, lambda p: f"/media/{p.name}"
        )
        assert unresolved.count("./sub-010/figures/sub-010_task-rest_run-1_desc-sdc_bold.svg") == 2

    def test_the_figure_is_counted_once_across_object_and_link(self, fmriprep_report):
        """Same file named twice by two attributes — the bytes are paid once."""
        found = local_asset_paths(fmriprep_report.read_text(), fmriprep_report.parent)
        assert sorted(p.name for p in found) == [
            "sub-010_dseg.svg",
            "sub-010_task-rest_run-1_desc-sdc_bold.svg",
        ]


class TestPayloadCost:
    """What embedding a report costs, answerable before paying it.

    Streamlit reads every asset into the server's memory to serve it, so an
    fMRIPrep subject report is ~80 MB of RAM. The QC page states the figure, and
    can only state it if it can be computed without embedding anything.
    """

    def test_lists_each_local_asset_once(self, report):
        found = local_asset_paths(report.read_text(), report.parent)
        assert sorted(p.name for p in found) == [
            "sub-010_desc-carpet_bold.svg",
            "sub-010_desc-mean_bold.svg",
        ]

    def test_a_figure_drawn_twice_is_counted_once(self, report):
        """Reports repeat a figure across sections; the bytes are paid once."""
        doubled = report.read_text().replace(
            "</body>", '<img src="./sub-010/figures/sub-010_desc-mean_bold.svg" /></body>'
        )
        report.write_text(doubled)
        assert len(local_asset_paths(doubled, report.parent)) == 2

    def test_cdn_and_anchors_cost_nothing(self, report):
        """The browser fetches those, not the server — they are not our bytes."""
        assert all(p.suffix == ".svg" for p in local_asset_paths(report.read_text(), report.parent))

    def test_counts_the_report_and_its_figures(self, report):
        figures = report.parent / "sub-010" / "figures"
        (figures / "sub-010_desc-carpet_bold.svg").write_text("x" * 5000)
        (figures / "sub-010_desc-mean_bold.svg").write_text("x" * 3000)
        assert payload_bytes(report) == report.stat().st_size + 8000

    def test_an_unreadable_report_costs_nothing_rather_than_raising(self, tmp_path):
        """The page shows this number in passing; it must not be able to crash."""
        assert payload_bytes(tmp_path / "absent.html") == 0

    def test_a_missing_figure_is_skipped_not_counted(self, report):
        (report.parent / "sub-010" / "figures" / "sub-010_desc-mean_bold.svg").unlink()
        assert payload_bytes(report) == report.stat().st_size + len("<svg/>")


class TestFindFmriprepReports:
    """fMRIPrep writes one report per subject at the root of its output dir."""

    def test_finds_them_keyed_by_subject(self, tmp_path):
        for name in ("sub-010.html", "sub-011.html"):
            (tmp_path / name).write_text("<html/>")
        assert qc_report.find_fmriprep_reports(tmp_path) == {
            "sub-010": "sub-010.html",
            "sub-011": "sub-011.html",
        }

    def test_a_session_aggregated_report_keys_distinctly(self, tmp_path):
        """``--aggregate-session-reports`` yields one per session; not a collision."""
        (tmp_path / "sub-010.html").write_text("<html/>")
        (tmp_path / "sub-010_ses-02.html").write_text("<html/>")
        assert set(qc_report.find_fmriprep_reports(tmp_path)) == {"sub-010", "sub-010_ses-02"}

    def test_ignores_everything_that_is_not_a_subject_report(self, tmp_path):
        (tmp_path / "dataset_description.json").write_text("{}")
        (tmp_path / "desc-aseg_dseg.tsv").write_text("x")
        (tmp_path / "sub-010").mkdir()
        assert qc_report.find_fmriprep_reports(tmp_path) == {}

    def test_no_derivative_is_no_reports_not_an_error(self, tmp_path):
        assert qc_report.find_fmriprep_reports(tmp_path / "nope") == {}


class TestReportBaseInTheRenderedReport:
    """``report_base=None`` is the embedded copy: it must not emit a link."""

    @pytest.fixture
    def runs(self):
        df = pd.DataFrame(
            [{"sub": "010", "task": "rest", "run": "1", "tsnr": 40.0, "is_outlier": True}]
        )
        return qc_report.build_run_rows(
            df,
            "bold",
            ["tsnr"],
            reports={"sub-010_task-rest_run-1_bold": "sub-010_task-rest_run-1_bold.html"},
        )

    def test_exported_copy_links_relative_to_itself(self, runs):
        html = qc_report.render_report(runs, "bold", ["tsnr"], report_base="../mriqc")
        assert '<a href="../mriqc/sub-010_task-rest_run-1_bold.html"' in html

    def test_embedded_copy_emits_no_link_at_all(self, runs):
        html = qc_report.render_report(runs, "bold", ["tsnr"], report_base=None)
        assert 'href="../mriqc' not in html
        assert "sub-010_task-rest_run-1_bold.html" in html, "still names the report"
        assert "open below" in html

    def test_outlier_detail_drops_its_link_too(self, runs):
        """The run table was not the only place a dead link was rendered."""
        assert "[MRIQC report]" in qc_report.render_report(
            runs, "bold", ["tsnr"], report_base="../mriqc"
        )
        assert "[MRIQC report]" not in qc_report.render_report(
            runs, "bold", ["tsnr"], report_base=None
        )


def test_a_real_mriqc_report_shape_survives_a_round_trip(report):
    """End to end on the shape MRIQC actually writes: every figure gets a URL."""
    served: dict[str, Path] = {}

    def resolve(path: Path) -> str:
        url = f"/node/n0123/8501/media/{len(served)}.svg"
        served[url] = path
        return url

    html, unresolved = rewrite_asset_links(report.read_text(), report.parent, resolve)
    assert unresolved == []
    assert len(served) == 2
    assert all(p.is_file() for p in served.values())
    for url in served:
        assert f'src="{url}"' in html
