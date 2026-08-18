"""Page 3a: Project — the dataset-management surface.

Status and Setup used to straddle three concerns — machine/user *config*,
project *management*, and *orchestration* — and the seams showed as pages that
felt like they were about several things at once. This page is the management
concern on its own: the BIDS root's metadata files (`participants.tsv`,
`dataset_description.json`), the standard validator, and the study's declared
expectations. Setup keeps machine/user config and project creation; Status is
purely the cockpit + SLURM view.

The panels are on-demand on purpose: everything here that costs a subprocess or
opens data runs only inside its button, never on a plain render. The warnings
the expectation checks produce still render on **Status**, next to the board
they judge — this page is where the declaration is *made*, not where its
shortfall is read.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Project — duckbrain", layout="wide")
st.title("Project")
st.caption(
    "Manage the open project as a dataset: the BIDS root's metadata files, "
    "standard validation, and what a session of this study should contain."
)

# ---- Load config ----
try:
    from duckbrain.config import load_config

    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
bids_dir = paths.get("bids_dir", "")
sourcedata_dir = paths.get("sourcedata_dir", "")
if not bids_dir:
    st.error("Project directory not set. Start with **Project Setup**.")
    st.stop()

from duckbrain.gui.components import flush_toasts, queue_toast

# A save on the previous run confirms itself here; see `components.queue_toast`
# for why it cannot confirm itself next to the save.
flush_toasts()


def _unit_label(subject: str, session: str) -> str:
    return f"sub-{subject}" + (f" / ses-{session}" if session else "")


# ---- BIDS metadata files ----
st.subheader("BIDS metadata")
st.markdown("Generate `participants.tsv` and `dataset_description.json` from DICOM demographics.")

col1, col2 = st.columns(2)
with col1:
    if st.button("Generate participants.tsv"):
        if not sourcedata_dir or not Path(sourcedata_dir).is_dir():
            st.error("No sourcedata found — ingest sessions on **Ingestion** first.")
        else:
            from duckbrain.core.bids_metadata import generate_participants_from_sourcedata

            try:
                tsv_path = generate_participants_from_sourcedata(sourcedata_dir, bids_dir)
                participants_df = pd.read_csv(tsv_path, sep="\t")
                if participants_df.empty:
                    st.warning(
                        f"No ingested subjects found under `{sourcedata_dir}` — "
                        "ingest sessions on the Ingestion page first. Wrote a "
                        f"header-only `{tsv_path}`."
                    )
                else:
                    st.success(f"Written: `{tsv_path}` ({len(participants_df)} subjects)")
                    st.dataframe(participants_df, width="stretch", hide_index=True)
            except Exception as e:
                st.error(f"Error: {e}")

with col2:
    if st.button("Generate dataset_description.json"):
        from duckbrain.core.bids_metadata import (
            converter_generated_by,
            dataset_extra_fields,
            write_dataset_description,
        )

        project_name = config.get("project", {}).get("name", "")
        try:
            # Record the converter too, not just duckbrain — dcm2bids' version
            # is what determines the BIDS this root contains. This button
            # *refreshes* on demand (after a rename, or new Authors); the
            # conversion choke point only *ensures presence*. Safe to press
            # repeatedly: the write preserves fields duckbrain doesn't own.
            desc_path = write_dataset_description(
                bids_dir,
                name=project_name,
                extra_fields=dataset_extra_fields(config),
                generated_by=converter_generated_by(config),
            )
            st.success(f"Written: `{desc_path}`")
        except Exception as e:
            st.error(f"Error: {e}")

#: Where the panel parks its last result. Not `st.cache_data`: a cache keyed on
#: the dataset path would serve a stale "clean" after a bad conversion, which is
#: the failure mode this whole item exists to remove.
_VALIDATION_STATE = "bids_validation"


def _bids_validation_section() -> None:
    """Run the BIDS validator on demand and show what it found.

    Its own panel rather than a `core/checks.py` REGISTRY entry, for three
    reasons and the first is decisive. (1) `run_checks` returns nothing when a
    project declares no `[expected]`, so registering here would make BIDS
    validation silently conditional on an opt-in that has nothing to do with it —
    the BIDS spec is not a project's declaration of intent. (2) `ConsistencyIssue`
    has no file list, and a validator finding is *about* files; flattening forty
    paths into a message destroys what makes it actionable. (3) It speaks a
    third-party vocabulary (code, helpUrl) and only when asked.

    The subprocess runs only inside the button — a render does a session-state
    lookup and a couple of `Path.exists()` calls, nothing more.
    """
    from duckbrain.core.pipeline import resolve_container
    from duckbrain.core.validation import validate_bids, validator_unavailable_reason

    try:
        container = resolve_container(config, "converted")
    except Exception:
        container = None
    reason = validator_unavailable_reason(container, bids_dir)

    result = st.session_state.get(_VALIDATION_STATE)
    if result is not None and result.bids_dir != str(bids_dir):
        result = None  # a different project's answer is not this project's
    state = result.headline() if result is not None else "not run this session"

    with st.expander(f"🧾 BIDS validation — {state}"):
        st.caption(
            "Checks that the dataset is well **formed** — structure, naming, required "
            "files. It does not check that the data means what you intended: run "
            "against a tree whose fieldmap intent was inverted, it reported zero "
            "fieldmap issues while fMRIPrep silently skipped distortion correction. "
            "A clean result here is a floor, not an all-clear."
        )
        if reason:
            st.info(f"Can't run the validator: {reason}")
        elif st.button("▶ Validate now", key="validate_bids_btn", width="stretch"):
            with st.spinner("Running bids-validator…"):
                st.session_state[_VALIDATION_STATE] = validate_bids(config)
            st.rerun()

        if result is None:
            return
        if not result.ran:
            st.warning(f"The validator did not run: {result.unavailable_reason}")
            return

        for issue in (*result.errors, *result.warnings):
            render = st.error if issue.severity == "error" else st.warning
            render(f"**{issue.code}** — {issue.reason}")
            if issue.files:
                shown = "\n".join(f"- `{p}`" for p in issue.files)
                extra = issue.n_files - len(issue.files)
                if extra > 0:
                    shown += f"\n- …and {extra} more"
                st.caption(shown)
            if issue.help_url:
                st.caption(issue.help_url)

        if not result.issues:
            st.success("No errors or warnings.")

        summary = result.summary or {}
        bits = [f"{summary.get('totalFiles', 0)} files"]
        for key, label in (("subjects", "subjects"), ("sessions", "sessions"), ("tasks", "tasks")):
            n = len(summary.get(key) or [])
            if n:
                bits.append(f"{n} {label}")
        st.caption(
            f"{' · '.join(bits)} — measured {result.ran_at:%Y-%m-%d %H:%M:%S} "
            f"in {result.duration_s:.1f}s"
        )


def _expectations_section() -> None:
    """Declare what a session of this study should contain — elicit, then freeze.

    The elicit-from-a-good-session flow is the whole usability argument for the
    feature: nobody hand-writes a declaration, so the draft has to come from data
    the user has already reviewed. What makes it worth anything is that it is then
    *frozen* — every later session is judged against that one instead of against
    itself, which is the circularity `core/expectations.py` exists to break.

    Deliberately not on the Setup page: this is a study-design statement made once
    you have seen a session convert correctly, not a machine setting. The warnings
    it drives render on **Status**, next to the board they judge — the declaration
    lives here, the *reading* stayed with the cockpit.
    """
    from duckbrain.config import resolve_project_dir, save_project_expectations
    from duckbrain.core.expectations import (
        SessionExpectation,
        declared,
        elicit,
        expected_participants,
        has_bids_unit,
    )
    from duckbrain.core.surveyor import discover_units

    current = declared(config) or {}
    label = "🎯 Declared expectations" + ("" if current else " — none set (checks off)")

    with st.expander(label):
        st.caption(
            "Every other expectation in duckbrain is re-derived from the data it "
            "judges, so a run that was never acquired shrinks the expectation to "
            "match and reads complete. This is the one declaration that can't. "
            "Absent means the checks don't run. Shortfalls against it appear as "
            "warnings on **Status**."
        )

        if current:
            want = SessionExpectation.from_config_section(current.get("session"))
            _, count = expected_participants(config)
            bits = []
            if count:
                bits.append(f"**{count}** participants")
            if want.anat:
                bits.append(", ".join(f"**{n}**× {s}" for s, n in sorted(want.anat.items())))
            if want.fmap_pairs:
                bits.append(f"**{want.fmap_pairs}** fieldmap pair(s)")
            if want.task:
                bits.append(
                    ", ".join(f"**{n}** run(s) of `{t}`" for t, n in sorted(want.task.items()))
                )
            st.markdown("Each session should have: " + " · ".join(bits) if bits else "_(empty)_")
            exceptions = current.get("exceptions") or {}
            if exceptions:
                st.caption(
                    f"{len(exceptions)} accepted deviation(s): "
                    + ", ".join(f"`{k}`" for k in sorted(exceptions))
                    + " — edit these in `code/duckbrain.toml`."
                )

        units = [
            (sub, ses) for sub, ses in discover_units(paths) if has_bids_unit(bids_dir, sub, ses)
        ]
        if not units:
            st.info("Nothing converted yet — there's no session to derive a declaration from.")
            return

        choice = st.selectbox(
            "Derive from a session you've reviewed and trust",
            units,
            format_func=lambda u: _unit_label(*u),
            key="expect_source",
        )
        draft = elicit(config, *choice)
        st.code(str(draft or "{}"), language="python")

        n_participants = st.number_input(
            "Participants this study plans to scan (0 = don't declare)",
            min_value=0,
            value=expected_participants(config)[1],
            key="expect_participants",
            help="The one thing the filesystem genuinely can't know — reading it "
            "back off disk would reproduce the circularity this exists to break. "
            "It's what catches a subject scanned but never ingested.",
        )

        c_save, c_clear = st.columns(2)
        project_dir = resolve_project_dir() or bids_dir
        with c_save:
            if st.button(
                "⭑ Freeze this as the study's expectation",
                width="stretch",
                disabled=not (draft or n_participants),
            ):
                if not project_dir:
                    st.error("No project directory resolved — can't save.")
                else:
                    section = dict(current)
                    if draft:
                        section["session"] = draft
                    if n_participants:
                        section["participants"] = int(n_participants)
                    else:
                        section.pop("participants", None)
                    save_project_expectations(project_dir, section)
                    queue_toast(f"Saved to {project_dir}/code/duckbrain.toml")
                    st.rerun()
        with c_clear:
            if st.button(
                "Remove declaration",
                width="stretch",
                disabled=not current,
                help="Turns the expectation checks back off. Nothing else changes.",
            ):
                save_project_expectations(project_dir, {})
                queue_toast("Declaration removed — expectation checks are off.")
                st.rerun()


_bids_validation_section()
_expectations_section()
