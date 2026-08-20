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

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

if TYPE_CHECKING:
    from streamlit.delta_generator import DeltaGenerator
    from streamlit.elements.lib.mutable_popover_container import PopoverContainer

    from duckbrain.config import Config
    from duckbrain.core.pipeline import JobIndex
    from duckbrain.slurm.monitor import JobInfo

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
    st.caption(
        "🧊 **use_nordic** on — fMRIPrep reads NORDIC-denoised input and is "
        "gated on the `nordic` stage."
    )

if config.get("freesurfer", {}).get("use_external", False):
    st.caption(
        "🧠 **use_external** FreeSurfer on — fMRIPrep imports the external "
        "recon (`--fs-no-resume`) and is gated on the `freesurfer` stage, "
        "which runs once per subject."
    )

from duckbrain.core.checks import run_checks
from duckbrain.core.consistency import check_consistency
from duckbrain.core.pipeline import (
    SLURM_STAGES,
    STAGE_SPECS,
    advance_one,
    read_submissions,
    stage_runnable,
    survey_live,
)
from duckbrain.core.surveyor import STAGES, Status, summarize
from duckbrain.gui.components import flush_toasts, queue_toast

# A launch or cancel on the previous run confirms itself here; see
# `components.queue_toast` for why it cannot confirm itself at the call site.
flush_toasts()

# ---- Refresh controls ----
c_refresh, c_auto = st.columns([1, 3])
with c_refresh:
    if st.button("↻ Refresh", help="Re-scan the filesystem and re-query SLURM"):
        st.rerun()
with c_auto:
    auto = st.checkbox(
        "Auto-refresh every 30s",
        value=False,
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


def _cell(fs_val: str, job_val: str) -> str:
    """A live job overlay (running/queued/failed) wins the icon; else filesystem."""
    return _JOB_ICON.get(job_val) or _FS_ICON.get(fs_val, fs_val)


def _unit_label(subject: str, session: str) -> str:
    return f"sub-{subject}" + (f" / ses-{session}" if session else "")


def _emoji(icon: str) -> str:
    """First token of a '<emoji> <word>' status label, for a compact cell trigger."""
    return icon.split(" ", 1)[0] if icon else "·"


def _latest_jobs(config: Config) -> dict[tuple[str, str, str], str]:
    """Map (subject, session, stage) -> most-recent job id from the durable log.

    The submission log is written in chronological (append) order, so a later row
    for the same unit/stage wins. This is the durable source for a failed cell's
    job id — it outlives sacct's window, and the log file it names is still on disk.
    """
    subs = read_submissions(config, limit=1_000_000)
    out: dict[tuple[str, str, str], str] = {}
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


def _stage_params(
    stage: str, config: Config, key_prefix: str, subject: str = "", session: str = ""
) -> dict[str, Any]:
    """Render (and return) the per-stage launch parameters. Same knobs the old
    single-launch control exposed, now scoped to one cell's popover via key_prefix.

    subject/session gate options that only make sense given what is already on
    disk for that unit (currently anat reuse)."""
    params: dict[str, Any] = {}
    if stage == "fmriprep":
        fp = config.get("fmriprep", {})
        params["output_spaces"] = st.text_input(
            "Output spaces",
            value=" ".join(
                fp.get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])
            ),
            key=f"{key_prefix}_spaces",
        )
        # Both knobs name the SLURM allocation, not the fMRIPrep flags: --nprocs is
        # the allocation's CPUs outright and --mem-mb is derived from its memory
        # (config.tool_mem_gb), so raising either moves both of its numbers.
        from duckbrain.config import MEM_HEADROOM_GB, get_slurm_resources, parse_mem_gb

        fp_slurm = get_slurm_resources(config, "fmriprep")
        params["nprocs"] = st.number_input(
            "CPUs",
            value=int(fp_slurm["cpus"]),
            min_value=1,
            key=f"{key_prefix}_nprocs",
            help="The SLURM allocation, and fMRIPrep's --nprocs — one number, since "
            "fMRIPrep counts --nprocs across all its processes.",
        )
        params["mem_gb"] = st.number_input(
            "Memory (GB)",
            value=parse_mem_gb(fp_slurm["memory"]),
            min_value=1,
            key=f"{key_prefix}_mem",
            help="The SLURM allocation. fMRIPrep is told "
            f"{MEM_HEADROOM_GB} GB less, so a node overshooting its target stays "
            "inside the allocation instead of being OOM-killed.",
        )
        params["anat_only"] = st.checkbox("Anat-only", key=f"{key_prefix}_anat")
        # Reuse needs preprocessed anatomicals already on disk for this SUBJECT —
        # any session, since the anat is typically acquired once and shared. Offering
        # it otherwise submits a job that silently rebuilds the anat.
        from duckbrain.core.fmriprep import anat_derivative_session, has_anat_derivatives

        deriv_dir = config["paths"]["derivatives_dir"]
        reusable = has_anat_derivatives(deriv_dir, subject) if subject else False
        anat_ses = anat_derivative_session(deriv_dir, subject) if reusable else ""
        # Name the source session: reusing another session's anat is the intended
        # longitudinal behaviour, but silently is how it reads as a bug.
        source = f"ses-{anat_ses}" if anat_ses else "this subject"
        params["use_derivatives"] = st.checkbox(
            "Reuse anat derivatives",
            key=f"{key_prefix}_deriv",
            disabled=not reusable,
            help=f"Skips anat preprocessing and reuses the anatomicals already on disk "
            f"for {source}. If you are re-running because the anat stage itself went "
            "wrong, leave this off — it would reuse the bad anat."
            if reusable
            else f"No preprocessed anatomicals for sub-{subject} in any session yet — "
            "run fMRIPrep with Anat-only first.",
        )
        params["extra_flags"] = st.text_input(
            "Custom fMRIPrep flags", value=fp.get("extra_flags", ""), key=f"{key_prefix}_flags"
        )
    elif stage == "converted":
        params["force"] = st.checkbox(
            "Force re-convert (dcm2bids --force)", key=f"{key_prefix}_force"
        )
    return params


