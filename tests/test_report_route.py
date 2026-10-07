"""The full-window report route (``gui/report_route.py``, usability F37).

Driven as raw ASGI like ``test_access_gate.py``: no HTTP client in the env. The
live check through OnDemand (and how long the 52 MB fMRIPrep report takes to
open from a laptop) is in TODO ``#30``.
"""

import asyncio

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware

from duckbrain.gui import report_route
from duckbrain.gui.access import AccessGate, cookie_name

TOKEN = "s3cret-token"
BASE = "/node/n0001/8766"


def _get(app, path, cookie=None, method="GET"):
    """One request through *app*; returns (status, headers, body)."""
    headers = [(b"cookie", cookie.encode())] if cookie else []
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "scheme": "http",
        "server": ("testserver", 80),
        "root_path": "",
    }
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), body


@pytest.fixture
def report(tmp_path):
    """An MRIQC-shaped tree: a report with its rating widget, a figure beside it,
    and a file outside the tree that must stay unreachable."""
    mriqc = tmp_path / "derivatives" / "mriqc"
    (mriqc / "sub-01" / "figures").mkdir(parents=True)
    (mriqc / "sub-01" / "figures" / "carpet.svg").write_text("<svg/>")
    (mriqc / "sub-01_T1w.json").write_text("{}")
    page = mriqc / "sub-01_T1w.html"
    page.write_text(
        '<html><head></head><body><input id="qcrating-toggler"/>'
        '<img src="./sub-01/figures/carpet.svg"/></body></html>'
    )
    (tmp_path / "secret.txt").write_text("nope")
    return page


def _app():
    return Starlette(routes=report_route.ROUTES)


def test_a_registered_report_is_served_with_its_widget_hidden(report):
    url = "/" + report_route.register(report)
    status, headers, body = _get(_app(), url)
    assert status == 200
    assert headers[b"content-type"].startswith(b"text/html")
    assert b"#qcrating-menu" in body and b"display: none" in body


def test_its_figures_resolve_beside_it(report):
    url = "/" + report_route.register(report)
    figure = url.rsplit("/", 1)[0] + "/sub-01/figures/carpet.svg"
    status, headers, body = _get(_app(), figure)
    assert status == 200
    assert headers[b"content-type"] == b"image/svg+xml"
    assert body == b"<svg/>"


def test_it_answers_behind_the_ondemand_prefix(report):
    url = BASE + "/" + report_route.register(report)
    assert _get(_app(), url)[0] == 200


def test_nothing_outside_the_report_tree_is_served(report):
    url = "/" + report_route.register(report)
    escape = url.rsplit("/", 1)[0] + "/../../secret.txt"
    assert _get(_app(), escape)[0] == 404


def test_only_report_media_types_are_served(report):
    url = "/" + report_route.register(report)
    assert _get(_app(), url.rsplit("/", 1)[0] + "/sub-01_T1w.json")[0] == 404


def test_an_unregistered_key_says_to_reopen_it_from_inspect():
    status, _, body = _get(_app(), f"/{report_route.PREFIX}/0123456789abcdef/x.html")
    assert status == 404
    assert b"Inspect" in body


def test_the_gate_covers_the_route(report):
    """Mounted the way serve.py mounts it: middleware wraps user routes too."""
    app = Starlette(
        routes=report_route.ROUTES,
        middleware=[Middleware(AccessGate, token=TOKEN, cookie_path=lambda: BASE + "/")],
    )
    url = BASE + "/" + report_route.register(report)
    status, _, body = _get(app, url)
    assert b"carpet.svg" not in body, "served without the cookie"
    status, _, body = _get(app, url, cookie=f"{cookie_name(TOKEN)}={TOKEN}")
    assert status == 200 and b"carpet.svg" in body
