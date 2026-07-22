"""Project surveyor — per-subject/session pipeline completion status.

The rest of duckbrain keeps no state store: every page re-derives "what exists"
live from the filesystem. That is nicely tool-agnostic but conflates *presence*
with *completion* — a crashed fMRIPrep leaves a ``derivatives/fmriprep/sub-XX``
dir that looks identical to a finished one (see TODO #6).

The surveyor closes that gap by borrowing Nipoppy's tracker approach: a stage is
judged **by the presence of its expected output files** (globs), not by folder
presence or exit codes. Each stage declares the files a finished run must leave
behind; the surveyor reports COMPLETE (all present), PARTIAL (some — i.e. started
but not finished / crashed), or MISSING (none).

Two integration lessons from the Nipoppy prototype (see the
``nipoppy-status-tracking`` memory) are designed out here:

* **Sessionless data.** Stock Nipoppy fmriprep trackers glob a literal
  ``ses-<id>`` token, so single-session (sessionless) BIDS never matched. Here
  every glob absorbs the optional session with ``*``/``**`` wildcards, so the
  same tracker matches ``sub-01/anat/...`` and ``sub-01/ses-01/anat/...``.
* **Layout shim.** Nipoppy expects ``derivatives/<pipe>/<version>/output/``;
  duckbrain writes ``derivatives/<pipe>/`` directly. The trackers here target
  duckbrain's flat layout — no symlink bridge needed.

Designed to port back to mmmdata, which already grew Nipoppy's shape
(build_manifest.py, generate_sessions_tsv.py) independently.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import pandas as pd

from .ingestion import sub_ses_relpath

STAGES = ("ingested", "converted", "nordic", "fmriprep", "mriqc")


class Status(str, Enum):
    """Completion of one stage for one subject/session unit.

    Ordered worst→best by ``RANK`` below so a project rollup can report the
    weakest link. ``str`` base so the value drops straight into a DataFrame cell
    and compares equal to its plain-string form.
    """

    MISSING = "missing"   # no expected outputs at all — stage not started
    PARTIAL = "partial"   # some but not all — started, not finished (or crashed)
    COMPLETE = "complete"  # every expected output present
    NA = "n/a"            # stage does not apply to this unit


RANK = {Status.MISSING: 0, Status.PARTIAL: 1, Status.COMPLETE: 2, Status.NA: 3}


# ---- low-level glob helpers -------------------------------------------------

def _has_match(root: Path, pattern: str) -> bool:
    """True if any path under *root* matches the glob *pattern* (non-empty file)."""
    try:
        for p in root.glob(pattern):
            if p.is_file() and p.stat().st_size > 0:
                return True
            if p.is_dir():
                return True
    except (OSError, ValueError):
        return False
    return False


def _status_from(root: Path, required: list[str], subtree: str) -> Status:
    """Grade a stage from *required* globs, all relative to *root*.

    Returns COMPLETE when every required glob matches, PARTIAL when some do (or
    the stage's *subtree* exists but nothing expected landed — a crashed run),
    and MISSING when the subtree is absent entirely.

    A glob is a *presence* test — it says some matching file exists, not that
    every one that should exist does. For anything with one output per BOLD run,
    use :func:`_grade` against :func:`_expected_bold_keys` instead; see the
    "expected vs. found" section below.
    """
    subtree_exists = _has_match(root, subtree)
    hits = sum(_has_match(root, pat) for pat in required)
    if hits == len(required) and required:
        return Status.COMPLETE
    if hits > 0 or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


# ---- expected vs. found -----------------------------------------------------
#
# Presence was never completion, but the trackers below graded COMPLETE off a
# single wildcard match — so a unit with four BOLD runs where one succeeded and
# three failed read green at every stage (DB-001 in the 2026-07-22 review, and a
# repeat of the MRIQC anat/func bug noted in `_mriqc_status`, one granularity
# down). Green also *unlocks* downstream work through `pipeline.stage_runnable`
# and suppresses a real sacct failure in `pipeline.survey_live`, so the wrong
# answer propagated rather than merely displaying.
#
# The fix needs no state store, because all four stages are one-output-per-run
# downstream of the same fact — the unit's raw BOLD list. Count what should
# exist, count what does, and compare identities rather than totals so a stale
# leftover can't stand in for a missing run.

#: Entities that identify the *acquisition* a file belongs to. Anything else in
#: a derivative filename (``space-``, ``res-``, ``den-``, ``desc-``, ``hemi-``)
#: describes a representation of that acquisition, not a different one.
#:
#: An allowlist rather than a denylist, deliberately: an entity we have never
#: seen is then ignored, collapsing two files to one key. A denylist would do the
#: opposite and split one run into two, inventing a shortfall out of an fMRIPrep
#: upgrade.
_KEY_ENTITIES = ("sub", "ses", "task", "acq", "ce", "dir", "rec", "run", "echo", "part")


def _entity_key(name: str) -> str:
    """The acquisition identity of a BIDS filename, stripped of representation.

    ``sub-01_task-rest_run-1_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz``
    and ``sub-01_task-rest_run-1_bold.nii.gz`` are the same acquisition, so both
    key to ``sub-01_task-rest_run-1``.
    """
    stem = name.split(".")[0]
    parts = []
    for token in stem.split("_"):
        key, sep, value = token.partition("-")
        if sep and key in _KEY_ENTITIES:
            parts.append(f"{key}-{value}")
    return "_".join(parts)


def _found_keys(root: Path, pattern: str) -> set[str]:
    """:func:`_entity_key` of every non-empty file under *root* matching *pattern*."""
    keys: set[str] = set()
    try:
        for p in root.glob(pattern):
            if p.is_file() and p.stat().st_size > 0:
                keys.add(_entity_key(p.name))
    except (OSError, ValueError):
        return set()
    return keys


def _expected_bold_keys(bids_root: str | Path, subject: str, session: str) -> set[str]:
    """One key per raw BOLD run the unit has — what every downstream stage owes.

    Reuses ``nordic.get_bold_runs``, already the run-count source of truth in
    ``pipeline._build_nordic``/``_build_fmriprep``, so the surveyor cannot
    disagree with what was actually launched.
    """
    from .nordic import get_bold_runs

    return {_entity_key(p.name) for p in get_bold_runs(bids_root, subject, session)}


def _grade(expected: set[str], found: set[str], subtree_exists: bool) -> Status:
    """COMPLETE when every *expected* key is present, PARTIAL when only some are.

    Superset, never equality: a tree holding *more* than expected — two output
    spaces, a re-run, a leftover from a previous config — is still complete. That
    asymmetry is what keeps this from firing on every legitimate difference
    between what a tool writes and what we predicted.
    """
    if expected and expected <= found:
        return Status.COMPLETE
    if found or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


def _fmriprep_input_dir(config: dict) -> str:
    """The BIDS root fMRIPrep actually reads for this project.

    Mirrors ``pipeline._build_fmriprep``: raw BIDS normally, but the assembled
    ``derivatives/nordic/bids_format`` tree when ``use_nordic``. fMRIPrep must be
    graded against what it was given — expecting runs NORDIC never produced would
    pin it at PARTIAL forever for work it was never asked to do. The shortfall
    still surfaces, once, at the NORDIC stage that caused it.
    """
    paths = config["paths"]
    if config.get("nordic", {}).get("use_nordic", False):
        return f"{paths['derivatives_dir']}/nordic/bids_format"
    return paths["bids_dir"]


# ---- unit discovery ---------------------------------------------------------

def _iter_sub_ses(root: str | Path):
    """Yield ``(subject, session)`` for every ``sub-XX[/ses-YY]`` under *root*.

    ``session`` is ``""`` for single-session (sessionless) layouts. Works for
    any BIDS-shaped tree (bids_dir, sourcedata, a derivative), so external
    heudiconv/fMRIPrep output landing in the standard paths is picked up too.
    """
    root = Path(root)
    if not root.is_dir():
        return
    for sub_dir in sorted(root.glob("sub-*")):
        if not sub_dir.is_dir():
            continue
        subject = sub_dir.name[len("sub-"):]
        ses_dirs = [d for d in sorted(sub_dir.glob("ses-*")) if d.is_dir()]
        if ses_dirs:
            for d in ses_dirs:
                yield subject, d.name[len("ses-"):]
        else:
            yield subject, ""


def discover_units(paths: dict) -> list[tuple[str, str]]:
    """The row universe: every ``(subject, session)`` seen in sourcedata or BIDS.

    Union of ingested sessions and BIDS subjects, so a unit shows up whether it
    was ingested through duckbrain or dropped in as external BIDS.
    """
    units: set[tuple[str, str]] = set()
    units.update(_iter_sub_ses(paths["sourcedata_dir"]))
    units.update(_iter_sub_ses(paths["bids_dir"]))
    return sorted(units)


# ---- per-stage trackers -----------------------------------------------------
#
# Each returns a Status for one (subject, session). Globs use ``{ss}`` = the
# ``sub-XX[/ses-YY]`` fragment and ``sub-{sub}`` for filename tokens; ``**`` and
# ``*`` absorb the optional session so one pattern serves sessionless and
# multi-session layouts alike.
#
# They take the whole *config*, not just ``config["paths"]``: fMRIPrep's
# expectation depends on ``use_nordic`` (see :func:`_fmriprep_input_dir`), and a
# tracker that could only see paths had no way to ask.

def _fmt(pattern: str, subject: str, session: str) -> str:
    ss = str(sub_ses_relpath(subject, session))
    return pattern.format(ss=ss, sub=subject)


def _ingested_status(config: dict, subject: str, session: str) -> Status:
    paths = config["paths"]
    dicom = Path(paths["sourcedata_dir"]) / sub_ses_relpath(subject, session) / "dicom"
    resolved = dicom.resolve() if dicom.is_symlink() else dicom
    if resolved.is_dir() and any(resolved.iterdir()):
        return Status.COMPLETE
    return Status.MISSING


def _expected_conversion_counts(
    paths: dict, subject: str, session: str
) -> dict[str, int] | None:
    """How many NIfTIs each datatype should hold, per the reviewed dcm2bids config.

    ``None`` when there is no config to read — see :func:`_converted_status`.

    Counts by datatype rather than matching filenames: a description carries
    ``datatype``/``suffix``/``custom_entities``, not an output name, and
    reconstructing dcm2bids' naming here would be a second implementation of it
    that could drift.
    """
    import json

    cfg = (Path(paths["sourcedata_dir"]) / sub_ses_relpath(subject, session)
           / "dcm2bids_config.json")
    try:
        descriptions = json.loads(cfg.read_text()).get("descriptions", [])
    except (OSError, ValueError):
        return None
    counts: dict[str, int] = {}
    for d in descriptions:
        datatype = d.get("datatype")
        if datatype:
            counts[datatype] = counts.get(datatype, 0) + 1
    return counts or None


def _converted_status(config: dict, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["bids_dir"])
    subtree = _fmt("{ss}", subject, session)
    expected = _expected_conversion_counts(paths, subject, session)

    if expected is not None:
        # Compare per datatype, so a session that converted its anat and dropped
        # half its BOLDs is partial rather than green.
        found: dict[str, int] = {}
        for p in root.glob(_fmt("{ss}/**/*.nii.gz", subject, session)):
            if p.is_file() and p.stat().st_size > 0:
                found[p.parent.name] = found.get(p.parent.name, 0) + 1
        if found and all(found.get(dt, 0) >= n for dt, n in expected.items()):
            return Status.COMPLETE
        if found:
            return Status.PARTIAL
    elif _has_match(root, _fmt("{ss}/**/*.nii.gz", subject, session)):
        # No reviewed config to compare against — an externally converted or
        # hand-dropped BIDS tree, which `discover_units` deliberately supports.
        # Presence is the only claim we can make about a dataset duckbrain did
        # not produce; grading every such unit PARTIAL would be a worse lie.
        return Status.COMPLETE

    # A leftover tmp_dcm2bids scratch dir with no NIfTIs means a crashed run.
    tmp = root / "sourcedata" / "tmp_dcm2bids"
    if _has_match(root, subtree) or _has_match(tmp, f"sub-{subject}*"):
        return Status.PARTIAL
    return Status.MISSING


def _fmriprep_status(config: dict, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / "fmriprep"
    if not root.is_dir():
        return Status.MISSING

    # Subject-level markers: the .html report is written per subject, only once
    # the workflow finishes, and the anat preproc image. Anat is deliberately not
    # counted — fMRIPrep merges N input T1w into one preprocessed image, so there
    # is no run-to-output correspondence to check.
    anat_required = [
        f"sub-{subject}.html",
        _fmt("{ss}/**/anat/sub-{sub}*_desc-preproc_T1w.nii.gz", subject, session),
    ]
    anat_ok = all(_has_match(root, p) for p in anat_required)

    # Func is one preprocessed BOLD per input BOLD. An anat-only unit has an
    # empty expected set and so carries no func requirement at all — the
    # expectation *is* the list of files the input tree holds.
    expected = _expected_bold_keys(_fmriprep_input_dir(config), subject, session)
    found = _found_keys(
        root, _fmt("{ss}/**/func/sub-{sub}*_desc-preproc_bold.nii.gz", subject, session)
    )
    subtree_exists = _has_match(root, _fmt("{ss}", subject, session))

    if not expected:
        return Status.COMPLETE if anat_ok else (
            Status.PARTIAL if subtree_exists else Status.MISSING
        )
    if anat_ok and expected <= found:
        return Status.COMPLETE
    if anat_ok or found or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


def _mriqc_status(config: dict, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / "mriqc"
    if not root.is_dir():
        return Status.MISSING
    # MRIQC writes one IQM JSON per BIDS image. Grading complete on the anat json
    # alone hid a real failure: the func synthstrip node OOM-killed after the anat
    # json had landed, so the whole func QC was missing yet the cell read green
    # (all 9 divatten_gui_beta subjects, 2026-07-10). Requiring *any* func json
    # fixed that at the anat/func granularity and left the same bug one level
    # down — an OOM one run later still read green. Count the runs.
    #
    # Both of MRIQC's layouts have to be checked: nested (sub-XX/**/…) and flat
    # filenames at the derivative root.
    has_anat = any(_has_match(root, p) for p in (
        _fmt("{ss}/**/*_T1w.json", subject, session), f"sub-{subject}*_T1w.json"))

    expected = _expected_bold_keys(paths["bids_dir"], subject, session)
    found = _found_keys(root, _fmt("{ss}/**/*_bold.json", subject, session)) | \
        _found_keys(root, f"sub-{subject}*_bold.json")
    subtree_exists = _has_match(root, _fmt("{ss}", subject, session)) or \
        _has_match(root, f"sub-{subject}*")

    if has_anat and (not expected or expected <= found):
        return Status.COMPLETE
    if has_anat or found or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


def _nordic_status(config: dict, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / "nordic"
    if not root.is_dir():
        return Status.MISSING
    # NORDIC denoises one BOLD per array task, keeps the input basename, and
    # skips any run whose output already exists — so a partial array leaves
    # exactly the "some runs denoised" state a single wildcard called complete.
    # This is the stage where the bug was most reachable.
    expected = _expected_bold_keys(paths["bids_dir"], subject, session)
    found = _found_keys(
        root, _fmt("{ss}/**/func/sub-{sub}*_bold.nii.gz", subject, session)
    )
    return _grade(expected, found, _has_match(root, _fmt("{ss}", subject, session)))


_TRACKERS = {
    "ingested": _ingested_status,
    "converted": _converted_status,
    "nordic": _nordic_status,
    "fmriprep": _fmriprep_status,
    "mriqc": _mriqc_status,
}


# ---- public API -------------------------------------------------------------

def survey_project(config: dict) -> pd.DataFrame:
    """Build the pipeline status matrix for a project.

    Rows are ``(subject, session)`` units; columns are the pipeline stages
    (:data:`STAGES`) holding a :class:`Status` value each. Presence is *not*
    completion — see the module docstring.

    Parameters
    ----------
    config : dict
        A loaded duckbrain config with derived ``[paths]`` (``bids_dir``,
        ``sourcedata_dir``, ``derivatives_dir``).

    Returns
    -------
    pd.DataFrame
        Columns: ``subject``, ``session``, then one per stage. Empty (with the
        right columns) when the project has no subjects yet.
    """
    paths = config["paths"]
    units = discover_units(paths)

    # NORDIC is opt-in per project. Without use_nordic nothing consumes its
    # output — fMRIPrep reads the raw BIDS tree — so grading it MISSING presented
    # every unit of every non-NORDIC project as unfinished work: the rollup read
    # "Nordic 0/N", the cockpit offered a one-click "run all", and "every stage
    # complete" was unreachable (TODO #17.4). NA is what that state means, and it
    # is why the enum has the member. Launching NORDIC deliberately in such a
    # project is still possible from the Preprocessing page's NORDIC tab.
    nordic_applies = bool(config.get("nordic", {}).get("use_nordic", False))

    rows = []
    for subject, session in units:
        row = {"subject": subject, "session": session}
        for stage, tracker in _TRACKERS.items():
            if stage == "nordic" and not nordic_applies:
                row[stage] = Status.NA.value
                continue
            row[stage] = tracker(config, subject, session).value
        rows.append(row)

    columns = ["subject", "session", *STAGES]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def run_progress(
    config: dict, stage: str, subject: str, session: str
) -> tuple[int, int] | None:
    """``(runs_done, runs_expected)`` for a run-counted stage, or None.

    A PARTIAL cell with no number is its own silent degrade — it says "not
    finished" and leaves the operator to go count files. Returns None for stages
    that aren't one-output-per-run (ingested, converted) and whenever the unit
    has no BOLD runs to count.

    Shares :func:`_expected_bold_keys` and :func:`_found_keys` with the trackers
    so the number shown and the status shown cannot disagree.
    """
    paths = config["paths"]
    if stage == "nordic":
        expected = _expected_bold_keys(paths["bids_dir"], subject, session)
        found = _found_keys(
            Path(paths["derivatives_dir"]) / "nordic",
            _fmt("{ss}/**/func/sub-{sub}*_bold.nii.gz", subject, session),
        )
    elif stage == "fmriprep":
        expected = _expected_bold_keys(_fmriprep_input_dir(config), subject, session)
        found = _found_keys(
            Path(paths["derivatives_dir"]) / "fmriprep",
            _fmt("{ss}/**/func/sub-{sub}*_desc-preproc_bold.nii.gz", subject, session),
        )
    elif stage == "mriqc":
        expected = _expected_bold_keys(paths["bids_dir"], subject, session)
        root = Path(paths["derivatives_dir"]) / "mriqc"
        found = _found_keys(root, _fmt("{ss}/**/*_bold.json", subject, session)) | \
            _found_keys(root, f"sub-{subject}*_bold.json")
    else:
        return None

    if not expected:
        return None
    return len(expected & found), len(expected)


def summarize(matrix: pd.DataFrame) -> dict:
    """Per-stage counts of each status across all units.

    Returns ``{stage: {status: count}}`` — the numbers behind a dashboard's
    "12 complete / 3 partial / 5 missing" per stage.
    """
    out: dict[str, dict[str, int]] = {}
    for stage in STAGES:
        if stage not in matrix.columns:
            continue
        counts = matrix[stage].value_counts().to_dict()
        out[stage] = {s.value: int(counts.get(s.value, 0)) for s in Status}
    return out
