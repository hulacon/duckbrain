"""Sanity checks — what we asked for versus what we got (TODO #16).

Distinct from :mod:`duckbrain.core.consistency`, which is about **provenance
agreement**: whether the records of a run contradict each other. This module asks
a different question — whether the pipeline delivered what the study *declared*
it would — and it needs a declaration to do it (see
:mod:`duckbrain.core.expectations`).

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

from collections.abc import Callable
from dataclasses import dataclass

from .consistency import ConsistencyIssue
from .expectations import (
    SessionExpectation,
    declared,
    expected_for,
    expected_participants,
    has_bids_unit,
    observe,
)
from .surveyor import discover_units

#: Reads JSON, filenames and config only — safe on the cockpit's render path.
CHEAP = "cheap"
#: Opens image data or parses a tool report — needs a cache before it can run.
EXPENSIVE = "expensive"


@dataclass(frozen=True)
class Check:
    """One registered check: a slug, its cost, and the function that runs it."""

    slug: str
    cost: str
    run: Callable[[dict], list[ConsistencyIssue]]


def _shortfall(label: str, want: int, got: int) -> str:
    return f"{label}: expected {want}, found {got}"


def _check_roster(config: dict) -> list[ConsistencyIssue]:
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
    got: SessionExpectation,
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


def _check_session_contents(config: dict) -> list[ConsistencyIssue]:
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


#: Ordered so the cockpit renders deterministically — project-level first, then
#: per-unit, matching how someone reads the board.
REGISTRY: tuple[Check, ...] = (
    Check("expected-roster", CHEAP, _check_roster),
    Check("expected-contents", CHEAP, _check_session_contents),
)


def run_checks(config: dict, *, include_expensive: bool = False) -> list[ConsistencyIssue]:
    """Run the registered checks; return the flagged issues.

    Empty list means either nothing was found or — far more often — the project
    declares no expectations, which is the supported default. Each check is
    isolated: one blowing up must not sink the whole panel, the same contract
    :func:`~duckbrain.core.consistency.check_consistency` holds.
    """
    if declared(config) is None:
        return []
    issues: list[ConsistencyIssue] = []
    for check in REGISTRY:
        if check.cost == EXPENSIVE and not include_expensive:
            continue
        try:
            issues.extend(check.run(config))
        except Exception:
            continue
    return issues
