"""NORDIC denoising — MATLAB wrapper + BIDS input tree builder."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def get_bold_runs(
    bids_dir: str | Path,
    subject: str,
    session: str,
) -> list[Path]:
    """Discover BOLD NIfTI files for a subject/session.

    Parameters
    ----------
    bids_dir : path
        Root BIDS directory.
    subject : str
        Subject label (without "sub-" prefix).
    session : str
        Session label (without "ses-" prefix).

    Returns
    -------
    list[Path]
        Paths to *_bold.nii.gz files, sorted.
    """
    bids_dir = Path(bids_dir)
    func_dir = bids_dir / f"sub-{subject}" / f"ses-{session}" / "func"

    if not func_dir.is_dir():
        return []

    return sorted(func_dir.glob("*_bold.nii.gz"))


def build_nordic_matlab_command(
    bold_path: str | Path,
    output_dir: str | Path,
    nordic_toolbox_dir: str | Path,
    matlab_module: str = "matlab/R2024a",
) -> str:
    """Build the MATLAB command string for NORDIC denoising.

    Parameters
    ----------
    bold_path : path
        Input BOLD NIfTI.
    output_dir : path
        Directory for denoised output.
    nordic_toolbox_dir : path
        Path to NORDIC_Raw MATLAB toolbox.
    matlab_module : str
        Module to load for MATLAB.

    Returns
    -------
    str
        Shell command to execute NORDIC denoising.
    """
    bold_path = Path(bold_path)
    output_dir = Path(output_dir)
    nordic_toolbox_dir = Path(nordic_toolbox_dir)

    # Get the directory containing nordic_denoise.m (shipped with duckbrain)
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"

    matlab_cmd = (
        f"addpath('{nordic_toolbox_dir}'); "
        f"addpath('{scripts_dir}'); "
        f"nordic_denoise('{bold_path}', '{output_dir}'); "
        f"exit;"
    )

    return (
        f"module load {matlab_module} && "
        f"matlab -nodisplay -nosplash -nodesktop -r \"{matlab_cmd}\""
    )


def build_nordic_bids_input(
    bids_dir: str | Path,
    subject: str,
    session: str,
    nordic_derivatives_dir: str | Path,
    output_bids_input_dir: str | Path | None = None,
) -> Path:
    """Build a BIDS-compatible input tree from NORDIC-denoised data.

    Reimplements mmmdata's nordic_build_bids_input.sh in Python:
    - NORDIC BOLDs are hardlinked (not copied) to save disk
    - All other func/ files (JSON, events, physio, SBRef) copied from raw BIDS
    - Fieldmaps copied from raw BIDS

    Parameters
    ----------
    bids_dir : path
        Raw BIDS root.
    subject : str
        Subject label (without "sub-" prefix).
    session : str
        Session label (without "ses-" prefix).
    nordic_derivatives_dir : path
        e.g., <derivatives>/nordic/<sub>/<ses>/func/ containing denoised BOLDs.
    output_bids_input_dir : path, optional
        Output directory. Defaults to <derivatives>/nordic/bids_input/.

    Returns
    -------
    Path
        The output BIDS input directory for this subject/session.
    """
    bids_dir = Path(bids_dir)
    nordic_derivatives_dir = Path(nordic_derivatives_dir)

    sub = f"sub-{subject}"
    ses = f"ses-{session}"

    if output_bids_input_dir is None:
        output_bids_input_dir = nordic_derivatives_dir.parent.parent / "bids_input"

    output_bids_input_dir = Path(output_bids_input_dir)
    out_sub_ses = output_bids_input_dir / sub / ses
    out_func = out_sub_ses / "func"
    out_fmap = out_sub_ses / "fmap"

    out_func.mkdir(parents=True, exist_ok=True)
    out_fmap.mkdir(parents=True, exist_ok=True)

    raw_func = bids_dir / sub / ses / "func"
    raw_fmap = bids_dir / sub / ses / "fmap"
    nordic_func = nordic_derivatives_dir / sub / ses / "func"

    # 1. Hardlink NORDIC BOLDs
    if nordic_func.is_dir():
        for bold in nordic_func.glob("*_bold.nii.gz"):
            dest = out_func / bold.name
            if not dest.exists():
                os.link(bold, dest)

    # 2. Copy non-BOLD func files from raw BIDS
    if raw_func.is_dir():
        for f in raw_func.iterdir():
            if f.name.endswith("_bold.nii.gz"):
                continue  # Skip — we use NORDIC versions
            dest = out_func / f.name
            if not dest.exists():
                shutil.copy2(f, dest)

    # 3. Copy fieldmaps from raw BIDS
    if raw_fmap.is_dir():
        for f in raw_fmap.iterdir():
            dest = out_fmap / f.name
            if not dest.exists():
                shutil.copy2(f, dest)

    # 4. Copy session-level scans.tsv if present
    scans_tsv = bids_dir / sub / ses / f"{sub}_{ses}_scans.tsv"
    if scans_tsv.exists():
        dest = out_sub_ses / scans_tsv.name
        if not dest.exists():
            shutil.copy2(scans_tsv, dest)

    return out_sub_ses


def nordic_output_dir(derivatives_dir: str | Path, subject: str, session: str) -> Path:
    """Standard NORDIC derivatives output path."""
    return Path(derivatives_dir) / "nordic" / f"sub-{subject}" / f"ses-{session}" / "func"
