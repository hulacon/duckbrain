"""Sort unsorted DICOM files into an organized directory hierarchy.

Inspired by mrpyconvert's dicom_sorter.py (Jolinda Smith, LCNI/UO).

Organizes flat/mixed DICOM files into:
    <output_dir>/[StudyDescription/]<PatientName>_<Date>_<Time>/Series_<NN>_<Description>/<file>

This is the directory layout expected by LCNI tools and duckbrain's ingestion module.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pydicom

#: Characters allowed through into a path component built from DICOM metadata.
#: Everything else — separators, NULs, control characters, quotes, whitespace —
#: becomes an underscore.
_UNSAFE = re.compile(r"[^A-Za-z0-9.+-]")


class UnsafeSortPaths(ValueError):
    """The input/output roots given to :func:`sort_dicoms` are not usable."""


def safe_component(raw: str, fallback: str) -> str:
    """Reduce DICOM metadata to one safe path component.

    Not :func:`~duckbrain.core.dicom_inspect.sanitize_task_label`, deliberately:
    that reduces a string to bare alphanumerics because a BIDS entity value has
    to. This is a *directory name* a human reads and LCNI tooling parses, so
    dots, plus signs and hyphens survive and only genuinely dangerous characters
    are replaced.

    Metadata went into the destination path unmodified, and none of it is under
    duckbrain's control: a ``PatientName`` of ``../../etc`` escaped the output
    tree, and ``joinpath`` with an absolute-looking part discarded the output
    root entirely. This needs no malicious DICOM — site and scanner conventions
    put slashes, carets and spaces in these fields routinely.

    Returns *fallback* when nothing usable survives, so a blank field can never
    produce an empty component (which would silently collapse the hierarchy).
    """
    cleaned = _UNSAFE.sub("_", str(raw)).strip("._")
    if not cleaned or set(cleaned) <= {"."}:
        return fallback
    return cleaned


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
    input_dir = Path(input_dir).absolute()
    output_dir = Path(output_dir).absolute()
    result = SortResult()

    # Overlapping roots are never what the user meant, and with the default
    # move they are destructive: the sorter rearranges the source tree into
    # itself, and already-sorted output can be rediscovered as new input.
    in_res, out_res = Path(os.path.normpath(input_dir)), Path(os.path.normpath(output_dir))
    if in_res == out_res or out_res.is_relative_to(in_res) or in_res.is_relative_to(out_res):
        raise UnsafeSortPaths(
            f"Input {input_dir} and output {output_dir} overlap. Sorting one tree "
            "into itself moves files while they are being walked."
        )

    # Collect all files recursively. Not followlinks=True: a symlinked directory
    # can point back into the tree (an unbounded walk) or out of it entirely,
    # and a DICOM export has no reason to need it.
    all_files = []
    for root, _dirs, files in os.walk(input_dir):
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

        # Build output path. Every component comes from metadata, so every
        # component is sanitized — see `safe_component`.
        session_dir = output_dir
        if include_study_dir and study_desc:
            # StudyDescription uses ^ as its own separator, so it legitimately
            # expands to several levels. Each is sanitized independently, which
            # is what stops an absolute-looking part from resetting the join.
            for part in str(study_desc).split("^"):
                cleaned = safe_component(part, "")
                if cleaned:
                    session_dir = session_dir / cleaned

        dest = (
            session_dir
            / (
                safe_component(patient_name, "Unknown")
                + f"_{safe_component(date, '00000000')}"
                + f"_{safe_component(time, '000000')}"
            )
            / f"Series_{series_num:02d}_{safe_component(series_desc, 'unknown')}"
            / safe_component(filepath.name, "file.dcm")
        )

        # The invariant, asserted rather than assumed: whatever the metadata
        # said, the destination is inside the output root.
        if not Path(os.path.normpath(dest)).is_relative_to(out_res):
            result.failed_files += 1
            result.errors.append(f"{filepath.name}: destination {dest} escapes {output_dir}")
            continue

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
