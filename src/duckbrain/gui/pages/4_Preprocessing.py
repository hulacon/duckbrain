"""Page 4: Preprocessing — fMRIPrep, NORDIC, MRIQC submission."""

import streamlit as st
import pandas as pd
from pathlib import Path


st.set_page_config(page_title="Preprocessing — duckbrain", layout="wide")
st.title("Preprocessing")

# ---- Load config ----
try:
    from duckbrain.config import load_config
    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
bids_dir = paths.get("bids_dir", "")
work_dir = paths.get("work_dir", "")
# Logs, submitted scripts, and BIDS filter files must be on shared FS (not
# node-local work_dir=/tmp): SLURM logs are read back from the login node, and
# a filter file passed to a compute-node job must be visible there.
log_dir = paths.get("log_dir", "") or f"{work_dir}/logs"

if not bids_dir or not Path(bids_dir).is_dir():
    st.error("BIDS directory not found. Check Project Setup.")
    st.stop()

Path(log_dir).mkdir(parents=True, exist_ok=True)

# ---- Discover subjects/sessions ----
bids_path = Path(bids_dir)
subjects = sorted(
    d.name.replace("sub-", "")
    for d in bids_path.iterdir()
    if d.is_dir() and d.name.startswith("sub-")
)

if not subjects:
    st.warning("No subjects found in BIDS directory.")
    st.stop()


def _get_sessions(subject: str) -> list[str]:
    sub_dir = bids_path / f"sub-{subject}"
    return sorted(
        d.name.replace("ses-", "")
        for d in sub_dir.iterdir()
        if d.is_dir() and d.name.startswith("ses-")
    )


def _targets(subject: str, selected_sessions: list[str]) -> list[str]:
    """Sessions to process for *subject*.

    A subject with no ``ses-`` level (single-session study) yields ``[""]`` — one
    run, no session entity. A multi-session subject yields the intersection of
    its sessions with the user's selection.
    """
    subj_ses = _get_sessions(subject)
    if not subj_ses:
        return [""]
    return [s for s in selected_sessions if s in subj_ses]


def _session_picker(selected_subjects: list[str], key: str) -> tuple[list[str], list[str]]:
    """Render the Sessions multiselect (hidden for single-session studies).

    Returns ``(study_sessions, selected)`` where ``study_sessions`` is empty when
    no selected subject has a ``ses-`` level.
    """
    study_sessions = sorted({s for sub in selected_subjects for s in _get_sessions(sub)})
    if study_sessions:
        return study_sessions, st.multiselect("Sessions", study_sessions, key=key)
    if selected_subjects:
        st.caption("Single-session study (no ses- entity)")
    return [], []


# ---- Tabs ----
tab_fmriprep, tab_nordic, tab_mriqc = st.tabs(["fMRIPrep", "NORDIC", "MRIQC"])

# ============================================================
# fMRIPrep Tab
# ============================================================
with tab_fmriprep:
    st.subheader("fMRIPrep")

    if config.get("nordic", {}).get("use_nordic", False):
        st.info("🧊 **use_nordic** is on for this project — fMRIPrep runs on the "
                "NORDIC-denoised input (`derivatives/nordic/bids_format`) and "
                "requires the NORDIC stage to be complete for each subject first.")

    col1, col2 = st.columns(2)
    with col1:
        fp_subjects = st.multiselect("Subjects", subjects, key="fp_subjects")
    with col2:
        fp_study_sessions, fp_sessions = _session_picker(fp_subjects, "fp_sessions")

    st.markdown("**Options**")
    col1, col2, col3 = st.columns(3)
    with col1:
        fp_spaces = st.text_input(
            "Output spaces",
            value=" ".join(config.get("fmriprep", {}).get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])),
        )
    with col2:
        fp_nprocs = st.number_input("nprocs", value=config.get("fmriprep", {}).get("nprocs", 8), min_value=1)
        fp_mem = st.number_input("mem_gb", value=config.get("fmriprep", {}).get("mem_gb", 32), min_value=4)
    with col3:
        fp_anat_only = st.checkbox("Anat-only mode", value=False)
        fp_use_derivatives = st.checkbox("Reuse anat derivatives", value=False)

    fp_extra_flags = st.text_input(
        "Custom fMRIPrep flags",
        value=config.get("fmriprep", {}).get("extra_flags", ""),
        help="Extra flags appended verbatim to the fMRIPrep command, e.g. "
        "`--fs-no-reconall --dummy-scans 2 --bold2anat-dof 12`. Applied to every "
        "selected subject/session. Don't repeat flags duckbrain already sets "
        "(output spaces, nprocs, mem, -w, filter file).",
    )

    # SLURM resources
    from duckbrain.config import get_slurm_resources
    fp_slurm = get_slurm_resources(config, "fmriprep")
    with st.expander("SLURM Resources"):
        st.json(fp_slurm)

    col1, col2 = st.columns(2)
    with col1:
        fp_submit = st.button("Submit fMRIPrep Jobs", type="primary", key="fp_submit")
    with col2:
        fp_export = st.button("Export Scripts", key="fp_export")

    if fp_submit or fp_export:
        if not fp_subjects:
            st.error("Select at least one subject.")
        elif fp_study_sessions and not fp_sessions:
            st.error("Select at least one session.")
        else:
            from duckbrain.core.pipeline import advance_one

            results = []
            for sub in fp_subjects:
                for ses in _targets(sub, fp_sessions):
                    try:
                        ref = advance_one(
                            config, "fmriprep", sub, ses,
                            export_only=fp_export,
                            output_spaces=fp_spaces, anat_only=fp_anat_only,
                            use_derivatives=fp_use_derivatives,
                            extra_flags=fp_extra_flags, nprocs=fp_nprocs, mem_gb=fp_mem,
                        )
                        if fp_submit:
                            results.append({"subject": sub, "session": ses, "job_id": ref, "status": "submitted"})
                        else:
                            results.append({"subject": sub, "session": ses, "path": ref, "status": "exported"})
                    except Exception as e:
                        results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

            st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)

