"""BIDS metadata file generation — participants.tsv and dataset_description.json.

Inspired by mrpyconvert (Jolinda Smith, LCNI/UO).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pydicom

if TYPE_CHECKING:
    from ..config import Config


def read_dicom_demographics(dicom_dir: str | Path) -> dict[str, Any]:
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
    participants: list[dict[str, Any]],
    append: bool = True,
) -> Path:
    """Write or append to participants.tsv, plus its JSON sidecar when absent.

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

    # The sidecar only when absent: it describes the two columns *this function*
    # writes, but an existing participants.json can define columns duckbrain
    # knows nothing about (group, handedness, diagnosis…) — an imported BIDS
    # tree's, or a hand-extended one. The TSV path above never removes columns,
    # so the sidecar must not either.
    if not json_path.exists():
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


def _duckbrain_repo() -> Path:
    """duckbrain's own source root (``src/duckbrain/core/`` → repo root)."""
    return Path(__file__).resolve().parents[3]


def duckbrain_version() -> str:
    """duckbrain's own version: a ``git describe`` of its checkout, else ``__version__``.

    See :func:`_duckbrain_generated_by` for why the checkout wins.
    """
    from .. import __version__
    from .toolbox import describe

    return describe(_duckbrain_repo()) or __version__


def _duckbrain_generated_by() -> dict[str, Any]:
    """The ``GeneratedBy`` entry for duckbrain itself.

    Prefers a ``git describe`` of duckbrain's *own checkout* over the packaged
    ``__version__``. duckbrain is distributed by ``git clone`` and served straight
    from a working copy (the OnDemand app runs whatever is checked out), so users
    sit on arbitrary commits — a hand-maintained ``__version__`` would go stale
    between releases and stamp every derivative with the same number regardless of
    what actually ran. That is precisely the failure this codebase already
    diagnosed *upstream* in NORDIC, whose in-file ``% VERSION 4/22/2021`` marker is
    years behind its own HEAD (see ``core.toolbox``); recording it of others while
    committing it ourselves would be indefensible.

    Falls back to ``__version__`` when duckbrain is installed from a wheel rather
    than a checkout — there the packaged version *is* the truth.
    """
    return {"Name": "duckbrain", "Version": duckbrain_version()}


def _duckbrain_converted(config: Config) -> bool:
    """Whether this project's BIDS tree has a duckbrain conversion behind it.

    The evidence is the per-session ``dcm2bids_config.json`` duckbrain saves into
    sourcedata for every conversion — the same discriminator the surveyor's
    ``_converted_status`` uses to tell duckbrain output from an externally
    converted tree, so the two answer alike. Both sourcedata layouts are checked
    (``sub-XX/`` and ``sub-XX/ses-YY/``, per ``ingestion.sub_ses_relpath``).
    """
    src = Path((config.get("paths") or {}).get("sourcedata_dir", "") or "")
    if not src.is_dir():
        return False
    return any(
        next(src.glob(pattern), None) is not None
        for pattern in ("sub-*/dcm2bids_config.json", "sub-*/ses-*/dcm2bids_config.json")
    )


def converter_generated_by(config: Config, *, converting: bool = False) -> list[dict[str, Any]]:
    """``GeneratedBy`` for an ingested BIDS root: duckbrain **and** its converter.

    The raw BIDS root is duckbrain's own output too — it ran dcm2bids to make it —
    so it should say which converter produced it, in the same shape the derivative
    stamps use. Without this the root records duckbrain but not the tool that
    actually did the conversion, which is the more decision-relevant of the two:
    dcm2bids' own version determines the BIDS it emits.

    But the converter entry is a *claim that dcm2bids produced this tree*, and the
    provenance the entry is built from is config, not any record of a run — so it
    is only made when it can be true. At the conversion choke point it is true by
    construction (a dcm2bids submission is being built; pass ``converting=True``).
    Everywhere else it must be proven by :func:`_duckbrain_converted`, because an
    externally converted BIDS tree — which ``discover_units`` deliberately
    supports — would otherwise get a fabricated dcm2bids attribution stamped over
    provenance some other tool honestly wrote.

    Note this complements rather than duplicates dcm2bids' per-file
    ``Dcm2bidsVersion`` sidecar fields — those describe each file, this describes
    the dataset. Best-effort: degrades to duckbrain's entry alone rather than
    blocking a write.
    """
    entries = [_duckbrain_generated_by()]
    if not converting and not _duckbrain_converted(config):
        return entries
    try:
        from .containers import container_uri
        from .pipeline import resolve_container, run_provenance

        prov = run_provenance(config, "converted")
        entry: dict[str, Any] = {"Name": prov["tool"] or "dcm2bids"}
        if prov["tool_version"]:
            entry["Version"] = prov["tool_version"]
        if prov["runtime"]:
            entry["Container"] = {"Type": "singularity", "Tag": prov["runtime"]}
            image = resolve_container(config, "converted")
            uri = container_uri(image) if image else ""
            if uri:
                entry["Container"]["URI"] = uri
        entries.append(entry)
    except Exception:
        pass
    return entries


