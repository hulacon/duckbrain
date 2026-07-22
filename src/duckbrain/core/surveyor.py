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
    """
    subtree_exists = _has_match(root, subtree)
    hits = sum(_has_match(root, pat) for pat in required)
    if hits == len(required) and required:
        return Status.COMPLETE
    if hits > 0 or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


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

def _fmt(pattern: str, subject: str, session: str) -> str:
    ss = str(sub_ses_relpath(subject, session))
    return pattern.format(ss=ss, sub=subject)


def _ingested_status(paths: dict, subject: str, session: str) -> Status:
    dicom = Path(paths["sourcedata_dir"]) / sub_ses_relpath(subject, session) / "dicom"
    resolved = dicom.resolve() if dicom.is_symlink() else dicom
    if resolved.is_dir() and any(resolved.iterdir()):
        return Status.COMPLETE
    return Status.MISSING


def _converted_status(paths: dict, subject: str, session: str) -> Status:
    root = Path(paths["bids_dir"])
    subtree = _fmt("{ss}", subject, session)
    # A finished conversion leaves NIfTIs; a leftover tmp_dcm2bids scratch dir
    # with no NIfTIs means a crashed/partial run.
    if _has_match(root, _fmt("{ss}/**/*.nii.gz", subject, session)):
        return Status.COMPLETE
    tmp = root / "sourcedata" / "tmp_dcm2bids"
    if _has_match(root, subtree) or _has_match(tmp, f"sub-{subject}*"):
        return Status.PARTIAL
    return Status.MISSING


def _bids_has_func(paths: dict, subject: str, session: str) -> bool:
    root = Path(paths["bids_dir"])
    return _has_match(root, _fmt("{ss}/**/func/*_bold.nii.gz", subject, session))


def _fmriprep_status(paths: dict, subject: str, session: str) -> Status:
    root = Path(paths["derivatives_dir"]) / "fmriprep"
    if not root.is_dir():
        return Status.MISSING
    # Subject-level markers (the .html report is written per subject, only once
    # the workflow finishes) + the anat preproc image. Wildcards absorb space-
    # and session-tagged filename variants.
    required = [
        f"sub-{subject}.html",
        _fmt("{ss}/**/anat/sub-{sub}*_desc-preproc_T1w.nii.gz", subject, session),
    ]
    # Only demand func output when the input BIDS actually has func for this unit
    # (an anat-only run legitimately has none).
    if _bids_has_func(paths, subject, session):
        required.append(
            _fmt("{ss}/**/func/sub-{sub}*_desc-preproc_bold.nii.gz", subject, session)
        )
    return _status_from(root, required, _fmt("{ss}", subject, session))


def _mriqc_status(paths: dict, subject: str, session: str) -> Status:
    root = Path(paths["derivatives_dir"]) / "mriqc"
    if not root.is_dir():
        return Status.MISSING
    # MRIQC writes one IQM JSON per BIDS image. A *finished* run therefore has the
    # anat T1w IQMs and — when the unit has func — the bold IQMs too. Grading
    # complete on the anat json alone hid a real failure mode: the func synthstrip
    # node OOM-killed after the anat json had already landed, so the whole func
    # QC was missing yet the cell read green (all 9 divatten_gui_beta subjects,
    # 2026-07-10). Mirror _fmriprep_status: anat required, func required only when
    # the input BIDS actually has func. Check both MRIQC's nested (sub-XX/anat/…)
    # and flat-root filename layouts.
    def _any(*pats: str) -> bool:
        return any(_has_match(root, p) for p in pats)

    has_anat = _any(_fmt("{ss}/**/*_T1w.json", subject, session),
                    f"sub-{subject}*_T1w.json")
    has_func = _any(_fmt("{ss}/**/*_bold.json", subject, session),
                    f"sub-{subject}*_bold.json")
    needs_func = _bids_has_func(paths, subject, session)
    if has_anat and (has_func or not needs_func):
        return Status.COMPLETE
    if has_anat or has_func or _has_match(root, _fmt("{ss}", subject, session)) \
            or _has_match(root, f"sub-{subject}*"):
        return Status.PARTIAL
    return Status.MISSING


def _nordic_status(paths: dict, subject: str, session: str) -> Status:
    root = Path(paths["derivatives_dir"]) / "nordic"
    if not root.is_dir():
        return Status.MISSING
    # Completion = NORDIC-denoised BOLD niftis under the unit's func dir. The `**`
    # absorbs the optional session (and NORDIC's own hardcoded ``ses-`` for
    # sessionless data — a known nordic.py path quirk), so one glob serves both
    # layouts. A ``nordic/sub-XX`` dir with no denoised bold → partial (crashed).
    required = [_fmt("{ss}/**/func/sub-{sub}*_bold.nii.gz", subject, session)]
    return _status_from(root, required, _fmt("{ss}", subject, session))


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
            row[stage] = tracker(paths, subject, session).value
        rows.append(row)

    columns = ["subject", "session", *STAGES]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


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
