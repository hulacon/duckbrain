"""SLURM job submission."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path


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
    if scripts_dir:
        scripts_dir = Path(scripts_dir)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / f"{job_name}.sbatch"
        script_path.write_text(sbatch_content)
    else:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".sbatch", prefix=f"{job_name}_", delete=False
        )
        tmp.write(sbatch_content)
        tmp.close()
        script_path = Path(tmp.name)

    result = subprocess.run(
        ["sbatch", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"sbatch failed (exit {result.returncode}):\n{result.stderr}"
        )

    # Parse job ID from "Submitted batch job 12345"
    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job ID from sbatch output: {result.stdout}")

    return match.group(1)


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
    if scripts_dir:
        scripts_dir = Path(scripts_dir)
        scripts_dir.mkdir(parents=True, exist_ok=True)
        script_path = scripts_dir / f"{job_name}.sbatch"
        script_path.write_text(sbatch_content)
    else:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".sbatch", prefix=f"{job_name}_", delete=False
        )
        tmp.write(sbatch_content)
        tmp.close()
        script_path = Path(tmp.name)

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
        raise RuntimeError(
            f"sbatch failed (exit {result.returncode}):\n{result.stderr}"
        )

    match = re.search(r"Submitted batch job (\d+)", result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse job ID from sbatch output: {result.stdout}")

    return match.group(1)


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
