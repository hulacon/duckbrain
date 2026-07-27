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
