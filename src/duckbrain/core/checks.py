"""Sanity checks — what we asked for versus what we got (TODO #16).

Distinct from :mod:`duckbrain.core.consistency`, which is about **provenance
agreement**: whether the records of a run contradict each other. This module asks
a different question — whether the pipeline delivered what was *declared* — and
it needs a declaration to do it. Two exist, with different authors:

- the experimenter's ``[expected]`` section (L1 — roster and per-session
  contents; :mod:`duckbrain.core.expectations`), and
- duckbrain's own request record, written at launch (L2 —
  ``pipeline.record_request``), which is the only statement anywhere of what a
  job was asked to produce.

Each check gates on *its* declaration being present — absent means off, per
source, the same stance ``consistency.py`` takes toward absent provenance. A
project that declares nothing and has no recorded launches gets an empty answer
in silence.

The two share :class:`~duckbrain.core.consistency.ConsistencyIssue` and the
cockpit panel that renders it, deliberately. A user does not care which module
noticed; a second issue type and a second panel would be two things to read
instead of one.

**Where the boundary sits.** duckbrain checks the *contract* — did the things we
said would exist, exist. It does not assess image quality (MRIQC's job) and does
not audit acquisition parameters against a scanner protocol (mrQA's job, done
properly there against a real protocol export). Both of those are real and
neither belongs here; growing them in would make this a worse copy of a tool that
already exists.

**Registry entries declare a cost**, which is not decoration. The cockpit
re-derives everything on every render — and every 30 s under auto-refresh — so a
check that opens a NIfTI or parses an fMRIPrep HTML report cannot join that path
naively. ``CHEAP`` checks read JSON, filenames and config and run inline;
``EXPENSIVE`` ones are excluded by default and will need a cached, fingerprinted
result before any are registered. None are yet — the field exists so adding one
does not mean reshaping the registry.

**Reports, never blocks.** ``pipeline.stage_runnable`` is untouched: a failed
check surfaces, it does not gate. Where a condition is genuinely dangerous the
right answer is to raise at *build* time, per the silently-degrading rule in
CLAUDE.md — a check that stops you working is a check people learn to disable.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .consistency import ConsistencyIssue
from .expectations import (
    SessionCounts,
    SessionExpectation,
    declared,
    expected_for,
    expected_participants,
    has_bids_unit,
    observe,
)
from .ingestion import sub_ses_relpath
from .pipeline import read_submissions
from .surveyor import Status, _fmriprep_status, discover_units

if TYPE_CHECKING:
    from ..config import Config

#: Reads JSON, filenames and config only — safe on the cockpit's render path.
CHEAP = "cheap"
#: Opens image data or parses a tool report — needs a cache before it can run.
EXPENSIVE = "expensive"


@dataclass(frozen=True)
class Check:
    """One registered check: a slug, its cost, and the function that runs it."""

    slug: str
    cost: str
    run: Callable[[Config], list[ConsistencyIssue]]


def _shortfall(label: str, want: int, got: int) -> str:
    return f"{label}: expected {want}, found {got}"


def _check_roster(config: Config) -> list[ConsistencyIssue]:
    """Declared participants versus the subjects that actually exist.

    The only check here that can see a subject who was *scanned but never
    ingested* — every other view of the project is built from the union of what
    is on disk, so a missing subject is simply a row that never appears.

    Unexpected extras are reported too, at ``note`` severity, because they are
    diagnostic rather than wrong: a stray ``sub-`` label is the visible symptom of
    a qualified session folder being adopted as a subject, which is one of the
    five bugs real exports found under TODO #4.
    """
    labels, count = expected_participants(config)
    if not count:
        return []

    found = sorted({subject for subject, _ in discover_units(config["paths"])})
    issues: list[ConsistencyIssue] = []

    if labels:
        missing = [label for label in labels if label not in found]
        extra = [label for label in found if label not in labels]
        if missing:
            issues.append(
                ConsistencyIssue(
                    check="expected-roster",
                    severity="error",
                    message=(
                        f"{len(missing)} declared participant(s) have no data at all: "
                        + ", ".join(f"`sub-{m}`" for m in missing[:5])
                        + (f" (+{len(missing) - 5} more)" if len(missing) > 5 else "")
                        + ". They were declared in `[expected] participants` but appear "
                        "in neither sourcedata nor BIDS — so nothing else in duckbrain "
                        "can see them missing."
                    ),
                )
            )
        if extra:
            issues.append(
                ConsistencyIssue(
                    check="expected-roster",
                    severity="note",
                    message=(
                        f"{len(extra)} subject(s) not in the declared roster: "
                        + ", ".join(f"`sub-{e}`" for e in extra[:5])
                        + (f" (+{len(extra) - 5} more)" if len(extra) > 5 else "")
                        + ". Fine if they are pilots or re-scans. Worth a look if a "
                        "label looks like a session qualifier — that is what a "
                        "mis-parsed folder name looks like from here."
                    ),
                )
            )
    elif len(found) < count:
        issues.append(
            ConsistencyIssue(
                check="expected-roster",
                message=(
                    f"{len(found)} of {count} declared participants have data. "
                    "Expected while a study is still collecting; a shortfall at the "
                    "end means someone was scanned and never ingested."
                ),
            )
        )
    return issues


def _unit_issues(
    subject: str,
    session: str,
    want: SessionExpectation,
    got: SessionCounts,
) -> list[ConsistencyIssue]:
    """Compare one unit's declaration against what its BIDS tree holds.

    Shortfalls only. A session holding *more* than declared is not flagged — the
    same asymmetry ``surveyor._grade`` takes, and for the same reason: a re-scan,
    an extra localizer or a second T1w is a normal thing for real data to contain,
    and a check that fires on every legitimate difference gets switched off.
    """
    issues: list[ConsistencyIssue] = []
    where = f"sub-{subject}" + (f"/ses-{session}" if session else "")
    tail = " Accepted deviation? Record it under `[expected.exceptions]` with a reason."

    short_anat = [suffix for suffix, n in want.anat.items() if got.anat.get(suffix, 0) < n]
    missing_anat = [
        _shortfall(suffix, want.anat[suffix], got.anat.get(suffix, 0))
        for suffix in sorted(short_anat)
    ]
    if missing_anat:
        issues.append(
            ConsistencyIssue(
                check="expected-anat",
                subject=subject,
                stage="converted",
                severity="error" if any(got.anat.get(s, 0) == 0 for s in short_anat) else "warning",
                message=(
                    f"{where} is short on anatomical scans — "
                    + "; ".join(missing_anat)
                    + ". fMRIPrep needs a T1w; without one the stage will fail hours in "
                    "rather than here." + tail
                ),
            )
        )

    if want.fmap_pairs and got.fmap_pairs < want.fmap_pairs:
        issues.append(
            ConsistencyIssue(
                check="expected-fmap",
                subject=subject,
                stage="converted",
                severity="error" if got.fmap_pairs == 0 else "warning",
                message=(
                    f"{where} has {got.fmap_pairs} complete fieldmap pair(s), expected "
                    f"{want.fmap_pairs}. A pair needs two opposed phase-encoding "
                    "directions; a lone direction estimates nothing, so fMRIPrep will "
                    "exit 0 and report susceptibility distortion correction `None`." + tail
                ),
            )
        )

    short_task = [label for label, n in want.task.items() if got.task.get(label, 0) < n]
    missing_task = [
        _shortfall(f"task-{label}", want.task[label], got.task.get(label, 0))
        for label in sorted(short_task)
    ]
    if missing_task:
        absent = [label for label in short_task if got.task.get(label, 0) == 0]
        issues.append(
            ConsistencyIssue(
                check="expected-task",
                subject=subject,
                stage="converted",
                severity="error" if absent else "warning",
                message=(
                    f"{where} is short on BOLD runs — "
                    + "; ".join(missing_task)
                    + ". Every downstream stage derives its expectation from the runs "
                    "that *are* here, so a run that was never acquired or never "
                    "converted reads complete everywhere else." + tail
                ),
            )
        )
    return issues


def _check_session_contents(config: Config) -> list[ConsistencyIssue]:
    """Per-unit anat / fieldmap / task-run counts against the declaration.

    Skips units with no BIDS directory: a subject that is ingested but not yet
    converted is *pending*, not deficient, and reporting every one of them would
    make the panel unreadable on day one of a study.
    """
    if declared(config) is None:
        return []
    bids_dir = (config.get("paths") or {}).get("bids_dir") or ""
    if not bids_dir:
        return []

    issues: list[ConsistencyIssue] = []
    for subject, session in discover_units(config["paths"]):
        want = expected_for(config, subject, session)
        if want is None or not has_bids_unit(bids_dir, subject, session):
            continue
        issues.extend(_unit_issues(subject, session, want, observe(bids_dir, subject, session)))
    return issues


#: Requested space names that write **no** ``space-`` entity: fMRIPrep's
#: native-space aliases. The surveyor already requires the native preproc BOLD
#: (``_fmriprep_func_keys``), so there is nothing left for this check to say
#: about them.
_NATIVE_SPACES = frozenset({"func", "run", "boldref", "sbref"})


def _space_tokens(space: str) -> list[str] | None:
    """Filename tokens that evidence one requested ``--output-spaces`` entry.

    ``MNI152NLin2009cAsym:res-2`` → ``["space-MNI152NLin2009cAsym", "res-2"]``:
    the name becomes the ``space-`` entity and each colon modifier is already a
    ``key-value`` filename token, so all must appear in one filename. ``None``
    for the native aliases (nothing to look for) — and ``anat`` is the one alias
    that *does* write an entity, as ``space-T1w``.
    """
    parts = [p for p in str(space).split(":") if p]
    if not parts or parts[0] in _NATIVE_SPACES:
        return None
    name = "T1w" if parts[0] == "anat" else parts[0]
    return [f"space-{name}", *parts[1:]]


def _read_request(path: str) -> dict[str, Any]:
    """One ``requests/<job_id>.json``, or ``{}`` — an unreadable file is not a
    finding, the same contract every reader in ``consistency.py`` holds."""
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _func_token_sets(fmriprep_root: Path, subject: str, session: str) -> list[set[str]]:
    """The ``_``-separated tokens of every non-empty func file the unit's
    fMRIPrep output holds — what a requested space is checked against."""
    unit = fmriprep_root / sub_ses_relpath(subject, session)
    try:
        return [
            set(p.name.split(".")[0].split("_"))
            for p in unit.glob("func/*")
            if p.is_file() and p.stat().st_size > 0
        ]
    except (OSError, ValueError):
        return []


def _check_requested_spaces(config: Config) -> list[ConsistencyIssue]:
    """Requested fMRIPrep ``--output-spaces`` versus the spaces actually written.

    The one comparison nowhere else can make (``docs/sanity-checks.md``, Slice
    B): the surveyor strips
    ``space-``/``res-``/``den-`` when grading — deliberately, so an fMRIPrep
    upgrade renaming a representation can't invent a shortfall — which means a
    unit is COMPLETE as soon as every BOLD is preprocessed in *some* space. A
    run that quietly dropped ``fsaverage6`` reads done everywhere. Only the
    request record states the ask, so this check reads it back.

    Two silences are deliberate, both borrowed from lessons already paid for:

    - **Only the newest attempt per unit is judged**, and only when that attempt
      carries a request record. An older record describes a superseded run —
      the same staleness that made a naive crash-file check cry wolf
      (``consistency._check_tool_crashes``) — and a newer launch *without* a
      record (a duckbrain from before records existed, a hand-run sbatch) leaves nothing current to
      judge against.
    - **Only a COMPLETE unit is judged.** A PARTIAL unit's shortfall already
      shows on the board, and a running job would read as missing every space
      it hadn't written yet. This check exists for the run that *looks* done.

    More spaces on disk than requested is never flagged — a leftover from a
    previous config is the surveyor's asymmetry, held here too.
    """
    derivatives = (config.get("paths") or {}).get("derivatives_dir") or ""
    if not derivatives:
        return []
    subs = read_submissions(config)
    fp = subs[subs["stage"] == "fmriprep"]
    if fp.empty:
        return []
    root = Path(derivatives) / "fmriprep"

    issues: list[ConsistencyIssue] = []
    for _, row in fp.drop_duplicates(subset=["subject", "session"], keep="last").iterrows():
        request_path = str(row.get("request_path", "") or "")
        if not request_path:
            continue
        record = _read_request(request_path)
        spaces = (record.get("request") or {}).get("output_spaces")
        if isinstance(spaces, str):
            spaces = spaces.split()
        if not isinstance(spaces, list) or not spaces:
            continue
        subject, session = str(row["subject"]), str(row["session"])
        if _fmriprep_status(config, subject, session) is not Status.COMPLETE:
            continue
        found = _func_token_sets(root, subject, session)
        missing = [
            str(space)
            for space in spaces
            if (tokens := _space_tokens(str(space))) is not None
            and not any(set(tokens) <= file_tokens for file_tokens in found)
        ]
        if not missing:
            continue
        where = f"sub-{subject}" + (f"/ses-{session}" if session else "")
        issues.append(
            ConsistencyIssue(
                check="requested-spaces",
                subject=subject,
                stage="fmriprep",
                severity="warning",
                message=(
                    f"{where}: fMRIPrep reads complete, but the requested output "
                    f"space(s) {', '.join(f'`{m}`' for m in missing)} appear nowhere in "
                    f"its func output. The board can't see this — a run is graded on "
                    f"acquisitions, not representations, so *some* space being present "
                    f"is enough to read done. What was asked is recorded in "
                    f"`requests/{row['job_id']}.json` (output_spaces = {spaces}). "
                    "Re-run fMRIPrep if the space is still wanted; if the ask changed, "
                    "the next run's record will say so."
                ),
            )
        )
    return issues


#: Ordered so the cockpit renders deterministically — project-level first, then
#: per-unit, matching how someone reads the board.
REGISTRY: tuple[Check, ...] = (
    Check("expected-roster", CHEAP, _check_roster),
    Check("expected-contents", CHEAP, _check_session_contents),
    Check("requested-spaces", CHEAP, _check_requested_spaces),
)


def run_checks(config: Config, *, include_expensive: bool = False) -> list[ConsistencyIssue]:
    """Run the registered checks; return the flagged issues.

    Empty list means either nothing was found or — far more often — nothing was
    declared, which is the supported default. There is no gate here: each check
    gates on its *own* declaration (the ``[expected]`` checks on that section,
    the request-record check on a recorded launch), so a project with no
    ``[expected]`` still gets the L2 checks and vice versa. Each check is
    isolated: one blowing up must not sink the whole panel, the same contract
    :func:`~duckbrain.core.consistency.check_consistency` holds.
    """
    issues: list[ConsistencyIssue] = []
    for check in REGISTRY:
        if check.cost == EXPENSIVE and not include_expensive:
            continue
        try:
            issues.extend(check.run(config))
        except Exception:
            continue
    return issues
