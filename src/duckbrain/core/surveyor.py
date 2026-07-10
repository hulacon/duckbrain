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

STAGES = ("ingested", "converted", "fmriprep", "mriqc")


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
    # MRIQC completion marker = the per-image IQM JSONs. Check the subject
    # subtree and the flat root layout MRIQC sometimes uses.
    iqm_globs = [
        _fmt("{ss}/**/*_bold.json", subject, session),
        _fmt("{ss}/**/*_T1w.json", subject, session),
        f"sub-{subject}*_bold.json",
        f"sub-{subject}*_T1w.json",
    ]
    if any(_has_match(root, g) for g in iqm_globs):
        return Status.COMPLETE
    if _has_match(root, _fmt("{ss}", subject, session)) or _has_match(root, f"sub-{subject}*"):
        return Status.PARTIAL
    return Status.MISSING


_TRACKERS = {
    "ingested": _ingested_status,
    "converted": _converted_status,
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

    rows = []
    for subject, session in units:
        row = {"subject": subject, "session": session}
        for stage, tracker in _TRACKERS.items():
            row[stage] = tracker(paths, subject, session).value
        rows.append(row)

    columns = ["subject", "session", *STAGES]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


# ---- Nipoppy interop: imaging-bagel (processing_status.tsv) export ----------
#
# Escape hatch, not a dependency: emit the neurobagel/Nipoppy "imaging bagel"
# long-format TSV on demand so the project can feed a neurobagel dashboard or a
# future ENIGMA-style consortium — without adopting Nipoppy's layout envelope or
# taking a runtime dependency on it. See the nipoppy-status-tracking notes.

# duckbrain Status -> Nipoppy/neurobagel status vocabulary.
_BAGEL_STATUS = {
    Status.COMPLETE.value: "SUCCESS",
    Status.PARTIAL.value: "INCOMPLETE",
    Status.MISSING.value: "UNAVAILABLE",
    Status.NA.value: "UNAVAILABLE",
}

# Processing pipelines a neurobagel dashboard understands, mapped to their
# neurobagel name and the [containers] config key holding each version.
# ingested/converted are duckbrain-internal provenance, not neurobagel
# pipelines, so they're excluded from the default export.
_BAGEL_PIPELINES = {
    "fmriprep": ("fmriprep", "fmriprep_version"),
    "mriqc": ("mriqc", "mriqc_version"),
    "converted": ("dcm2bids", "dcm2bids_version"),
}

BAGEL_COLUMNS = [
    "participant_id",
    "bids_participant_id",
    "session_id",
    "bids_session_id",
    "pipeline_name",
    "pipeline_version",
    "pipeline_step",
    "status",
]


def to_bagel(
    matrix: pd.DataFrame,
    config: dict,
    pipelines: tuple[str, ...] = ("fmriprep", "mriqc"),
) -> pd.DataFrame:
    """Reshape a status matrix into a Nipoppy imaging-bagel (long) DataFrame.

    One row per ``(unit, pipeline)`` with the neurobagel status vocabulary
    (SUCCESS / INCOMPLETE / UNAVAILABLE). ``pipelines`` selects which stages to
    emit; defaults to the genuine processing pipelines.
    """
    versions = config.get("containers", {})
    rows = []
    for _, r in matrix.iterrows():
        sub, ses = r["subject"], r["session"]
        for stage in pipelines:
            if stage not in matrix.columns or stage not in _BAGEL_PIPELINES:
                continue
            name, vkey = _BAGEL_PIPELINES[stage]
            rows.append({
                "participant_id": sub,
                "bids_participant_id": f"sub-{sub}",
                "session_id": ses,
                "bids_session_id": f"ses-{ses}" if ses else "",
                "pipeline_name": name,
                "pipeline_version": versions.get(vkey, ""),
                "pipeline_step": "default",
                "status": _BAGEL_STATUS.get(r[stage], "UNAVAILABLE"),
            })
    return pd.DataFrame(rows, columns=BAGEL_COLUMNS)


def write_bagel(
    config: dict,
    path: str | Path | None = None,
    pipelines: tuple[str, ...] = ("fmriprep", "mriqc"),
) -> Path:
    """Survey the project and write its Nipoppy bagel TSV.

    Defaults to ``<derivatives_dir>/processing_status.tsv`` (Nipoppy's location).
    Returns the written path.
    """
    matrix = survey_project(config)
    bagel = to_bagel(matrix, config, pipelines=pipelines)
    if path is None:
        path = Path(config["paths"]["derivatives_dir"]) / "processing_status.tsv"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    bagel.to_csv(path, sep="\t", index=False)
    return path


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