def write_dataset_description(
    bids_dir: str | Path,
    name: str = "",
    extra_fields: dict[str, Any] | None = None,
    generated_by: list[dict[str, Any]] | None = None,
) -> Path:
    """Write dataset_description.json to the BIDS root, preserving what it didn't write.

    **Read-modify-write over the keys duckbrain owns**, not a whole-file dump. The
    raw root's description is shared with the user: BIDS defines ``License``,
    ``Funding``, ``EthicsApprovals``, ``ReferencesAndLinks`` and ``DatasetDOI``,
    duckbrain elicits none of them, and a whole-file dump destroyed every one on
    each press of the Ingestion page's "Generate" button. Same contract as
    :func:`~duckbrain.config._save_sections`' ``owned=``, one layer down and for
    the same reason. :func:`write_derivative_description` stays a full overwrite,
    correctly — a derivative's description is duckbrain's output end to end.

    Three rules that look like edge cases and are not:

    - *name* sets ``Name`` only when it is non-empty. The project name is a
      config field a user may never have filled in, and an unset one must not
      blank a hand-written dataset name.
    - *extra_fields* is applied on top, so a caller passes a key **only when it
      has a value**. :func:`dataset_extra_fields` omits ``Authors`` rather than
      passing ``[]``, so clearing the Setup field cannot blank an existing list.
      Same rule the Setup page's ``_clean_dict`` enforces one layer up.
    - *generated_by* **merges by ``Name``** into any existing list rather than
      replacing it (:func:`_merge_generated_by`). Replacement was the one hole
      left in the read-modify-write contract: on an imported BIDS tree it
      discarded the provenance the real converter wrote (heudiconv's, say) in
      favour of duckbrain's claim about itself. Entries duckbrain passes refresh
      in place; entries it didn't write survive.

    Parameters
    ----------
    bids_dir : path
        Root BIDS directory.
    name : str
        Dataset name. Only written when non-empty; falls back to the directory
        name when the file is being created from scratch.
    extra_fields : dict, optional
        Additional fields to set (e.g. License, Authors, Funding).
    generated_by : list[dict], optional
        ``GeneratedBy`` entries, merged by ``Name`` into any existing list (see
        above). Defaults to duckbrain's own entry when the file is being created
        from scratch. Pass e.g. a dcm2bids entry to record the converter.

    Returns
    -------
    Path
        Path to the written file.
    """
    bids_dir = Path(bids_dir)
    bids_dir.mkdir(parents=True, exist_ok=True)
    desc_path = bids_dir / "dataset_description.json"

    description = _read_json(desc_path)

    description["BIDSVersion"] = "1.9.0"
    if name or "Name" not in description:
        description["Name"] = name or bids_dir.name
    if generated_by:
        description["GeneratedBy"] = _merge_generated_by(
            description.get("GeneratedBy"), generated_by
        )
    elif "GeneratedBy" not in description:
        description["GeneratedBy"] = [_duckbrain_generated_by()]

    if extra_fields:
        description.update(extra_fields)

    with open(desc_path, "w") as f:
        json.dump(description, f, indent=2)

    return desc_path


