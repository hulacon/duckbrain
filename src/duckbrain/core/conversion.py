"""Orchestrate dcm2bids runs via Singularity."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..config import get_slurm_resources, load_config


def build_dcm2bids_command(
    subject: str,
    session: str,
    dicom_dir: str | Path,
    bids_dir: str | Path,
    config_json: str | Path,
    container_path: str | Path,
    force: bool = False,
) -> list[str]:
    """Construct a Singularity exec command for dcm2bids.

    Parameters
    ----------
    subject : str
        Subject label (without "sub-" prefix).
    session : str
        Session label (without "ses-" prefix).
    dicom_dir : path
        Path to DICOM directory for this session.
    bids_dir : path
        Output BIDS directory root.
    config_json : path
        Path to dcm2bids config JSON file.
    container_path : path
        Path to dcm2bids Singularity image.
    force : bool
        Force overwrite of existing output.

    Returns
    -------
    list[str]
        Command arguments for subprocess.
    """
    dicom_dir = Path(dicom_dir)
    bids_dir = Path(bids_dir)
    config_json = Path(config_json)
    container_path = Path(container_path)

    cmd = [
        "singularity",
        "run",
        "--cleanenv",
        "-B", f"{dicom_dir}:{dicom_dir}:ro",
        "-B", f"{bids_dir}:{bids_dir}",
        "-B", f"{config_json.parent}:{config_json.parent}:ro",
        str(container_path),
        "-d", str(dicom_dir),
        "-p", subject,
        "-s", session,
        "-c", str(config_json),
        "-o", str(bids_dir),
    ]

    if force:
        cmd.append("--force_dcm2bids")

    return cmd


def run_dcm2bids(
    subject: str,
    session: str,
    dicom_dir: str | Path,
    bids_dir: str | Path,
    config_json: str | Path,
    container_path: str | Path,
    force: bool = False,
    dry_run: bool = False,
) -> subprocess.CompletedProcess | list[str]:
    """Run dcm2bids conversion.

    Parameters
    ----------
    dry_run : bool
        If True, return the command instead of executing.

    Returns
    -------
    CompletedProcess or list[str]
        Execution result or command (if dry_run).
    """
    cmd = build_dcm2bids_command(
        subject, session, dicom_dir, bids_dir, config_json, container_path, force
    )

    if dry_run:
        return cmd

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result


def save_dcm2bids_config(config_dict: dict, output_path: str | Path) -> Path:
    """Write a dcm2bids config dict to a JSON file.

    Parameters
    ----------
    config_dict : dict
        The dcm2bids config (from dcm2bids_config.generate_config).
    output_path : path
        Where to write the JSON.

    Returns
    -------
    Path
        The written file path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(config_dict, f, indent=2)
    return output_path


def get_container_path(config: dict) -> Path:
    """Get the path to the dcm2bids Singularity image from config."""
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["dcm2bids_version"]
    # Try common naming patterns
    for pattern in [
        f"dcm2bids-{version}.sif",
        f"dcm2bids-{version}.simg",
        f"dcm2bids_{version}.sif",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    # Return the default pattern even if it doesn't exist yet
    return containers_dir / f"dcm2bids-{version}.sif"
