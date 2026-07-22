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
    ("5_QC_Dashboard.py", "QC"),
    ("6_Guide.py", "Guide"),
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


def _project_bar() -> None:
    """One-line active-project indicator + recent-projects switcher.

    Rendered *before* ``nav.run()`` for two reasons: it appears above whichever
    page is showing (replacing the sidebar indicator that top nav displaced), and
    it re-exports ``PROJECT_ENV`` before the page body reads it.
    """
    active = active_project()
    if active:
        os.environ[PROJECT_ENV] = active

    others = [p for p in recent_projects() if p != active]
    label, switcher = st.columns([6, 1], vertical_alignment="center")

    with label:
        st.caption(f"Project: `{active}`" if active else "No project open — start in **Setup**.")
    with switcher:
        if not others:
            return
        with st.popover("Switch", width="stretch"):
            st.caption("Recent projects")
            for path in others:
                if st.button(_shorten(path), key=f"_recent_{path}", help=path, width="stretch"):
                    activate_project(path)
                    st.rerun()


def main():
    st.set_page_config(
        page_title="duckbrain",
        page_icon="\U0001f9e0",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    nav = st.navigation(
        [st.Page(_PAGES_DIR / f, title=t, default=(i == 0)) for i, (f, t) in enumerate(_PAGES)],
        position="top",
    )
    _project_bar()
    nav.run()


if __name__ == "__main__":
    main()
