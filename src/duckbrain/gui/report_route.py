"""Full-window tool reports: a route that serves a report's own directory.

Inspect embeds MRIQC and fMRIPrep reports in a 1200 px frame inside a very long
page, and until this route there was no way to open one on its own (usability
F37). The embed also costs server RAM: Streamlit's media manager reads every
figure in as the page builds, about 80 MB for an fMRIPrep subject.

This route serves the report the way the tool meant it to be read: the HTML at
a real URL, with its figures beside it. The report's relative links
(``./sub-010/figures/…svg``) then resolve against that URL with no rewriting,
and figures stream from disk as the browser asks for them.

What it may serve is narrow on purpose:

- **Only directories Inspect registered** (:func:`register`, called when it
  draws the link). The key in the URL names a registration, not a path, so the
  URL cannot be edited to point anywhere else. The registry is in-process, so a
  restarted server answers an old link with "open it again from Inspect".
- **Only files inside that directory's tree**, by
  :func:`~duckbrain.core.report_embed.resolve_asset`, the same containment the
  embed uses.
- **Only the media types a report is made of** (HTML, SVG, raster images, CSS,
  JS). Anything else is a 404, not a download.

It is mounted by ``serve.py`` and sits behind the same
:class:`~duckbrain.gui.access.AccessGate` as every other route. Starlette's
middleware wraps user routes too, so a link reaches nobody but the session's
owner. ``app.py`` run on its own (the tests, the walk driver) has no route, so
:data:`mounted` tells Inspect whether to offer the link at all.

The path must start outside Streamlit's reserved prefixes (``/_stcore/``,
``/media/`` …), hence ``/api/…``. User routes are not placed under
``server.baseUrlPath``, and under OnDemand every request arrives as
``/node/<host>/<port>/…``, so the route also matches behind any prefix.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from starlette.routing import Route

from duckbrain.core.report_embed import hide_rating_widget, resolve_asset

#: Path segment the route lives under, relative to the app's base path.
PREFIX = "api/duckbrain/report"

#: Set by ``serve.py`` when it mounts :data:`ROUTES`. False under a bare
#: ``streamlit run app.py``, where a link would 404.
mounted = False

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".css": "text/css",
    ".js": "text/javascript",
}

#: key → report directory. Written by a script thread, read on the event loop;
#: single dict operations are atomic under the GIL, and entries are never removed.
_registry: dict[str, Path] = {}


def register(report: Path) -> str:
    """Make *report*'s directory servable; return the report's path under the app.

    The return value is relative to the app's base path (no leading slash), so
    the caller prefixes it with whatever the app is served under.
    """
    report = Path(report).resolve()
    key = hashlib.sha256(str(report.parent).encode()).hexdigest()[:16]
    _registry[key] = report.parent
    return f"{PREFIX}/{key}/{quote(report.name)}"


_GONE = (
    "This report link has expired (duckbrain was restarted since it was made). "
    "Open the report again from the Inspect page."
)


async def _serve(request: Request) -> Response:
    root = _registry.get(request.path_params["key"])
    if root is None:
        return PlainTextResponse(_GONE, status_code=404)
    path = resolve_asset(root, request.path_params["rel"])
    if path is None:
        return PlainTextResponse("Not found.", status_code=404)
    media_type = _MEDIA_TYPES.get(path.suffix.lower())
    if media_type is None:
        return PlainTextResponse("Not found.", status_code=404)
    if media_type.startswith("text/html"):
        # The same rating-widget hiding as the embed (F36): the full-window
        # report is still duckbrain's view of it, and a verdict is still saved
        # only on Inspect.
        html = path.read_text(encoding="utf-8", errors="replace")
        return HTMLResponse(hide_rating_widget(html))
    return FileResponse(path, media_type=media_type)


ROUTES = [
    Route(f"/{PREFIX}/{{key}}/{{rel:path}}", _serve, methods=["GET", "HEAD"]),
    Route(f"/{{base:path}}/{PREFIX}/{{key}}/{{rel:path}}", _serve, methods=["GET", "HEAD"]),
]
