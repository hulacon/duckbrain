"""Subject/session selection and batch launching, for the Preprocessing page.

Lives here rather than in the page for the reason ``gui.qc_panels`` gives: a page
is a Streamlit script no test imports, so logic put there is logic nothing
covers. The concrete debt was three near-verbatim copies of the same submit
loop — one per tab, ~90 of the page's 321 lines — carrying the same dozen branch
paths and differing only in which stage name and which parameters they passed.
:func:`run_batch` is that loop, once.

The selection helpers take ``bids_path`` as an argument instead of closing over a
module global the way the page did, which is what makes :func:`targets` — the
only real logic in the file — testable with a directory and no Streamlit at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


def list_subjects(bids_path: Path) -> list[str]:
    """Subject labels (no ``sub-`` prefix) present in the BIDS root."""
    return sorted(
        d.name.replace("sub-", "")
        for d in bids_path.iterdir()
        if d.is_dir() and d.name.startswith("sub-")
    )


def get_sessions(bids_path: Path, subject: str) -> list[str]:
    """Session labels (no ``ses-`` prefix) for one subject; empty if it has no ses- level."""
    sub_dir = bids_path / f"sub-{subject}"
    if not sub_dir.is_dir():
        return []
    return sorted(
        d.name.replace("ses-", "")
        for d in sub_dir.iterdir()
        if d.is_dir() and d.name.startswith("ses-")
    )


def targets(bids_path: Path, subject: str, selected_sessions: list[str]) -> list[str]:
    """Sessions to process for *subject*.

    A subject with no ``ses-`` level (single-session study) yields ``[""]`` — one
    run, no session entity. A multi-session subject yields the intersection of
    its sessions with the user's selection, which is empty when the two do not
    meet; :func:`run_batch` is what reports that rather than dropping it.
    """
    subj_ses = get_sessions(bids_path, subject)
    if not subj_ses:
        return [""]
    return [s for s in selected_sessions if s in subj_ses]


def session_picker(
    bids_path: Path, selected_subjects: list[str], key: str
) -> tuple[list[str], list[str]]:
    """Render the Sessions multiselect (hidden for single-session studies).

    Returns ``(study_sessions, selected)`` where ``study_sessions`` is empty when
    no selected subject has a ``ses-`` level.
    """
    study_sessions = sorted({s for sub in selected_subjects for s in get_sessions(bids_path, sub)})
    if study_sessions:
        return study_sessions, st.multiselect("Sessions", study_sessions, key=key)
    if selected_subjects:
        st.caption("Single-session study (no ses- entity)")
    return [], []


def run_batch(
    config: dict,
    stage: str,
    bids_path: Path,
    subjects: list[str],
    sessions: list[str],
    study_sessions: list[str],
    *,
    submit: bool,
    export: bool,
    **params: Any,
) -> None:
    """Validate the selection, launch every selected unit, and show the outcome.

    Reports on screen rather than returning: it is the whole body of a tab's
    submit branch. ``submit``/``export`` are the two buttons' return values, so
    at most one is true per rerun.
    """
    if not subjects:
        st.error("Select at least one subject.")
        return
    if study_sessions and not sessions:
        st.error("Select at least one session.")
        return

    # Deferred: core.pipeline pulls in the whole stage registry and its builders,
    # which no render of this page needs until a button is actually pressed.
    from duckbrain.core.pipeline import advance_one

    results = []
    skipped = []
    for sub in subjects:
        unit_sessions = targets(bids_path, sub, sessions)
        if not unit_sessions:
            # Reached when the subject has a ses- level but none of the selected
            # sessions. Naming it is the point: the user asked for this subject,
            # and a batch that silently returns fewer units than were selected
            # looks exactly like one that worked.
            skipped.append(sub)
            continue
        for ses in unit_sessions:
            try:
                ref = advance_one(config, stage, sub, ses, export_only=export, **params)
            except Exception as e:
                # Per unit, so one subject's failed precondition does not sink
                # the rest of the batch. The row is the only channel that says so.
                results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})
                continue
            if submit:
                results.append(
                    {"subject": sub, "session": ses, "job_id": ref, "status": "submitted"}
                )
            else:
                results.append({"subject": sub, "session": ses, "path": ref, "status": "exported"})

    if skipped:
        named = ", ".join(f"sub-{s}" for s in skipped)
        st.warning(
            f"Skipped {named}: no selected session exists for "
            f"{'them' if len(skipped) > 1 else 'it'}. Widen the session selection "
            "to include these subjects."
        )
    if not results:
        # An empty dataframe renders as an empty table and explains nothing.
        # Not reachable from the Preprocessing page as it stands: the session
        # multiselect offers only the union of the selected subjects' sessions,
        # and Streamlit clears the selection when that union changes, so the
        # "Select at least one session" guard above catches it first. It is
        # reachable by any other caller, which is the reason to keep it.
        st.error("Nothing to launch — no selected subject has any selected session.")
        return

    st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