def _launch(
    stage: str,
    sub: str,
    ses: str,
    config: Config,
    params: dict[str, Any],
    *,
    verb: str = "Submitted",
) -> None:
    """Submit one stage for one unit, queue a confirmation, and rerun the fragment."""
    try:
        job_id = advance_one(config, stage, sub, ses, **params)
        queue_toast(f"{verb} {stage} for {_unit_label(sub, ses)} — job {job_id}")
        st.rerun()
    except Exception as e:
        st.error(f"Could not launch: {e}")


def _run_popover(row: pd.Series, stage: str, config: Config) -> None:
    from duckbrain.core.surveyor import run_progress

    sub, ses = str(row["subject"]), str(row["session"])
    st.markdown(f"**Run {stage}** — {_unit_label(sub, ses)}")
    # A partial cell has to say how partial. Without the count it reads as an
    # unexplained "not done" and the operator goes and counts files by hand.
    if row.get(stage) == "partial":
        progress = run_progress(config, stage, sub, ses)
        if progress:
            done, total = progress
            st.warning(
                f"{done} of {total} expected outputs present — {total - done} still missing."
            )
    params = _stage_params(
        stage, config, key_prefix=f"run_{stage}_{sub}_{ses}", subject=sub, session=ses
    )
    if st.button(f"▶ Run {stage}", type="primary", key=f"runbtn_{stage}_{sub}_{ses}"):
        _launch(stage, sub, ses, config, params)


