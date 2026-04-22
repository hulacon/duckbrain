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
derivatives_dir = paths.get("derivatives_dir", "")
work_dir = paths.get("work_dir", "")

if not bids_dir or not Path(bids_dir).is_dir():
    st.error("BIDS directory not found. Check Project Setup.")
    st.stop()

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


# ---- Tabs ----
tab_fmriprep, tab_nordic, tab_mriqc = st.tabs(["fMRIPrep", "NORDIC", "MRIQC"])

# ============================================================
# fMRIPrep Tab
# ============================================================
with tab_fmriprep:
    st.subheader("fMRIPrep")

    col1, col2 = st.columns(2)
    with col1:
        fp_subjects = st.multiselect("Subjects", subjects, key="fp_subjects")
    with col2:
        all_sessions = set()
        for s in fp_subjects:
            all_sessions.update(_get_sessions(s))
        fp_sessions = st.multiselect("Sessions", sorted(all_sessions), key="fp_sessions")

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
        if not fp_subjects or not fp_sessions:
            st.error("Select at least one subject and session.")
        else:
            from duckbrain.slurm.templates import render_sbatch, build_context
            from duckbrain.core.fmriprep import get_container_path, find_fs_license

            container = get_container_path(config)
            fs_license = find_fs_license(config)
            if not fs_license:
                st.error("FreeSurfer license not found. Set it in Project Setup.")
            else:
                output_dir = f"{derivatives_dir}/fmriprep"
                results = []
                for sub in fp_subjects:
                    for ses in fp_sessions:
                        if ses not in _get_sessions(sub):
                            continue
                        ctx = build_context(
                            config, "fmriprep",
                            subject=sub, session=ses,
                            bids_dir=bids_dir,
                            output_dir=output_dir,
                            container_path=str(container),
                            fs_license=str(fs_license),
                            fs_license_dir=str(fs_license.parent),
                            output_spaces=fp_spaces.split(),
                            filter_file="",
                            anat_only=fp_anat_only,
                            derivatives=f"{derivatives_dir}/fmriprep" if fp_use_derivatives else "",
                        )
                        try:
                            script = render_sbatch("fmriprep", ctx)
                            if fp_submit:
                                from duckbrain.slurm.submit import submit_job
                                job_id = submit_job(script, f"fmriprep_{sub}_{ses}", scripts_dir=f"{work_dir}/scripts")
                                results.append({"subject": sub, "session": ses, "job_id": job_id, "status": "submitted"})
                            else:
                                from duckbrain.slurm.submit import export_script
                                path = export_script(script, Path(work_dir) / "scripts" / f"fmriprep_{sub}_{ses}.sbatch")
                                results.append({"subject": sub, "session": ses, "path": str(path), "status": "exported"})
                        except Exception as e:
                            results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

                st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

