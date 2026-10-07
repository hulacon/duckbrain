"""Per-session access gate for the GUI, on both launch routes.

The GUI has no login of its own and acts as whoever started it: it browses
their files and submits jobs on their account, and the "Custom fMRIPrep flags"
field is pasted into the job script as a shell fragment, so it can run
arbitrary commands as well. So it must only answer the person who started it.
Neither route's network position ensures that:

- OnDemand's ``/node/<host>/<port>/`` proxy forwards for any signed-in
  OnDemand user, not just the session's owner.
- ``scripts/launch.sh`` binds 127.0.0.1, which keeps other hosts out but not
  other users on the same host. Compute nodes are shared between jobs, Slurm
  lets anyone with a job on a node ssh into it, and a login node is shared
  by everyone.

The secret is a per-session token. Under OnDemand it is the ``password`` the
template already generates, and ``view.html.erb`` puts it in the Connect link
as ``?token=``. ``launch.sh`` generates one and prints a link carrying it. The
first request with the token gets an HttpOnly cookie and a redirect to the
same URL without the token. From then on the cookie authenticates every
request: page loads, reloads, new tabs, the websocket every script run goes
over, uploads, media and component assets. A valid user never types anything.
SSO to OnDemand, or the SSH login that started ``launch.sh``, is the
authentication, and the token only proves that this browser was handed the
owner's link.

This is ASGI middleware rather than a check at the top of ``app.py`` because a
script-level gate only stops script runs. The upload, media and component
routes are served without running the script. A script-level gate would also
need a way to persist the token across reloads, which Streamlit has no API for
(``st.context.cookies`` is read-only). Here the browser's own cookie jar does it.

The cookie is ``SameSite=Strict``, so a page on another site cannot reach the
app with it: no cross-site websocket and no cross-site upload POST. That is
the attack Streamlit's XSRF protection is for, and the reason it is safe for
the OnDemand launcher to leave that protection off.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qsl, urlencode

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

TOKEN_ENV = "DUCKBRAIN_ACCESS_TOKEN"
QUERY_PARAM = "token"
COOKIE_PREFIX = "duckbrain_access_"

# 1008 = policy violation. Closing before ``websocket.accept`` makes the ASGI
# server answer the upgrade request with HTTP 403.
_WS_POLICY_VIOLATION = 1008

_GATE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>duckbrain</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 36rem; margin: 4rem auto;
         padding: 0 1rem; color: #1a1a1a; background: #fff; line-height: 1.5; }}
  label {{ display: block; margin-top: 2rem; font-size: .9rem; }}
  input {{ font: inherit; padding: .3rem; width: 16rem; max-width: 100%; }}
  button {{ font: inherit; padding: .3rem .8rem; }}
</style>
</head>
<body>
<main>
<h1>duckbrain</h1>
<p>{message}</p>
<form method="get" action="{action}">
  <label for="token">Access token (on your OnDemand session card,
    or in the link launch.sh printed)</label>
  <input id="token" name="{param}" type="password" autocomplete="off" required>
  <button type="submit">Open</button>
</form>
</main>
</body>
</html>
"""

_BARE = (
    "Open duckbrain from the link it gave you: the <strong>Connect</strong> button "
    "on your OnDemand session, or the link <code>launch.sh</code> printed."
)
_WRONG = (
    "That link is for a different duckbrain session, which may have ended. "
    "Open duckbrain from the link your current session gave you: the "
    "<strong>Connect</strong> button on OnDemand, or the link <code>launch.sh</code> printed."
)


def _headers(scope: Scope) -> dict[str, str]:
    """Request headers, lower-cased, last value wins (ASGI gives raw bytes pairs)."""
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def _cookie(scope: Scope, name: str) -> str | None:
    raw = _headers(scope).get("cookie", "")
    for part in raw.split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return None


def _matches(presented: str | None, token: str) -> bool:
    return presented is not None and hmac.compare_digest(presented.encode(), token.encode())


def cookie_name(token: str) -> str:
    """A cookie name unique to this session's token.

    Browsers scope cookies by host and path but not by port. Two ``launch.sh``
    GUIs are both ``localhost`` with path ``/``, so under one fixed name the
    second session's cookie would overwrite the first, and the first tab would
    be locked out at its next request. A name derived from the token keeps
    them apart and reveals nothing about the token.
    """
    return COOKIE_PREFIX + hashlib.sha256(token.encode()).hexdigest()[:12]


def normalise_base_path(base: str) -> str:
    """Streamlit's ``server.baseUrlPath`` as a cookie path: leading and trailing slash."""
    base = base.strip("/")
    return f"/{base}/" if base else "/"


class AccessGate:
    """ASGI middleware: only a browser that presented *token* reaches *app*.

    *cookie_path* is Streamlit's base path: ``/node/<host>/<port>/`` under
    OnDemand, ``/`` for ``launch.sh``. It is a callable because Streamlit's config, where the
    base path lives, is only final once the server has started.
    """

    def __init__(self, app: ASGIApp, token: str, cookie_path: Callable[[], str]) -> None:
        if not token:
            # A gate with an empty secret would let every request in.
            raise ValueError("AccessGate needs a non-empty token")
        self.app = app
        self.token = token
        self.cookie_name = cookie_name(token)
        self.cookie_path = cookie_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # lifespan
            await self.app(scope, receive, send)
            return
        if _matches(_cookie(scope, self.cookie_name), self.token):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
            return

        query = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        presented = [v for k, v in query if k == QUERY_PARAM]
        if presented and _matches(presented[-1], self.token):
            await self._admit(scope, send, [(k, v) for k, v in query if k != QUERY_PARAM])
        else:
            await self._refuse(scope, send, _WRONG if presented else _BARE)

    async def _admit(self, scope: Scope, send: Send, rest: list[tuple[str, str]]) -> None:
        """Set the cookie and redirect to the same URL with the token removed.

        The redirect keeps the token out of the address bar, out of history
        after this one entry, and out of ``st.query_params``.
        """
        location = scope.get("root_path", "") + scope["path"]
        if rest:
            location += "?" + urlencode(rest)
        cookie = (
            f"{self.cookie_name}={self.token}; Path={self.cookie_path()}; HttpOnly; SameSite=Strict"
        )
        if _headers(scope).get("x-forwarded-proto") == "https" or scope.get("scheme") == "https":
            cookie += "; Secure"
        await send(
            {
                "type": "http.response.start",
                "status": 303,
                "headers": [
                    (b"location", location.encode("latin-1")),
                    (b"set-cookie", cookie.encode("latin-1")),
                    (b"cache-control", b"no-store"),
                    (b"content-length", b"0"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b""})

    async def _refuse(self, scope: Scope, send: Send, message: str) -> None:
        body = _GATE_PAGE.format(
            message=message, action=self.cookie_path(), param=QUERY_PARAM
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"text/html; charset=utf-8"),
                    (b"cache-control", b"no-store"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send(
            {"type": "http.response.body", "body": b"" if scope.get("method") == "HEAD" else body}
        )
