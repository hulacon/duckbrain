"""Project surveyor — per-subject/session pipeline completion status.

The rest of duckbrain keeps no state store: every page re-derives "what exists"
live from the filesystem. That is nicely tool-agnostic but conflates *presence*
with *completion* — a crashed fMRIPrep leaves a ``derivatives/fmriprep/sub-XX``
dir that looks identical to a finished one (see TODO #6). (One deliberate
exception exists: ``checks.json``, the expensive-checks snapshot in
``core/checks.py``, which earns it by carrying a fingerprint of the inputs it
was measured from — a cached verdict that can say when it has gone stale.)

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

import os
from collections.abc import Iterator
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

import pandas as pd

from .ingestion import sub_ses_relpath

if TYPE_CHECKING:
    from ..config import Config

STAGES = ("ingested", "converted", "nordic", "freesurfer", "fmriprep", "mriqc", "qsiprep")

#: The canonical fMRIPrep derivative name, and the stem every variant tree shares.
#: A project may preprocess one BIDS root more than once (``#5b`` Case 2); the
#: extra trees are found by :func:`fmriprep_variants` and become additive columns.
FMRIPREP_STAGE = "fmriprep"


class Status(StrEnum):
    """Completion of one stage for one subject/session unit.

    Ordered worst→best by ``RANK`` below so a project rollup can report the
    weakest link. ``StrEnum`` so the value drops straight into a DataFrame cell
    and compares equal to its plain-string form (and, unlike the old
    ``str, Enum`` mixin, ``str()``/f-strings yield the value itself).
    """

    MISSING = "missing"  # no expected outputs at all — stage not started
    PARTIAL = "partial"  # some but not all — started, not finished (or crashed)
    COMPLETE = "complete"  # every expected output present
    NA = "n/a"  # stage does not apply to this unit


RANK = {Status.MISSING: 0, Status.PARTIAL: 1, Status.COMPLETE: 2, Status.NA: 3}


# ---- low-level glob helpers -------------------------------------------------


def _is_evidence(path: Path) -> bool:
    """A non-empty file, or a directory — what counts as a match on disk.

    An empty file is not evidence a stage produced anything: a tool that died
    mid-write leaves exactly that, and every grade here is meant to read
    *partial* in such a case rather than complete.
    """
    try:
        return path.is_dir() or (path.is_file() and path.stat().st_size > 0)
    except OSError:
        return False


def _has_match(root: Path, pattern: str) -> bool:
    """True if any path under *root* matches the glob *pattern* (non-empty file)."""
    try:
        if not any(c in pattern for c in "*?["):
            # A pattern with no wildcards names exactly one path, so answer it
            # with one stat. `Path.glob` is not free here: Python 3.12 rewrote
            # pathlib to resolve *every* component by listing its parent, where
            # 3.11 statted the named child and never read the directory. Each
            # subtree probe below is a literal `{ss}`, so on 3.12 it cost a full
            # listing of the stage's derivative root — on MRIQC's flat layout,
            # thousands of entries, once per unit. That is why
            # `tests/test_surveyor.py::TestFlatLayoutIsScannedOnce` was red on
            # the 3.12 leg alone while the code looked fine on 3.11.
            return _is_evidence(root / pattern)
        return any(_is_evidence(p) for p in root.glob(pattern))
    except (OSError, ValueError):
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


def _entities(key: str) -> dict[str, str]:
    """The ``entity: value`` pairs of an :func:`_entity_key`."""
    pairs = (token.partition("-") for token in key.split("_"))
    return {entity: value for entity, sep, value in pairs if sep}


def _covers(found: str, expected: str) -> bool:
    """Whether a *found* key accounts for an *expected* one, allowing for merging.

    True when every entity the found key names has the same value in the expected
    key. So a coarser output covers a finer input — ``sub-01_ses-01_acq-multishell``
    covers ``sub-01_ses-01_acq-multishell_dir-AP_run-1`` — while a contradiction
    never does: a found ``dir-AP`` does not cover an expected ``dir-PA``.

    Exact equality is the special case where the two key sets match, so this is a
    strict widening of the identity test the other stages use.
    """
    e = _entities(expected)
    return all(e.get(entity) == value for entity, value in _entities(found).items())


def _grade_merged(expected: set[str], found: set[str], subtree_exists: bool) -> Status:
    """:func:`_grade` for a stage whose outputs may be **coarser** than its inputs.

    QSIPrep concatenates DWI scans that share a warped space before head-motion
    correction, dropping the entity that distinguished them: three inputs
    ``…run-{1,2,3}`` become one ``…desc-preproc_dwi.nii.gz``. Superset semantics
    (``expected <= found``) is correct for every other stage duckbrain has,
    because all of them are one-output-per-input; against a merged output it is
    false *forever* — a completely successful run grades PARTIAL, which
    ``pipeline.stage_runnable`` reads as "not done", so the cockpit invites a
    re-run that produces exactly the same result.

    **The honest cost, which is a real limit on what the board can claim rather
    than a bug to paper over:** coarsening means a genuinely dropped run inside a
    merged group cannot be detected from filenames. There is no per-input
    artifact to fall back on — QSIPrep's ``desc-confounds_timeseries.tsv`` and
    ``desc-image_qc.tsv`` are per-*output* and merge too. Declaring the runs a
    session should have is what ``[expected]`` is for (``#16``).

    **The rejected alternative, recorded so it is not re-proposed:** forcing
    ``--separate-all-dwis`` to restore 1:1 tracking. That trades preprocessing
    quality — less data for head-motion correction — for the convenience of a
    status column. The tail wagging the dog, and a silent science change at that.
    """
    if expected and all(any(_covers(f, e) for f in found) for e in expected):
        return Status.COMPLETE
    if found or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


def _fmriprep_input_dir(config: Config) -> str:
    """The BIDS root fMRIPrep actually reads for this project.

    Mirrors ``pipeline._build_fmriprep``: raw BIDS normally, but the assembled
    ``derivatives/nordic/bids_format`` tree when ``use_nordic``. fMRIPrep must be
    graded against what it was given — expecting runs NORDIC never produced would
    pin it at PARTIAL forever for work it was never asked to do. The shortfall
    still surfaces, once, at the NORDIC stage that caused it.
    """
    from .nordic import nordic_bids_input_dir

    paths = config["paths"]
    if config.get("nordic", {}).get("use_nordic", False):
        return str(nordic_bids_input_dir(paths["derivatives_dir"]))
    return str(paths["bids_dir"])


def fmriprep_variants(paths: dict[str, str]) -> tuple[str, ...]:
    """Extra ``derivatives/fmriprep*`` trees beside the canonical one, named as on disk.

    A project may preprocess one BIDS root more than once — mmmdata carries
    ``fmriprep`` (raw) and ``fmriprep_nordic`` (denoised), 535 G each. The
    surveyor hardcoded ``derivatives/fmriprep``, so it graded one of them and had
    no way to say the other was there, on a board whose whole job is to report
    what exists. That is ``#5b`` Case 2.

    **The name is read, never imposed.** ``#5b`` itself guessed
    ``fmriprep-nordic``; what mmmdata wrote is ``fmriprep_nordic``. A convention
    duckbrain invents for trees other tools produced is a convention that will be
    wrong. A directory qualifies when its name is ``fmriprep`` joined by ``_`` or
    ``-`` to a suffix **and** it holds at least one ``sub-*`` directory — the
    second half is what keeps scratch and work dirs off the board, since only an
    output tree has subjects in it.

    Reporting only: a variant carries no ``STAGE_SPECS`` entry, so it is not in
    ``SLURM_STAGES``, the cockpit draws it as plain status, and ``stage_runnable``
    refuses it. That is ``#5b``'s "do not branch the pipeline" holding at the one
    place it could leak.
    """
    root = Path(paths["derivatives_dir"])
    stem = FMRIPREP_STAGE
    try:
        entries = sorted(root.iterdir())
    except OSError:  # no derivatives dir yet, or unreadable — nothing to report
        return ()

    out: list[str] = []
    for path in entries:
        name = path.name
        if name == stem or not name.startswith(stem) or name[len(stem)] not in "_-":
            continue
        if not path.is_dir():
            continue
        try:
            has_subjects = any(c.name.startswith("sub-") and c.is_dir() for c in path.iterdir())
        except OSError:
            continue
        if has_subjects:
            out.append(name)
    return tuple(out)


def _stage_columns(variants: tuple[str, ...]) -> tuple[str, ...]:
    """:data:`STAGES` with *variants* spliced in directly after ``fmriprep``.

    Order matters on the board: column order mirrors pipeline order, so a variant
    belongs beside the stage it varies rather than appended after ``qsiprep``.
    """
    if not variants:
        return STAGES
    cut = STAGES.index(FMRIPREP_STAGE) + 1
    return (*STAGES[:cut], *variants, *STAGES[cut:])


def stage_columns(config: Config) -> tuple[str, ...]:
    """The stage columns :func:`survey_project` will produce for this project.

    :data:`STAGES` plus one column per extra fMRIPrep tree on disk. A project with
    a single fMRIPrep tree — every project duckbrain produced itself — gets
    :data:`STAGES` unchanged, so the extra column is additive and opted into by
    the only signal that cannot be stale: the tree being there.

    **Anything laying out stage columns must call this, not** :data:`STAGES`, or
    the board surveys a variant and then declines to draw it.
    """
    return _stage_columns(fmriprep_variants(config["paths"]))


def _fmriprep_func_keys(root: Path, subject: str, session: str) -> set[str]:
    """Runs fMRIPrep actually **finished**: a preproc BOLD *and* its confounds.

    The intersection, not the union, because either file alone is a run that
    stopped partway. The confounds TSV earns its place in the requirement rather
    than being one more glob: it is the QC dashboard's *only* fMRIPrep input
    (``qc_report.CONFOUNDS_GLOB``, ``qc.summarize_motion``), so a tree of preproc
    BOLDs with no confounds used to grade finished while every motion column sat
    blank and nothing said why. Shared by :func:`_fmriprep_status` and
    :func:`run_progress` so the grade and the ``n/N`` beside it cannot disagree.

    **The false positive this knowingly accepts.** ``--level minimal`` and
    ``--level resampling`` write no confounds, and either can reach fMRIPrep
    through the Preprocessing page's free-text flags box. The request record
    (``pipeline.record_request``) captures those flags now, but the grade
    deliberately does not read it: an externally-run fMRIPrep has no record, so
    a record-dependent grade would make identical trees read differently in two
    projects — the surveyor judges the tree against the tree, on purpose.
    Guessing was refused; the cost of not guessing is bounded, which is what
    makes accepting it reasonable — no
    ``STAGE_SPECS`` entry depends on ``fmriprep``, so a stricter grade blocks no
    downstream stage. It colours a cell PARTIAL, offers a re-run where a green
    cell offered nothing, and stops ``pipeline.survey_live`` suppressing a real
    sacct failure for that unit.
    """
    return _found_keys(
        root, _fmt("{ss}/**/func/sub-{sub}*_desc-preproc_bold.nii.gz", subject, session)
    ) & _found_keys(
        root, _fmt("{ss}/**/func/sub-{sub}*_desc-confounds_timeseries.tsv", subject, session)
    )


# ---- unit discovery ---------------------------------------------------------


def _iter_sub_ses(root: str | Path) -> Iterator[tuple[str, str]]:
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
        subject = sub_dir.name[len("sub-") :]
        ses_dirs = [d for d in sorted(sub_dir.glob("ses-*")) if d.is_dir()]
        if ses_dirs:
            for d in ses_dirs:
                yield subject, d.name[len("ses-") :]
        else:
            yield subject, ""


def discover_units(paths: dict[str, str]) -> list[tuple[str, str]]:
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


def _ingested_status(config: Config, subject: str, session: str) -> Status:
    paths = config["paths"]
    dicom = Path(paths["sourcedata_dir"]) / sub_ses_relpath(subject, session) / "dicom"
    resolved = dicom.resolve() if dicom.is_symlink() else dicom
    if resolved.is_dir() and any(resolved.iterdir()):
        return Status.COMPLETE
    return Status.MISSING


def _expected_conversion_counts(
    paths: dict[str, str], subject: str, session: str
) -> dict[str, int] | None:
    """How many NIfTIs each datatype should hold, per the reviewed dcm2bids config.

    ``None`` when there is no config to read — see :func:`_converted_status`.

    Counts by datatype rather than matching filenames: a description carries
    ``datatype``/``suffix``/``custom_entities``, not an output name, and
    reconstructing dcm2bids' naming here would be a second implementation of it
    that could drift.
    """
    import json

    from .conversion import resolve_dcm2bids_config_path

    cfg = resolve_dcm2bids_config_path(paths, subject, session)
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


def _converted_status(config: Config, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["bids_dir"])
    subtree = _fmt("{ss}", subject, session)
    expected = _expected_conversion_counts(paths, subject, session)

    from .ingestion import nii_glob

    niftis = [
        p for p in nii_glob(root, _fmt("{ss}/**/*", subject, session)) if p.stat().st_size > 0
    ]
    if expected is not None:
        # Compare per datatype, so a session that converted its anat and dropped
        # half its BOLDs is partial rather than green.
        found: dict[str, int] = {}
        for p in niftis:
            found[p.parent.name] = found.get(p.parent.name, 0) + 1
        if found and all(found.get(dt, 0) >= n for dt, n in expected.items()):
            return Status.COMPLETE
        if found:
            return Status.PARTIAL
    elif niftis:
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


def _fmriprep_status(
    config: Config, subject: str, session: str, tree: str = FMRIPREP_STAGE
) -> Status:
    # *tree* is the derivative dir to grade: ``fmriprep`` normally, or one of
    # `fmriprep_variants`' extra trees, which `survey_project` binds via partial.
    # The expectation is the same for every tree, deliberately — they preprocess
    # the same BIDS units, so a variant short of the runs the raw tree has really
    # is incomplete and should read PARTIAL. What duckbrain must not do is invent
    # a *different* expectation for a tree it did not produce and cannot ask.
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / tree
    if not root.is_dir():
        return Status.MISSING

    # Subject-level markers: the .html report is written per subject, only once
    # the workflow finishes, and the anat preproc image. Anat is deliberately not
    # counted — fMRIPrep merges N input T1w into one preprocessed image, so there
    # is no run-to-output correspondence to check.
    #
    # The anat glob is subject-scoped, not session-scoped, for the same reason
    # anat reuse is (see fmriprep.find_anat_derivatives): in a longitudinal study
    # the anatomical is acquired once and fMRIPrep writes it under the session it
    # came from, so every *other* session's cell would sit at PARTIAL forever
    # with its func complete and nothing missing.
    #
    # **The report has two shapes**, and asking only for the combined one is a
    # false negative on every densely-sampled study. `--aggregate-session-reports`
    # (default 4) splits the report once a subject exceeds that many sessions:
    # fMRIPrep then writes `sub-XX_anat.html` plus one `sub-XX_ses-YY_func.html`
    # per session and **no** `sub-XX.html` at all. mmmdata's raw arm is split at
    # 29 sessions and its NORDIC arm is not, so requiring the combined name alone
    # graded a finished tree PARTIAL beside a full run count — the "4/4 beside
    # PARTIAL" contradiction this module exists to prevent. Same principle as
    # `_qsiprep_report_present`: judge the tree against the tree, because an
    # externally-run one is not duckbrain's to predict.
    report_ok = _has_match(root, f"sub-{subject}.html") or _has_match(
        root, f"sub-{subject}_anat.html"
    )
    anat_ok = report_ok and _has_match(
        root, f"sub-{subject}/**/anat/sub-{subject}*_desc-preproc_T1w.nii.gz"
    )

    # Func is one preprocessed BOLD *and* one confounds TSV per input BOLD; see
    # `_fmriprep_func_keys` for why the confounds file is part of the
    # requirement. An anat-only unit has an empty expected set and so carries no
    # func requirement at all — the expectation *is* the list of files the input
    # tree holds.
    expected = _expected_bold_keys(_fmriprep_input_dir(config), subject, session)
    found = _fmriprep_func_keys(root, subject, session)
    subtree_exists = _has_match(root, _fmt("{ss}", subject, session))

    if not expected:
        return (
            Status.COMPLETE if anat_ok else (Status.PARTIAL if subtree_exists else Status.MISSING)
        )
    if anat_ok and expected <= found:
        return Status.COMPLETE
    if anat_ok or found or subtree_exists:
        return Status.PARTIAL
    return Status.MISSING


#: Image suffixes MRIQC rates — it writes one IQM json per input image carrying
#: one of these. Deliberately without ``dwi``: only MRIQC >= 23.1 rates
#: diffusion, so expecting a dwi json would pin any dwi-holding project run with
#: an older container at PARTIAL for work its MRIQC never did. The cost is the
#: usual bounded one (see `_fmriprep_func_keys`): a missing dwi json is never
#: flagged, a present one is ignored rather than miscounted.
_MRIQC_RATED_SUFFIXES = ("T1w", "T2w", "bold")


def _mriqc_key(name: str) -> str | None:
    """``<acquisition key>:<suffix>`` for an image MRIQC rates, else ``None``.

    The suffix is part of the identity here, unlike :func:`_entity_key` alone: a
    T1w and a T2w share every entity except the suffix (``sub-01_run-1_T1w`` /
    ``sub-01_run-1_T2w``), so an entity-only key would collapse them and one
    modality's json could stand in for the other's. ``None`` filters out both
    unrated images (MP2RAGE, sbref) and MRIQC's non-IQM jsons (``_timeseries``).
    """
    suffix = name.split(".")[0].rsplit("_", 1)[-1]
    if suffix not in _MRIQC_RATED_SUFFIXES:
        return None
    return f"{_entity_key(name)}:{suffix}"


def _mriqc_flat_prefix(subject: str, session: str) -> str:
    """Filename prefix of this unit's files in MRIQC's flat layout.

    Session-scoped when there is a session: the flat layout puts every session's
    files side by side at the derivative root, so a subject-scoped glob credits a
    sibling session's output to this one.
    """
    return f"sub-{subject}_ses-{session}" if session else f"sub-{subject}"


class _FlatListing(NamedTuple):
    """One reading of a derivative root: what is named there, and what is a directory.

    ``by_subject`` buckets entry *names* under their leading ``sub-XX`` token.
    ``subdirs`` holds the names that are directories — which is exactly what
    tells MRIQC's two layouts apart, since a flat root holds
    ``sub-01_ses-02_T1w.json`` files where a nested one holds a ``sub-01``
    directory. Carrying both means one reading answers every question about
    this root, rather than a caller going back to the filesystem to ask which
    layout it is looking at.
    """

    by_subject: dict[str, list[str]]
    subdirs: frozenset[str]


_EMPTY_LISTING = _FlatListing({}, frozenset())

#: One ``scandir`` of a flat MRIQC root per state of that directory:
#: ``{root: (dir mtime_ns, listing)}``.
_FLAT_LISTINGS: dict[str, tuple[int, _FlatListing]] = {}


def _flat_listing(root: Path) -> _FlatListing:
    """Entries directly under *root*, bucketed by their leading ``sub-XX`` token.

    MRIQC's flat layout puts every unit's files side by side at the derivative
    root, so the only way to find one unit's is to match a filename prefix — and
    ``root.glob("sub-01_ses-02_*.json")`` is a full ``scandir`` of that root each
    time it is asked. Once per unit and twice over (the json search and the
    subtree probe) that is O(N²) in units: ~400 scans of a directory holding
    thousands of files, per survey, at 100 subjects × 2 sessions (`#42.5`).

    Bucketing by the subject token and not by the full prefix keeps the glob's
    exact semantics — the caller still filters on ``sub-XX_ses-YY_`` — while
    making the per-unit share of the scan proportional to one subject's files.

    Cached on the directory's own mtime, which POSIX moves whenever an entry is
    created or removed. Deliberately **not** on the files' contents or sizes:
    MRIQC creates a json and then fills it, so a listing that recorded "empty"
    would keep saying so after the write landed. What is cached is each entry's
    *name and type*; every caller still stats the file it is about to believe
    in. The type is safe to cache for the same reason the name is — an entry
    cannot become a directory without being created, and creating it moves this
    directory's mtime.
    """
    try:
        mtime = root.stat().st_mtime_ns
    except OSError:
        return _EMPTY_LISTING
    key = str(root)
    cached = _FLAT_LISTINGS.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    buckets: dict[str, list[str]] = {}
    subdirs: set[str] = set()
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                name = entry.name
                if not name.startswith("sub-"):
                    continue
                buckets.setdefault(name.split("_", 1)[0], []).append(name)
                try:
                    if entry.is_dir():
                        subdirs.add(name)
                except OSError:  # a symlink to nowhere is not a subtree
                    pass
    except OSError:
        return _EMPTY_LISTING
    listing = _FlatListing(buckets, frozenset(subdirs))
    _FLAT_LISTINGS[key] = (mtime, listing)
    return listing


def _flat_matches(root: Path, prefix: str, suffix: str = "") -> list[Path]:
    """Files at *root* named ``{prefix}_…{suffix}`` — the flat glob, listed once."""
    names = _flat_listing(root).by_subject.get(prefix.split("_", 1)[0], ())
    return [
        root / name
        for name in names
        if name.startswith(f"{prefix}_") and (not suffix or name.endswith(suffix))
    ]


def _mriqc_nested_jsons(root: Path, subject: str, session: str) -> list[Path]:
    """This unit's IQM jsons in MRIQC's *nested* layout — nothing when *root* is flat.

    Globbed from the subject's own directory rather than from *root*, because a
    pattern starting ``sub-XX/`` makes Python 3.12's pathlib list *root* to
    resolve that first component (3.11 statted the child instead). On a flat
    root that is a scan of thousands of files which can only ever match
    nothing — and it ran once per unit, which is the third of the three scans
    `tests/test_surveyor.py::TestFlatLayoutIsScannedOnce` counts.

    The cached listing already knows whether a ``sub-XX`` *directory* exists
    here, so the nested search runs only where a nested layout does, and asking
    which layout this is costs no filesystem call of its own.
    """
    sub, *rest = sub_ses_relpath(subject, session).parts
    if sub not in _flat_listing(root).subdirs:
        return []
    return list((root / sub).glob("/".join((*rest, "**", "*.json"))))


def _mriqc_expected_found(config: Config, subject: str, session: str) -> tuple[set[str], set[str]]:
    """Every image MRIQC owes this unit, and every IQM json it has written.

    The expectation is derived from the session's *own* BIDS images — its BOLDs
    plus whatever rated anat it actually holds — not from a fixed "anat + func"
    template. In a longitudinal study the anatomical is acquired once, so every
    other session holds func only and owes no anat json; requiring one anyway
    pinned all of mmmduck's func-only sessions at PARTIAL forever, right beside
    a run counter saying 9/9 (2026-08-11). This is `_fmriprep_status`'s
    session-scoping problem with the opposite resolution, deliberately: fMRIPrep
    merges N T1w into one subject-level output, so its anat check widens to the
    subject; MRIQC rates each image where it lies, so the *expectation* narrows
    to what the session holds.

    Both of MRIQC's layouts are read: nested (``sub-XX/ses-YY/…``) and flat
    filenames at the derivative root, the latter through the session-scoped
    prefix so a sibling session's json can't satisfy — or partial-ify — this one.

    Shared by :func:`_mriqc_status` and :func:`run_progress` so the grade and
    the count beside it cannot disagree.
    """
    paths = config["paths"]
    bids_root = Path(paths["bids_dir"])
    root = Path(paths["derivatives_dir"]) / "mriqc"

    expected = {f"{k}:bold" for k in _expected_bold_keys(bids_root, subject, session)}
    found: set[str] = set()
    try:
        for p in bids_root.glob(_fmt("{ss}/**/anat/*.nii*", subject, session)):
            if p.is_file() and p.stat().st_size > 0 and (key := _mriqc_key(p.name)):
                expected.add(key)
        nested = _mriqc_nested_jsons(root, subject, session)
        flat = _flat_matches(root, _mriqc_flat_prefix(subject, session), ".json")
        for p in (*nested, *flat):
            if p.is_file() and p.stat().st_size > 0 and (key := _mriqc_key(p.name)):
                found.add(key)
    except (OSError, ValueError):
        pass
    return expected, found


def _mriqc_status(config: Config, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / "mriqc"
    if not root.is_dir():
        return Status.MISSING
    # MRIQC writes one IQM JSON per BIDS image. Grading complete on the anat json
    # alone hid a real failure: the func synthstrip node OOM-killed after the anat
    # json had landed, so the whole func QC was missing yet the cell read green
    # (all 9 divatten_gui_beta subjects, 2026-07-10) — and counting only at the
    # anat/func granularity left the same bug one level down, an OOM one run
    # later. So count every rated image, and expect only what the session's own
    # BIDS tree holds — see `_mriqc_expected_found` for both halves.
    expected, found = _mriqc_expected_found(config, subject, session)
    subtree_exists = _has_match(root, _fmt("{ss}", subject, session)) or any(
        _is_evidence(p) for p in _flat_matches(root, _mriqc_flat_prefix(subject, session))
    )
    return _grade(expected, found, subtree_exists)


def _nordic_status(config: Config, subject: str, session: str) -> Status:
    paths = config["paths"]
    root = Path(paths["derivatives_dir"]) / "nordic"
    if not root.is_dir():
        return Status.MISSING
    # NORDIC denoises one BOLD per array task, keeps the input basename, and
    # skips any run whose output already exists — so a partial array leaves
    # exactly the "some runs denoised" state a single wildcard called complete.
    # This is the stage where the bug was most reachable.
    expected = _expected_bold_keys(paths["bids_dir"], subject, session)
    found = _found_keys(root, _fmt("{ss}/**/func/sub-{sub}*_bold.nii.gz", subject, session))
    return _grade(expected, found, _has_match(root, _fmt("{ss}", subject, session)))


def _freesurfer_status(config: Config, subject: str, session: str) -> Status:
    """External FreeSurfer recon — subject-level, like fMRIPrep's anat.

    recon-all consumes every session's T1w at once (fMRIPrep 25's default
    subject-level anatomical reference), so all of a subject's rows grade
    together — the same widening `_fmriprep_status` applies to its anat half,
    for the same longitudinal reason.

    COMPLETE requires `core.freesurfer.recon_complete`: the `recon-all.done`
    marker AND a build-stamp matching the pinned [freesurfer] version. The
    marker alone cannot distinguish this stage's recon from one fMRIPrep's own
    bundled FreeSurfer 7 wrote at the *identical* path on a pre-toggle run —
    grading that COMPLETE would wave the wrong surface through to import
    (`docs/pipeline-extras.md` §9 Trap 1, in surveyor form). A subject dir that
    exists but fails the check grades PARTIAL: something is there and needs a
    decision, and the launch gate's message states the choices. The dot-prefixed
    staging dir is invisible to this tracker on purpose — an in-flight recon
    reads MISSING plus a running job, not PARTIAL.
    """
    from .freesurfer import recon_complete, subject_import_dir

    subject_dir = subject_import_dir(config["paths"]["derivatives_dir"], subject)
    if recon_complete(config, subject_dir):
        return Status.COMPLETE
    if subject_dir.is_dir():
        return Status.PARTIAL
    return Status.MISSING


def _qsiprep_dwi_keys(root: Path, subject: str, session: str) -> set[str]:
    """Acquisition keys of the preprocessed DWI images QSIPrep wrote for this unit.

    ``space-``/``desc-`` are representation, not identity, so ``_entity_key``
    strips them and ``sub-01_ses-01_space-ACPC_desc-preproc_dwi.nii.gz`` keys to
    the acquisition it came from — coarsened by any merge, which
    :func:`_grade_merged` is what handles.
    """
    return _found_keys(
        root, _fmt("{ss}/**/dwi/sub-{sub}*_desc-preproc_dwi.nii.gz", subject, session)
    )


def _qsiprep_report_present(root: Path, subject: str, session: str) -> bool:
    """Whether this unit's QSIPrep HTML report exists — in either of its two shapes.

    The path is **conditional on ``--subject-anatomical-reference``**, which is
    why both are asked for rather than one being picked. Read out of QSIPrep
    26.0.0's ``reports/core.py``: the sessionwise branch writes
    ``sub-XX/ses-YY/sub-XX_ses-YY.html``, every other value writes ``sub-XX.html``
    at the derivative root. duckbrain forces sessionwise for a session-scoped unit
    and ``qsiprep.SESSIONLESS_REFERENCE`` for a sessionless one, so in practice a
    project sees one shape — but an externally-run tree is not duckbrain's to
    predict, and the surveyor judges the tree against the tree.

    Subject-scoped in the second shape, so in a multi-session project every row
    of a subject grades together on it. Same widening ``_fmriprep_status``
    applies to its anat half, and for the same reason: one artifact covering
    several rows must not leave all but one of them PARTIAL forever.
    """
    return _has_match(root, f"sub-{subject}.html") or _has_match(
        root, _fmt("{ss}/sub-{sub}*.html", subject, session)
    )


def _qsiprep_status(config: Config, subject: str, session: str) -> Status:
    """QSIPrep, graded against the unit's own diffusion runs.

    **NA when the unit has no DWI**, and that is a different shape from NORDIC's
    NA: NORDIC's is a project-level config question (``use_nordic``), QSIPrep's
    is per-unit *data* — one session can have diffusion and the next not, which
    is exactly what mmmdata looks like (6 diffusion sessions out of 88). Without
    it the rollup, the bulk "run all", and the all-complete message are each
    poisoned by rows that will never have anything to run (``#17.4``'s lesson).
    Deliberately decided here rather than in ``survey_project``'s ``applies``
    map, which can only answer per *project*.

    COMPLETE needs the report as well as the images: the images can land while
    the workflow is still running, and the report is the only per-unit artifact
    QSIPrep writes at the end.
    """
    from .qsiprep import get_dwi_runs

    paths = config["paths"]
    expected = {_entity_key(p.name) for p in get_dwi_runs(paths["bids_dir"], subject, session)}
    if not expected:
        return Status.NA

    root = Path(paths["derivatives_dir"]) / "qsiprep"
    if not root.is_dir():
        return Status.MISSING

    found = _qsiprep_dwi_keys(root, subject, session)
    subtree_exists = _has_match(root, _fmt("{ss}", subject, session))
    grade = _grade_merged(expected, found, subtree_exists)
    if grade is Status.COMPLETE and not _qsiprep_report_present(root, subject, session):
        return Status.PARTIAL
    return grade


_TRACKERS = {
    "ingested": _ingested_status,
    "converted": _converted_status,
    "nordic": _nordic_status,
    "freesurfer": _freesurfer_status,
    "fmriprep": _fmriprep_status,
    "mriqc": _mriqc_status,
    "qsiprep": _qsiprep_status,
}


# ---- public API -------------------------------------------------------------


def survey_project(config: Config) -> pd.DataFrame:
    """Build the pipeline status matrix for a project.

    Rows are ``(subject, session)`` units; columns are the pipeline stages
    holding a :class:`Status` value each — :data:`STAGES`, plus one per extra
    fMRIPrep tree the project carries (:func:`stage_columns`). Presence is *not*
    completion — see the module docstring.

    Parameters
    ----------
    config : dict
        A loaded duckbrain config with derived ``[paths]`` (``bids_dir``,
        ``sourcedata_dir``, ``derivatives_dir``).

    Returns
    -------
    pd.DataFrame
        Columns: ``subject``, ``session``, then one per stage — see
        :func:`stage_columns`, which callers should use to lay them out. Empty
        (with the right columns) when the project has no subjects yet.
    """
    from ..config import external_bids

    paths = config["paths"]
    units = discover_units(paths)

    # Extra fMRIPrep trees grade through the *same* tracker with a different
    # derivative dir bound (`#5b` Case 2): one tracker, N trees, no second code
    # path to keep in step with the first.
    variants = fmriprep_variants(paths)
    trackers = dict(_TRACKERS)
    for variant in variants:
        trackers[variant] = partial(_fmriprep_status, tree=variant)

    # Per-stage applicability. A stage that cannot apply to this project grades
    # NA — the enum member exists for exactly this — because graded MISSING it
    # presents permanent unfinished work: the rollup reads "0/N", the cockpit
    # offers a one-click "run all", and "every stage complete" is unreachable.
    applies = dict.fromkeys(trackers, True)
    # NORDIC is opt-in per project. Without use_nordic nothing consumes its
    # output — fMRIPrep reads the raw BIDS tree — so it doesn't apply (TODO
    # #17.4, the first instance of the failure mode above). Launching NORDIC
    # deliberately in such a project is still possible from the Preprocessing
    # page's NORDIC tab.
    applies["nordic"] = bool(config.get("nordic", {}).get("use_nordic", False))
    # Same rule, same reason: the external FreeSurfer recon is opt-in, and
    # without use_external nothing imports it — fMRIPrep runs its own bundled
    # recon — so offering the stage would spend recon-all hours on a derivative
    # nothing reads.
    applies["freesurfer"] = bool(config.get("freesurfer", {}).get("use_external", False))
    # A declared external-BIDS project ingests no DICOMs, ever — the tree was
    # converted elsewhere and dropped in (#41.2, #17.4's shape again). Only
    # `ingested` goes NA: `converted` keeps grading, deliberately, because its
    # external branch (presence-as-COMPLETE, see `_converted_status`) is what
    # every downstream stage gates on — `pipeline.stage_runnable` requires the
    # dependency COMPLETE, so an NA `converted` would lock fMRIPrep/MRIQC out of
    # the very projects this flag exists for — and because "this unit has BIDS
    # data" is real information on a board whose rows may include hand-dropped
    # partial subjects.
    applies["ingested"] = not external_bids(config)
    # Variants are absent from `applies` overrides on purpose: a variant column
    # exists *because* its tree was found on disk, so it always applies. There is
    # no config toggle to disagree with — which is the point of reading the name
    # off disk rather than declaring it.

    rows = []
    for subject, session in units:
        row = {"subject": subject, "session": session}
        for stage, tracker in trackers.items():
            row[stage] = (
                tracker(config, subject, session).value if applies[stage] else Status.NA.value
            )
        rows.append(row)

    # `_stage_columns` reuses the `variants` read above rather than re-scanning:
    # a tree appearing mid-survey would otherwise give the frame a column no row
    # has a key for.
    columns = ["subject", "session", *_stage_columns(variants)]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns)


def run_progress(config: Config, stage: str, subject: str, session: str) -> tuple[int, int] | None:
    """``(runs_done, runs_expected)`` for a run-counted stage, or None.

    A PARTIAL cell with no number is its own silent degrade — it says "not
    finished" and leaves the operator to go count files. Returns None for stages
    that aren't one-output-per-run (ingested, converted) and whenever the unit
    expects no outputs at all.

    Shares :func:`_expected_bold_keys` and :func:`_found_keys` with the trackers
    so the number shown and the status shown cannot disagree — fMRIPrep through
    :func:`_fmriprep_func_keys`, which is what keeps a cell from reading ``4/4``
    beside PARTIAL when the confounds are missing, and MRIQC through
    :func:`_mriqc_expected_found`, whose count spans every rated image (anat
    included) for the same reason: bold-only counting put ``9/9`` beside a
    PARTIAL cell, the mmmduck contradiction.
    """
    paths = config["paths"]
    if stage == "nordic":
        expected = _expected_bold_keys(paths["bids_dir"], subject, session)
        found = _found_keys(
            Path(paths["derivatives_dir"]) / "nordic",
            _fmt("{ss}/**/func/sub-{sub}*_bold.nii.gz", subject, session),
        )
    elif stage == FMRIPREP_STAGE or stage in fmriprep_variants(paths):
        # For a variant the stage name *is* the derivative dir name (`#5b` Case
        # 2), so one branch counts every fMRIPrep tree and the number shown cannot
        # drift from the status the same-named tracker produced.
        expected = _expected_bold_keys(_fmriprep_input_dir(config), subject, session)
        found = _fmriprep_func_keys(Path(paths["derivatives_dir"]) / stage, subject, session)
    elif stage == "mriqc":
        expected, found = _mriqc_expected_found(config, subject, session)
    elif stage == "qsiprep":
        # Counted through `_covers`, not set intersection, for the same reason
        # `_qsiprep_status` grades through `_grade_merged` — a merged output is
        # coarser than the runs it covers, so an identity count would report 0/4
        # beside a COMPLETE cell.
        from .qsiprep import get_dwi_runs

        expected = {_entity_key(p.name) for p in get_dwi_runs(paths["bids_dir"], subject, session)}
        found = _qsiprep_dwi_keys(Path(paths["derivatives_dir"]) / "qsiprep", subject, session)
        if not expected:
            return None
        return sum(any(_covers(f, e) for f in found) for e in expected), len(expected)
    else:
        return None

    if not expected:
        return None
    return len(expected & found), len(expected)


def summarize(matrix: pd.DataFrame) -> dict[str, dict[str, int]]:
    """Per-stage counts of each status across all units.

    Returns ``{stage: {status: count}}`` — the numbers behind a dashboard's
    "12 complete / 3 partial / 5 missing" per stage.
    """
    out: dict[str, dict[str, int]] = {}
    for stage in matrix.columns:
        # Driven by the matrix's own columns rather than by STAGES, so a project's
        # fMRIPrep variants (`#5b` Case 2) are counted in the rollup instead of
        # being dropped from it. `_job` columns are the overlay `pipeline_matrix`
        # adds, not stages, and carry SLURM state rather than a Status.
        if stage in ("subject", "session") or stage.endswith("_job"):
            continue
        counts = matrix[stage].value_counts().to_dict()
        out[stage] = {s.value: int(counts.get(s.value, 0)) for s in Status}
    return out
