"""Page 0: Project Status — the pipeline cockpit.

Answers "what's done, what's half-done, what's running, what's left" across the
whole project *and* lets you launch the next step per unit from one place.

Two truths are fused (see ``core.pipeline.survey_live``): filesystem completion
(graded by expected outputs, so a crashed run reads *partial* not done) and live
SLURM state (so a job running *right now* reads *running*, never re-runnable).
Run controls are dependency-gated by ``stage_runnable``. Ingestion is intentionally
not launchable here (synchronous, maps raw folders → units); use Data Ingestion.

The board *is* the launch surface: each SLURM cell is a status icon that opens a
popover — ▶ to launch (params inline), or, when a job exists, a reference to that
exact job (id + live squeue/sacct detail + log tail, and re-run when failed).
The former separate Job Monitor is folded in as the "All SLURM jobs" panel (the
catch-all for jobs not tied to a board cell) fed from the same single SLURM pull.
"""

from collections import defaultdict

import pandas as pd
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


def _cell(fs_val, job_val):
    """A live job overlay (running/queued/failed) wins the icon; else filesystem."""
    return _JOB_ICON.get(job_val) or _FS_ICON.get(fs_val, fs_val)


def _unit_label(subject, session):
    return f"sub-{subject}" + (f" / ses-{session}" if session else "")


def _emoji(icon):
    """First token of a '<emoji> <word>' status label, for a compact cell trigger."""
    return icon.split(" ", 1)[0] if icon else "·"


def _latest_jobs(config):
    """Map (subject, session, stage) -> most-recent job id from the durable log.

    The submission log is written in chronological (append) order, so a later row
    for the same unit/stage wins. This is the durable source for a failed cell's
    job id — it outlives sacct's window, and the log file it names is still on disk.
    """
    subs = read_submissions(config, limit=1_000_000)
    out = {}
    if subs.empty:
        return out
    for _, r in subs.iterrows():
        sub = "" if pd.isna(r["subject"]) else str(r["subject"])
        ses = "" if pd.isna(r["session"]) else str(r["session"])
        stage = "" if pd.isna(r["stage"]) else str(r["stage"])
        job = "" if pd.isna(r["job_id"]) else str(r["job_id"])
        if job:
            out[(sub, ses, stage)] = job
    return out


def _stage_params(stage, config, key_prefix, subject="", session=""):
    """Render (and return) the per-stage launch parameters. Same knobs the old
    single-launch control exposed, now scoped to one cell's popover via key_prefix.

    subject/session gate options that only make sense given what is already on
    disk for that unit (currently anat reuse)."""
    params = {}
    if stage == "fmriprep":
        fp = config.get("fmriprep", {})
        params["output_spaces"] = st.text_input(
            "Output spaces",
            value=" ".join(fp.get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])),
            key=f"{key_prefix}_spaces")
        params["nprocs"] = st.number_input(
            "nprocs", value=fp.get("nprocs", 8), min_value=1, key=f"{key_prefix}_nprocs")
        params["mem_gb"] = st.number_input(
            "mem_gb", value=fp.get("mem_gb", 32), min_value=4, key=f"{key_prefix}_mem")
        params["anat_only"] = st.checkbox("Anat-only", key=f"{key_prefix}_anat")
        # Reuse needs preprocessed anatomicals already on disk for this unit;
        # offering it otherwise submits a job that silently rebuilds the anat.
        from duckbrain.core.fmriprep import has_anat_derivatives

        reusable = has_anat_derivatives(
            config["paths"]["derivatives_dir"], subject, session) if subject else False
        params["use_derivatives"] = st.checkbox(
            "Reuse anat derivatives", key=f"{key_prefix}_deriv", disabled=not reusable,
            help="Skips anat preprocessing and reuses what is already on disk. If "
            "you are re-running because the anat stage itself went wrong, leave "
            "this off — it would reuse the bad anat."
            if reusable else
            "No preprocessed anatomicals for this unit yet — run fMRIPrep with "
            "Anat-only first.")
        params["extra_flags"] = st.text_input(
            "Custom fMRIPrep flags", value=fp.get("extra_flags", ""), key=f"{key_prefix}_flags")
    elif stage == "converted":
        params["force"] = st.checkbox(
            "Force re-convert (dcm2bids --force)", key=f"{key_prefix}_force")
    return params