def _job_popover(
    row: pd.Series,
    stage: str,
    config: Config,
    latest_jobs: dict[tuple[str, str, str], str],
    log_dir: str,
    jobs_by_id: dict[str, JobInfo],
    runnable: bool,
    job_state: str,
) -> None:
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
            for label, val in (
                ("state", info.state),
                ("node", info.nodes),
                ("elapsed", info.time_used),
                ("reason", info.reason),
                ("exit", info.exit_code),
            ):
                if val and str(val) not in ("None", ""):
                    bits.append(f"{label} {val}")
        st.caption(" · ".join(bits))
        if not log_dir:
            st.caption("No log directory configured.")
        else:
            files = find_job_logs(job_id, log_dir)
            logs = job_log(job_id, log_dir)
            if files:
                st.caption("log: " + ", ".join(f"`{p.name}`" for p in files))
            # Both streams, stderr first for a failed job. This used to be
            # `stdout or stderr`, so stderr appeared only when stdout was
            # entirely empty — and fMRIPrep always writes a stdout banner, which
            # made the traceback unreachable from the cell that was reporting the
            # failure. The Job Monitor tab below has always shown both.
            order = ("stderr", "stdout") if job_state == "failed" else ("stdout", "stderr")
            shown = False
            for stream in order:
                text = logs[stream]
                if not text:
                    continue
                shown = True
                st.caption(f"**{stream}**")
                st.code(text[-4000:], language="text")
                st.download_button(
                    f"⬇ Download {stream} tail",
                    data=text,
                    file_name=f"{stage}_{job_id}.{stream}.log",
                    key=f"dl_{stream}_{stage}_{sub}_{ses}",
                )
            if not shown:
                st.caption(f"No log file yet in `{log_dir}` for job {job_id}.")
    if runnable:  # a failed stage is re-runnable; running/queued are gated
        st.divider()
        params = _stage_params(
            stage, config, key_prefix=f"re_{stage}_{sub}_{ses}", subject=sub, session=ses
        )
        if st.button(f"↻ Re-run {stage}", type="primary", key=f"rerun_{stage}_{sub}_{ses}"):
            _launch(stage, sub, ses, config, params, verb="Re-submitted")
    elif job_state in ("running", "queued") and job_id:
        # An in-flight job can be cancelled here (scancel), behind a confirm tick.
        st.divider()
        confirm = st.checkbox("Confirm cancel", key=f"cancelchk_{stage}_{sub}_{ses}")
        if st.button(
            f"✖ Cancel job {job_id}", disabled=not confirm, key=f"cancel_{stage}_{sub}_{ses}"
        ):
            from duckbrain.slurm.monitor import cancel_job

            try:
                cancel_job(job_id)
                queue_toast(f"Cancelled job {job_id} — {stage} {_unit_label(sub, ses)}", icon="🛑")
                st.rerun()
            except Exception as e:
                st.error(f"Could not cancel: {e}")


def _queue_headroom(config: Config, n: int, queued: int) -> str:
    """Empty unless SLURM would refuse some of *n* submissions for a full queue.

    A ceiling nobody has met here — Talapas allows 30001 submitted jobs — and one
    that is ordinary at 100 or 500 elsewhere, where a 200-unit bulk run walks
    into it halfway and reports as a pile of identical rejections. ``None`` from
    ``submit_limit`` means the question could not be asked, which is not the same
    as no headroom: say nothing rather than refuse a submission the cluster would
    have taken.

    *queued* comes from the render's own squeue pull rather than a fresh one —
    the cockpit makes exactly one squeue and one sacct call per render on
    purpose (``docs/pipeline-cockpit.md``), and this is a bulk popover per stage.
    """
    from duckbrain.slurm.monitor import submit_limit

    limit = submit_limit(account=config.get("slurm", {}).get("account", ""))
    if limit is None:
        return ""
    if queued + n <= limit:
        return ""
    return (
        f"SLURM allows you {limit} submitted job(s) at once and {queued} are already "
        f"queued, so at most {max(limit - queued, 0)} of these {n} would be accepted. "
        "Submit in batches, or wait for the queue to drain."
    )


