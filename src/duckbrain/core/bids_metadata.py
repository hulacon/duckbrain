"""BIDS metadata file generation — participants.tsv and dataset_description.json.

Inspired by mrpyconvert (Jolinda Smith, LCNI/UO).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pydicom


def read_dicom_demographics(dicom_dir: str | Path) -> dict:
    """Extract participant demographics from a DICOM file in a directory.

    Reads the first valid DICOM found and extracts PatientSex and PatientAge.

    Parameters
    ----------
    dicom_dir : path
        Directory containing DICOM files (or a series subdirectory).

    Returns
    -------
    dict
        {"sex": str, "age": int | None}. Sex is "M", "F", "O", or "".
    """
    dicom_dir = Path(dicom_dir)

    for f in dicom_dir.iterdir():
        if f.is_dir():
            # Recurse into first subdirectory (e.g., Series_01_...)
            result = read_dicom_demographics(f)
            if result["sex"] or result["age"] is not None:
                return result
            continue
        try:
            ds = pydicom.dcmread(f, stop_before_pixels=True)
            sex = getattr(ds, "PatientSex", "")
            age_str = getattr(ds, "PatientAge", "")
            age = None
            if age_str:
                # DICOM age format: "032Y", "045Y", etc.
                age = int(age_str.rstrip("YyMmWwDd"))
            return {"sex": sex, "age": age}
        except Exception:
            continue

    return {"sex": "", "age": None}


def write_participants_tsv(
    bids_dir: str | Path,
    participants: list[dict],
    append: bool = True,
) -> Path:
    """Write or append to participants.tsv and its companion JSON sidecar.

    Parameters
    ----------
    bids_dir : path
        Root BIDS directory.
    participants : list[dict]
        Each dict has keys: participant_id (e.g., "sub-01"), sex, age.
    append : bool
        If True, append to existing file (skipping duplicates). If False, overwrite.

    Returns
    -------
    Path
        Path to the written participants.tsv.
    """
    bids_dir = Path(bids_dir)
    bids_dir.mkdir(parents=True, exist_ok=True)

    tsv_path = bids_dir / "participants.tsv"
    json_path = bids_dir / "participants.json"
    fields = ["participant_id", "sex", "age"]

    # Load existing participants to avoid duplicates
    existing_ids = set()
    if append and tsv_path.exists():
        with open(tsv_path) as f:
            reader = csv.DictReader(f, dialect="excel-tab")
            for row in reader:
                existing_ids.add(row.get("participant_id", ""))

    new_participants = [p for p in participants if p["participant_id"] not in existing_ids]

    # Always ensure the file exists with a header, even with nothing to add, so
    # the returned path is valid (an empty BIDS participants.tsv is header-only).
    write_header = not tsv_path.exists()
    if write_header or new_participants:
        with open(tsv_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fields, dialect="excel-tab", extrasaction="ignore")
            if write_header:
                writer.writeheader()
            for p in new_participants:
                writer.writerow(p)

    # Always write the sidecar JSON
    sidecar = {
        "sex": {
            "Description": "Sex of the participant",
            "Levels": {"M": "male", "F": "female", "O": "other"},
        },
        "age": {
            "Description": "Age of the participant at time of scan",
            "Units": "years",
        },
    }
    with open(json_path, "w") as f:
        json.dump(sidecar, f, indent=2)

    return tsv_path


def _duckbrain_generated_by() -> dict:
    """The ``GeneratedBy`` entry for duckbrain itself, versioned from the package."""
    from .. import __version__

    return {"Name": "duckbrain", "Version": __version__}


def write_dataset_description(
    bids_dir: str | Path,
    name: str = "",
    extra_fields: dict | None = None,
    generated_by: list[dict] | None = None,
) -> Path:
    """Write dataset_description.json to the BIDS root.

    Parameters
    ----------
    bids_dir : path
        Root BIDS directory.
    name : str
        Dataset name. Defaults to the directory name.
    extra_fields : dict, optional
        Additional fields to include (e.g., License, Authors, Funding).
    generated_by : list[dict], optional
        ``GeneratedBy`` entries. Defaults to duckbrain's own entry (versioned
        from the package). Pass e.g. a dcm2bids entry to record the converter.

    Returns
    -------
    Path
        Path to the written file.
    """
    bids_dir = Path(bids_dir)
    bids_dir.mkdir(parents=True, exist_ok=True)
    desc_path = bids_dir / "dataset_description.json"

    description = {
        "Name": name or bids_dir.name,
        "BIDSVersion": "1.9.0",
        "GeneratedBy": generated_by or [_duckbrain_generated_by()],
    }

    if extra_fields:
        description.update(extra_fields)

    with open(desc_path, "w") as f:
        json.dump(description, f, indent=2)

    return desc_path


def write_derivative_description(
    deriv_dir: str | Path,
    pipeline_name: str,
    *,
    tool: str = "",
    tool_version: str = "",
    container: str = "",
    container_uri: str = "",
    code_url: str = "",
    source_dataset: str | Path | None = None,
    name: str = "",
) -> Path:
    """Write a BIDS-Derivatives ``dataset_description.json`` for a derivative.

    For derivatives duckbrain *produces itself* (e.g. NORDIC, which is a MATLAB
    job that writes no provenance of its own) so their on-disk provenance is in
    the **same format** the consistency checker reads from tool-written
    derivatives (fMRIPrep/MRIQC). Records ``DatasetType: derivative``, a
    ``GeneratedBy`` list (duckbrain + the underlying tool, with version and
    container when known), and — when *source_dataset* is given — a
    ``SourceDatasets`` entry plus a ``DatasetLinks.raw`` pointer, mirroring how
    fMRIPrep records its input.

    Idempotent: overwrites the derivative's dataset_description.json.
    """
    deriv_dir = Path(deriv_dir)
    deriv_dir.mkdir(parents=True, exist_ok=True)
    desc_path = deriv_dir / "dataset_description.json"

    tool_entry: dict = {}
    if tool:
        tool_entry["Name"] = tool
        if tool_version:
            tool_entry["Version"] = tool_version
        if container:
            # BIDS Container: Tag is the image we ran; URI its build source (the
            # registry reference the image records being built from), which is
            # provenance the filename can only approximate.
            tool_entry["Container"] = {"Type": "singularity", "Tag": container}
            if container_uri:
                tool_entry["Container"]["URI"] = container_uri
        if code_url:
            # For a tool that runs from a source checkout rather than an image
            # (NORDIC), the commit is the artifact — CodeURL pins it browsably.
            tool_entry["CodeURL"] = code_url

    generated_by = [_duckbrain_generated_by()]
    if tool_entry:
        generated_by.append(tool_entry)

    description: dict = {
        "Name": name or pipeline_name,
        "BIDSVersion": "1.9.0",
        "DatasetType": "derivative",
        "GeneratedBy": generated_by,
    }
    if source_dataset is not None:
        src = str(source_dataset)
        description["SourceDatasets"] = [{"URL": src}]
        description["DatasetLinks"] = {"raw": src}

    with open(desc_path, "w") as f:
        json.dump(description, f, indent=2)

    return desc_path


def generate_participants_from_sourcedata(
    sourcedata_dir: str | Path,
    bids_dir: str | Path,
) -> Path:
    """Scan sourcedata DICOM directories and generate participants.tsv.

    For each subject in sourcedata, reads the first available DICOM to
    extract demographics, then writes participants.tsv.

    Parameters
    ----------
    sourcedata_dir : path
        Sourcedata directory with sub-XX/ses-YY/dicom/ structure.
    bids_dir : path
        Root BIDS directory where participants.tsv will be written.

    Returns
    -------
    Path
        Path to participants.tsv.
    """
    sourcedata_dir = Path(sourcedata_dir)
    participants = []
    seen_subjects = set()

    for sub_dir in sorted(sourcedata_dir.iterdir()):
        if not sub_dir.is_dir() or not sub_dir.name.startswith("sub-"):
            continue

        subject_id = sub_dir.name
        if subject_id in seen_subjects:
            continue
        seen_subjects.add(subject_id)

        # Find any DICOM directory for this subject. Handles both the
        # single-session layout (sub-XX/dicom) and the multi-session layout
        # (sub-XX/ses-YY/dicom).
        demographics = {"sex": "", "age": None}
        dicom_dirs = [sub_dir / "dicom"] + [
            d / "dicom" for d in sorted(sub_dir.iterdir()) if d.is_dir()
        ]
        for dicom_dir in dicom_dirs:
            if dicom_dir.exists():
                demographics = read_dicom_demographics(dicom_dir)
                if demographics["sex"] or demographics["age"] is not None:
                    break

        participants.append(
            {
                "participant_id": subject_id,
                "sex": demographics["sex"],
                "age": demographics["age"],
            }
        )

    return write_participants_tsv(bids_dir, participants)
