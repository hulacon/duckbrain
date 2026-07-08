"""MRIQC orchestration — build Singularity commands for MRIQC."""

from __future__ import annotations

import subprocess
from pathlib import Path


def build_mriqc_command(
    bids_dir: str | Path,
    output_dir: str | Path,
    work_dir: str | Path,
    container_path: str | Path,
    subject: str | None = None,
    session: str | None = None,
    analysis_level: str = "participant",
    nprocs: int = 4,
    mem_gb: int = 16,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Construct a Singularity run command for MRIQC.

    Parameters
    ----------
    bids_dir : path
        Input BIDS directory.
    output_dir : path
        MRIQC output directory.
    work_dir : path
        Working directory.
    container_path : path
        Path to MRIQC Singularity image.
    subject : str, optional
        Subject label (without "sub-" prefix).
    session : str, optional
        Session label (without "ses-" prefix).
    analysis_level : str
        "participant" or "group".
    nprocs : int
        Number of processors.
    mem_gb : int
        Memory limit in GB.
    extra_args : list[str], optional
        Additional MRIQC arguments.

    Returns
    -------
    list[str]
        Command arguments for subprocess.
    """
    bids_dir = Path(bids_dir)
    output_dir = Path(output_dir)
    work_dir = Path(work_dir)
    container_path = Path(container_path)

    # Session-isolated work dir
    if subject and session:
        work_dir = work_dir / f"mriqc_sub-{subject}_ses-{session}"

    binds = [
        f"{bids_dir}:{bids_dir}:ro",
        f"{output_dir}:{output_dir}",
        f"{work_dir}:{work_dir}",
    ]

    cmd = ["singularity", "run", "--cleanenv"]
    for b in binds:
        cmd.extend(["-B", b])

    cmd.extend([
        str(container_path),
        str(bids_dir),
        str(output_dir),
        analysis_level,
        "--nprocs", str(nprocs),
        "--mem-gb", str(mem_gb),
        "-w", str(work_dir),
        "--no-sub",
    ])

    if subject:
        cmd.extend(["--participant-label", subject])
    if session:
        cmd.extend(["--session-id", session])

    if extra_args:
        cmd.extend(extra_args)

    return cmd


def run_mriqc(
    dry_run: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess | list[str]:
    """Build and optionally execute the MRIQC command.

    All kwargs are forwarded to build_mriqc_command.
    """
    cmd = build_mriqc_command(**kwargs)
    if dry_run:
        return cmd
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def get_container_path(config: dict) -> Path:
    """Get the path to the MRIQC Singularity image from config."""
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["mriqc_version"]
    for pattern in [
        f"mriqc-{version}.sif",
        f"mriqc-{version}.simg",
        f"mriqc_{version}.sif",
        "mriqc.sif",
        "mriqc.simg",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    return containers_dir / f"mriqc-{version}.sif"