def _bulk_popover(stage: str, units: list[pd.Series], config: Config, queued: int) -> None:
    """Column-header bulk: run every currently-runnable unit for one stage (guarded).

    Submission is a blocking sequential loop — one sbatch per unit, ~0.2-1 s each
    — so at 100 subjects the GUI would sit dead for a minute or more with nothing
    on screen. It reports like the Conversion page's bulk path instead: a
    progress bar while it runs and one row per unit when it is done, so a
    submission that half-worked says *which* half (`#42.4`).
    """
    n = len(units)
    st.markdown(f"**Run all {stage}**")
    st.caption(
        f"{n} ready: " + ", ".join(_unit_label(str(r["subject"]), str(r["session"])) for r in units)
    )
    st.caption("Bulk runs use config-default parameters. For per-unit knobs, open a cell.")
    too_many = _queue_headroom(config, n, queued)
    if too_many:
        st.error(too_many)
    # Per-stage confirm key so ticking one column can't arm another.
    confirm = st.checkbox(f"Yes — submit {n} {stage} job(s)", key=f"bulk_confirm_{stage}")
    if st.button(
        f"▶▶ Run all {n} {stage}",
        type="primary",
        disabled=not confirm or bool(too_many),
        key=f"bulk_run_{stage}",
    ):
        _bulk_submit(stage, units, config)


def _bulk_submit(stage: str, units: list[pd.Series], config: Config) -> None:
    """Submit every unit, reporting progress and one result row each."""
    from duckbrain.slurm.monitor import is_submit_limit_rejection

    n = len(units)
    progress = st.progress(0.0, text=f"Submitting {n} {stage} job(s)…")
    results: list[dict[str, str]] = []
    ok = 0
    for i, r in enumerate(units):
        sub, ses = str(r["subject"]), str(r["session"])
        label = _unit_label(sub, ses)
        try:
            job_id = advance_one(config, stage, sub, ses)
            results.append({"unit": label, "job": job_id, "result": "submitted"})
            ok += 1
        except Exception as e:
            results.append({"unit": label, "job": "—", "result": f"error: {e}"})
            # A full queue rejects every job still to come, so continuing turns
            # one fact into 200 copies of itself. Stop and say what was skipped.
            if is_submit_limit_rejection(str(e)):
                for skipped in units[i + 1 :]:
                    results.append(
                        {
                            "unit": _unit_label(str(skipped["subject"]), str(skipped["session"])),
                            "job": "—",
                            "result": "not attempted — SLURM refused the one before it",
                        }
                    )
                break
        progress.progress((i + 1) / n, text=f"Submitting {stage}: {i + 1}/{n}")
    progress.empty()

    st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
    queue_toast(f"Submitted {ok}/{n} {stage} job(s)")
    if ok:
        st.rerun()


#: Cell popover keys. Their real job is to be the *open-state* handle: a
#: state-tracking popover parks its open/closed flag in ``st.session_state`` under
#: this key, which is how a test opens one and how the state survives the
#: fragment's next auto-refresh.
def _cell_popover_key(stage: str, subject: str, session: str) -> str:
    return f"cellpop_{stage}_{subject}_{session}"


def _lazy_popover(
    col: DeltaGenerator, label: str, stage: str, sub: str, ses: str
) -> PopoverContainer:
    """A cell popover that computes its body only while it is open."""
    return col.popover(
        label,
        width="stretch",
        on_change="rerun",
        key=_cell_popover_key(stage, sub, ses),
    )


