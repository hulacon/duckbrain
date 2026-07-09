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
    # Resolve the DICOM dir so the Singularity bind source is the REAL directory.
    # Sourcedata uses symlink ingestion (sub-XX/dicom -> LCNI export). Binding the
    # symlink location works on Talapas (Singularity follows it), but binding the
    # resolved target is explicit and portable across Singularity/Apptainer configs
    # that restrict or don't follow symlinked bind sources.
    dicom_dir = Path(dicom_dir).resolve()
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
    ]

    # Omit -s for single-session studies (no ses- entity)
    if session:
        cmd += ["-s", session]

    cmd += [
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


def resolve_dicom_dir(sourcedata_dir: str | Path, subject: str, session: str) -> Path:
    """Path to a session's ingested DICOM dir, following the ingest symlink."""
    from .ingestion import sub_ses_relpath

    dicom_dir = Path(sourcedata_dir) / sub_ses_relpath(subject, session) / "dicom"
    return dicom_dir.resolve() if dicom_dir.is_symlink() else dicom_dir


def session_bids_exists(bids_dir: str | Path, subject: str, session: str) -> bool:
    """Whether a session already has BIDS output (any NIfTI under its sub[/ses] dir).

    Presence-based, not completion-based: a partial/failed conversion also counts
    as "exists". Callers that want to redo it should pass force to dcm2bids.
    """
    from .ingestion import sub_ses_relpath

    sub_dir = Path(bids_dir) / sub_ses_relpath(subject, session)
    return sub_dir.is_dir() and any(sub_dir.rglob("*.nii.gz"))


def generate_session_config(
    dicom_dir: str | Path,
    subject: str,
    session: str,
    template: str | None = None,
) -> dict:
    """Inspect a session's DICOMs and build a default dcm2bids config.

    The non-interactive equivalent of the Conversion page's inspect → classify →
    fieldmap → task/run mapping → generate_config pipeline, using the auto-derived
    task/run mapping (no manual edits). Used for bulk conversion.
    """
    from .dicom_inspect import list_series, classify_series, detect_fieldmaps
    from .dcm2bids_config import build_task_run_mapping, generate_config

    series_list = list_series(dicom_dir)
    if not series_list:
        raise ValueError(f"No series directories found in {dicom_dir}")
    classify_series(series_list)
    fieldmaps = detect_fieldmaps(series_list)
    mapping = build_task_run_mapping(series_list, template=template or None)
    return generate_config(
        series_list, fieldmaps, subject=subject, session=session, mapping=mapping
    )


def get_container_path(config: dict) -> Path:
    """Get the path to the dcm2bids Singularity image from config."""
    containers_dir = Path(config["paths"]["containers_dir"])
    version = config["containers"]["dcm2bids_version"]
    # Try common naming patterns
    for pattern in [
        f"dcm2bids-{version}.sif",
        f"dcm2bids-{version}.simg",
        f"dcm2bids_{version}.sif",
        "dcm2bids.sif",
        "dcm2bids.simg",
    ]:
        path = containers_dir / pattern
        if path.exists():
            return path
    # Return the default pattern even if it doesn't exist yet
    return containers_dir / f"dcm2bids-{version}.sif"