# ============================================================
# NORDIC Tab
# ============================================================
with tab_nordic:
    st.subheader("NORDIC Denoising")

    col1, col2 = st.columns(2)
    with col1:
        nd_subjects = st.multiselect("Subjects", subjects, key="nd_subjects")
    with col2:
        nd_study_sessions, nd_sessions = _session_picker(nd_subjects, "nd_sessions")

    # Show BOLD count per selection
    if nd_subjects and (nd_sessions or not nd_study_sessions):
        from duckbrain.core.nordic import get_bold_runs
        for sub in nd_subjects:
            for ses in _targets(sub, nd_sessions):
                bolds = get_bold_runs(bids_dir, sub, ses)
                label = f"sub-{sub}/ses-{ses}" if ses else f"sub-{sub}"
                st.markdown(f"{label}: **{len(bolds)} BOLD runs**")

    nd_slurm = get_slurm_resources(config, "nordic")
    with st.expander("SLURM Resources"):
        st.json(nd_slurm)

    col1, col2 = st.columns(2)
    with col1:
        nd_submit = st.button("Submit NORDIC Jobs", type="primary", key="nd_submit")
    with col2:
        nd_export = st.button("Export Scripts", key="nd_export")

    if nd_submit or nd_export:
        if not nd_subjects:
            st.error("Select at least one subject.")
        elif nd_study_sessions and not nd_sessions:
            st.error("Select at least one session.")
        else:
            from duckbrain.core.pipeline import advance_one

            results = []
            for sub in nd_subjects:
                for ses in _targets(sub, nd_sessions):
                    try:
                        ref = advance_one(config, "nordic", sub, ses, export_only=nd_export)
                        if nd_submit:
                            results.append({"subject": sub, "session": ses, "job_id": ref, "status": "submitted"})
                        else:
                            results.append({"subject": sub, "session": ses, "path": ref, "status": "exported"})
                    except Exception as e:
                        results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

            st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)

# ============================================================
# MRIQC Tab
# ============================================================
with tab_mriqc:
    st.subheader("MRIQC")

    col1, col2 = st.columns(2)
    with col1:
        mq_subjects = st.multiselect("Subjects", subjects, key="mq_subjects")
    with col2:
        mq_study_sessions, mq_sessions = _session_picker(mq_subjects, "mq_sessions")

    mq_slurm = get_slurm_resources(config, "mriqc")
    with st.expander("SLURM Resources"):
        st.json(mq_slurm)

    col1, col2 = st.columns(2)
    with col1:
        mq_submit = st.button("Submit MRIQC Jobs", type="primary", key="mq_submit")
    with col2:
        mq_export = st.button("Export Scripts", key="mq_export")

    if mq_submit or mq_export:
        if not mq_subjects:
            st.error("Select at least one subject.")
        elif mq_study_sessions and not mq_sessions:
            st.error("Select at least one session.")
        else:
            from duckbrain.core.pipeline import advance_one

            results = []
            for sub in mq_subjects:
                for ses in _targets(sub, mq_sessions):
                    try:
                        ref = advance_one(config, "mriqc", sub, ses, export_only=mq_export)
                        if mq_submit:
                            results.append({"subject": sub, "session": ses, "job_id": ref, "status": "submitted"})
                        else:
                            results.append({"subject": sub, "session": ses, "path": ref, "status": "exported"})
                    except Exception as e:
                        results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

            st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