# ============================================================
# NORDIC Tab
# ============================================================
with tab_nordic:
    st.subheader("NORDIC Denoising")

    col1, col2 = st.columns(2)
    with col1:
        nd_subjects = st.multiselect("Subjects", subjects, key="nd_subjects")
    with col2:
        nd_all_sessions = set()
        for s in nd_subjects:
            nd_all_sessions.update(_get_sessions(s))
        nd_sessions = st.multiselect("Sessions", sorted(nd_all_sessions), key="nd_sessions")

    # Show BOLD count per selection
    if nd_subjects and nd_sessions:
        from duckbrain.core.nordic import get_bold_runs
        for sub in nd_subjects:
            for ses in nd_sessions:
                if ses not in _get_sessions(sub):
                    continue
                bolds = get_bold_runs(bids_dir, sub, ses)
                st.markdown(f"sub-{sub}/ses-{ses}: **{len(bolds)} BOLD runs**")

    nd_slurm = get_slurm_resources(config, "nordic")
    with st.expander("SLURM Resources"):
        st.json(nd_slurm)

    col1, col2 = st.columns(2)
    with col1:
        nd_submit = st.button("Submit NORDIC Jobs", type="primary", key="nd_submit")
    with col2:
        nd_export = st.button("Export Scripts", key="nd_export")

    if nd_submit or nd_export:
        if not nd_subjects or not nd_sessions:
            st.error("Select at least one subject and session.")
        else:
            from duckbrain.slurm.templates import render_sbatch, build_context
            from duckbrain.core.nordic import get_bold_runs
            import sys

            scripts_dir = Path(__file__).resolve().parents[4] / "scripts"
            results = []
            for sub in nd_subjects:
                for ses in nd_sessions:
                    if ses not in _get_sessions(sub):
                        continue
                    bolds = get_bold_runs(bids_dir, sub, ses)
                    if not bolds:
                        results.append({"subject": sub, "session": ses, "status": "no BOLD files"})
                        continue
                    ctx = build_context(
                        config, "nordic",
                        subject=sub, session=ses,
                        bold_count=len(bolds),
                        scripts_dir=str(scripts_dir),
                        python_cmd=sys.executable,
                    )
                    try:
                        script = render_sbatch("nordic_denoise", ctx)
                        if nd_submit:
                            from duckbrain.slurm.submit import submit_job
                            job_id = submit_job(script, f"nordic_{sub}_{ses}", scripts_dir=f"{work_dir}/scripts")
                            results.append({"subject": sub, "session": ses, "job_id": job_id, "status": "submitted"})
                        else:
                            from duckbrain.slurm.submit import export_script
                            path = export_script(script, Path(work_dir) / "scripts" / f"nordic_{sub}_{ses}.sbatch")
                            results.append({"subject": sub, "session": ses, "path": str(path), "status": "exported"})
                    except Exception as e:
                        results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

# ============================================================
# MRIQC Tab
# ============================================================
with tab_mriqc:
    st.subheader("MRIQC")

    col1, col2 = st.columns(2)
    with col1:
        mq_subjects = st.multiselect("Subjects", subjects, key="mq_subjects")
    with col2:
        mq_all_sessions = set()
        for s in mq_subjects:
            mq_all_sessions.update(_get_sessions(s))
        mq_sessions = st.multiselect("Sessions", sorted(mq_all_sessions), key="mq_sessions")

    mq_slurm = get_slurm_resources(config, "mriqc")
    with st.expander("SLURM Resources"):
        st.json(mq_slurm)

    col1, col2 = st.columns(2)
    with col1:
        mq_submit = st.button("Submit MRIQC Jobs", type="primary", key="mq_submit")
    with col2:
        mq_export = st.button("Export Scripts", key="mq_export")

    if mq_submit or mq_export:
        if not mq_subjects or not mq_sessions:
            st.error("Select at least one subject and session.")
        else:
            from duckbrain.slurm.templates import render_sbatch, build_context
            from duckbrain.core.mriqc import get_container_path as get_mriqc_container

            container = get_mriqc_container(config)
            results = []
            for sub in mq_subjects:
                for ses in mq_sessions:
                    if ses not in _get_sessions(sub):
                        continue
                    # Parse memory as integer GB
                    mem_str = mq_slurm.get("memory", "16G")
                    mem_gb = int(mem_str.replace("G", "").replace("g", ""))
                    ctx = build_context(
                        config, "mriqc",
                        subject=sub, session=ses,
                        container_path=str(container),
                        mem_gb=mem_gb,
                    )
                    try:
                        script = render_sbatch("mriqc", ctx)
                        if mq_submit:
                            from duckbrain.slurm.submit import submit_job
                            job_id = submit_job(script, f"mriqc_{sub}_{ses}", scripts_dir=f"{work_dir}/scripts")
                            results.append({"subject": sub, "session": ses, "job_id": job_id, "status": "submitted"})
                        else:
                            from duckbrain.slurm.submit import export_script
                            path = export_script(script, Path(work_dir) / "scripts" / f"mriqc_{sub}_{ses}.sbatch")
                            results.append({"subject": sub, "session": ses, "path": str(path), "status": "exported"})
                    except Exception as e:
                        results.append({"subject": sub, "session": ses, "status": "error", "error": str(e)})

            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