def _merge_generated_by(existing: Any, new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge ``GeneratedBy`` entries by ``Name``: refresh ours, keep the rest.

    Entries in *new* replace an existing entry of the same ``Name`` in place and
    append otherwise, so an imported dataset's original provenance (heudiconv's,
    OpenNeuro's) keeps its position while duckbrain's own entries stay current.
    Existing entries that aren't dicts with a string ``Name`` are preserved
    untouched — duckbrain didn't write them and can't match on them. A malformed
    *existing* (anything but a list) is replaced outright, mirroring
    :func:`_read_json`'s trade for the file as a whole.
    """
    if not isinstance(existing, list):
        return list(new)
    merged = list(existing)
    by_name = {
        e["Name"]: i
        for i, e in enumerate(merged)
        if isinstance(e, dict) and isinstance(e.get("Name"), str)
    }
    for entry in new:
        i = by_name.get(entry.get("Name", ""))
        if i is None:
            merged.append(entry)
        else:
            merged[i] = entry
    return merged


def _read_json(path: Path) -> dict[str, Any]:
    """An existing JSON object, or ``{}`` if it is absent, unreadable or not a dict.

    Degrading to ``{}`` means a corrupt file is *replaced* rather than making the
    write fail. That is the right trade here only because every caller is about to
    write a complete, valid description over it.
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def dataset_extra_fields(config: Config) -> dict[str, Any]:
    """The ``dataset_description.json`` fields duckbrain elicits from project config.

    One helper rather than two call sites assembling it, because the Ingestion
    button and the conversion choke point must not disagree about what the
    description says. Omits ``Authors`` entirely when none are configured — see
    :func:`write_dataset_description` for why an empty list must not be written.
    """
    authors = [a for a in (config.get("project") or {}).get("authors", []) if str(a).strip()]
    return {"Authors": authors} if authors else {}


def ensure_dataset_description(
    bids_dir: str | Path,
    *,
    name: str = "",
    extra_fields: dict[str, Any] | None = None,
    generated_by: list[dict[str, Any]] | None = None,
) -> Path | None:
    """Write ``dataset_description.json`` only if the BIDS root has none.

    BIDS makes it compulsory and the validator reports its absence as an error,
    but duckbrain only ever wrote it from a button on the Ingestion page — so a
    project where nobody pressed it converted fine and then failed validation for
    a reason that was duckbrain's doing. Found on ``dwi_eyeball``, where it was
    the only error a clean validator run reported.

    Returns the path when it wrote, ``None`` when it left an existing file alone.
    Non-destructive by construction, which is what makes it safe to call on a path
    that runs at every conversion.
    """
    bids_dir = Path(bids_dir)
    if _read_json(bids_dir / "dataset_description.json"):
        return None
    return write_dataset_description(
        bids_dir, name=name, extra_fields=extra_fields, generated_by=generated_by
    )


#: BIDS 1.9 accepts any of these; finding one means the dataset has its README.
_README_NAMES = ("README", "README.md", "README.txt")


def ensure_readme(bids_dir: str | Path, *, name: str = "") -> Path | None:
    """Write a ``README`` stub only if the BIDS root has none.

    BIDS requires a root README and nothing in duckbrain ever wrote one, so every
    project duckbrain built warned. The stub deliberately **invents no study
    facts** — it names the dataset and says what to replace it with. A stub that
    fabricated a study description would be worse than the warning it silences.

    Returns the path when it wrote, ``None`` when any of :data:`_README_NAMES`
    already exists.
    """
    bids_dir = Path(bids_dir)
    if any((bids_dir / n).exists() for n in _README_NAMES):
        return None
    bids_dir.mkdir(parents=True, exist_ok=True)
    path = bids_dir / "README"
    title = name or bids_dir.name
    path.write_text(
        f"# {title}\n"
        "\n"
        "Placeholder written by duckbrain so this dataset has the README BIDS\n"
        "requires. Replace it with a description of the study: what was acquired\n"
        "and why, what each task is, anything a reader needs to interpret the\n"
        "data, and references to any publication or preregistration.\n"
    )
    return path


def _runtime_generated_by(runtime: str) -> dict[str, Any]:
    """A ``GeneratedBy`` entry for a non-container runtime, e.g. ``matlab/R2024a``.

    A container image needs none — it *is* the runtime, and ``Container`` already
    records it. NORDIC runs under a MATLAB module instead, which is a genuine
    second tool in the chain, so it earns its own entry (``GeneratedBy`` is a
    list). Splits ``<name>/<version>``; a bare string with no version records the
    name alone rather than inventing one.
    """
    r = (runtime or "").strip()
    if not r:
        return {}
    name, sep, version = r.rpartition("/")
    if not sep:
        return {"Name": r}
    return {"Name": name, "Version": version}


def write_derivative_description(
    deriv_dir: str | Path,
    pipeline_name: str,
    *,
    tool: str = "",
    tool_version: str = "",
    container: str = "",
    container_uri: str = "",
    code_url: str = "",
    runtime: str = "",
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

    tool_entry: dict[str, Any] = {}
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
    runtime_entry = _runtime_generated_by(runtime)
    if runtime_entry:
        generated_by.append(runtime_entry)

    description: dict[str, Any] = {
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
