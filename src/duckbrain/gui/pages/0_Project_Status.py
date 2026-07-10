"""Page 0: Project Status — the pipeline cockpit.

Answers "what's done, what's half-done, what's running, what's left" across the
whole project *and* lets you launch the next step per unit from one place.

Two truths are fused (see ``core.pipeline.survey_live``): filesystem completion
(graded by expected outputs, so a crashed run reads *partial* not done) and live
SLURM state (so a job running *right now* reads *running*, never re-runnable).
The run controls are dependency-gated by ``stage_runnable`` — a stage is only
launchable once its prerequisite is complete and nothing is already queued/running
for it. Ingestion is intentionally not launchable here (it's synchronous and maps
raw scanner folders → units); do that on the Data Ingestion page.
"""

import streamlit as st

st.set_page_config(page_title="Project Status — duckbrain", layout="wide")
st.title("Project Status")
st.caption(
    "Completion by expected outputs (not folder presence) fused with live SLURM "
    "state — a crashed run shows *partial*, a live one shows *running*."
)

# ---- Load config ----
try:
    from duckbrain.config import load_config
    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
if not paths.get("bids_dir"):
    st.error("Project directory not set. Start with **Project Setup**.")
    st.stop()

project_name = config.get("project", {}).get("name", "")
if project_name:
    st.caption(f"Project: **{project_name}** — `{paths['bids_dir']}`")

if st.button("↻ Refresh", help="Re-scan the filesystem and re-query SLURM"):
    st.rerun()

# ---- Survey (filesystem + live SLURM state) ----
from duckbrain.core.surveyor import STAGES, Status, summarize
from duckbrain.core.pipeline import (
    SLURM_STAGES,
    advance_one,
    stage_runnable,
    survey_live,
)

with st.spinner("Surveying project & querying SLURM…"):
    matrix = survey_live(config)

if matrix.empty:
    st.info(
        "No subjects found yet. Ingest DICOMs on the **Data Ingestion** page, or "
        "point Project Setup at a directory that already contains BIDS data."
    )
    st.stop()

# ---- Per-stage rollup ----
summary = summarize(matrix)
st.subheader("Overview")
cols = st.columns(len(STAGES))
for col, stage in zip(cols, STAGES):
    counts = summary[stage]
    done = counts[Status.COMPLETE.value]
    partial = counts[Status.PARTIAL.value]
    missing = counts[Status.MISSING.value]
    col.metric(stage.capitalize(), f"{done}/{len(matrix)}", help="complete / total")
    bits = []
    # Live counts from the job overlay, if this stage has one.
    job_col = f"{stage}_job"
    if job_col in matrix.columns:
        running = int((matrix[job_col] == "running").sum() + (matrix[job_col] == "queued").sum())
        failed = int((matrix[job_col] == "failed").sum())
        if running:
            bits.append(f"🔵 {running} running")
        if failed:
            bits.append(f"🔴 {failed} failed")
    if partial:
        bits.append(f"⚠ {partial} partial")
    if missing:
        bits.append(f"○ {missing} missing")
    col.caption(" · ".join(bits) if bits else "✓ all complete")

# ---- Launch next step (the actionable part) ----
st.subheader("Launch a step")

# Every runnable (unit, stage): stage not complete, no active job, dependency met.
runnable = []
for _, row in matrix.iterrows():
    unit_label = f"sub-{row['subject']}" + (f" / ses-{row['session']}" if row["session"] else "")
    for stage in SLURM_STAGES:
        if stage in matrix.columns and stage_runnable(row, stage):
            runnable.append({
                "label": f"{unit_label}  →  run {stage}",
                "subject": row["subject"], "session": row["session"], "stage": stage,
                "unit": unit_label,
            })

if not runnable:
    st.info(
        "Nothing is ready to launch — every stage is complete, already "
        "running/queued, or waiting on a prior stage. Hit ↻ to refresh, or use the "
        "**Preprocessing** / **BIDS Conversion** pages for bulk or advanced runs."
    )
