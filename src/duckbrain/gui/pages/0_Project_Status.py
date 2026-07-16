"""Page 0: Project Status — the pipeline cockpit.

Answers "what's done, what's half-done, what's running, what's left" across the
whole project *and* lets you launch the next step per unit from one place.

Two truths are fused (see ``core.pipeline.survey_live``): filesystem completion
(graded by expected outputs, so a crashed run reads *partial* not done) and live
SLURM state (so a job running *right now* reads *running*, never re-runnable).
Run controls are dependency-gated by ``stage_runnable``. Ingestion is intentionally
not launchable here (synchronous, maps raw folders → units); use Data Ingestion.
"""

from collections import defaultdict

import streamlit as st

st.set_page_config(page_title="Project Status — duckbrain", layout="wide")
st.title("Project Status")
st.caption(
    "Completion by expected outputs (not folder presence) fused with live SLURM "
    "state — a crashed run shows *partial*, a live one shows *running*."
)

# ---- Load config (outside the refreshing fragment) ----
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

if config.get("nordic", {}).get("use_nordic", False):
    st.caption("🧊 **use_nordic** on — fMRIPrep reads NORDIC-denoised input and is "
               "gated on the `nordic` stage.")

from duckbrain.core.surveyor import STAGES, Status, summarize
from duckbrain.core.pipeline import (
    SLURM_STAGES,
    advance_one,
    read_submissions,
    stage_runnable,
    survey_live,
)
from duckbrain.core.consistency import check_consistency

# ---- Refresh controls ----
c_refresh, c_auto = st.columns([1, 3])
with c_refresh:
    if st.button("↻ Refresh", help="Re-scan the filesystem and re-query SLURM"):
        st.rerun()
with c_auto:
    auto = st.checkbox(
        "Auto-refresh every 30s", value=False,
        help="Re-queries SLURM (squeue/sacct) every 30s. Off by default to avoid "
        "load on the scheduler.",
    )

_FS_ICON = {
    Status.COMPLETE.value: "🟢 complete",
    Status.PARTIAL.value: "🟡 partial",
    Status.MISSING.value: "⚪ missing",
    Status.NA.value: "— n/a",
}
_JOB_ICON = {"running": "🔵 running", "queued": "⏳ queued", "failed": "🔴 failed"}
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
    return _JOB_ICON.get(job_val) or _FS_ICON.get(fs_val, fs_val)


def _unit_label(subject, session):
    return f"sub-{subject}" + (f" / ses-{session}" if session else "")


