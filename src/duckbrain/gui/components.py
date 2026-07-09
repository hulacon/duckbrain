"""Shared Streamlit widgets for duckbrain GUI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


_DP_MAX_BUTTONS = 300
_DP_LIST_HEIGHT = 280


def _nearest_dir(path: str) -> Path:
    """Deepest existing directory at or above *path* (home as last resort)."""
    p = Path(path) if path else Path.home()
    for candidate in (p, *p.parents):
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return Path.home()


def directory_picker(
    label: str,
    *,
    key: str,
    default: str = "",
    must_exist: bool = False,
    allow_create: bool = False,
    help: str | None = None,
) -> str:
    """A server-side directory browser that works like a file manager.

    The GUI runs on the compute node, so this browses the *server's* filesystem
    (a native OS dialog would open on the wrong machine; a recursive-glob tree
    component would choke on large HPC trees). It lists one level at a time
    (a single ``iterdir``).

    Selection model: the text field holds the **committed** selection (type or
    paste a path directly). The "Browse" expander below it navigates without
    committing — clicking folders/breadcrumbs reruns only a fragment, not the
    whole page — until **✓ Use this folder** commits the browsed directory.
    With ``allow_create`` a new folder can be made. Returns the committed path.
    """
    sel_key = f"__dp_{key}"        # committed selection (= text input state)
    cwd_key = f"__dp_{key}_cwd"    # directory the browser is currently showing
    new_key = f"__dp_{key}_new"
    err_key = f"__dp_{key}_err"
    flt_key = f"__dp_{key}_flt"

    if sel_key not in st.session_state:
        st.session_state[sel_key] = default or str(Path.home())
    if cwd_key not in st.session_state:
        st.session_state[cwd_key] = str(_nearest_dir(st.session_state[sel_key]))

    def _typed():
        st.session_state[cwd_key] = str(_nearest_dir(st.session_state[sel_key]))

    def _commit():
        # runs before widgets instantiate, so writing the text input's state is legal
        st.session_state[sel_key] = st.session_state[cwd_key]

    def _goto(target):
        st.session_state[cwd_key] = str(target)
        st.session_state[flt_key] = ""

    def _create():
        name = (st.session_state.get(new_key) or "").strip()
        if name:
            target = Path(st.session_state[cwd_key]) / name
            try:
                target.mkdir(parents=True, exist_ok=True)
                _goto(target)
                st.session_state[new_key] = ""
            except OSError as e:
                st.session_state[err_key] = str(e)

    st.text_input(label, key=sel_key, on_change=_typed,
                  help=help or "Type / paste a path, or pick one with Browse below.")

    @st.fragment
    def _browser():
        cwd = Path(st.session_state[cwd_key])

        # breadcrumb — click any segment to jump straight there
        crumbs = cwd.parts
        with st.container(horizontal=True, gap=None, vertical_alignment="center"):
            for i, part in enumerate(crumbs):
                if i >= 2:
                    st.markdown("/")
                st.button(part, key=f"{key}_bc{i}", type="tertiary",
                          on_click=_goto, args=(Path(*crumbs[: i + 1]),))

        bar = st.columns([3, 1]) if allow_create else st.columns([1])
        flt = bar[0].text_input("filter", key=flt_key, placeholder="filter folders…",
                                label_visibility="collapsed")
        if allow_create:
            with bar[1].popover("➕ New", width="stretch"):
                st.text_input("New folder name", key=new_key, placeholder="folder name")
                st.button("Create here", key=f"{key}_mk", on_click=_create)
                if (err := st.session_state.pop(err_key, None)):
                    st.error(f"Could not create folder: {err}")

        subdirs: list[str] = []
        unreadable = False
        try:
            subdirs = sorted(
                d.name for d in cwd.iterdir() if d.is_dir() and not d.name.startswith(".")
            )
        except OSError:
            unreadable = True
        if flt:
            subdirs = [d for d in subdirs if flt.lower() in d.lower()]

        with st.container(height=_DP_LIST_HEIGHT, border=True):
            if unreadable:
                st.caption("🚫 cannot read this directory")
            elif not subdirs:
                st.caption("(no subfolders here)" if not flt else "(no folders match the filter)")
            else:
                for i, name in enumerate(subdirs[:_DP_MAX_BUTTONS]):
                    st.button(f"📁 {name}", key=f"{key}_d{i}", type="tertiary",
                              on_click=_goto, args=(cwd / name,))
                if len(subdirs) > _DP_MAX_BUTTONS:
                    st.caption(f"… {len(subdirs) - _DP_MAX_BUTTONS} more — narrow with the filter")

        if st.button("✓ Use this folder", key=f"{key}_use", type="primary",
                     on_click=_commit):
            st.rerun(scope="app")  # propagate the new selection to the whole page

    with st.expander("📂 Browse"):
        _browser()

    sel = st.session_state[sel_key]
    if not sel:
        st.caption("No folder selected.")
    elif Path(sel).is_dir():
        st.caption(f"✓ Selected: `{sel}`")
    elif must_exist:
        st.caption(f"⚠ does not exist: `{sel}`")
    else:
        st.caption(f"↳ will be created: `{sel}`")

    return sel


def job_card(job_id: str, name: str, state: str, time_used: str = "", partition: str = ""):
    """Display a job status card."""
    state_colors = {
        "RUNNING": "blue",
        "PENDING": "orange",
        "COMPLETED": "green",
        "FAILED": "red",
        "CANCELLED": "gray",
        "TIMEOUT": "red",
    }
    color = state_colors.get(state, "gray")

    st.markdown(
        f"""
        <div style="border-left: 4px solid {color}; padding: 8px 12px; margin: 4px 0;
                    background: rgba(0,0,0,0.02); border-radius: 0 4px 4px 0;">
            <strong>{name}</strong> (Job {job_id})<br/>
            <span style="color: {color}; font-weight: bold;">{state}</span>
            {f' | {time_used}' if time_used else ''}
            {f' | {partition}' if partition else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def progress_bar(current: int, total: int, label: str = ""):
    """Display a labeled progress bar."""
    if total == 0:
        return
    pct = current / total
    st.progress(pct, text=f"{label}: {current}/{total}" if label else f"{current}/{total}")


def status_badge(status: str) -> str:
    """Return an emoji badge for a status string."""
    badges = {
        "complete": "\u2705",
        "running": "\U0001f535",
        "pending": "\U0001f7e1",
        "failed": "\u274c",
        "missing": "\u2b1c",
        "keep": "\u2705",
        "exclude": "\u274c",
        "investigate": "\U0001f50d",
    }
    return badges.get(status.lower(), "\u2753")


def subject_session_selector(
    subjects: list[str],
    sessions: list[str],
    key_prefix: str = "",
    multiselect: bool = False,
) -> tuple:
    """Render subject/session selection widgets.

    Returns
    -------
    tuple
        (selected_subjects, selected_sessions) — lists if multiselect, else single values.
    """
    col1, col2 = st.columns(2)
    with col1:
        if multiselect:
            selected_subs = st.multiselect(
                "Subjects", subjects, key=f"{key_prefix}_subjects"
            )
        else:
            selected_subs = st.selectbox(
                "Subject", subjects, key=f"{key_prefix}_subject"
            )
    with col2:
        if multiselect:
            selected_ses = st.multiselect(
                "Sessions", sessions, key=f"{key_prefix}_sessions"
            )
        else:
            selected_ses = st.selectbox(
                "Session", sessions, key=f"{key_prefix}_session"
            )
    return selected_subs, selected_ses


def load_config_or_warn():
    """Try to load config, show warning if not found. Returns config or None."""
    try:
        from ..config import load_config
        return load_config()
    except FileNotFoundError:
        st.error(
            "Configuration not found. Please complete **Project Setup** first."
        )
        st.stop()
    except Exception as e:
        st.error(f"Error loading config: {e}")
        st.stop()
