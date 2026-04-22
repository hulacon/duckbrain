"""Shared Streamlit widgets for duckbrain GUI."""

from __future__ import annotations

import streamlit as st


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
