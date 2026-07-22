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

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from ..slurm.monitor import job_history, list_jobs
from ..slurm.submit import archived_script_path, export_script, submit_job
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
    # Auto-generation inherits the project-wide task/run mapping (if any), so a
    # bulk/cockpit convert honors the study's once-defined task labels.
    if not cfg_path.exists():
        from .dcm2bids_config import fmap_rules_from_config, task_rules_from_config

        rules = task_rules_from_config(config)
        fmap_rules = fmap_rules_from_config(config)
        save_dcm2bids_config(
            generate_session_config(
                dicom_dir, subject, session, rules=rules, fmap_rules=fmap_rules
            ),
            cfg_path,
        )
    ctx = build_context(
        config,
        "dcm2bids",
        subject=subject,
        session=session,
        dicom_dir=str(dicom_dir),
        config_json=str(cfg_path),
        config_json_dir=str(cfg_path.parent),
        container_path=str(container_path),
        force=force,
    )
    return "dcm2bids", ctx


def _build_fmriprep(config, subject, session, log_dir, params):
    from .fmriprep import (
        find_fs_license,
        get_container_path,
        has_anat_derivatives,
        write_session_filter,
    )

    paths = config["paths"]
    derivatives_dir = paths["derivatives_dir"]
    fp_cfg = config.get("fmriprep", {})

    container = get_container_path(config)
    fs_license = find_fs_license(config)
    if not fs_license:
        raise PipelineError("FreeSurfer license not found. Set it in Project Setup.")

    output_dir = f"{derivatives_dir}/fmriprep"

    # Input source is the only variable between with- and without-NORDIC runs
    # (TODO #5b Case 1). Default: raw BIDS. When use_nordic, assemble the unit's
    # self-contained bids_format tree (denoised BOLDs + anat/fmap/sidecars + root
    # files) and read that instead.
    fmriprep_input = paths["bids_dir"]
    if _use_nordic(config):
        from .nordic import build_nordic_bids_input, get_bold_runs

        nordic_root = f"{derivatives_dir}/nordic"
        denoised = get_bold_runs(nordic_root, subject, session)
        if not denoised:
            raise PipelineError(
                "use_nordic is on but no NORDIC-denoised BOLDs were found for "
                f"sub-{subject}{('/ses-' + session) if session else ''}. "
                "Run the NORDIC stage first."
            )
        build_nordic_bids_input(
            bids_dir=paths["bids_dir"],
            subject=subject,
            session=session,
            nordic_derivatives_dir=nordic_root,
        )
        fmriprep_input = f"{nordic_root}/bids_format"

    # A session filter restricts fMRIPrep to one session (multi-session only).
    filter_file = ""
    if session:
        filter_file = str(
            write_session_filter(
                Path(log_dir) / f"bids_filter_{tag_for(subject, session)}.json", session
            )
        )

    spaces = params.get(
        "output_spaces",
        fp_cfg.get("output_spaces", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"]),
    )
    if isinstance(spaces, str):
        spaces = spaces.split()
    anat_only = bool(params.get("anat_only", False))
    use_derivatives = bool(params.get("use_derivatives", False))
    # Reuse is only meaningful when this unit already has preprocessed anatomicals.
    # Without the check fMRIPrep accepts --derivatives pointing at a tree with no
    # anat for the subject, rebuilds the anat workflow, and reports nothing —
    # the option looks honoured but did nothing.
    if use_derivatives and not has_anat_derivatives(derivatives_dir, subject, session):
        raise PipelineError(
            "Reuse anat derivatives is on, but no preprocessed anatomicals exist for "
            f"sub-{subject}{('/ses-' + session) if session else ''}. Run fMRIPrep once "
            "with Anat-only first, or clear the reuse option."
        )
    extra_flags = str(params.get("extra_flags", fp_cfg.get("extra_flags", ""))).strip()
    nprocs = int(params.get("nprocs", fp_cfg.get("nprocs", 8)))
    mem_gb = int(params.get("mem_gb", fp_cfg.get("mem_gb", 32)))

    ctx = build_context(
        config,
        "fmriprep",
        subject=subject,
        session=session,
        bids_dir=fmriprep_input,
        output_dir=output_dir,
        container_path=str(container),
        fs_license=str(fs_license),
        fs_license_dir=str(fs_license.parent),
        output_spaces=spaces,
        filter_file=filter_file,
        anat_only=anat_only,
        derivatives=output_dir if use_derivatives else "",
        extra_flags=extra_flags,
    )
    # GUI nprocs/mem_gb override the config defaults the template reads.
    ctx["fmriprep"] = {**ctx.get("fmriprep", {}), "nprocs": nprocs, "mem_gb": mem_gb}
    return "fmriprep", ctx


def _build_nordic(config, subject, session, log_dir, params):
    from .nordic import get_bold_runs

    paths = config["paths"]
    bolds = get_bold_runs(paths["bids_dir"], subject, session)
    if not bolds:
        raise PipelineError("No BOLD runs found for this subject/session.")
    # NORDIC is a MATLAB job that writes no provenance of its own — stamp the
    # derivative root so it carries on-disk provenance in the same format the
    # consistency checker reads from tool-written derivatives. Guarded: a
    # provenance write must never block the launch.
    try:
        from .bids_metadata import duckbrain_version, write_derivative_description
        from .containers import container_uri
        from .nordic import write_nordic_sidecars
        from .toolbox import code_url

        prov = run_provenance(config, "nordic")
        image = resolve_container(config, "nordic")
        write_derivative_description(
            f"{paths['derivatives_dir']}/nordic",
            "nordic",
            tool=prov["tool"],
            tool_version=prov["tool_version"],
            container=image.name if image else "",
            container_uri=container_uri(image) if image else "",
            code_url=code_url(nordic_toolbox_dir(config)),
            runtime=prov["runtime"],
            source_dataset=paths["bids_dir"],
        )
        # Per-file sidecars too: dataset_description is dataset-level and the
        # submission log doesn't travel with the data, so only these keep a
        # copied/archived NORDIC output self-describing.
        write_nordic_sidecars(
            paths["bids_dir"],
            paths["derivatives_dir"],
            subject,
            session,
            provenance={
                "Version": duckbrain_version(),
                "Tool": prov["tool"],
                "ToolVersion": prov["tool_version"],
                "Runtime": prov["runtime"],
                "CodeSource": prov["code_source"],
                "InputVariant": prov["input_variant"],
            },
        )
    except Exception:
        pass
    # NORDIC's sbatch shells out to a duckbrain script in the repo's scripts/ dir.
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    ctx = build_context(
        config,
        "nordic",
        subject=subject,
        session=session,
        bold_count=len(bolds),
        scripts_dir=str(scripts_dir),
        python_cmd=sys.executable,
    )
    return "nordic_denoise", ctx


def _build_mriqc(config, subject, session, log_dir, params):
    from ..config import get_slurm_resources
    from .mriqc import get_container_path

    container = get_container_path(config)
    mq_slurm = get_slurm_resources(config, "mriqc")
    mem_str = str(mq_slurm.get("memory", "32G"))
    alloc_gb = int(mem_str.replace("G", "").replace("g", ""))
    # MRIQC's --mem-gb is a soft target for its nipype scheduler, not a hard RSS
    # cap. The func synthstrip node (torch brain extraction) overshoots it, so if
    # --mem-gb == the SLURM --mem the cgroup OOM-kills the step (observed on all 9
    # divatten_gui_beta subjects, 2026-07-10). Target the allocation minus an 8 GB
    # headroom buffer so overshoot stays inside the cgroup limit.
    mem_gb = int(params.get("mem_gb", max(alloc_gb - 8, 1)))
    ctx = build_context(
        config,
        "mriqc",
        subject=subject,
        session=session,
        container_path=str(container),
        mem_gb=mem_gb,
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


def _use_nordic(config: dict) -> bool:
    """Whether this project routes fMRIPrep through NORDIC (TODO #5b Case 1)."""
    return bool(config.get("nordic", {}).get("use_nordic", False))


def effective_depends_on(config: dict, stage: str) -> str | None:
    """The dependency stage that must be COMPLETE before *stage* is runnable.

    Same as ``STAGE_SPECS[stage].depends_on`` except fMRIPrep depends on
    ``nordic`` (not ``converted``) when the project has ``use_nordic`` on — the
    denoised input must exist first. NORDIC itself stays a pure ``converted``
    producer regardless.
    """
    spec = STAGE_SPECS.get(stage)
    if spec is None:
        return None
    if stage == "fmriprep" and _use_nordic(config):
        return "nordic"
    return spec.depends_on


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
        record_submission(
            config,
            stage,
            subject,
            session,
            job_id,
            script_path=str(archived_script_path(log_dir, job_name, job_id)),
            **run_provenance(config, stage),
        )
    except Exception:
        pass
    return job_id


# ---- durable submission log (cockpit phase 4) -------------------------------

_SUBMISSION_LOG = "submissions.tsv"
# Provenance columns (tool/tool_version/container/input_variant) sit between the
# unit and the job id so a run is self-describing: *what* tool at *what* version,
# from *which* container, over *which* input variant (raw vs NORDIC-denoised).
# This is duckbrain's own per-run record — the one source that can catch mixed
# provenance in a single derivative dir (on-disk dataset_description.json is
# dataset-level and overwritten by the last run). See TODO ★ Phase A.
# ``runtime`` is what executed the tool, ``code_source`` where its code came from.
# For a container stage the image is the runtime and its Docker tag names the code
# inside; NORDIC has two genuinely distinct artifacts (MATLAB runs it, the toolbox
# checkout is the code). One pair of columns spans both — see run_provenance.
# ``script_path`` points at the immutable per-attempt copy of what was actually
# submitted. Without it the record said which container ran but not what was
# asked of it — and the on-disk script was overwritten by the next retry, so
# after a re-run with different resources or flags the exact command line of the
# failed attempt was unrecoverable even though its log and its row both survived.
_SUBMISSION_COLUMNS = [
    "timestamp",
    "subject",
    "session",
    "stage",
    "tool",
    "tool_version",
    "runtime",
    "code_source",
    "input_variant",
    "job_id",
    "script_path",
]

# Columns renamed since logs were first written. The migration maps rows by *name*,
# so without this a renamed column's values would be silently dropped — and the log
# is rewritten in place, making that loss permanent.
_SUBMISSION_RENAMES = {
    "container": "runtime",
    "container_source": "code_source",
}

# Which underlying tool each surveyor stage runs, and the config key holding its
# pinned version. NORDIC is a MATLAB-toolbox stage with no semantic version key.
_STAGE_TOOL = {
    "converted": ("dcm2bids", "dcm2bids_version"),
    "fmriprep": ("fmriprep", "fmriprep_version"),
    "mriqc": ("mriqc", "mriqc_version"),
    "nordic": ("nordic", None),
}


def matlab_module(config: dict) -> str:
    """MATLAB module NORDIC runs under, e.g. ``matlab/R2024a``.

    NORDIC's *runtime* — the second of its two version axes, independent of the
    toolbox checkout that supplies its code.
    """
    return str(config.get("nordic", {}).get("matlab_module", "") or "")


def nordic_toolbox_dir(config: dict) -> str:
    """Configured NORDIC toolbox checkout, or ``""``.

    Each user holds their own clone (the licence forbids redistribution), so this
    path — and the commit at it — varies per user. See ``core.toolbox``.
    """
    return str(config.get("paths", {}).get("nordic_toolbox_dir", "") or "")


def resolve_container(config: dict, stage: str) -> Path | None:
    """The container file *stage* would run, via the stage's own resolution.

    Single source of truth for "which image does config point at", so provenance
    recording and the consistency checker can never disagree with the builder.
    ``None`` for stages that run no container (e.g. NORDIC, a MATLAB job).
    """
    if stage == "converted":
        from .conversion import get_container_path
    elif stage == "fmriprep":
        from .fmriprep import get_container_path
    elif stage == "mriqc":
        from .mriqc import get_container_path
    else:
        return None
    return get_container_path(config)


def run_provenance(config: dict, stage: str) -> dict:
    """Best-effort provenance for a launch: tool, version, runtime, code source,
    input variant.

    Two slots span both kinds of stage. ``runtime`` is what executed the tool —
    the container image, or MATLAB for NORDIC. ``code_source`` is where its code
    came from: for an image, its *build provenance* (the Docker tag it was
    bootstrapped from, read out of the image's own labels — a stronger identity
    than the filename, which is only a convention; see ``core.containers``); for
    NORDIC, the toolbox checkout as ``Owner/Repo@sha`` (``core.toolbox``). A
    container needs only one artifact because the image is both; NORDIC's two move
    independently.

    ``input_variant`` is ``nordic`` when fMRIPrep is routed through the denoised
    tree, else ``raw``. Every field degrades to ``""`` off the resolvable path —
    provenance should never block a submission.
    """
    tool, version_key = _STAGE_TOOL.get(stage, ("", None))
    containers = config.get("containers", {})
    tool_version = containers.get(version_key, "") if version_key else ""

    runtime = ""
    code_source = ""
    try:
        path = resolve_container(config, stage)
        if path:
            # A container image *is* the runtime; its Docker tag names the code.
            runtime = Path(path).name
            from .containers import container_build_tag

            code_source = container_build_tag(path)
    except Exception:
        runtime = runtime or ""
        code_source = ""

    # NORDIC's two artifacts are genuinely distinct: MATLAB executes it, and its
    # code is a git checkout of the toolbox (core.toolbox). They map onto the same
    # pair of slots a container stage uses — the runtime slot is free precisely
    # because NORDIC runs no image.
    if stage == "nordic":
        try:
            from .toolbox import describe, source_ref

            repo = nordic_toolbox_dir(config)
            tool_version = describe(repo)
            code_source = source_ref(repo)
            runtime = matlab_module(config)
        except Exception:
            tool_version = tool_version or ""
            code_source = ""
            runtime = ""

    if stage == "fmriprep":
        input_variant = "nordic" if _use_nordic(config) else "raw"
    elif stage in ("mriqc", "nordic"):
        input_variant = "raw"
    else:
        input_variant = ""

    return {
        "tool": tool,
        "tool_version": tool_version,
        "runtime": runtime,
        "code_source": code_source,
        "input_variant": input_variant,
    }


def _submission_log_path(config: dict) -> Path:
    return Path(_resolve_log_dir(config)) / _SUBMISSION_LOG


def _parse_log_rows(text: str) -> tuple[list[str], list[dict]]:
    """Parse the log's header and rows, mapping each row onto its header names.

    Tolerant by design: ragged rows (from a pre-migration append of a wider row
    onto a narrower header) are zipped against the header rather than rejected,
    so a log that is already mixed-width still reads.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], []
    header = [_SUBMISSION_RENAMES.get(c, c) for c in lines[0].split("\t")]
    rows = [dict(zip(header, ln.split("\t"))) for ln in lines[1:]]
    return header, rows


def _migrate_log_header(path: Path) -> None:
    """Rewrite an existing log to the current column set, preserving its rows.

    The provenance columns were added after logs already existed in the wild
    (`divatten_gui_beta`'s is the original 5-column ``timestamp/subject/session/
    stage/job_id``). Appending a wider row under a narrower header produces a
    ragged file that ``pd.read_csv`` refuses outright — which would take the
    submission log, the Job Monitor, and every log-overlay consistency check down
    with it. So bring the header up to date *before* appending.

    Rows are re-mapped by column *name* (honoring ``_SUBMISSION_RENAMES``, so a
    renamed column keeps its values rather than being silently dropped into a
    rewritten file), so no data moves columns and new fields fill empty. Rewritten
    atomically: a crash mid-migration leaves the original log intact, never a
    half-written one. Idempotent, and a no-op for a current
    or absent log.
    """
    if not path.exists():
        return
    try:
        text = path.read_text()
    except OSError:
        return
    raw_header = text.splitlines()[0].split("\t") if text.strip() else []
    if not raw_header or raw_header == _SUBMISSION_COLUMNS:
        return
    # Compare the header *as written*: _parse_log_rows renames on the way in, so a
    # log using the old column names would otherwise look current and keep its
    # stale header on disk forever.
    _, rows = _parse_log_rows(text)
    tmp = path.with_suffix(path.suffix + ".migrating")
    try:
        with open(tmp, "w") as f:
            f.write("\t".join(_SUBMISSION_COLUMNS) + "\n")
            for row in rows:
                f.write("\t".join(row.get(c, "") for c in _SUBMISSION_COLUMNS) + "\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)  # leave the original untouched


def record_submission(
    config: dict,
    stage: str,
    subject: str,
    session: str,
    job_id: str,
    *,
    tool: str = "",
    tool_version: str = "",
    runtime: str = "",
    code_source: str = "",
    input_variant: str = "",
    script_path: str = "",
) -> Path:
    """Append one launched job to ``<log_dir>/submissions.tsv`` (tab-separated).

    Provenance fields (``tool``/``tool_version``/``runtime``/``code_source``/
    ``input_variant``/``script_path``) are keyword-only with empty defaults, so
    older/hand callers still work; the cockpit passes them via
    :func:`run_provenance`. Idempotent header: writes the column row only when
    creating the file.
    """
    path = _submission_log_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    _migrate_log_header(path)
    write_header = not path.exists()
    ts = datetime.now().isoformat(timespec="seconds")
    row = [
        ts,
        subject,
        session,
        stage,
        tool,
        tool_version,
        runtime,
        code_source,
        input_variant,
        str(job_id),
        script_path,
    ]
    with open(path, "a") as f:
        if write_header:
            f.write("\t".join(_SUBMISSION_COLUMNS) + "\n")
        f.write("\t".join(row) + "\n")
    return path


def read_submissions(config: dict, limit: int | None = None) -> pd.DataFrame:
    """Read the durable submission log (empty frame if none). Oldest-first.

    Reindexed to the current column set so a legacy log written before the
    provenance columns existed still reads back with those columns present
    (empty), and consumers can rely on a stable schema.

    Never raises on a malformed log: a ragged file (a wider row appended under a
    narrower header, before :func:`_migrate_log_header` existed) falls back to a
    tolerant hand parse rather than taking down every caller. A durable record is
    worth more read best-effort than not at all.
    """
    path = _submission_log_path(config)
    if not path.exists():
        return pd.DataFrame(columns=_SUBMISSION_COLUMNS)
    try:
        df = pd.read_csv(path, sep="\t", dtype=str).fillna("")
        df = df.rename(columns=_SUBMISSION_RENAMES)
    except (ValueError, OSError, pd.errors.ParserError):
        try:
            _, rows = _parse_log_rows(path.read_text())  # renames on the way in
        except OSError:
            return pd.DataFrame(columns=_SUBMISSION_COLUMNS)
        df = pd.DataFrame(rows, dtype=str).fillna("")
    df = df.reindex(columns=_SUBMISSION_COLUMNS, fill_value="")
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
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "BOOT_FAIL",
    "DEADLINE",
    "PREEMPTED",
}


def _norm_state(state: str) -> str:
    """Leading SLURM state token, upper-cased (sacct emits e.g. 'CANCELLED by 42')."""
    return state.split()[0].upper() if state else ""


def _attempt_order(job) -> tuple:
    """Sort key putting the most recent attempt of a job name last.

    ``submit_time`` is sacct's ``Submit``, ISO-8601 and so lexically ordered;
    it reads ``Unknown`` or empty for some records, which sorts before any real
    timestamp — right, since a record we can't date shouldn't outrank one we can.
    The numeric job id breaks ties (two submissions in the same second) and is
    monotonic within a cluster. Array tasks arrive as ``12345_3``; the base id is
    what orders attempts, the task index is noise here.
    """
    ts = job.submit_time if job.submit_time and job.submit_time[0].isdigit() else ""
    base = str(job.job_id).split("_")[0].split(".")[0]
    return (ts, int(base) if base.isdigit() else 0)


def _job_state_maps():
    """Build name→state lookups from squeue (active) and sacct (recent history).

    Returns ``(active, latest, active_jobs, hist)`` — the first two are the
    name-keyed maps survey_live overlays; the last two are the raw
    :class:`JobInfo` lists (so a single squeue/sacct pull can also feed the
    cockpit's per-cell job detail + the all-jobs panel without querying twice).
    Degrades to empty maps/lists when SLURM isn't reachable (e.g. off-cluster).

    History reduces to the **latest attempt per job name**, not to a pair of
    unordered "has failed" / "has completed" sets. Those sets discarded order
    entirely, so a name that had ever completed could never show a failure again:
    attempt 1 completes, attempt 2 fails, and the cell stayed silent for the
    remaining seven days of the window (DB-006 in the 2026-07-22 review). The
    test that was supposed to pin this asserted the failed-then-completed case,
    which an order-insensitive implementation passes either way round.
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

    latest: dict[str, object] = {}
    for j in hist:
        prev = latest.get(j.name)
        if prev is None or _attempt_order(j) >= _attempt_order(prev):
            latest[j.name] = j
    return active, latest, active_jobs, hist


def survey_live(config: dict, with_jobs: bool = False):
    """:func:`~duckbrain.core.surveyor.survey_project` overlaid with SLURM state.

    For each surveyor stage that is SLURM-launchable (converted/fmriprep/mriqc),
    adds a companion ``<stage>_job`` column with one of ``running`` / ``queued``
    / ``failed`` / ``""``. Precedence: an active job wins; else a filesystem
    COMPLETE is never downgraded by a stale sacct failure; else the **latest**
    recent attempt of that job name reads ``failed`` if it failed.

    The base status columns are left untouched — filesystem truth and scheduler
    truth stay separate, debuggable facts.

    With ``with_jobs=True`` returns ``(matrix, jobs)`` where ``jobs`` is
    ``{"by_id": {job_id: JobInfo}, "active": [...], "history": [...]}`` from the
    *same* squeue/sacct pull — so the cockpit can show per-cell job detail and an
    all-jobs panel without querying SLURM again. Default returns just the matrix.
    """
    matrix = survey_project(config)
    active, latest, active_jobs, hist = _job_state_maps()

    overlay_stages = [s for s in STAGES if STAGE_SPECS.get(s) and STAGE_SPECS[s].is_slurm]
    for stage in overlay_stages:
        if stage not in matrix.columns:  # defensive: stage w/o a surveyor column
            continue
        prefix = STAGE_SPECS[stage].job_prefix
        vals = []
        for _, row in matrix.iterrows():
            name = f"{prefix}_{tag_for(row['subject'], row['session'])}"
            if name in active:
                vals.append(active[name])
            elif row[stage] == Status.COMPLETE.value:
                vals.append("")
            elif (job := latest.get(name)) is not None and _norm_state(job.state) in _FAILED_STATES:
                vals.append("failed")
            else:
                vals.append("")
        matrix[f"{stage}_job"] = vals

    if with_jobs:
        by_id: dict[str, object] = {}
        for j in hist:  # active overrides history for the same id
            by_id[str(j.job_id)] = j
        for j in active_jobs:
            by_id[str(j.job_id)] = j
        return matrix, {"by_id": by_id, "active": list(active_jobs), "history": list(hist)}
    return matrix


def stage_runnable(row, stage: str, config: dict | None = None) -> bool:
    """Whether *stage* can be launched now for the unit in *row* (a survey_live row).

    True when the stage is SLURM-launchable, not already complete, has no active
    (running/queued) job, and its dependency stage is complete. This is the
    cockpit's per-cell run gate — it deliberately excludes re-running a COMPLETE
    stage (that's a separate "advanced" affordance).

    When *config* is supplied, the dependency is resolved via
    :func:`effective_depends_on`, so a ``use_nordic`` project gates fMRIPrep on
    ``nordic`` instead of ``converted``. Omitting *config* keeps the static
    ``STAGE_SPECS`` dependency (back-compat for existing callers).
    """
    spec = STAGE_SPECS.get(stage)
    if spec is None or not spec.is_slurm or stage not in row:
        return False
    if row.get(f"{stage}_job", "") in ("running", "queued"):
        return False
    # COMPLETE: nothing left to do. NA: nothing to do at all — the stage does not
    # apply to this project (NORDIC without use_nordic), and offering it launched
    # days of compute for a derivative nothing would read (TODO #17.4).
    if row[stage] in (Status.COMPLETE.value, Status.NA.value):
        return False
    dep = effective_depends_on(config, stage) if config is not None else spec.depends_on
    if dep is not None and row.get(dep) != Status.COMPLETE.value:
        return False
    return True
