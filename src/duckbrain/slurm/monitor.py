"""SLURM job status monitoring via squeue and sacct."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class JobInfo:
    """Information about a SLURM job."""

    job_id: str
    name: str
    state: str
    partition: str
    time_used: str = ""
    time_limit: str = ""
    nodes: str = ""
    reason: str = ""
    submit_time: str = ""
    start_time: str = ""
    end_time: str = ""
    exit_code: str = ""


def cancel_job(job_id: str) -> None:
    """Cancel a SLURM job by id (``scancel``).

    scancel exits 0 and prints nothing on success (including for an already-gone
    job). Raises :class:`RuntimeError` with stderr on a non-zero exit so the GUI
    can surface why a cancel didn't take.
    """
    result = subprocess.run(["scancel", str(job_id)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"scancel failed (exit {result.returncode}): {result.stderr.strip()}")


def known_partitions() -> set[str]:
    """Partition names this cluster actually has (``sinfo``), or an empty set.

    Best-effort by design: an empty set means "could not ask" (no SLURM on this
    machine, sinfo missing, a timeout) and callers must treat that as "cannot
    validate" rather than "no partitions exist". Validation that turns into a
    false accusation off-cluster would be worse than none.

    Exists because a partition name is the one SLURM setting duckbrain cannot
    check by looking at itself, and a wrong one is only discovered when sbatch
    rejects the job. duckbrain shipped ``medium`` as a default for months — not a
    Talapas partition at all — which was invisible only because a per-stage
    default silently outranked it (TODO #17.2).
    """
    try:
        result = subprocess.run(
            ["sinfo", "-h", "-o", "%P"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    # sinfo marks the cluster default with a trailing '*'.
    return {p.strip().rstrip("*") for p in result.stdout.split() if p.strip()}


def list_jobs(user: str | None = None) -> list[JobInfo]:
    """List pending/running jobs from squeue.

    Parameters
    ----------
    user : str, optional
        Username to filter. Defaults to current user.

    Returns
    -------
    list[JobInfo]
        Active jobs.
    """
    if user is None:
        user = os.environ.get("USER", "")

    result = subprocess.run(
        [
            "squeue",
            "-u",
            user,
            "-o",
            "%i|%j|%T|%P|%M|%l|%N|%R",
            "--noheader",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return []

    jobs = []
    for line in result.stdout.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 8:
            jobs.append(
                JobInfo(
                    job_id=parts[0].strip(),
                    name=parts[1].strip(),
                    state=parts[2].strip(),
                    partition=parts[3].strip(),
                    time_used=parts[4].strip(),
                    time_limit=parts[5].strip(),
                    nodes=parts[6].strip(),
                    reason=parts[7].strip(),
                )
            )

    return jobs


def job_status(job_id: str) -> JobInfo | None:
    """Query sacct for a specific job's status (including completed jobs).

    Parameters
    ----------
    job_id : str
        SLURM job ID.

    Returns
    -------
    JobInfo or None
    """
    result = subprocess.run(
        [
            "sacct",
            "-j",
            job_id,
            "--format=JobID,JobName,State,Partition,Elapsed,Timelimit,NodeList,Submit,Start,End,ExitCode",
            "--parsable2",
            "--noheader",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0 or not result.stdout.strip():
        return None

    # Take the first line (main job, not sub-steps)
    line = result.stdout.strip().splitlines()[0]
    parts = line.split("|")
    if len(parts) < 11:
        return None

    return JobInfo(
        job_id=parts[0],
        name=parts[1],
        state=parts[2],
        partition=parts[3],
        time_used=parts[4],
        time_limit=parts[5],
        nodes=parts[6],
        submit_time=parts[7],
        start_time=parts[8],
        end_time=parts[9],
        exit_code=parts[10],
    )


def job_history(user: str | None = None, days: int = 7) -> list[JobInfo]:
    """Query sacct for recent job history.

    Parameters
    ----------
    user : str, optional
        Username. Defaults to current user.
    days : int
        How many days back to look.

    Returns
    -------
    list[JobInfo]
    """
    if user is None:
        user = os.environ.get("USER", "")

    from datetime import datetime, timedelta

    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    result = subprocess.run(
        [
            "sacct",
            "-u",
            user,
            "--starttime",
            start_date,
            "--format=JobID,JobName,State,Partition,Elapsed,Timelimit,NodeList,Submit,Start,End,ExitCode",
            "--parsable2",
            "--noheader",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return []

    jobs = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 11:
            # Skip sub-steps (e.g., "12345.batch", "12345.extern")
            if "." in parts[0]:
                continue
            jobs.append(
                JobInfo(
                    job_id=parts[0],
                    name=parts[1],
                    state=parts[2],
                    partition=parts[3],
                    time_used=parts[4],
                    time_limit=parts[5],
                    nodes=parts[6],
                    submit_time=parts[7],
                    start_time=parts[8],
                    end_time=parts[9],
                    exit_code=parts[10],
                )
            )

    return jobs


def find_job_logs(job_id: str, log_dir: str) -> list[Path]:
    """Resolve the on-disk log files for a job id, sorted by name.

    Matches the sbatch ``--output`` conventions duckbrain emits:
    - ``<tool>_<job_id>.out`` — the plain per-job stages (dcm2bids/fmriprep/mriqc)
    - ``<tool>_<job_id>_<task>.out`` — **array** jobs (NORDIC denoise writes one
      file per subject/task as ``nordic_%A_%a.out``); the plain ``*_<job_id>.out``
      glob misses these because of the trailing ``_<task>``.
    - ``slurm-<job_id>.out`` — SLURM's default fallback name
    plus the ``.err``/``.log`` counterparts. Deduped by filename.
    """
    log_dir = Path(log_dir)
    if not log_dir.is_dir():
        return []

    found: dict[str, "Path"] = {}
    for ext in ("out", "err", "log"):
        for pattern in (
            f"*_{job_id}.{ext}",  # plain per-job
            f"*_{job_id}_*.{ext}",  # array task (nordic_<A>_<a>.out)
            f"slurm-{job_id}.{ext}",  # SLURM default
        ):
            for match in log_dir.glob(pattern):
                found[match.name] = match
    return [found[name] for name in sorted(found)]


def tail_text(path, max_bytes: int = 64_000) -> str:
    """The last *max_bytes* of *path*, decoded leniently.

    Seeks rather than reading the whole file. fMRIPrep logs run to tens of
    megabytes and every caller here displays a few thousand characters of the
    end, so reading the lot was pure cost — paid, in the cockpit's case, on every
    render of every failed or running cell.

    Drops the first line after a truncation, since seeking lands mid-line.
    """
    from pathlib import Path

    path = Path(path)
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                raw = f.read()
                _, _, raw = raw.partition(b"\n")
                return "…\n" + raw.decode(errors="replace")
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def job_log(job_id: str, log_dir: str, max_bytes: int = 64_000) -> dict[str, str]:
    """Read the tail of a job's stdout/stderr logs.

    Resolves files via :func:`find_job_logs` (so array-job / NORDIC logs are
    included), routing ``.err`` to stderr and everything else to stdout.

    Bounded per file — see :func:`tail_text`. Pass a larger *max_bytes* for a
    caller that genuinely wants more; nothing wants the whole file.

    Returns
    -------
    dict
        {"stdout": content, "stderr": content}
    """
    result = {"stdout": "", "stderr": ""}
    for match in find_job_logs(job_id, log_dir):
        content = tail_text(match, max_bytes)
        if match.suffix == ".err":
            result["stderr"] += content
        else:
            result["stdout"] += content
    return result
