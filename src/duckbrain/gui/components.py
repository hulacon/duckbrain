"""Shared Streamlit widgets for duckbrain GUI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


_DP_GRID_COLS = 3
_DP_MAX_BUTTONS = 300


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
    (a single ``iterdir``): **click a folder to open it**, use ⬆ Up to go up, or
    type / paste a full path. With ``allow_create`` a new folder can be made.
    The currently shown directory is the selection. Returns its path string.
    """
    cur_key = f"__dp_{key}"
    new_key = f"__dp_{key}_new"
    err_key = f"__dp_{key}_err"
    flt_key = f"__dp_{key}_flt"

    if cur_key not in st.session_state:
        st.session_state[cur_key] = default or str(Path.home())

    def _goto(target):
        st.session_state[cur_key] = str(target)
        st.session_state[flt_key] = ""

    def _up():
        _goto(Path(st.session_state[cur_key]).parent)

    def _create():
        name = (st.session_state.get(new_key) or "").strip()
        if name:
            target = Path(st.session_state[cur_key]) / name
            try:
                target.mkdir(parents=True, exist_ok=True)
                _goto(target)
                st.session_state[new_key] = ""
            except OSError as e:
                st.session_state[err_key] = str(e)

    st.text_input(label, key=cur_key, help=help or "Click a folder to open it, or type / paste a full path.")
    cur = Path(st.session_state[cur_key]) if st.session_state[cur_key] else None

    bar = st.columns([1, 1, 3]) if allow_create else st.columns([1, 4])
    bar[0].button("⬆ Up", key=f"{key}_up", on_click=_up, use_container_width=True)
    if allow_create:
        with bar[1].expander("➕ New"):
            st.text_input("New folder name", key=new_key, label_visibility="collapsed",
                          placeholder="folder name")
            st.button("Create here", key=f"{key}_mk", on_click=_create)
    flt = bar[-1].text_input("filter", key=flt_key, placeholder="filter folders…",
                             label_visibility="collapsed")

    subdirs: list[str] = []
    unreadable = False
    if cur and cur.is_dir():
        try:
            subdirs = sorted(
                d.name for d in cur.iterdir() if d.is_dir() and not d.name.startswith(".")
            )
        except OSError:
            unreadable = True
    if flt:
        subdirs = [d for d in subdirs if flt.lower() in d.lower()]

    if unreadable:
        st.caption("🚫 cannot read this directory")
    elif subdirs:
        cols = st.columns(_DP_GRID_COLS)
        for i, name in enumerate(subdirs[:_DP_MAX_BUTTONS]):
            cols[i % _DP_GRID_COLS].button(
                f"📁 {name}", key=f"{key}_d{i}", on_click=_goto,
                args=(cur / name,), use_container_width=True,
            )
        if len(subdirs) > _DP_MAX_BUTTONS:
            st.caption(f"… {len(subdirs) - _DP_MAX_BUTTONS} more — narrow with the filter")
    elif cur and cur.is_dir():
        st.caption("(no subfolders here)" if not flt else "(no folders match the filter)")

    if (err := st.session_state.pop(err_key, None)):
        st.error(f"Could not create folder: {err}")

    if not st.session_state[cur_key]:
        st.caption("No folder selected.")
    elif cur and cur.is_dir():
        st.caption(f"✓ Selected: `{cur}`")
    elif must_exist:
        st.caption(f"⚠ does not exist: `{st.session_state[cur_key]}`")
    else:
        st.caption(f"↳ will be created: `{st.session_state[cur_key]}`")

    return st.session_state[cur_key]


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
