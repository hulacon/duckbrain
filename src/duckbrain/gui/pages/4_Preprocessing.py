"""Page 4: Preprocessing — fMRIPrep, NORDIC, MRIQC submission."""

from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Preprocessing — duckbrain", layout="wide")
st.title("Preprocessing")

# ---- Load config ----
try:
    # get_slurm_resources is imported here, not in the fMRIPrep tab: all three
    # tabs read it, and a tab body that returns early would leave the others
    # with a NameError.
    from duckbrain.config import get_slurm_resources, load_config
    from duckbrain.gui import preproc_panels

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
subjects = preproc_panels.list_subjects(bids_path)

if not subjects:
    st.warning("No subjects found in BIDS directory.")
    st.stop()

# ---- Tabs ----
tab_fmriprep, tab_nordic, tab_mriqc = st.tabs(["fMRIPrep", "NORDIC", "MRIQC"])

# ============================================================
# fMRIPrep Tab
# ============================================================
with tab_fmriprep:
    st.subheader("fMRIPrep")

    if config.get("nordic", {}).get("use_nordic", False):
        st.info(
            "🧊 **use_nordic** is on for this project — fMRIPrep runs on the "
            "NORDIC-denoised input (`derivatives/nordic/bids_format`) and "
            "requires the NORDIC stage to be complete for each subject first."
        )

    col1, col2 = st.columns(2)
    with col1:
        fp_subjects = st.multiselect("Subjects", subjects, key="fp_subjects")
    with col2:
        fp_study_sessions, fp_sessions = preproc_panels.session_picker(
            bids_path, fp_subjects, "fp_sessions"
        )

    st.markdown("**Options**")
    col1, col2, col3 = st.columns(3)
    with col1:
        fp_spaces = st.text_input(
            "Output spaces",
            value=" ".join(
                config.get("fmriprep", {}).get(
                    "output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"]
                )
            ),
            key="fp_spaces",
        )
    with col2:
        fp_nprocs = st.number_input(
            "nprocs",
            value=config.get("fmriprep", {}).get("nprocs", 8),
            min_value=1,
            key="fp_nprocs",
        )
        fp_mem = st.number_input(
            "mem_gb", value=config.get("fmriprep", {}).get("mem_gb", 32), min_value=4, key="fp_mem"
        )
    with col3:
        fp_anat_only = st.checkbox("Anat-only mode", value=False, key="fp_anat_only")
        fp_use_derivatives = st.checkbox(
            "Reuse anat derivatives",
            value=False,
            key="fp_use_derivatives",
            help="Reuses preprocessed anatomicals instead of rebuilding them. The "
            "anat may come from any session of the subject — that is the point in a "
            "longitudinal study, where it is acquired once and shared. Requires a "
            "prior Anat-only run: any selected subject without one is reported as an "
            "error below rather than submitted. If you are re-running because the "
            "anat went wrong, leave this off.",
        )

    fp_extra_flags = st.text_input(
        "Custom fMRIPrep flags",
        value=config.get("fmriprep", {}).get("extra_flags", ""),
        key="fp_extra_flags",
        help="Extra flags appended verbatim to the fMRIPrep command, e.g. "
        "`--fs-no-reconall --dummy-scans 2 --bold2anat-dof 12`. Applied to every "
        "selected subject/session. Don't repeat flags duckbrain already sets "
        "(output spaces, nprocs, mem, -w, filter file).",
    )

    # SLURM resources
    fp_slurm = get_slurm_resources(config, "fmriprep")
    with st.expander("SLURM Resources"):
        st.json(fp_slurm)

    col1, col2 = st.columns(2)
    with col1:
        fp_submit = st.button("Submit fMRIPrep Jobs", type="primary", key="fp_submit")
    with col2:
        fp_export = st.button("Export Scripts", key="fp_export")

    if fp_submit or fp_export:
        preproc_panels.run_batch(
            config,
            "fmriprep",
            bids_path,
            fp_subjects,
            fp_sessions,
            fp_study_sessions,
            submit=fp_submit,
            export=fp_export,
            output_spaces=fp_spaces,
            anat_only=fp_anat_only,
            use_derivatives=fp_use_derivatives,
            extra_flags=fp_extra_flags,
            nprocs=fp_nprocs,
            mem_gb=fp_mem,
        )

# ============================================================
# NORDIC Tab
# ============================================================
with tab_nordic:
    st.subheader("NORDIC Denoising")

    col1, col2 = st.columns(2)
    with col1:
        nd_subjects = st.multiselect("Subjects", subjects, key="nd_subjects")
    with col2:
        nd_study_sessions, nd_sessions = preproc_panels.session_picker(
            bids_path, nd_subjects, "nd_sessions"
        )

    # Show BOLD count per selection
    if nd_subjects and (nd_sessions or not nd_study_sessions):
        from duckbrain.core.nordic import get_bold_runs

        for sub in nd_subjects:
            for ses in preproc_panels.targets(bids_path, sub, nd_sessions):
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
        preproc_panels.run_batch(
            config,
            "nordic",
            bids_path,
            nd_subjects,
            nd_sessions,
            nd_study_sessions,
            submit=nd_submit,
            export=nd_export,
        )

# ============================================================
# MRIQC Tab
# ============================================================
with tab_mriqc:
    st.subheader("MRIQC")

    col1, col2 = st.columns(2)
    with col1:
        mq_subjects = st.multiselect("Subjects", subjects, key="mq_subjects")
    with col2:
        mq_study_sessions, mq_sessions = preproc_panels.session_picker(
            bids_path, mq_subjects, "mq_sessions"
        )

    mq_slurm = get_slurm_resources(config, "mriqc")
    with st.expander("SLURM Resources"):
        st.json(mq_slurm)

    col1, col2 = st.columns(2)
    with col1:
        mq_submit = st.button("Submit MRIQC Jobs", type="primary", key="mq_submit")
    with col2:
        mq_export = st.button("Export Scripts", key="mq_export")

    if mq_submit or mq_export:
        preproc_panels.run_batch(
            config,
            "mriqc",
            bids_path,
            mq_subjects,
            mq_sessions,
            mq_study_sessions,
            submit=mq_submit,
            export=mq_export,
        )
