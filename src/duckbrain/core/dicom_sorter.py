"""Sort unsorted DICOM files into an organized directory hierarchy.

Inspired by mrpyconvert's dicom_sorter.py (Jolinda Smith, LCNI/UO).

Organizes flat/mixed DICOM files into:
    <output_dir>/[StudyDescription/]<PatientName>_<Date>_<Time>/Series_<NN>_<Description>/<file>

This is the directory layout expected by LCNI tools and duckbrain's ingestion module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pydicom


@dataclass
class SortResult:
    """Summary of a DICOM sorting operation."""

    total_files: int = 0
    sorted_files: int = 0
    skipped_files: int = 0
    failed_files: int = 0
    duplicates: int = 0
    errors: list[str] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


def sort_dicoms(
    input_dir: str | Path,
    output_dir: str | Path,
    include_study_dir: bool = False,
    overwrite: bool = False,
    copy: bool = False,
    dry_run: bool = False,
) -> SortResult:
    """Sort unsorted DICOM files into an organized hierarchy.

    Walks the input directory recursively, reads each DICOM file's metadata,
    and moves (or copies) it into:
        <output_dir>/[<StudyDescription>/]<PatientName>_<Date>_<Time>/
            Series_<NN>_<Description>/<original_filename>

    Parameters
    ----------
    input_dir : path
        Directory containing unsorted DICOM files.
    output_dir : path
        Root directory for organized output.
    include_study_dir : bool
        If True, add StudyDescription as a top-level grouping directory.
    overwrite : bool
        If True, overwrite existing files. Otherwise skip duplicates.
    copy : bool
        If True, copy files instead of moving them.
    dry_run : bool
        If True, report what would happen without moving/copying files.

    Returns
    -------
    SortResult
        Summary of the operation.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    result = SortResult()

    # Collect all files recursively
    all_files = []
    for root, _dirs, files in os.walk(input_dir, followlinks=True):
        for fname in files:
            all_files.append(Path(root) / fname)

    result.total_files = len(all_files)

    for filepath in all_files:
        try:
            ds = pydicom.dcmread(filepath, stop_before_pixels=True)
        except Exception:
            result.skipped_files += 1
            continue

        try:
            patient_name = str(getattr(ds, "PatientName", "Unknown"))
            date = getattr(ds, "StudyDate", "00000000")
            time = getattr(ds, "StudyTime", "000000").split(".")[0]
            series_num = getattr(ds, "SeriesNumber", 0)
            series_desc = getattr(ds, "SeriesDescription", "unknown")
            study_desc = getattr(ds, "StudyDescription", "")
        except Exception as e:
            result.failed_files += 1
            result.errors.append(f"{filepath.name}: {e}")
            continue

        # Build output path
        if include_study_dir and study_desc:
            # StudyDescription may contain ^ separators
            study_parts = study_desc.split("^")
            session_dir = output_dir.joinpath(*study_parts)
        else:
            session_dir = output_dir

        dest = (
            session_dir
            / f"{patient_name}_{date}_{time}"
            / f"Series_{series_num:02d}_{series_desc}"
            / filepath.name
        )

        if not overwrite and dest.exists():
            result.duplicates += 1
            continue

        if dry_run:
            result.sorted_files += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        if copy:
            import shutil
            shutil.copy2(filepath, dest)
        else:
            os.renames(filepath, dest)
        result.sorted_files += 1

    return result
