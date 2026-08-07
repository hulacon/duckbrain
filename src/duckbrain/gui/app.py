"""Main Streamlit entrypoint for duckbrain (multipage app).

Navigation is **declarative** (``st.navigation``) rather than the filesystem
``pages/`` convention, so it can sit along the top and leave the left side free
for content. Calling ``st.navigation`` also switches Streamlit out of
pages-directory mode (it sets ``PagesManager.uses_pages_directory = False``), so
``pages/`` no longer auto-registers a second nav — the two cannot fight.

The pages keep their own ``st.set_page_config`` calls. Redundant here, but it is
what lets each page still be run — and AppTest-driven — standalone.
"""

import os
from pathlib import Path

import streamlit as st

# Absolute, not relative: Streamlit executes this file as a *script*, so there is
# no parent package and ``from ..config`` raises ImportError. The previous version
# hid exactly that behind a bare ``except Exception``, which is why the sidebar's
# project indicator always read "Config not found" under `streamlit run`.
from duckbrain.config import PROJECT_ENV, recent_projects, remember_project
from duckbrain.core.bids_metadata import duckbrain_version
from duckbrain.core.updates import update_available

# resolve(): st.Page validates the path, and __file__ is only relative-safe while
# the cwd happens to be the repo root. An absolute path makes nav independent of
# where the process was launched from — which is not a given under OnDemand.
_PAGES_DIR = Path(__file__).resolve().parent / "pages"

# (filename, nav title). Pipeline order, but Status leads: it is the cockpit and
# the page you land on daily. Deliberately no icons — the top bar stays legible,
# and glyphs in chrome were exactly the thing that read as noise.
_PAGES = [
    ("0_Project_Status.py", "Status"),
    ("1_Project_Setup.py", "Setup"),
    ("2_Data_Ingestion.py", "Ingestion"),
    ("3_BIDS_Conversion.py", "Conversion"),
    ("4_Preprocessing.py", "Preprocessing"),
    ("6_Guide.py", "Guide"),
    ("7_New_to_Talapas.py", "New to Talapas?"),
]

# QC is six pages, so it is a *group*: passing st.navigation a dict makes each
# grouping one collapsible item at position="top", which keeps the top bar the
# length it was. The empty-string key is what puts the pipeline pages before the
# groups rather than inside one.
_QC_PAGES = [
    ("5_QC_Overview.py", "Overview"),
    ("5a_QC_Signal.py", "Signal & contrast"),
    ("5b_QC_Temporal.py", "Temporal stability"),
    ("5c_QC_Alignment.py", "Alignment & distortion"),
    ("5d_QC_Artifacts.py", "Artifacts"),
]


def active_project() -> str:
    """The project this session is pointed at, session state winning over env."""
    return st.session_state.get("project_dir") or os.environ.get(PROJECT_ENV, "")


def activate_project(project_dir: str) -> None:
    """Make *project_dir* the active project and record it as most-recent.

    Sets both the session key the GUI reads and the env var the config layer
    reads, so a switch is visible to pages that go through either.
    """
    st.session_state["project_dir"] = project_dir
    os.environ[PROJECT_ENV] = project_dir
    remember_project(project_dir)


def _shorten(path: str, keep: int = 2) -> str:
    """Trailing *keep* path components — enough to tell projects apart in a menu."""
    parts = Path(path).parts
    return path if len(parts) <= keep else ".../" + "/".join(parts[-keep:])


@st.cache_data(ttl=3600, show_spinner=False)
def _newer_release() -> tuple[str, str] | None:
    """Cached ``update_available()`` — one network call an hour, process-wide.

    The check reaches out to GitHub, and it sits in the render path of *every*
    page, so it must not be paid per rerun. An hour is the right coarseness: this
    is a "you have been on this checkout for weeks" notice, not a live feed.
    """
    return update_available()


def _version_note() -> str:
    """The running version, plus a link when a newer release exists.

    ``duckbrain_version()`` and not ``__version__``: it prefers a ``git describe``
    of the checkout, which is what actually runs and what a user needs to quote
    when reporting a bug. Says nothing about being current —
    :mod:`duckbrain.core.updates` cannot distinguish "current" from "could not
    reach GitHub", and a false all-clear is worse than no line at all.
    """
    here = duckbrain_version()
    newer = _newer_release()
    if not newer:
        return f"`{here}`" if here else ""
    tag, url = newer
    return f"`{here}` · [**{tag}** available]({url})" if here else f"[**{tag}** available]({url})"


def _project_bar() -> None:
    """One-line active-project indicator, version, + recent-projects switcher.

    Rendered *before* ``nav.run()`` for two reasons: it appears above whichever
    page is showing (replacing the sidebar indicator that top nav displaced), and
    it re-exports ``PROJECT_ENV`` before the page body reads it.
    """
    active = active_project()
    if active:
        os.environ[PROJECT_ENV] = active

    others = [p for p in recent_projects() if p != active]
    label, version, switcher = st.columns([5, 2, 1], vertical_alignment="center")

    with label:
        st.caption(f"Project: `{active}`" if active else "No project open — start in **Setup**.")
    with version:
        note = _version_note()
        if note:
            st.caption(note)
    with switcher:
        if not others:
            return
        with st.popover("Switch", width="stretch"):
            st.caption("Recent projects")
            for path in others:
                if st.button(_shorten(path), key=f"_recent_{path}", help=path, width="stretch"):
                    activate_project(path)
                    st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="duckbrain",
        page_icon="\U0001f9e0",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    nav = st.navigation(
        {
            "": [
                st.Page(_PAGES_DIR / f, title=t, default=(i == 0))
                for i, (f, t) in enumerate(_PAGES)
            ],
            "QC": [st.Page(_PAGES_DIR / f, title=t) for f, t in _QC_PAGES],
        },
        position="top",
    )
    _project_bar()
    nav.run()


if __name__ == "__main__":
    main()
