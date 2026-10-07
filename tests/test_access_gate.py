"""The OnDemand access gate (``gui/access.py``) and its gated entrypoint (``gui/serve.py``).

Driven as raw ASGI, so no HTTP client is needed: each test hands the gate a
scope and records what it sends. The live checks (through a real server, from
another host, and the browser round trip) are in TODO ``#30``.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from duckbrain.gui.access import (
    TOKEN_ENV,
    AccessGate,
    cookie_name,
    normalise_base_path,
)

TOKEN = "s3cret-token"
COOKIE_NAME = cookie_name(TOKEN)
BASE = "/node/n0001/8766/"


class _App:
    """Stands in for Streamlit: records whether a request got through."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True


def _run(gate, scope):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    asyncio.run(gate(scope, receive, send))
    return sent


def _scope(path=BASE, query="", cookie=None, kind="http", method="GET"):
    headers = [(b"cookie", cookie.encode())] if cookie else []
    scope = {"type": kind, "path": path, "query_string": query.encode(), "headers": headers}
    if kind == "http":
        scope["method"] = method
    return scope


def _gate():
    inner = _App()
    return AccessGate(inner, token=TOKEN, cookie_path=lambda: BASE), inner


def _header(message, name):
    return dict(message["headers"]).get(name.encode(), b"").decode()


def test_a_bare_request_gets_the_gate_page_not_the_app():
    gate, inner = _gate()
    sent = _run(gate, _scope())
    assert not inner.called
    assert sent[0]["status"] == 403
    assert b"Connect" in sent[1]["body"]
    assert b"launch.sh" in sent[1]["body"]


@pytest.mark.parametrize("path", [f"{BASE}_stcore/health", f"{BASE}_stcore/upload_file/x/y"])
def test_streamlit_internal_routes_are_gated_too(path):
    """The point of gating in middleware: these never run the script."""
    gate, inner = _gate()
    sent = _run(gate, _scope(path=path))
    assert not inner.called
    assert sent[0]["status"] == 403


def test_the_right_token_sets_a_strict_httponly_cookie_and_redirects_without_it():
    gate, inner = _gate()
    sent = _run(gate, _scope(query=f"token={TOKEN}"))
    assert not inner.called
    assert sent[0]["status"] == 303
    assert _header(sent[0], "location") == BASE
    cookie = _header(sent[0], "set-cookie")
    assert cookie.startswith(f"{COOKIE_NAME}={TOKEN};")
    assert f"Path={BASE}" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie


def test_a_deep_link_keeps_its_page_and_other_parameters():
    gate, _ = _gate()
    sent = _run(gate, _scope(path=f"{BASE}status", query=f"token={TOKEN}&run=2"))
    assert _header(sent[0], "location") == f"{BASE}status?run=2"


def test_secure_is_added_only_when_the_request_came_over_https():
    gate, _ = _gate()
    plain = _run(gate, _scope(query=f"token={TOKEN}"))
    scope = _scope(query=f"token={TOKEN}")
    scope["headers"].append((b"x-forwarded-proto", b"https"))
    tls = _run(gate, scope)
    assert "Secure" not in _header(plain[0], "set-cookie")
    assert _header(tls[0], "set-cookie").endswith("; Secure")


def test_a_wrong_token_is_refused_and_says_the_link_is_stale():
    gate, inner = _gate()
    sent = _run(gate, _scope(query="token=nope"))
    assert not inner.called
    assert sent[0]["status"] == 403
    assert b"different duckbrain session" in sent[1]["body"]


def test_the_cookie_lets_every_request_through():
    gate, inner = _gate()
    _run(gate, _scope(path=f"{BASE}qc-overview", cookie=f"other=1; {COOKIE_NAME}={TOKEN}"))
    assert inner.called


def test_a_wrong_cookie_is_refused():
    gate, inner = _gate()
    sent = _run(gate, _scope(cookie=f"{COOKIE_NAME}=forged"))
    assert not inner.called
    assert sent[0]["status"] == 403