def _launch(stage, sub, ses, config, params, *, verb="Submitted"):
    """Submit one stage for one unit, toast the result, and rerun the fragment."""
    try:
        job_id = advance_one(config, stage, sub, ses, **params)
        st.toast(f"{verb} {stage} for {_unit_label(sub, ses)} — job {job_id}", icon="✅")
        st.rerun()
    except Exception as e:
        st.error(f"Could not launch: {e}")


def _run_popover(row, stage, config):
    sub, ses = str(row["subject"]), str(row["session"])
    st.markdown(f"**Run {stage}** — {_unit_label(sub, ses)}")
    params = _stage_params(
        stage, config, key_prefix=f"run_{stage}_{sub}_{ses}", subject=sub, session=ses)
    if st.button(f"▶ Run {stage}", type="primary", key=f"runbtn_{stage}_{sub}_{ses}"):
        _launch(stage, sub, ses, config, params)


def _job_popover(row, stage, config, latest_jobs, log_dir, jobs_by_id, runnable, job_state):
    """A cell with a SLURM job (running / queued / failed) — a reference to the
    exact job: its id + live squeue/sacct detail (state, node, elapsed, reason,
    exit) + the log tail, and a re-run for a failed stage. Running/queued show the
    *live* partial log, so a "pending"/"running" cell answers "what is it doing?"."""
    from duckbrain.slurm.monitor import find_job_logs, job_log

    sub, ses = str(row["subject"]), str(row["session"])
    st.markdown(f"**{_JOB_ICON.get(job_state, job_state)}** — {stage} · {_unit_label(sub, ses)}")

    job_id = latest_jobs.get((sub, ses, stage), "")
    info = jobs_by_id.get(job_id) if job_id else None
    if not job_id:
        st.caption("No job id recorded for this unit/stage.")
    else:
        bits = [f"job `{job_id}`"]
        if info is not None:
            for label, val in (("state", info.state), ("node", info.nodes),
                               ("elapsed", info.time_used), ("reason", info.reason),
                               ("exit", info.exit_code)):
                if val and str(val) not in ("None", ""):
                    bits.append(f"{label} {val}")
        st.caption(" · ".join(bits))
        if not log_dir:
            st.caption("No log directory configured.")
        else:
            files = find_job_logs(job_id, log_dir)
            logs = job_log(job_id, log_dir)
            text = logs["stdout"] or logs["stderr"]
            if files:
                st.caption("log: " + ", ".join(f"`{p.name}`" for p in files))
            if text:
                st.code(text[-4000:], language="text")
                if len(text) > 4000:
                    st.caption(f"(tail — {len(text):,} chars total)")
                st.download_button(
                    "⬇ Download full log", data=text,
                    file_name=f"{stage}_{job_id}.log", key=f"dl_{stage}_{sub}_{ses}")
            else:
                st.caption(f"No log file yet in `{log_dir}` for job {job_id}.")
    if runnable:  # a failed stage is re-runnable; running/queued are gated
        st.divider()
        params = _stage_params(
            stage, config, key_prefix=f"re_{stage}_{sub}_{ses}", subject=sub, session=ses)
        if st.button(f"↻ Re-run {stage}", type="primary", key=f"rerun_{stage}_{sub}_{ses}"):
            _launch(stage, sub, ses, config, params, verb="Re-submitted")
    elif job_state in ("running", "queued") and job_id:
        # An in-flight job can be cancelled here (scancel), behind a confirm tick.
        st.divider()
        confirm = st.checkbox("Confirm cancel", key=f"cancelchk_{stage}_{sub}_{ses}")
        if st.button(f"✖ Cancel job {job_id}", disabled=not confirm,
                     key=f"cancel_{stage}_{sub}_{ses}"):
            from duckbrain.slurm.monitor import cancel_job
            try:
                cancel_job(job_id)
                st.toast(f"Cancelled job {job_id} — {stage} {_unit_label(sub, ses)}", icon="🛑")
                st.rerun()
            except Exception as e:
                st.error(f"Could not cancel: {e}")