def _render_cell(
    col: DeltaGenerator,
    row: pd.Series,
    stage: str,
    config: Config,
    runnable_map: dict[tuple[str, str, str], bool],
    latest_jobs: dict[tuple[str, str, str], str],
    log_dir: str,
    jobs_by_id: dict[str, JobInfo],
) -> None:
    """One matrix cell: status icon, upgraded to a popover when there's an action.

    - running / queued / failed -> job-reference popover (id + live detail + log;
      re-run when the stage is failed/runnable). A "pending" cell thus links to
      the exact SLURM job instead of being a dead badge.
    - runnable (missing, deps met) -> ▶ popover with the stage's launch params
    - otherwise (complete / gated) -> static icon, in place (never vanishes).

    **The body runs only while the popover is open**, which is not Streamlit's
    default: an ``on_change="ignore"`` popover computes its whole content on
    every render and ships it to the browser closed. That is affordable for one
    cell and not for a board — a running cell globs and reads its SLURM logs, a
    runnable fMRIPrep cell walks the derivatives tree twice asking whether this
    subject has anatomicals to reuse, and the board redraws inside a 30 s
    fragment. At 100 subjects it was doing all of that ~200 times a refresh for
    content nobody had asked to see. ``on_change="rerun"`` makes opening and
    closing a state change, so ``.open`` can be read and the work deferred to
    the one cell the operator actually clicked (`#42.2`, and the half of DB-010
    that never shipped).
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
        pop = _lazy_popover(col, _emoji(icon), stage, sub, ses)
        if pop.open:
            with pop:
                _job_popover(row, stage, config, latest_jobs, log_dir, jobs_by_id, runnable, job)
    elif runnable:
        pop = _lazy_popover(col, f"▶ {_emoji(icon)}", stage, sub, ses)
        if pop.open:
            with pop:
                _run_popover(row, stage, config)
    else:
        col.markdown(icon)


def _deep_links() -> None:
    st.caption("Need advanced params or per-session review? Open the full pages:")
    for path, label, icon in [
        ("pages/3_BIDS_Conversion.py", "BIDS Conversion", "🧬"),
        ("pages/4_Preprocessing.py", "Preprocessing", "🧠"),
        ("pages/3a_Project.py", "Project (metadata, validation, expectations)", "🗂️"),
    ]:
        try:
            st.page_link(path, label=label, icon=icon)
        except Exception:
            pass  # standalone (non-multipage) render — links are best-effort


def _outcome_checks_section(config: Config) -> None:
    """The cached outcome checks (L3, `docs/sanity-checks.md` Slice C).

    These open tool reports and image data, so they never run on the render
    path — this body reads one small JSON (`code/logs/checks.json`) and a
    fingerprint of stats, and the measurement itself runs only inside the
    button. What makes rendering a *cached* verdict honest is the staleness
    marker: the snapshot carries a fingerprint of the inputs it measured, and
    a changed fingerprint is shown rather than silently serving an old "clean"
    as current — the exact failure the validation panel refused a cache over.
    """
    from duckbrain.core.checks import (
        read_checks_snapshot,
        run_expensive_checks,
        snapshot_is_stale,
    )

    snapshot = read_checks_snapshot(config)
    stale = snapshot is not None and snapshot_is_stale(config, snapshot)
    if snapshot is None:
        state = "not measured yet"
    else:
        n = len(snapshot.issues)
        state = ("clean" if not n else f"{n} issue(s)") + f", measured {snapshot.ran_at}"
        if stale:
            state += " — ⚠ inputs changed since"

    with st.expander(f"🔬 Outcome checks — {state}"):
        st.caption(
            "What the tools actually **did**, read from their own output: fMRIPrep's "
            "susceptibility-distortion verdict against the fieldmap intent in the "
            "sidecars it was given, and NORDIC output compared against its raw input. "
            "The board grades what exists; these catch the run that looks done and "
            "quietly isn't. They open reports and image data, so they run only when "
            "asked and the result is kept until the inputs change."
        )
        if st.button("▶ Run outcome checks now", key="outcome_checks_btn", width="stretch"):
            with st.spinner("Reading tool reports and image data…"):
                run_expensive_checks(config)
            st.rerun()

        if snapshot is None:
            return
        if stale:
            st.warning(
                "Inputs have changed since this was measured — a new run, a fixed "
                "sidecar, or deleted files. The findings below describe the state at "
                "measurement time; re-run to refresh."
            )
        for issue in snapshot.issues:
            text = f"**{issue.check}** — {issue.message}"
            if issue.severity == "note":
                st.info(text)
            elif issue.severity == "error":
                st.error(text)
            else:
                st.warning(text)
        if not snapshot.issues:
            st.success("Nothing flagged.")


def _submission_log(config: Config) -> None:
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


def _all_jobs_section(jobs: JobIndex, config: Config) -> None:
    """The folded-in Job Monitor: every SLURM job (active + 7-day history) — the
    catch-all the unit×stage board can't hold (orphan/manual/other-tool jobs) —
    plus an arbitrary-job-id log viewer. Fed from survey_live's single pull."""
    active, history = jobs["active"], jobs["history"]
    with st.expander(
        f"🖥 All SLURM jobs — {len(active)} active · {len(history)} recent (+ log lookup)"
    ):
        st.caption(
            "The board is organized by unit × stage; this catches every job — "
            "including ones not tied to a cell — and looks up any job's log."
        )
        st.markdown("**Active** (squeue)")
        if active:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Job ID": j.job_id,
                            "Name": j.name,
                            "State": j.state,
                            "Partition": j.partition,
                            "Time": j.time_used,
                            "Limit": j.time_limit,
                            "Nodes": j.nodes,
                            "Reason": j.reason,
                        }
                        for j in active
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("No active jobs.")

        st.markdown("**Recent history** (sacct, 7 days)")
        if history:
            hist_df = pd.DataFrame(
                [
                    {
                        "Job ID": j.job_id,
                        "Name": j.name,
                        "State": j.state,
                        "Elapsed": j.time_used,
                        "Start": j.start_time,
                        "End": j.end_time,
                        "Exit": j.exit_code,
                    }
                    for j in history
                ]
            )
            states = sorted(hist_df["State"].unique())
            sel = st.multiselect("Filter by state", states, default=states, key="jm_states")
            st.dataframe(hist_df[hist_df["State"].isin(sel)], width="stretch", hide_index=True)
        else:
            st.caption("No job history in the last 7 days.")

        st.markdown("**Log viewer** — any job id")
        c1, c2 = st.columns(2)
        jid = c1.text_input("Job ID", key="jm_jobid", placeholder="e.g. 45452962")
        ld = c2.text_input(
            "Log directory", value=config.get("paths", {}).get("log_dir", ""), key="jm_logdir"
        )
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
def dashboard() -> None:
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
    for col, stage in zip(cols, STAGES, strict=True):
        counts = summary[stage]
        # A stage that applies to no unit reads "—", not "0/N": 0-of-N is a
        # progress claim, and it was the headline number telling a finished
        # non-NORDIC project it had N units of work left (TODO #17.4).
        if counts.get(Status.NA.value, 0) == len(matrix) and len(matrix):
            col.metric(stage.capitalize(), "—", help="does not apply to this project")
            continue
        col.metric(
            stage.capitalize(),
            f"{counts[Status.COMPLETE.value]}/{len(matrix)}",
            help="complete / total",
        )
        bits = []
        job_col = f"{stage}_job"
        if job_col in matrix.columns:
            running = int(
                (matrix[job_col] == "running").sum() + (matrix[job_col] == "queued").sum()
            )
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
    # `run_checks` is folded into the same panel on purpose: it asks a different
    # question (did we get what the study DECLARED, per core/expectations.py) but
    # a reader shouldn't have to know which module noticed. It is silent unless
    # the project declares `[expected]`, so this adds nothing for projects that
    # haven't opted in.
    # `matrix` and not a second survey: four of these checks want the completion
    # matrix, and the one above is the same survey they would each go and take
    # (`#42.3` — five surveys per 30 s refresh, ~25 s of them at 100 subjects).
    issues = check_consistency(config, matrix=matrix) + run_checks(config)
    if issues:
        warnings = [i for i in issues if i.severity != "note"]
        st.subheader("⚠️ Warnings" if warnings else "Notes")
        st.caption(
            "Self-contradictory pipeline state — config vs. what's on disk, mixed "
            "provenance/versions across subjects, staleness, or a missing input — "
            "plus any shortfall against this project's declared expectations."
        )
        for issue in issues:
            where = f" *(sub-{issue.subject})*" if issue.subject else ""
            text = f"**{issue.check}** — {issue.message}{where}"
            # A note is worth knowing, not a contradiction to fix — keep it
            # visually distinct so it can't dilute the real warnings. An error
            # means a downstream stage will fail or quietly do the wrong thing.
            if issue.severity == "note":
                st.info(text)
            elif issue.severity == "error":
                st.error(text)
            else:
                st.warning(text)

    # Adjacent to the warnings panel, not inside it: the same on-demand-and-cached
    # question — what did the tools actually *do* — but these findings are
    # duckbrain's own, so they wear the panel's severity vocabulary. The other
    # dataset-level panels (BIDS validation, the expectations declaration) live
    # on the Project page; the warnings their checks produce still land above,
    # next to the board they judge.
    _outcome_checks_section(config)

    # ---- Actionable status board ----
    # One board instead of three blocks: the matrix cells ARE the launch controls.
    # A cell upgrades to a popover when it has an action (▶ run / 🔴 log+re-run);
    # a gated cell keeps its icon in place rather than vanishing from a dropdown.
    st.subheader("Subjects")
    only_incomplete = st.checkbox(
        "Show only units with unfinished stages",
        value=True,
        help="Hide subject/sessions where every stage is complete. On by default "
        "so the board stays focused on what needs action.",
    )

    # Runnable (unit, stage) universe — computed over the FULL matrix so column
    # bulk is correct, indexed for O(1) per-cell lookup. stage_runnable enforces
    # deps + no-double-submit, so a running/queued/complete cell is never offered.
    runnable_map: dict[tuple[str, str, str], bool] = {}
    runnable_by_stage: defaultdict[str, list[pd.Series]] = defaultdict(list)
    seen_subject_units: set[tuple[str, str]] = set()
    for _, row in matrix.iterrows():
        for stage in SLURM_STAGES:
            if stage in matrix.columns and stage_runnable(row, stage, config):
                runnable_map[(str(row["subject"]), str(row["session"]), stage)] = True
                # A subject-level stage (freesurfer) covers every session row of
                # the subject with one job, so the bulk list takes one entry per
                # subject — otherwise "run all" submits one duplicate recon per
                # session. Per-cell launches stay offered on every row; the
                # duplicates there are absorbed by advance_one dropping the
                # session and the job overlay marking all rows once one runs.
                if STAGE_SPECS[stage].unit == "subject":
                    key = (stage, str(row["subject"]))
                    if key in seen_subject_units:
                        continue
                    seen_subject_units.add(key)
                runnable_by_stage[stage].append(row)

    view = matrix
    if only_incomplete:
        # "Unfinished" means there is work left, so a stage that does not apply to
        # this project (NORDIC without use_nordic) must not keep a finished unit on
        # the board — that is what made this filter hide nothing, ever, and the
        # all-complete message unreachable (TODO #17.4).
        _done = (Status.COMPLETE.value, Status.NA.value)
        mask = matrix[list(STAGES)].apply(lambda r: any(v not in _done for v in r), axis=1)
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
                # Lazy for the same reason as the cells (`#42.2`), and with a new
                # one of its own: the headroom preflight below asks sacctmgr, and
                # an eager body would ask once per stage on every 30 s refresh.
                pop = hc.popover(
                    f"{stage} ▾", width="stretch", on_change="rerun", key=f"bulkpop_{stage}"
                )
                if pop.open:
                    with pop:
                        _bulk_popover(stage, units, config, len(jobs["active"]))
            else:
                hc.markdown(f"**{stage}**")

        # One row per unit; each SLURM cell becomes a popover when it has an action.
        for _, row in view.iterrows():
            rc = st.columns(spec)
            rc[0].markdown(f"sub-{row['subject']}")
            rc[1].markdown(row["session"] or "—")
            for i, stage in enumerate(STAGES):
                _render_cell(
                    rc[2 + i], row, stage, config, runnable_map, latest_jobs, log_dir, jobs["by_id"]
                )

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
