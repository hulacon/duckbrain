"""fMRIPrep orchestration — build Singularity commands for fMRIPrep runs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def build_fmriprep_command(
    bids_dir: str | Path,
    output_dir: str | Path,
    work_dir: str | Path,
    subject: str,
    container_path: str | Path,
    fs_license: str | Path,
    session: str | None = None,
    output_spaces: list[str] | None = None,
    nprocs: int = 8,
    mem_gb: int = 32,
    anat_only: bool = False,
    derivatives: str | Path | None = None,
    bids_filter_file: str | Path | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Construct a Singularity run command for fMRIPrep.

    Parameters
    ----------
    bids_dir : path
        Input BIDS directory.
    output_dir : path
        fMRIPrep output directory.
    work_dir : path
        Working directory for intermediate files.
    subject : str
        Subject label (without "sub-" prefix).
    container_path : path
        Path to fMRIPrep Singularity image.
    fs_license : path
        Path to FreeSurfer license file.
    session : str, optional
        Session label to restrict processing.
    output_spaces : list[str], optional
        Output spaces. Defaults to MNI152NLin2009cAsym:res-2, fsaverage6, func.
    nprocs : int
        Number of processors.
    mem_gb : int
        Memory limit in GB.
    anat_only : bool
        Run only anatomical workflows.
    derivatives : path, optional
        Precomputed derivatives (e.g., anat-only outputs to reuse).
    bids_filter_file : path, optional
        BIDS filter JSON to restrict processing.
    extra_args : list[str], optional
        Additional fMRIPrep arguments.

    Returns
    -------
    list[str]
        Command arguments for subprocess.
    """
    bids_dir = Path(bids_dir)
    output_dir = Path(output_dir)
    work_dir = Path(work_dir)
    container_path = Path(container_path)
    fs_license = Path(fs_license)

    if output_spaces is None:
        output_spaces = ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"]

    # Session-isolated work dir to prevent race conditions
    if session:
        work_dir = work_dir / f"sub-{subject}_ses-{session}"

    binds = [
        f"{bids_dir}:{bids_dir}:ro",
        f"{output_dir}:{output_dir}",
        f"{work_dir}:{work_dir}",
        f"{fs_license.parent}:{fs_license.parent}:ro",
    ]

    if derivatives:
        derivatives = Path(derivatives)
        binds.append(f"{derivatives}:{derivatives}:ro")

    cmd = ["singularity", "run", "--cleanenv"]
    for b in binds:
        cmd.extend(["-B", b])

    cmd.extend([
        str(container_path),
        str(bids_dir),
        str(output_dir),
        "participant",
        "--participant-label", subject,
        "--output-spaces", *output_spaces,
        "--fs-license-file", str(fs_license),
        "--nprocs", str(nprocs),
        "--mem-mb", str(mem_gb * 1024),
        "-w", str(work_dir),
        "--skip-bids-validation",
        "--notrack",
    ])

    if anat_only:
        cmd.append("--anat-only")

    if derivatives:
        cmd.extend(["--derivatives", str(derivatives)])

    if bids_filter_file:
        cmd.extend(["--bids-filter-file", str(bids_filter_file)])
    elif session:
        # Auto-generate a filter file
        filter_path = work_dir / "bids_filter.json"
        filter_path.parent.mkdir(parents=True, exist_ok=True)
        bids_filter = {
            "bold": {"session": session},
            "sbref": {"session": session},
            "fmap": {"session": session},
            "t1w": {"session": session},
            "t2w": {"session": session},
        }
        with open(filter_path, "w") as f:
            json.dump(bids_filter, f, indent=2)
        cmd.extend(["--bids-filter-file", str(filter_path)])

    if extra_args:
        cmd.extend(extra_args)

    return cmd


def run_fmriprep(
    dry_run: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess | list[str]:
    """Build and optionally execute the fMRIPrep command.

    All kwargs are forwarded to build_fmriprep_command.
    """
    cmd = build_fmriprep_command(**kwargs)
    if dry_run:
        return cmd
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def get_container_path(config: dict) -> Path:
    """Get the path to the fMRIPrep Singularity image from config."""
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["fmriprep_version"]
    for pattern in [
        f"fmriprep-{version}.sif",
        f"fmriprep-{version}.simg",
        f"fmriprep_{version}.sif",
        "fmriprep.sif",
        "fmriprep.simg",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    return containers_dir / f"fmriprep-{version}.sif"


def find_fs_license(config: dict) -> Path | None:
    """Auto-detect FreeSurfer license file.

    Checks (in order):
    1. config paths.fs_license
    2. $FREESURFER_HOME/license.txt
    3. $FS_LICENSE
    4. ~/license.txt
    """
    import os

    # From config
    lic = config.get("paths", {}).get("fs_license", "")
    if lic and Path(lic).exists():
        return Path(lic)

    # Environment
    fs_home = os.environ.get("FREESURFER_HOME", "")
    if fs_home:
        p = Path(fs_home) / "license.txt"
        if p.exists():
            return p

    fs_lic = os.environ.get("FS_LICENSE", "")
    if fs_lic and Path(fs_lic).exists():
        return Path(fs_lic)

    # Home directory
    p = Path.home() / "license.txt"
    if p.exists():
        return p

    return None