def _bulk_popover(stage, units, config):
    """Column-header bulk: run every currently-runnable unit for one stage (guarded)."""
    n = len(units)
    st.markdown(f"**Run all {stage}**")
    st.caption(f"{n} ready: " + ", ".join(
        _unit_label(str(r["subject"]), str(r["session"])) for r in units))
    st.caption("Bulk runs use config-default parameters. For per-unit knobs, open a cell.")
    # Per-stage confirm key so ticking one column can't arm another.
    confirm = st.checkbox(f"Yes — submit {n} {stage} job(s)", key=f"bulk_confirm_{stage}")
    if st.button(f"▶▶ Run all {n} {stage}", type="primary",
                 disabled=not confirm, key=f"bulk_run_{stage}"):
        ok, errs = 0, []
        for r in units:
            try:
                advance_one(config, stage, str(r["subject"]), str(r["session"]))
                ok += 1
            except Exception as e:
                errs.append(f"{_unit_label(str(r['subject']), str(r['session']))}: {e}")
        st.toast(f"Submitted {ok}/{n} {stage} job(s)", icon="✅")
        for m in errs:
            st.error(m)
        if ok:
            st.rerun()


def _render_cell(col, row, stage, config, runnable_map, latest_jobs, log_dir, jobs_by_id):
    """One matrix cell: status icon, upgraded to a popover when there's an action.

    - running / queued / failed -> job-reference popover (id + live detail + log;
      re-run when the stage is failed/runnable). A "pending" cell thus links to
      the exact SLURM job instead of being a dead badge.
    - runnable (missing, deps met) -> ▶ popover with the stage's launch params
    - otherwise (complete / gated) -> static icon, in place (never vanishes).
    """
    fs = row.get(stage, "")
    job = row.get(f"{stage}_job", "")
    icon = _cell(fs, job)
    if stage not in SLURM_STAGES:
        col.markdown(icon)
        return
    sub, ses = str(row["subject"]), str(row["session"])
    runnable = runnable_map.get((sub, ses, stage), False)
    if job in ("running", "queued", "failed"):
        with col.popover(_emoji(icon), use_container_width=True):
            _job_popover(row, stage, config, latest_jobs, log_dir, jobs_by_id, runnable, job)
    elif runnable:
        with col.popover(f"▶ {_emoji(icon)}", use_container_width=True):
            _run_popover(row, stage, config)
    else:
        col.markdown(icon)


def _deep_links():
    st.caption("Need advanced params or per-session review? Open the full pages:")
    for path, label, icon in [
        ("pages/3_BIDS_Conversion.py", "BIDS Conversion", "🧬"),
        ("pages/4_Preprocessing.py", "Preprocessing", "🧠"),
    ]:
        try:
            st.page_link(path, label=label, icon=icon)
        except Exception:
            pass  # standalone (non-multipage) render — links are best-effort


def _submission_log(config):
    with st.expander("Recent submissions (durable log)"):
        subs = read_submissions(config, limit=25)
        if subs.empty:
            st.caption(
                "No submissions recorded yet. Jobs launched here (and from the "
                "stage pages) are appended to `code/logs/submissions.tsv` — a record "
                "that outlives sacct's ~7-day window."
            )
        else:
            st.dataframe(subs.iloc[::-1], width="stretch", hide_index=True)  # newest first


def _all_jobs_section(jobs, config):
    """The folded-in Job Monitor: every SLURM job (active + 7-day history) — the
    catch-all the unit×stage board can't hold (orphan/manual/other-tool jobs) —
    plus an arbitrary-job-id log viewer. Fed from survey_live's single pull."""
    active, history = jobs["active"], jobs["history"]
    with st.expander(f"🖥 All SLURM jobs — {len(active)} active · {len(history)} recent (+ log lookup)"):
        st.caption(
            "The board is organized by unit × stage; this catches every job — "
            "including ones not tied to a cell — and looks up any job's log."
        )
        st.markdown("**Active** (squeue)")
        if active:
            st.dataframe(pd.DataFrame([
                {"Job ID": j.job_id, "Name": j.name, "State": j.state,
                 "Partition": j.partition, "Time": j.time_used, "Limit": j.time_limit,
                 "Nodes": j.nodes, "Reason": j.reason} for j in active]),
                width="stretch", hide_index=True)
        else:
            st.caption("No active jobs.")

        st.markdown("**Recent history** (sacct, 7 days)")
        if history:
            hist_df = pd.DataFrame([
                {"Job ID": j.job_id, "Name": j.name, "State": j.state,
                 "Elapsed": j.time_used, "Start": j.start_time, "End": j.end_time,
                 "Exit": j.exit_code} for j in history])
            states = sorted(hist_df["State"].unique())
            sel = st.multiselect("Filter by state", states, default=states, key="jm_states")
            st.dataframe(hist_df[hist_df["State"].isin(sel)], width="stretch", hide_index=True)
        else:
            st.caption("No job history in the last 7 days.")

        st.markdown("**Log viewer** — any job id")
        c1, c2 = st.columns(2)
        jid = c1.text_input("Job ID", key="jm_jobid", placeholder="e.g. 45452962")
        ld = c2.text_input(
            "Log directory", value=config.get("paths", {}).get("log_dir", ""), key="jm_logdir")
        if jid and ld:
            from duckbrain.slurm.monitor import job_log
            logs = job_log(jid, ld)
            if logs["stdout"]:
                st.code(logs["stdout"][-5000:], language="text")
            if logs["stderr"]:
                st.caption("stderr:")
                st.code(logs["stderr"][-5000:], language="text")
            if not logs["stdout"] and not logs["stderr"]:
                st.info(f"No log found for job `{jid}` in `{ld}`.")