@st.fragment(run_every="30s" if auto else None)
def dashboard():
    with st.spinner("Surveying project & querying SLURM…"):
        matrix = survey_live(config)

    if matrix.empty:
        st.info(
            "No subjects found yet. Ingest DICOMs on the **Data Ingestion** page, "
            "or point Project Setup at a directory that already contains BIDS data."
        )
        return

    # ---- Per-stage rollup ----
    summary = summarize(matrix)
    st.subheader("Overview")
    cols = st.columns(len(STAGES))
    for col, stage in zip(cols, STAGES):
        counts = summary[stage]
        col.metric(stage.capitalize(), f"{counts[Status.COMPLETE.value]}/{len(matrix)}",
                   help="complete / total")
        bits = []
        job_col = f"{stage}_job"
        if job_col in matrix.columns:
            running = int((matrix[job_col] == "running").sum() + (matrix[job_col] == "queued").sum())
            failed = int((matrix[job_col] == "failed").sum())
            if running:
                bits.append(f"🔵 {running} running")
            if failed:
                bits.append(f"🔴 {failed} failed")
        if counts[Status.PARTIAL.value]:
            bits.append(f"⚠ {counts[Status.PARTIAL.value]} partial")
        if counts[Status.MISSING.value]:
            bits.append(f"○ {counts[Status.MISSING.value]} missing")
        col.caption(" · ".join(bits) if bits else "✓ all complete")

    # ---- Provenance consistency (⚠️) ----
    # On-disk provenance is authoritative; the submission log is an overlay that
    # catches cross-subject mixing on-disk can't represent. Silent when clean.
    issues = check_consistency(config)
    if issues:
        warnings = [i for i in issues if i.severity != "note"]
        st.subheader("⚠️ Provenance warnings" if warnings else "Provenance notes")
        st.caption(
            "Self-contradictory pipeline state — config vs. what's on disk, mixed "
            "provenance/versions across subjects, staleness, or a missing input."
        )
        for issue in issues:
            where = f" *(sub-{issue.subject})*" if issue.subject else ""
            text = f"**{issue.check}** — {issue.message}{where}"
            # A note is provenance worth knowing, not a contradiction to fix —
            # keep it visually distinct so it can't dilute the real warnings.
            (st.info if issue.severity == "note" else st.warning)(text)

    # ---- Runnable (unit, stage) universe ----
    runnable = []
    for _, row in matrix.iterrows():
        for stage in SLURM_STAGES:
            if stage in matrix.columns and stage_runnable(row, stage, config):
                runnable.append({
                    "subject": row["subject"], "session": row["session"], "stage": stage,
                    "unit": _unit_label(row["subject"], row["session"]),
                })

    # ---- Launch a single step ----
    st.subheader("Launch a step")
    if not runnable:
        st.info(
            "Nothing is ready to launch — every stage is complete, already "
            "running/queued, or waiting on a prior stage."
        )
    else:
        labels = [f"{o['unit']}  →  run {o['stage']}" for o in runnable]
        choice = st.selectbox("Ready to run", labels, key="cockpit_choice")
        sel = runnable[labels.index(choice)]
        stage, sub, ses = sel["stage"], sel["subject"], sel["session"]

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

    # ---- Bulk: run a whole stage (guarded) ----
    by_stage = defaultdict(list)
    for o in runnable:
        by_stage[o["stage"]].append(o)
    with st.expander("Bulk: run a whole stage"):
        if not by_stage:
            st.caption("No stage has units ready to run.")
        else:
            bstage = st.selectbox("Stage", sorted(by_stage), key="bulk_stage")
            units = by_stage[bstage]
            n = len(units)
            st.caption(f"{n} ready for **{bstage}**: " + ", ".join(o["unit"] for o in units))
            st.caption("Bulk runs use config-default parameters. For per-unit knobs, "
                       "use the single-launch control above or the full page.")
            # Scope the confirmation to the selected stage. A fixed key would keep
            # the box checked when the stage selectbox switches (e.g. arming an
            # fmriprep bulk run off a nordic confirmation) — the guard must be a
            # deliberate per-stage tick.
            confirm = st.checkbox(f"Yes — submit {n} {bstage} job(s)",
                                  key=f"bulk_confirm_{bstage}")
            if st.button(f"▶▶ Run all {n} {bstage}", type="primary",
                         disabled=not confirm, key="bulk_run"):
                ok = 0
                errs = []
                for o in units:
                    try:
                        advance_one(config, bstage, o["subject"], o["session"])
                        ok += 1
                    except Exception as e:
                        errs.append(f"{o['unit']}: {e}")
                st.toast(f"Submitted {ok}/{n} {bstage} job(s)", icon="✅")
                for msg in errs:
                    st.error(msg)
                if ok:
                    st.rerun()

    # ---- Deep links to the full pages (bulk/advanced/per-session review) ----
    st.caption("Need advanced params or per-session review? Open the full pages:")
    for path, label, icon in [
        ("pages/3_BIDS_Conversion.py", "BIDS Conversion", "🧬"),
        ("pages/4_Preprocessing.py", "Preprocessing", "🧠"),
    ]:
        try:
            st.page_link(path, label=label, icon=icon)
        except Exception:
            pass  # standalone (non-multipage) render — links are best-effort

    # ---- Status matrix ----
    st.subheader("Subjects")
    only_incomplete = st.checkbox(
        "Show only units with unfinished stages", value=False,
        help="Hide subject/sessions where every stage is complete.",
    )
    view = matrix.copy()
    view["session"] = view["session"].replace("", "—")
    if only_incomplete:
        mask = matrix[list(STAGES)].apply(
            lambda r: any(v != Status.COMPLETE.value for v in r), axis=1)
        view = view[mask.values]
        if view.empty:
            st.success("Every subject/session is complete across all stages. 🎉")
            return

    display = view.rename(columns={"subject": "sub", "session": "ses"})
    for stage in STAGES:
        job_col = f"{stage}_job"
        if job_col in view.columns:
            display[stage] = [_cell(f, j) for f, j in zip(view[stage], view[job_col])]
        else:
            display[stage] = view[stage].map(lambda v: _FS_ICON.get(v, v))
    display = display[["sub", "ses", *STAGES]]

    st.dataframe(
        display.style.map(lambda v: _STYLE.get(v, ""), subset=list(STAGES)),
        width="stretch", hide_index=True,
    )
    st.caption(
        "🟢 complete · 🟡 partial (crashed/half-done) · 🔵 running · ⏳ queued · "
        "🔴 failed · ⚪ missing. Stages: ingested → converted → fmriprep → mriqc."
    )

    # ---- Durable submission log ----
    with st.expander("Recent submissions (durable log)"):
        subs = read_submissions(config, limit=25)
        if subs.empty:
            st.caption(
                "No submissions recorded yet. Jobs launched here (and from the "
                "stage pages) are appended to `code/logs/submissions.tsv` — a record "
                "that outlives sacct's ~7-day window and the ephemeral Job Monitor."
            )
        else:
            st.dataframe(subs.iloc[::-1], width="stretch", hide_index=True)  # newest first



dashboard()
