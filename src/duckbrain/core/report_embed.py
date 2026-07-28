"""Make a tool-produced HTML report viewable from inside the duckbrain GUI.

MRIQC and fMRIPrep both write a small HTML page beside a directory of large SVG
figures, referenced relatively::

    <img class="svg-reportlet" src="./sub-010/figures/sub-010_..._desc-carpet_bold.svg" />
    <object class="svg-reportlet" type="image/svg+xml"
            data="./sub-010/figures/sub-010_..._desc-sdc_bold.svg"></object>

Both forms appear, and which one a figure gets is not cosmetic: fMRIPrep uses
``<object>`` for the reportlets that animate, because the before/after flicker is
a CSS ``:hover`` animation and an SVG inside an ``<img>`` is not a document that
can be hovered. Any attribute that names a file has to be rewritten or that
figure is simply absent.

Opened from disk that resolves. Served from the app it does not, and the reason
is worth stating because it is the same shape of failure ``qc_report``'s module
docstring records for ``file://`` links: duckbrain has never served project files
over HTTP at all, so there is no URL under which those SVGs exist. Worse, the
report link itself was relative to *the exported copy's* location, and inside the
QC page it sits in a sandboxed ``srcdoc`` iframe whose base URL is the parent
page's — so under OnDemand ``../mriqc/sub-010_..._bold.html`` resolved to
``/node/<host>/mriqc/...`` and 404'd. The link did not error. It did nothing.

So this module rewrites every relative asset reference to a URL the app really
serves, and returns the rewritten HTML. *What* that URL is deliberately belongs
to the caller — :func:`duckbrain.gui.components.embed_tool_report` passes a
resolver backed by Streamlit's own media endpoint, which is same-origin and
therefore survives OnDemand's reverse proxy without the app needing a route, a
launch flag, or a symlink. Nothing here imports Streamlit, which is what lets it
be tested.

Inlining the figures as ``data:`` URIs was the obvious alternative and is
rejected on size: one MRIQC ``T1w`` report carries 15 MB of SVG across two files,
20 MB once base64-encoded, and that would cross the websocket on every rerun.
Served as separate URLs the bytes go over plain HTTP, uninflated and cacheable.

Assets are confined to the report's own directory tree. A resolver here is
handed a path taken out of an HTML file and turns it into something the server
will read and send, so the containment is what keeps that from being a way to
read arbitrary files; ``qc_report`` has no such need and no such power.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

#: ``src=`` / ``href=`` / ``data=`` with a double-quoted value. Tool reports are
#: generated from templates, not hand-written, so the quoting is uniform; a
#: parser would buy nothing and would rewrite the whole document on the way out.
#:
#: ``data=`` is here because fMRIPrep embeds its *animated* reportlets — SDC
#: before/after, BOLD-to-T1w and fieldmap coregistration, spatial normalization —
#: as ``<object type="image/svg+xml" data="…">`` rather than ``<img src="…">``.
#: It needs a real document, not an image: the flicker is a CSS animation that
#: runs on ``:hover``, and an SVG in an ``<img>`` gets no hover. Missing ``data=``
#: left 41 of one subject's 95 figures pointing at a path that does not resolve
#: inside the iframe — blank frames, and *silently* so, because every one of them
#: is also linked by an ``<a href>`` "open in new tab" that did get rewritten. So
#: the file resolved, nothing landed in ``unresolved``, and the only symptom was
#: that the figures a reviewer most needs were the ones that did not appear.
#:
#: ``\b…\s*=`` cannot match ``data-bs-toggle=`` or ``data-cites=`` (a hyphen is
#: not an ``=``), which is what keeps Bootstrap's attributes out of it.
_ASSET_REF = re.compile(r'\b(?P<attr>src|href|data)\s*=\s*"(?P<url>[^"]*)"')

#: Prefixes that mean "not a file beside this report" — absolute URLs, protocol-
#: relative CDN links, already-inlined data, in-page anchors, and server-absolute
#: paths. MRIQC's Bootstrap and jQuery come from a CDN and are left alone: the
#: *browser* fetches those, and the browser has internet even when the compute
#: node serving the page does not.
_NOT_LOCAL = ("http://", "https://", "//", "data:", "#", "/", "mailto:", "javascript:")


def is_local_asset(url: str) -> bool:
    """Whether ``url`` names a file relative to the report that contains it."""
    url = url.strip()
    return bool(url) and not url.startswith(_NOT_LOCAL)


def resolve_asset(report_dir: Path, url: str) -> Path | None:
    """Resolve a relative reference against ``report_dir``, or None.

    None means "do not serve this": the reference escapes the report's own
    directory tree, or names something that is not a readable file.
    """
    root = report_dir.resolve()
    # Query strings and fragments are addressing, not path.
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    if not path:
        return None
    candidate = (root / path).resolve()
    if root not in candidate.parents and candidate != root:
        return None
    return candidate if candidate.is_file() else None


def local_asset_paths(html: str, report_dir: Path) -> list[Path]:
    """Every distinct file ``html`` draws on from beside it, deduplicated.

    Same resolution rules as :func:`rewrite_asset_links`, so this answers "what
    would that call serve" without serving it.
    """
    seen: dict[Path, None] = {}
    for match in _ASSET_REF.finditer(html):
        url = match.group("url")
        if not is_local_asset(url):
            continue
        path = resolve_asset(report_dir, url)
        if path is not None:
            seen.setdefault(path, None)
    return list(seen)


def payload_bytes(report_path: Path) -> int:
    """Bytes that embedding ``report_path`` pulls into memory — 0 if unreadable.

    Worth knowing before the fact, because Streamlit's media manager reads each
    asset into the server's RAM when the URL is registered and keeps it there.
    Browser-side laziness cannot claw that back: the read happens while the page
    is being built, before the browser has seen any of it. MRIQC made this
    invisible at 15 MB for a T1w report; one fMRIPrep *subject* report references
    ~80 MB of SVG, mostly per-run fieldmap and coregistration figures, so the
    caller is expected to show this and let the reader decide rather than spend
    it on their behalf.
    """
    report_path = Path(report_path)
    try:
        html = report_path.read_text(encoding="utf-8", errors="replace")
        total = report_path.stat().st_size
    except OSError:
        return 0
    for asset in local_asset_paths(html, report_path.parent):
        try:
            total += asset.stat().st_size
        except OSError:
            continue
    return total


def rewrite_asset_links(
    html: str,
    report_dir: Path,
    resolve: Callable[[Path], str | None],
) -> tuple[str, list[str]]:
    """Point every local asset reference in ``html`` at a served URL.

    Parameters
    ----------
    html : str
        The tool's report, read verbatim.
    report_dir : Path
        The directory the report was written to — what its relative references
        are relative to.
    resolve : callable
        Takes the resolved absolute path of one asset and returns the URL to
        serve it from, or None if it cannot be served.

    Returns
    -------
    (html, unresolved)
        The rewritten HTML, and the reference strings that could not be turned
        into a URL. A non-empty ``unresolved`` means the report will render
        incomplete, and the caller is expected to say so rather than show a page
        with silently missing figures.
    """
    unresolved: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        url = match.group("url")
        if not is_local_asset(url):
            return match.group(0)
        path = resolve_asset(report_dir, url)
        served = resolve(path) if path is not None else None
        if served is None:
            unresolved.append(url)
            return match.group(0)
        return f'{match.group("attr")}="{served}"'

    return _ASSET_REF.sub(_sub, html), unresolved
