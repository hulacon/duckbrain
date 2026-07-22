"""SLURM job submission."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def archived_script_path(scripts_dir: str | Path, job_name: str, job_id: str) -> Path:
    """Where the immutable copy of a submitted script lives.

    The job id is only known *after* sbatch returns, so the script is written
    under its job name, submitted, and then copied here.
    """
    return Path(scripts_dir) / f"{job_name}_{job_id}.sbatch"


def _stage_script(sbatch_content: str, job_name: str, scripts_dir) -> Path:
    """Write *sbatch_content* somewhere sbatch can read it."""
    if scripts_dir:
        scripts_dir = Path(scripts_dir)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / f"{job_name}.sbatch"
        script_path.write_text(sbatch_content)
        return script_path
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".sbatch", prefix=f"{job_name}_", delete=False
    )
    tmp.write(sbatch_content)
    tmp.close()
    return Path(tmp.name)


def _archive_script(script_path: Path, scripts_dir, job_name: str, job_id: str) -> None:
    """Keep an immutable copy of what was actually submitted.

    The staged filename is derived from the job name alone, and a job name is
    deterministic per unit and stage — so every retry overwrote the previous
    attempt's script. The submission log recorded which container ran but not
    what was asked of it, so after a re-run with different resources or flags the
    exact command line of the failed attempt was unrecoverable, even though its
    .out log and its submissions.tsv row both still existed.

    The ``{job_name}.sbatch`` copy stays as the convenient "latest" one. Never
    let an archiving failure sink a submission that already succeeded.
    """
    if not scripts_dir:
        return
    try:
        shutil.copy2(script_path, archived_script_path(scripts_dir, job_name, job_id))
    except OSError:
        pass


def submit_job(
    sbatch_content: str,
    job_name: str = "duckbrain",
    scripts_dir: str | Path | None = None,
) -> str:
    """Submit an sbatch script and return the job ID.

    Parameters
    ----------
    sbatch_content : str
        Rendered sbatch script content.
    job_name : str
        Job name (for the temp file).
    scripts_dir : path, optional
        Directory to write the script file. Uses tempdir if None.

    Returns
    -------
    str
        SLURM job ID.

    Raises
    ------
    RuntimeError
        If sbatch submission fails.
    """
    script_path = _stage_script(sbatch_content, job_name, scripts_dir)

    result = subprocess.run(
        ["sbatch", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed (exit {result.returncode}):\n{result.stderr}")

    # Parse job ID from "Submitted batch job 12345"
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job ID from sbatch output: {result.stdout}")

    job_id = match.group(1)
    _archive_script(script_path, scripts_dir, job_name, job_id)
    return job_id


def submit_with_dependency(
    sbatch_content: str,
    job_name: str,
    after_job_id: str,
    dependency_type: str = "afterok",
    scripts_dir: str | Path | None = None,
) -> str:
    """Submit a job that depends on another job completing successfully.

    Parameters
    ----------
    after_job_id : str
        Job ID to depend on.
    dependency_type : str
        Dependency type (afterok, afterany, after, afternotok).

    Returns
    -------
    str
        New SLURM job ID.
    """
    script_path = _stage_script(sbatch_content, job_name, scripts_dir)

    result = subprocess.run(
        [
            "sbatch",
            f"--dependency={dependency_type}:{after_job_id}",
            str(script_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"sbatch failed (exit {result.returncode}):\n{result.stderr}")

    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job ID from sbatch output: {result.stdout}")

    job_id = match.group(1)
    _archive_script(script_path, scripts_dir, job_name, job_id)
    return job_id


def export_script(sbatch_content: str, output_path: str | Path) -> Path:
    """Save an sbatch script to a file (for manual submission).

    Parameters
    ----------
    sbatch_content : str
        Rendered sbatch script.
    output_path : path
        Where to save.

    Returns
    -------
    Path
        The written file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sbatch_content)
    return output_path