else:
    labels = [o["label"] for o in runnable]
    choice = st.selectbox("Ready to run", labels, key="cockpit_choice")
    sel = runnable[labels.index(choice)]
    stage, sub, ses = sel["stage"], sel["subject"], sel["session"]

    # Stage params (config defaults; fMRIPrep exposes the common knobs).
    params = {}
    if stage == "fmriprep":
        fp = config.get("fmriprep", {})
        c1, c2, c3 = st.columns(3)
        params["output_spaces"] = c1.text_input(
            "Output spaces",
            value=" ".join(fp.get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])),
            key="ck_fp_spaces")
        params["nprocs"] = c2.number_input("nprocs", value=fp.get("nprocs", 8), min_value=1, key="ck_fp_nprocs")
        params["mem_gb"] = c2.number_input("mem_gb", value=fp.get("mem_gb", 32), min_value=4, key="ck_fp_mem")
        params["anat_only"] = c3.checkbox("Anat-only", key="ck_fp_anat")
        params["use_derivatives"] = c3.checkbox("Reuse anat derivatives", key="ck_fp_deriv")
        params["extra_flags"] = st.text_input(
            "Custom fMRIPrep flags", value=fp.get("extra_flags", ""), key="ck_fp_flags")
    elif stage == "converted":
        params["force"] = st.checkbox("Force re-convert (dcm2bids --force)", key="ck_conv_force")

    if st.button(f"▶ Run {stage} for {sel['unit']}", type="primary", key="cockpit_run"):
        try:
            job_id = advance_one(config, stage, sub, ses, **params)
            st.toast(f"Submitted {stage} for {sel['unit']} — job {job_id}", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"Could not launch: {e}")

# ---- Status matrix ----
st.subheader("Subjects")

only_incomplete = st.checkbox(
    "Show only units with unfinished stages", value=False,
    help="Hide subject/sessions where every stage is complete.",
)

view = matrix.copy()
view["session"] = view["session"].replace("", "—")

if only_incomplete:
    incomplete_mask = matrix[list(STAGES)].apply(
        lambda r: any(v != Status.COMPLETE.value for v in r), axis=1
    )
    view = view[incomplete_mask.values]
    if view.empty:
        st.success("Every subject/session is complete across all stages. 🎉")
        st.stop()

# Cell display fuses filesystem status with the live job overlay.
_FS_ICON = {
    Status.COMPLETE.value: "🟢 complete",
    Status.PARTIAL.value: "🟡 partial",
    Status.MISSING.value: "⚪ missing",
    Status.NA.value: "— n/a",
}
_JOB_ICON = {
    "running": "🔵 running",
    "queued": "⏳ queued",
    "failed": "🔴 failed",
}
_STYLE = {
    "🟢 complete": "background-color: #1b5e2033; color: inherit",
    "🟡 partial": "background-color: #f9a82533; color: inherit",
    "🔵 running": "background-color: #1565c033; color: inherit",
    "⏳ queued": "background-color: #6a1b9a33; color: inherit",
    "🔴 failed": "background-color: #b71c1c33; color: inherit",
    "⚪ missing": "color: #888",
    "— n/a": "color: #888",
}


def _cell(fs_val, job_val):
    """A live job overlay (running/queued/failed) wins the icon; else filesystem."""
    if job_val in _JOB_ICON:
        return _JOB_ICON[job_val]
    return _FS_ICON.get(fs_val, fs_val)


display = view.rename(columns={"subject": "sub", "session": "ses"})
for stage in STAGES:
    job_col = f"{stage}_job"
    if job_col in view.columns:
        display[stage] = [_cell(f, j) for f, j in zip(view[stage], view[job_col])]
    else:
        display[stage] = view[stage].map(lambda v: _FS_ICON.get(v, v))

# Drop the raw *_job helper columns from the rendered table.
display = display[["sub", "ses", *STAGES]]

st.dataframe(
    display.style.map(lambda v: _STYLE.get(v, ""), subset=list(STAGES)),
    width="stretch",
    hide_index=True,
)

st.caption(
    "🟢 complete · 🟡 partial (crashed/half-done) · 🔵 running · ⏳ queued · "
    "🔴 failed · ⚪ missing. Stages: ingested → converted → fmriprep → mriqc."
)

# ---- Nipoppy interop export ----
with st.expander("Export Nipoppy bagel (processing_status.tsv)"):
    st.caption(
        "Emit the neurobagel/Nipoppy imaging-bagel TSV — for a neurobagel "
        "dashboard or consortium sharing. duckbrain stays BIDS-native; this is "
        "an on-demand view, not a dependency."
    )
    from duckbrain.core.surveyor import to_bagel

    bagel = to_bagel(matrix, config)
    st.dataframe(bagel, width="stretch", hide_index=True)
    st.download_button(
        "⬇ Download processing_status.tsv",
        data=bagel.to_csv(sep="\t", index=False),
        file_name="processing_status.tsv",
        mime="text/tab-separated-values",
    )
