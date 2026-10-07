"""Gated entrypoint: ``app.py`` behind :class:`~duckbrain.gui.access.AccessGate`.

Both launchers (the OnDemand app and ``scripts/launch.sh``) run
``streamlit run .../gui/serve.py``. Streamlit finds the module-level
``app = st.App(...)`` by parsing this file, and serves it through its ASGI
server, which is where middleware can be attached. ``app.py`` itself is
unchanged, and it is what the tests run.

Fails closed: without ``DUCKBRAIN_ACCESS_TOKEN`` this module refuses to build
an app at all, rather than serving one that other users can reach.
"""

import os
from pathlib import Path

import streamlit as st
from starlette.middleware import Middleware
from streamlit import config

from duckbrain.gui import report_route
from duckbrain.gui.access import TOKEN_ENV, AccessGate, normalise_base_path

# Popped, not read. Every job the GUI submits inherits this process's
# environment, and a token copied into job environments and scheduler records
# would outlive the session it guards.
_token = os.environ.pop(TOKEN_ENV, "")
if not _token:
    raise SystemExit(
        f"{TOKEN_ENV} is not set: refusing to serve an ungated GUI. "
        "Start the GUI with scripts/launch.sh or the OnDemand app, which set it."
    )

# The full-window report route (usability F37). User routes sit inside the same
# Starlette app as Streamlit's, so the gate below covers them too.
report_route.mounted = True

app = st.App(
    Path(__file__).resolve().parent / "app.py",
    routes=report_route.ROUTES,
    middleware=[
        Middleware(
            AccessGate,
            token=_token,
            cookie_path=lambda: normalise_base_path(config.get_option("server.baseUrlPath")),
        )
    ],
)