@st.fragment(run_every="30s" if auto else None)
def dashboard():
    with st.spinner("Surveying project & querying SLURM…"):
        matrix, jobs = survey_live(config, with_jobs=True)

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

    # ---- Actionable status board ----
    # One board instead of three blocks: the matrix cells ARE the launch controls.
    # A cell upgrades to a popover when it has an action (▶ run / 🔴 log+re-run);
    # a gated cell keeps its icon in place rather than vanishing from a dropdown.
    st.subheader("Subjects")
    only_incomplete = st.checkbox(
        "Show only units with unfinished stages", value=True,
        help="Hide subject/sessions where every stage is complete. On by default "
        "so the board stays focused on what needs action.",
    )

    # Runnable (unit, stage) universe — computed over the FULL matrix so column
    # bulk is correct, indexed for O(1) per-cell lookup. stage_runnable enforces
    # deps + no-double-submit, so a running/queued/complete cell is never offered.
    runnable_map, runnable_by_stage = {}, defaultdict(list)
    for _, row in matrix.iterrows():
        for stage in SLURM_STAGES:
            if stage in matrix.columns and stage_runnable(row, stage, config):
                runnable_map[(str(row["subject"]), str(row["session"]), stage)] = True
                runnable_by_stage[stage].append(row)

    view = matrix
    if only_incomplete:
        mask = matrix[list(STAGES)].apply(
            lambda r: any(v != Status.COMPLETE.value for v in r), axis=1)
        view = matrix[mask.values]

    if view.empty:
        st.success("Every subject/session is complete across all stages. 🎉")
    else:
        latest_jobs = _latest_jobs(config)
        log_dir = paths.get("log_dir", "")
        spec = [1.3, 0.8] + [1.15] * len(STAGES)

        # Header: labels + a per-column bulk popover where the stage has runnable units.
        head = st.columns(spec)
        head[0].markdown("**sub**")
        head[1].markdown("**ses**")
        for i, stage in enumerate(STAGES):
            hc = head[2 + i]
            units = runnable_by_stage.get(stage)
            if stage in SLURM_STAGES and units:
                with hc.popover(f"{stage} ▾", use_container_width=True):
                    _bulk_popover(stage, units, config)
            else:
                hc.markdown(f"**{stage}**")

        # One row per unit; each SLURM cell becomes a popover when it has an action.
        for _, row in view.iterrows():
            rc = st.columns(spec)
            rc[0].markdown(f"sub-{row['subject']}")
            rc[1].markdown(row["session"] or "—")
            for i, stage in enumerate(STAGES):
                _render_cell(rc[2 + i], row, stage, config, runnable_map,
                             latest_jobs, log_dir, jobs["by_id"])

        st.caption(
            "🟢 complete · 🟡 partial (crashed/half-done) · 🔵 running · ⏳ queued · "
            "🔴 failed · ⚪ missing.  ▶ = launch (opens params) · 🔵/⏳/🔴 = open the "
            "SLURM job (id, live detail, log; cancel in-flight / re-run failed) · "
            "column ▾ = run the whole stage."
        )

    _all_jobs_section(jobs, config)
    _deep_links()
    _submission_log(config)


dashboard()
