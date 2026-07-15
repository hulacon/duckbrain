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
    from .ingestion import sub_ses_relpath

    bids_dir = Path(bids_dir)
    func_dir = bids_dir / sub_ses_relpath(subject, session) / "func"

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
    """Build a self-contained BIDS tree from NORDIC-denoised data for fMRIPrep.

    Assembles ``derivatives/nordic/bids_format/`` — a valid BIDS dataset that
    swaps the NORDIC-denoised BOLDs in for the raw ones while carrying everything
    else fMRIPrep needs:
    - NORDIC BOLDs are hardlinked (not copied) to save disk
    - All other func/ files (JSON, events, physio, SBRef) copied from raw BIDS
    - Fieldmaps copied from raw BIDS
    - Anatomicals included (nifti hardlinked, sidecars copied) so fMRIPrep runs
      end-to-end without a prior non-NORDIC run
    - Dataset root files (dataset_description.json, participants.*, .bidsignore)
      copied once, so fMRIPrep accepts the tree as a dataset

    Parameters
    ----------
    bids_dir : path
        Raw BIDS root.
    subject : str
        Subject label (without "sub-" prefix).
    session : str
        Session label (without "ses-" prefix).
    nordic_derivatives_dir : path
        The NORDIC derivatives root, ``<derivatives>/nordic``. The denoised BOLDs
        for a unit live under ``<nordic_derivatives_dir>/sub-XX[/ses-YY]/func/``.
    output_bids_input_dir : path, optional
        Output directory. Defaults to ``<derivatives>/nordic/bids_input/``.

    Returns
    -------
    Path
        The output BIDS input directory for this subject/session.
    """
    from .ingestion import sub_ses_relpath

    bids_dir = Path(bids_dir)
    nordic_derivatives_dir = Path(nordic_derivatives_dir)

    sub = f"sub-{subject}"
    # Session-aware relative fragment: omits the ses- level for sessionless data,
    # so nothing writes a malformed ``ses-/func`` path.
    ss = sub_ses_relpath(subject, session)

    if output_bids_input_dir is None:
        # Sibling of the per-subject NORDIC output, i.e.
        # <derivatives>/nordic/bids_format/ — the self-contained BIDS tree
        # fMRIPrep reads when use_nordic is on. (The caller passes
        # <derivatives>/nordic as nordic_derivatives_dir.)
        output_bids_input_dir = nordic_derivatives_dir / "bids_format"

    output_bids_input_dir = Path(output_bids_input_dir)
    out_sub_ses = output_bids_input_dir / ss
    out_func = out_sub_ses / "func"
    out_fmap = out_sub_ses / "fmap"
    out_anat = out_sub_ses / "anat"

    out_func.mkdir(parents=True, exist_ok=True)
    out_fmap.mkdir(parents=True, exist_ok=True)

    raw_func = bids_dir / ss / "func"
    raw_fmap = bids_dir / ss / "fmap"
    raw_anat = bids_dir / ss / "anat"
    nordic_func = nordic_derivatives_dir / ss / "func"

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

    # 4. Include anatomicals so fMRIPrep runs end-to-end (nifti hardlinked to save
    # disk — anat is unchanged by NORDIC — sidecars copied). Only make the dir if
    # the unit actually has anat.
    if raw_anat.is_dir():
        out_anat.mkdir(parents=True, exist_ok=True)
        for f in raw_anat.iterdir():
            dest = out_anat / f.name
            if dest.exists():
                continue
            if f.name.endswith(".nii.gz"):
                os.link(f, dest)
            else:
                shutil.copy2(f, dest)

    # 5. Copy the unit-level scans.tsv if present. Its filename carries the same
    # entities as the dir path: sub-XX_ses-YY_scans.tsv or sub-XX_scans.tsv.
    scans_name = f"{sub}_ses-{session}_scans.tsv" if session else f"{sub}_scans.tsv"
    scans_tsv = bids_dir / ss / scans_name
    if scans_tsv.exists():
        dest = out_sub_ses / scans_tsv.name
        if not dest.exists():
            shutil.copy2(scans_tsv, dest)

    # 6. Copy dataset root files once, so the tree is a valid BIDS dataset that
    # fMRIPrep accepts (it errors without dataset_description.json even with
    # --skip-bids-validation). Idempotent; skips whatever the raw dataset lacks.
    for root_name in ("dataset_description.json", "participants.tsv",
                      "participants.json", "README", ".bidsignore"):
        src = bids_dir / root_name
        dest = output_bids_input_dir / root_name
        if src.exists() and not dest.exists():
            shutil.copy2(src, dest)

    return out_sub_ses


def nordic_output_dir(derivatives_dir: str | Path, subject: str, session: str = "") -> Path:
    """Standard NORDIC derivatives output path.

    ``sub_ses_relpath`` omits the ``ses-`` level for sessionless (single-session)
    data, so this returns ``.../nordic/sub-XX/func`` when *session* is empty and
    ``.../nordic/sub-XX/ses-YY/func`` otherwise — matching what the
    ``nordic_denoise`` sbatch template writes.
    """
    from .ingestion import sub_ses_relpath

    return Path(derivatives_dir) / "nordic" / sub_ses_relpath(subject, session) / "func"
