"""NORDIC denoising — MATLAB wrapper + BIDS input tree builder."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

#: Prefix for a half-written file in the staged tree. Never pruned, never
#: mistaken for a desired output — see ``_materialize``.
_TMP_PREFIX = ".duckbrain-tmp-"


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
        f'module load {matlab_module} && matlab -nodisplay -nosplash -nodesktop -r "{matlab_cmd}"'
    )


def anat_dirs_for_subject(bids_dir: str | Path, subject: str) -> list[Path]:
    """Every ``anat`` dir belonging to *subject*, across all sessions.

    Anatomy is subject-scoped, not session-scoped. In multi-session studies the
    anatomical is often acquired once and shared, so taking anat only from the
    current session leaves fMRIPrep with no anatomical at all for every other
    session — see ``fmriprep._SESSION_FILTER_SUFFIXES``, which states the same
    policy for the BIDS filter half of this. The two must not disagree: the
    filter says "any session's anat" and used to point at a tree assembled with
    none, so a shared-anat project failed with the filter working as designed.

    Returns the subject-level ``sub-XX/anat`` (rare but legal) plus every
    ``sub-XX/ses-*/anat``, sorted. fMRIPrep is given all of them and does its own
    selection, which is exactly what a non-NORDIC run already does.
    """
    root = Path(bids_dir) / f"sub-{subject}"
    dirs = [d for d in [root / "anat"] if d.is_dir()]
    dirs += sorted(d for d in root.glob("ses-*/anat") if d.is_dir())
    return dirs


@dataclass(frozen=True)
class _Item:
    """One file the staged tree should hold, and how to make it."""

    dest: Path
    src: Path
    link: bool  # hardlink the payload (unchanged by NORDIC) vs. copy it


def _is_stale(item: _Item) -> bool:
    """Should *item* be (re)materialized?

    Presence was treated as equivalence, and it is not. The Conversion page edits
    fieldmap bindings and task labels into the raw sidecars, so a tree assembled
    before such an edit went on serving the old ``B0FieldSource`` to fMRIPrep
    forever, silently — the failure mode TODO #14 exists for, one layer along.
    """
    try:
        d = item.dest.stat()
    except OSError:
        return True
    try:
        s = item.src.stat()
    except OSError:
        return False  # source vanished mid-build; the prune pass will deal with it
    if item.link:
        return d.st_ino != s.st_ino
    return s.st_size != d.st_size or s.st_mtime_ns > d.st_mtime_ns


def _materialize(item: _Item) -> None:
    """Create ``item.dest`` from ``item.src``, atomically and idempotently.

    Concurrency is real here: ``nordic_bids_input.sbatch.j2`` submits one job per
    unit and they all write into the same project-wide ``bids_format`` root, so
    two jobs can target the same anat file. A bare ``os.link`` raises
    ``FileExistsError`` on the loser and kills that job. Writing to a unique temp
    sibling and ``os.replace``-ing it in is atomic on POSIX and same-filesystem by
    construction, so the last writer wins with byte-identical content.
    """
    item.dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = item.dest.with_name(f"{_TMP_PREFIX}{item.dest.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}")
    try:
        if item.link:
            try:
                os.link(item.src, tmp)
            except OSError:
                # EXDEV (derivatives on another filesystem), EPERM (some GPFS/NFS
                # configurations), EMLINK. Costs disk, not correctness — and it
                # used to be an uncaught crash reported only as a nonzero exit.
                shutil.copy2(item.src, tmp)
        else:
            shutil.copy2(item.src, tmp)
        os.replace(tmp, item.dest)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _prune(owned_dirs: list[Path], desired: set[Path]) -> None:
    """Delete files in *owned_dirs* that are not in *desired*.

    **This deletes files.** Scoped to directories whose contents this invocation
    is authoritative for, so a concurrent build of another unit cannot have its
    outputs removed. Anything hand-added to those directories will disappear on
    the next assembly; the tree is duckbrain-generated and documented as such.

    Skips temp files (a racer's in-flight write) and directories.
    """
    for d in owned_dirs:
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.is_dir() or p.name.startswith(_TMP_PREFIX) or p in desired:
                continue
            try:
                p.unlink()
            except OSError:
                pass  # a concurrent racer may have removed it already


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
    - Anatomicals from **every session of the subject** (nifti hardlinked,
      sidecars copied) so fMRIPrep runs end-to-end without a prior non-NORDIC
      run — see :func:`anat_dirs_for_subject` for why not just this session's
    - Dataset root files (dataset_description.json, participants.*, .bidsignore)
      copied once, so fMRIPrep accepts the tree as a dataset

    Convergent, not merely additive: a staged file is refreshed when its raw
    source changes, and **removed when its source is gone**. Presence used to be
    treated as equivalence, so an edited sidecar or a deleted run stayed in the
    tree fMRIPrep reads indefinitely. See :func:`_prune` for what is deleted and
    :func:`_materialize` for how concurrent per-unit jobs stay out of each
    other's way.

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

    raw_func = bids_dir / ss / "func"
    raw_fmap = bids_dir / ss / "fmap"
    nordic_func = nordic_derivatives_dir / ss / "func"

    items: list[_Item] = []

    # 1. NORDIC BOLDs — hardlinked, since they are the payload we are staging.
    if nordic_func.is_dir():
        for bold in sorted(nordic_func.glob("*_bold.nii.gz")):
            items.append(_Item(out_func / bold.name, bold, link=True))

    # 2. Every other func file from raw BIDS (sidecars, events, physio, SBRef).
    #    The raw BOLDs are deliberately absent — the NORDIC ones replace them.
    if raw_func.is_dir():
        for f in sorted(raw_func.iterdir()):
            if f.is_file() and not f.name.endswith("_bold.nii.gz"):
                items.append(_Item(out_func / f.name, f, link=False))

    # 3. Fieldmaps from raw BIDS.
    if raw_fmap.is_dir():
        for f in sorted(raw_fmap.iterdir()):
            if f.is_file():
                items.append(_Item(out_fmap / f.name, f, link=False))

    # 4. Anatomy, from EVERY session of this subject rather than just this one —
    #    see `anat_dirs_for_subject`. NIfTIs hardlinked (anat is unchanged by
    #    NORDIC), sidecars copied.
    anat_items: list[_Item] = []
    for raw_anat in anat_dirs_for_subject(bids_dir, subject):
        out_anat = output_bids_input_dir / raw_anat.relative_to(bids_dir)
        for f in sorted(raw_anat.iterdir()):
            if f.is_file():
                anat_items.append(_Item(out_anat / f.name, f, link=f.name.endswith(".nii.gz")))
    items += anat_items

    # 5. The unit-level scans.tsv. Its filename carries the same entities as the
    #    dir path: sub-XX_ses-YY_scans.tsv or sub-XX_scans.tsv.
    scans_name = f"{sub}_ses-{session}_scans.tsv" if session else f"{sub}_scans.tsv"
    scans_tsv = bids_dir / ss / scans_name
    if scans_tsv.exists():
        items.append(_Item(out_sub_ses / scans_tsv.name, scans_tsv, link=False))

    # 6. Dataset root files, so the tree is a valid BIDS dataset fMRIPrep accepts
    #    (it errors without dataset_description.json even with
    #    --skip-bids-validation). Shared by every unit; skips what the raw
    #    dataset lacks.
    for root_name in (
        "dataset_description.json",
        "participants.tsv",
        "participants.json",
        "README",
        ".bidsignore",
    ):
        src = bids_dir / root_name
        if src.exists():
            items.append(_Item(output_bids_input_dir / root_name, src, link=False))

    out_func.mkdir(parents=True, exist_ok=True)
    out_fmap.mkdir(parents=True, exist_ok=True)
    for item in items:
        if _is_stale(item):
            _materialize(item)

    # Reconcile: a file whose raw source is gone must go too, or a removed run or
    # a renamed sidecar lingers in the tree fMRIPrep reads. Only two scopes are
    # ever pruned, and both are safe against a concurrent build of another unit:
    #
    #   unit    — this unit's func/ and fmap/; no other invocation writes there.
    #   subject — the subject's anat dirs; the desired anat set is a pure function
    #             of (bids_dir, subject), so two concurrent units of one subject
    #             compute the SAME set and neither can delete what the other wants.
    #
    # Deliberately NOT pruned: the dataset root files and other units' scans.tsv,
    # which are shared and additive — pruning there would be one unit deleting the
    # dataset out from under another.
    owned = [out_func, out_fmap] + [i.dest.parent for i in anat_items]
    _prune(owned, {i.dest for i in items})

    return out_sub_ses


def _derivative_sidecar(bold: Path, bids_dir: Path, provenance: dict) -> dict:
    """Sidecar contents for the NORDIC output derived from *bold*.

    Starts from the raw sidecar: BIDS derivatives do **not** inherit metadata from
    the raw dataset, so a derivative sidecar must stand alone. Denoising changes
    the voxels, not the acquisition — ``RepetitionTime``, ``TaskName``,
    ``SliceTiming`` and the rest remain true of the output, and the raw file's own
    conversion provenance (``Dcm2bidsVersion`` &c.) remains true of its lineage.

    Adds ``Sources`` (the BIDS-spec'd per-file provenance link, resolvable via the
    ``raw`` entry in our ``DatasetLinks``) and a namespaced ``Duckbrain`` object.
    """
    raw_json = bold.parent / bold.name.replace(".nii.gz", ".json")
    content: dict = {}
    if raw_json.is_file():
        try:
            with open(raw_json) as f:
                content = json.load(f)
        except (OSError, ValueError):
            content = {}
    if not isinstance(content, dict):
        content = {}

    try:
        rel = bold.relative_to(bids_dir).as_posix()
    except ValueError:
        rel = bold.name
    content["Sources"] = [f"bids:raw:{rel}"]
    content["Duckbrain"] = {k: v for k, v in provenance.items() if v}
    return content


def write_nordic_sidecars(
    bids_dir: str | Path,
    derivatives_dir: str | Path,
    subject: str,
    session: str = "",
    *,
    provenance: dict,
) -> list[Path]:
    """Write a BIDS-derivatives sidecar for each BOLD this run will denoise.

    NORDIC's MATLAB job emits bare NIfTIs and no sidecar at all, leaving the
    derivative unable to describe itself. duckbrain writes them at launch — the
    same point, and for the same reason, it stamps the derivative's
    ``dataset_description.json``.

    Per-file provenance earns its place over the dataset-level stamp because
    **sidecars travel with the data**: ``dataset_description.json`` is
    dataset-level (so it cannot express per-subject mixing) and the submission log
    doesn't survive the derivative being copied elsewhere. A shared or archived
    NORDIC output stays self-describing.

    Only BOLDs whose output does **not** already exist get a sidecar, mirroring the
    sbatch's own skip-if-present rule. Without that, re-launching after a toolbox
    update would restamp already-denoised files with the new toolbox's provenance
    and quietly claim it produced them.

    The provenance object is namespaced under ``Duckbrain`` rather than
    ``GeneratedBy``: BEP028 (BIDS-Prov) already claims sidecar ``GeneratedBy`` and
    ``SidecarGeneratedBy`` for URI *references* into a provenance record
    (``"bids::prov#..."``), not inline objects — the opposite of what the same key
    means in ``dataset_description.json``. Keeping ours in one namespaced object
    also makes the eventual BEP028 migration a swap rather than a rewrite.

    Returns the sidecars written (empty if every output already exists).
    """
    bids_dir = Path(bids_dir)
    out_dir = nordic_output_dir(derivatives_dir, subject, session)
    written: list[Path] = []
    for bold in get_bold_runs(bids_dir, subject, session):
        if (out_dir / bold.name).exists():
            continue  # the sbatch will skip it; its sidecar already describes it
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / bold.name.replace(".nii.gz", ".json")
        with open(path, "w") as f:
            json.dump(_derivative_sidecar(bold, bids_dir, provenance), f, indent=2)
        written.append(path)
    return written


def nordic_output_dir(derivatives_dir: str | Path, subject: str, session: str = "") -> Path:
    """Standard NORDIC derivatives output path.

    ``sub_ses_relpath`` omits the ``ses-`` level for sessionless (single-session)
    data, so this returns ``.../nordic/sub-XX/func`` when *session* is empty and
    ``.../nordic/sub-XX/ses-YY/func`` otherwise — matching what the
    ``nordic_denoise`` sbatch template writes.
    """
    from .ingestion import sub_ses_relpath

    return Path(derivatives_dir) / "nordic" / sub_ses_relpath(subject, session) / "func"