def test_a_websocket_without_the_cookie_is_closed_before_accept():
    """Every script run goes over this socket; closing before accept is a 403."""
    gate, inner = _gate()
    sent = _run(gate, _scope(path=f"{BASE}_stcore/stream", kind="websocket"))
    assert not inner.called
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_a_websocket_with_the_cookie_reaches_the_app():
    gate, inner = _gate()
    _run(
        gate,
        _scope(path=f"{BASE}_stcore/stream", kind="websocket", cookie=f"{COOKIE_NAME}={TOKEN}"),
    )
    assert inner.called


def test_a_token_in_a_websocket_query_does_not_open_it():
    """Only a page load can trade the token for the cookie."""
    gate, inner = _gate()
    sent = _run(
        gate, _scope(path=f"{BASE}_stcore/stream", kind="websocket", query=f"token={TOKEN}")
    )
    assert not inner.called
    assert sent[0]["type"] == "websocket.close"


def test_lifespan_passes_straight_through():
    gate, inner = _gate()
    _run(gate, {"type": "lifespan"})
    assert inner.called


def test_head_gets_the_status_without_a_body():
    gate, _ = _gate()
    sent = _run(gate, _scope(method="HEAD"))
    assert sent[0]["status"] == 403
    assert sent[1]["body"] == b""


def test_two_sessions_on_one_host_get_different_cookies():
    """Cookies ignore ports: two launch.sh GUIs are both localhost, path /."""
    assert cookie_name("one") != cookie_name("two")
    assert "one" not in cookie_name("one")


def test_another_sessions_cookie_does_not_open_this_one():
    gate, inner = _gate()
    _run(gate, _scope(cookie=f"{cookie_name('other')}=other"))
    assert not inner.called


def test_an_empty_token_cannot_build_a_gate():
    with pytest.raises(ValueError):
        AccessGate(_App(), token="", cookie_path=lambda: "/")


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("", "/"),
        ("/", "/"),
        ("node/n1/8766", "/node/n1/8766/"),
        ("/node/n1/8766/", "/node/n1/8766/"),
    ],
)
def test_base_path_normalises_to_a_cookie_path(base, expected):
    assert normalise_base_path(base) == expected


SERVE = Path(__file__).resolve().parents[1] / "src" / "duckbrain" / "gui" / "serve.py"


def test_streamlit_run_finds_the_gated_app_in_serve_py():
    """``streamlit run serve.py`` only serves through the gate if its AST
    discovery recognises the module-level ``st.App``; otherwise it would run
    serve.py as a plain script and show a blank page."""
    from streamlit.web.server.app_discovery import discover_asgi_app

    found = discover_asgi_app(SERVE)
    assert found.is_asgi_app
    assert found.app_name == "app"


def _import_serve(env_token):
    env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
    if env_token is not None:
        env[TOKEN_ENV] = env_token
    code = (
        "import os, duckbrain.gui.serve as s; "
        f"print(type(s.app).__name__, {TOKEN_ENV!r} in os.environ)"
    )
    return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)


@pytest.mark.parametrize("value", [None, ""])
def test_serve_refuses_to_start_without_a_token(value):
    done = _import_serve(value)
    assert done.returncode != 0
    assert "refusing to serve an ungated GUI" in done.stderr


def test_serve_takes_the_token_out_of_the_environment_jobs_inherit():
    done = _import_serve("abc")
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["App", "False"]


def test_serve_mounts_the_full_window_report_route():
    """F37: serve.py, and only serve.py, mounts the route Inspect links to."""
    env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
    env[TOKEN_ENV] = "abc"
    code = (
        "import duckbrain.gui.serve as s; from duckbrain.gui import report_route as r; "
        "print(r.mounted, all(x in s.app._user_routes for x in r.ROUTES))"
    )
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["True", "True"]
