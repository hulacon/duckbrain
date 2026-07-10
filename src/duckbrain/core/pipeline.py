"""Pipeline controller — launch one stage for one (subject, session) unit.

The GUI pages historically inlined the "advance this unit to the next stage"
trio (``build_context`` → ``render_sbatch`` → ``submit_job``) inside their submit
loops, once per stage, with the stage-specific context assembly copy-pasted.

This module lifts that into a single reusable entry point, :func:`advance_one`,
so both the stage pages *and* the Project Status cockpit call the same code. Each
SLURM stage declares a :class:`StageSpec` (its job-name prefix, the prior stage it
depends on, and a builder that assembles the template context). See
``docs/pipeline-cockpit.md`` (TODO #0).

Ingestion is deliberately NOT launchable here: it is synchronous and maps raw
scanner folders → units (the unit doesn't exist until after it runs), so it stays
on the Data Ingestion page. Its spec is present with ``is_slurm=False`` only so
callers can reason about dependencies.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from ..slurm.monitor import job_history, list_jobs
from ..slurm.submit import export_script, submit_job
from ..slurm.templates import build_context, render_sbatch
from .surveyor import STAGES, Status, survey_project


class PipelineError(RuntimeError):
    """A stage could not be launched (misconfig, missing inputs, etc.).

    Raised with a user-facing message so the caller (page or cockpit) can show it
    without a traceback.
    """


def tag_for(subject: str, session: str) -> str:
    """Job/script name fragment: ``sub_ses`` when session present, else ``sub``.

    Must match the convention the pages use so job names join back to squeue/sacct
    rows (see the cockpit plan's live-state fusion).
    """
    return f"{subject}_{session}" if session else subject


def _resolve_log_dir(config: dict) -> str:
    """Shared-FS dir for logs, submitted scripts, and filter files.

    Mirrors the pages' fallback: derived ``log_dir`` (``<project>/code/logs``), or
    ``<work_dir>/logs`` if unset. Never node-local ``work_dir`` itself.
    """
    paths = config.get("paths", {})
    return paths.get("log_dir") or f"{paths.get('work_dir', '/tmp')}/logs"


# ---- per-stage context builders --------------------------------------------
#
# Each returns ``(template_name, context)`` for render_sbatch. Params come from
# the caller (GUI widgets or cockpit defaults) via **params, falling back to
# config so a bare ``advance_one(config, stage, sub, ses)`` works.

def _build_dcm2bids(config, subject, session, log_dir, params):
    from .conversion import (
        generate_session_config,
        get_container_path,
        resolve_dicom_dir,
        save_dcm2bids_config,
    )
    from .ingestion import sub_ses_relpath

    sourcedata_dir = config["paths"]["sourcedata_dir"]
    force = bool(params.get("force", False))
    container_path = get_container_path(config)
    dicom_dir = resolve_dicom_dir(sourcedata_dir, subject, session)
    cfg_path = Path(sourcedata_dir) / sub_ses_relpath(subject, session) / "dcm2bids_config.json"
    # Reuse a previously reviewed/saved config; only auto-generate when absent.
    if not cfg_path.exists():
        save_dcm2bids_config(generate_session_config(dicom_dir, subject, session), cfg_path)
    ctx = build_context(
        config, "dcm2bids", subject=subject, session=session,
        dicom_dir=str(dicom_dir), config_json=str(cfg_path),
        config_json_dir=str(cfg_path.parent), container_path=str(container_path),
        force=force,
    )
    return "dcm2bids", ctx


def _build_fmriprep(config, subject, session, log_dir, params):
    from .fmriprep import find_fs_license, get_container_path, write_session_filter

    paths = config["paths"]
    derivatives_dir = paths["derivatives_dir"]
    fp_cfg = config.get("fmriprep", {})

    container = get_container_path(config)
    fs_license = find_fs_license(config)
    if not fs_license:
        raise PipelineError("FreeSurfer license not found. Set it in Project Setup.")

    output_dir = f"{derivatives_dir}/fmriprep"
    # A session filter restricts fMRIPrep to one session (multi-session only).
    filter_file = ""
    if session:
        filter_file = str(write_session_filter(
            Path(log_dir) / f"bids_filter_{tag_for(subject, session)}.json", session))

    spaces = params.get(
        "output_spaces",
        fp_cfg.get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"]),
    )
    if isinstance(spaces, str):
        spaces = spaces.split()
    anat_only = bool(params.get("anat_only", False))
    use_derivatives = bool(params.get("use_derivatives", False))
    extra_flags = str(params.get("extra_flags", fp_cfg.get("extra_flags", ""))).strip()
    nprocs = int(params.get("nprocs", fp_cfg.get("nprocs", 8)))
    mem_gb = int(params.get("mem_gb", fp_cfg.get("mem_gb", 32)))

    ctx = build_context(
        config, "fmriprep", subject=subject, session=session,
        bids_dir=paths["bids_dir"], output_dir=output_dir,
        container_path=str(container), fs_license=str(fs_license),
        fs_license_dir=str(fs_license.parent), output_spaces=spaces,
        filter_file=filter_file, anat_only=anat_only,
        derivatives=output_dir if use_derivatives else "",
        extra_flags=extra_flags,
    )
    # GUI nprocs/mem_gb override the config defaults the template reads.
    ctx["fmriprep"] = {**ctx.get("fmriprep", {}), "nprocs": nprocs, "mem_gb": mem_gb}
    return "fmriprep", ctx


def _build_nordic(config, subject, session, log_dir, params):
    from .nordic import get_bold_runs

    bolds = get_bold_runs(config["paths"]["bids_dir"], subject, session)
    if not bolds:
        raise PipelineError("No BOLD runs found for this subject/session.")
    # NORDIC's sbatch shells out to a duckbrain script in the repo's scripts/ dir.
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    ctx = build_context(
        config, "nordic", subject=subject, session=session,
        bold_count=len(bolds), scripts_dir=str(scripts_dir), python_cmd=sys.executable,
    )
    return "nordic_denoise", ctx


def _build_mriqc(config, subject, session, log_dir, params):
    from ..config import get_slurm_resources
    from .mriqc import get_container_path

    container = get_container_path(config)
    mq_slurm = get_slurm_resources(config, "mriqc")
    mem_str = str(mq_slurm.get("memory", "16G"))
    mem_gb = int(params.get("mem_gb", int(mem_str.replace("G", "").replace("g", ""))))
    ctx = build_context(
        config, "mriqc", subject=subject, session=session,
        container_path=str(container), mem_gb=mem_gb,
    )
    return "mriqc", ctx


# ---- stage registry ---------------------------------------------------------

@dataclass(frozen=True)
class StageSpec:
    """How one pipeline stage is launched and where it sits in the dependency chain.

    ``name`` matches the surveyor's stage column. ``job_prefix`` + ``tag_for`` give
    the SLURM job name (the join key for live-state fusion). ``depends_on`` is the
    surveyor stage that must be COMPLETE before this stage is actionable. ``build``
    assembles ``(template, context)``; ``None`` for non-SLURM stages.
    """

    name: str
    job_prefix: str
    depends_on: str | None
    build: Callable | None = None
    is_slurm: bool = True


STAGE_SPECS: dict[str, StageSpec] = {
    "ingested": StageSpec("ingested", "ingest", None, build=None, is_slurm=False),
    "converted": StageSpec("converted", "dcm2bids", "ingested", build=_build_dcm2bids),
    "fmriprep": StageSpec("fmriprep", "fmriprep", "converted", build=_build_fmriprep),
    "nordic": StageSpec("nordic", "nordic", "converted", build=_build_nordic),
    "mriqc": StageSpec("mriqc", "mriqc", "converted", build=_build_mriqc),
}

# SLURM-launchable stages, in pipeline order (cockpit iterates these).
SLURM_STAGES = tuple(s for s, spec in STAGE_SPECS.items() if spec.is_slurm)


# ---- public API -------------------------------------------------------------

def advance_one(
    config: dict,
    stage: str,
    subject: str,
    session: str = "",
    *,
    export_only: bool = False,
    **params,
) -> str:
    """Launch (or export) the SLURM job that advances one unit through *stage*.

    Parameters
    ----------
    config : dict
        Loaded duckbrain config with derived ``[paths]``.
    stage : str
        A key of :data:`STAGE_SPECS` (surveyor stage name). Must be SLURM-launchable.
    subject, session : str
        The unit. ``session`` is ``""`` for single-session studies.
    export_only : bool
        Write the sbatch script to ``log_dir`` and return its path instead of
        submitting.
    **params
        Stage-specific overrides (e.g. fMRIPrep ``output_spaces``, ``nprocs``,
        ``mem_gb``, ``anat_only``, ``use_derivatives``, ``extra_flags``; dcm2bids
        ``force``). Omitted values fall back to config defaults.

    Returns
    -------
    str
        The SLURM job id, or the exported script path when ``export_only``.

    Raises
    ------
    PipelineError
        Unknown/non-SLURM stage, or a stage precondition failed (missing license,
        no BOLD runs, etc.).
    """
    spec = STAGE_SPECS.get(stage)
    if spec is None:
        raise PipelineError(f"Unknown stage {stage!r}.")
    if not spec.is_slurm or spec.build is None:
        raise PipelineError(f"Stage {stage!r} is not launchable as a SLURM job.")

    log_dir = _resolve_log_dir(config)
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    template, ctx = spec.build(config, subject, session, log_dir, params)
    script = render_sbatch(template, ctx)
    job_name = f"{spec.job_prefix}_{tag_for(subject, session)}"

    if export_only:
        return str(export_script(script, Path(log_dir) / f"{job_name}.sbatch"))

    job_id = submit_job(script, job_name, scripts_dir=log_dir)
    # Durable record of what we launched — survives past sacct's ~7-day window
    # and is independent of the ephemeral Job Monitor. Never let logging failure
    # sink an otherwise-successful submission.
    try:
        record_submission(config, stage, subject, session, job_id)
    except Exception:
        pass
    return job_id


# ---- durable submission log (cockpit phase 4) -------------------------------

_SUBMISSION_LOG = "submissions.tsv"
_SUBMISSION_COLUMNS = ["timestamp", "subject", "session", "stage", "job_id"]


def _submission_log_path(config: dict) -> Path:
    return Path(_resolve_log_dir(config)) / _SUBMISSION_LOG


def record_submission(config: dict, stage: str, subject: str, session: str, job_id: str) -> Path:
    """Append one launched job to ``<log_dir>/submissions.tsv`` (tab-separated).

    Idempotent header: writes the column row only when creating the file.
    """
    path = _submission_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    ts = datetime.now().isoformat(timespec="seconds")
    with open(path, "a") as f:
        if write_header:
            f.write("\t".join(_SUBMISSION_COLUMNS) + "\n")
        f.write("\t".join([ts, subject, session, stage, str(job_id)]) + "\n")
    return path


def read_submissions(config: dict, limit: int | None = None) -> pd.DataFrame:
    """Read the durable submission log (empty frame if none). Oldest-first."""
    path = _submission_log_path(config)
    if not path.exists():
        return pd.DataFrame(columns=_SUBMISSION_COLUMNS)
    df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
    return df.tail(limit) if limit else df


# ---- live SLURM-state fusion (cockpit phase 2) ------------------------------
#
# The surveyor reads only the filesystem, so a job that is *running right now*
# leaves the same half-populated derivative as one that *crashed* — both grade
# PARTIAL. An actionable cockpit must not offer "re-run" on a live job (that
# double-submits). survey_live() overlays scheduler truth (squeue + sacct) onto
# the filesystem matrix, keyed by the f"{prefix}_{tag}" job name.

# squeue states we treat as not-yet-running (everything else active = running).
_QUEUED_STATES = {"PENDING", "CONFIGURING"}
# sacct terminal states that mean the last attempt did not succeed.
_FAILED_STATES = {
    "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
    "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED",
}


def _norm_state(state: str) -> str:
    """Leading SLURM state token, upper-cased (sacct emits e.g. 'CANCELLED by 42')."""
    return state.split()[0].upper() if state else ""


def _job_state_maps():
    """Build name→state lookups from squeue (active) and sacct (recent history).

    Degrades to empty maps when SLURM isn't reachable (e.g. off-cluster), so
    survey_live() then just returns the filesystem matrix.
    """
    try:
        active_jobs = list_jobs()
    except Exception:
        active_jobs = []
    try:
        hist = job_history(days=7)
    except Exception:
        hist = []

    active: dict[str, str] = {}
    for j in active_jobs:
        st = _norm_state(j.state)
        active[j.name] = "queued" if st in _QUEUED_STATES else "running"

    failed: set[str] = set()
    completed: set[str] = set()
    for j in hist:
        st = _norm_state(j.state)
        if st in _FAILED_STATES:
            failed.add(j.name)
        elif st == "COMPLETED":
            completed.add(j.name)
    return active, failed, completed


def survey_live(config: dict):
    """:func:`~duckbrain.core.surveyor.survey_project` overlaid with SLURM state.

    For each surveyor stage that is SLURM-launchable (converted/fmriprep/mriqc),
    adds a companion ``<stage>_job`` column with one of ``running`` / ``queued``
    / ``failed`` / ``""``. Precedence: an active job wins; else a filesystem
    COMPLETE is never downgraded by a stale sacct failure; else a recent
    failed-and-not-completed run reads ``failed``.

    The base status columns and the Nipoppy bagel export are left untouched —
    filesystem truth and scheduler truth stay separate, debuggable facts.
    """
    matrix = survey_project(config)
    active, failed, completed = _job_state_maps()

    overlay_stages = [s for s in STAGES if STAGE_SPECS.get(s) and STAGE_SPECS[s].is_slurm]
    for stage in overlay_stages:
        prefix = STAGE_SPECS[stage].job_prefix
        vals = []
        for _, row in matrix.iterrows():
            name = f"{prefix}_{tag_for(row['subject'], row['session'])}"
            if name in active:
                vals.append(active[name])
            elif row[stage] == Status.COMPLETE.value:
                vals.append("")
            elif name in failed and name not in completed:
                vals.append("failed")
            else:
                vals.append("")
        matrix[f"{stage}_job"] = vals
    return matrix


def stage_runnable(row, stage: str) -> bool:
    """Whether *stage* can be launched now for the unit in *row* (a survey_live row).

    True when the stage is SLURM-launchable, not already complete, has no active
    (running/queued) job, and its dependency stage is complete. This is the
    cockpit's per-cell run gate — it deliberately excludes re-running a COMPLETE
    stage (that's a separate "advanced" affordance).
    """
    spec = STAGE_SPECS.get(stage)
    if spec is None or not spec.is_slurm or stage not in row:
        return False
    if row.get(f"{stage}_job", "") in ("running", "queued"):
        return False
    if row[stage] == Status.COMPLETE.value:
        return False
    dep = spec.depends_on
    if dep is not None and row.get(dep) != Status.COMPLETE.value:
        return False
    return True
