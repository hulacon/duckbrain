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
``EXPENSIVE`` ones (the L3 outcome family — Slice C in ``docs/sanity-checks.md``)
never run on the render path. They run only through :func:`run_expensive_checks`
— an explicit user action, never a post-job hook, because jobs die, get cancelled
and run outside duckbrain — which persists a :class:`CheckSnapshot` to
``<log_dir>/checks.json``. That file is deliberately duckbrain's first and only
state store: everything else re-derives live (``surveyor.py`` says why), and a
cached *verdict* earns the exception because it carries its own falsifiability —
a fingerprint of the inputs it was measured from, so the cockpit can render it
with a staleness marker instead of serving a stale "clean" as current, which is
the exact failure the validation panel refused a cache over.

**Reports, never blocks.** ``pipeline.stage_runnable`` is untouched: a failed
check surfaces, it does not gate. Where a condition is genuinely dangerous the
right answer is to raise at *build* time, per the silently-degrading rule in
CLAUDE.md — a check that stops you working is a check people learn to disable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .consistency import ConsistencyIssue, _b0_values, _examples, _read_json
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
from .nordic import get_bold_runs, nordic_output_dir
from .pipeline import _resolve_log_dir, read_submissions
from .surveyor import Status, _entity_key, _fmriprep_input_dir, _fmriprep_status, discover_units

if TYPE_CHECKING:
    from ..config import Config

#: Reads JSON, filenames and config only — safe on the cockpit's render path.
CHEAP = "cheap"
#: Opens image data or parses a tool report — needs a cache before it can run.
EXPENSIVE = "expensive"


@dataclass(frozen=True)
class Check:
    """One registered check: a slug, its cost, and the function that runs it.

    An ``EXPENSIVE`` check must also declare ``fingerprint`` — a *cheap* function
    (stats and globs, never file contents) identifying the inputs the check
    reads, so the cockpit can mark its cached result stale without paying for a
    re-measure. ``CHEAP`` checks re-run every render and need none.
    """

    slug: str
    cost: str
    run: Callable[[Config], list[ConsistencyIssue]]
    fingerprint: Callable[[Config], str] | None = None


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


# ---- the outcome family (L3, Slice C) — expensive, cached, run on demand ----


#: The exact value fMRIPrep's per-run summary reportlet carries when no
#: susceptibility distortion correction was applied — the one line the
#: fieldmap-intent bug left behind, in a report nobody read (CLAUDE.md).
_SDC_LINE = re.compile(r"Susceptibility distortion correction:\s*([^<\n]*)")


def _sdc_verdicts(fmriprep_root: Path, subject: str) -> dict[str, str]:
    """Acquisition key → the SDC value fMRIPrep's summary reportlet states.

    Read from the per-run reportlets under ``figures/``, not the monolithic
    ``sub-XX.html``: they are a few hundred bytes each, and the *filename*
    carries the run's entities — so the mapping back to a BOLD needs no HTML
    section parsing, just :func:`surveyor._entity_key` on the name. The figures
    directory sits at subject level even in longitudinal trees; the ``ses-``
    entity in the filename is what scopes a verdict to its session.
    """
    verdicts: dict[str, str] = {}
    try:
        for p in fmriprep_root.glob(f"sub-{subject}/**/figures/*_desc-summary_bold.html"):
            try:
                match = _SDC_LINE.search(p.read_text())
            except (OSError, ValueError):
                continue
            if match:
                verdicts[_entity_key(p.name)] = match.group(1).strip()
    except OSError:
        pass
    return verdicts


def _check_sdc_applied(config: Config) -> list[ConsistencyIssue]:
    """fMRIPrep's own SDC verdict versus the fieldmap intent in the sidecars.

    Complementary to ``consistency``'s ``fmap-intent``, not redundant: that
    check catches *malformed* intent from the sidecars before hours of compute;
    this one reads what fMRIPrep says it actually **did** — which also catches
    the run that happened before the metadata was fixed, and fMRIPrep declining
    intent that is correct. The declaration gating it is the ``B0FieldSource``
    duckbrain writes into each BOLD sidecar; a dataset stating no intent
    expects no correction and gets silence, per source.

    Judged only for COMPLETE units — the same silence ``requested-spaces``
    holds: a PARTIAL unit's shortfall already shows on the board, and this
    check exists for the run that *looks* done. A run without a summary
    reportlet is skipped: the tool left no testimony either way.
    """
    paths = config.get("paths") or {}
    derivatives = paths.get("derivatives_dir") or ""
    if not derivatives:
        return []
    root = Path(derivatives) / "fmriprep"
    if not root.is_dir():
        return []
    input_root = Path(_fmriprep_input_dir(config))

    issues: list[ConsistencyIssue] = []
    verdict_cache: dict[str, dict[str, str]] = {}
    for subject, session in discover_units(config["paths"]):
        declaring = [
            bold
            for bold in get_bold_runs(input_root, subject, session)
            if _b0_values(
                _read_json(bold.parent / bold.name.replace(".nii.gz", ".json")),
                "B0FieldSource",
            )
        ]
        if not declaring:
            continue
        if _fmriprep_status(config, subject, session) is not Status.COMPLETE:
            continue
        if subject not in verdict_cache:
            verdict_cache[subject] = _sdc_verdicts(root, subject)
        skipped = sorted(
            bold.name
            for bold in declaring
            if verdict_cache[subject].get(_entity_key(bold.name)) == "None"
        )
        if not skipped:
            continue
        where = f"sub-{subject}" + (f"/ses-{session}" if session else "")
        issues.append(
            ConsistencyIssue(
                check="outcome-sdc",
                subject=subject,
                stage="fmriprep",
                severity="warning",
                message=(
                    f"{where}: fMRIPrep reports `Susceptibility distortion correction: "
                    f"None` for {len(skipped)} run(s) whose sidecar declares a fieldmap "
                    f"(`B0FieldSource`): {_examples(skipped)}. The BOLD was preprocessed "
                    "uncorrected — either the run predates the current metadata, or "
                    "fMRIPrep declined intent that looks correct (check the fieldmap's "
                    "own files). The report is the tool's record of what it did, so "
                    "only re-running fMRIPrep changes this."
                ),
            )
        )
    return issues


def _first_volumes_match(raw: Path, denoised: Path) -> bool:
    """True when the two NIfTIs hold numerically identical first volumes.

    One volume, not the series: NORDIC changes essentially every voxel of every
    volume, so a single matching volume already convicts, and reading volume 0
    keeps the gzip decompression to the head of each stream. Compared as scaled
    values (``dataobj`` slicing) rather than raw bytes, because a silent no-op
    through MATLAB's writer re-encodes the file — byte comparison would acquit
    it. An unreadable file is not a finding, the module-wide contract.
    """
    import nibabel as nib
    import numpy as np

    try:
        # ``Any`` because nibabel types loads as the bare ``FileBasedImage``,
        # which declares neither ``shape`` nor ``dataobj``; the except clause
        # is already the contract for a file that doesn't duck-type as one.
        a: Any = nib.load(str(raw))
        b: Any = nib.load(str(denoised))
        if a.shape != b.shape:
            return False
        va = np.asanyarray(a.dataobj[..., 0] if len(a.shape) == 4 else a.dataobj)
        vb = np.asanyarray(b.dataobj[..., 0] if len(b.shape) == 4 else b.dataobj)
        return bool(np.allclose(va, vb, rtol=1e-6, atol=0.0))
    except Exception:
        return False


def _check_nordic_denoised(config: Config) -> list[ConsistencyIssue]:
    """NORDIC output that is numerically identical to its raw input.

    The denoise's whole product is a *difference*; an output equal to its input
    is a run that silently did nothing, and every consumer downstream (the
    staged fMRIPrep tree first) would treat it as denoised. The sbatch has no
    copy path — MATLAB always writes the output — so identical data is never
    legitimate. Presence/counts are the surveyor's job (``_nordic_status``);
    this only compares content where both files exist, so a running array
    can't be false-flagged for outputs it hasn't written yet.
    """
    paths = config.get("paths") or {}
    derivatives = paths.get("derivatives_dir") or ""
    bids_dir = paths.get("bids_dir") or ""
    if not derivatives or not bids_dir or not (Path(derivatives) / "nordic").is_dir():
        return []

    issues: list[ConsistencyIssue] = []
    for subject, session in discover_units(config["paths"]):
        raw_dir = Path(bids_dir) / sub_ses_relpath(subject, session) / "func"
        try:
            outs = sorted(nordic_output_dir(derivatives, subject, session).glob("*_bold.nii.gz"))
        except OSError:
            continue
        unchanged = [
            out.name
            for out in outs
            if (raw := raw_dir / out.name).is_file() and _first_volumes_match(raw, out)
        ]
        if not unchanged:
            continue
        where = f"sub-{subject}" + (f"/ses-{session}" if session else "")
        issues.append(
            ConsistencyIssue(
                check="outcome-nordic",
                subject=subject,
                stage="nordic",
                severity="warning",
                message=(
                    f"{where}: {len(unchanged)} NORDIC output(s) are numerically "
                    f"identical to their raw input: {_examples(unchanged)}. Denoising "
                    "changes every volume, so an identical output means the run "
                    "silently did nothing — and fMRIPrep would read it as denoised. "
                    "Delete the file(s) and re-run NORDIC; the job skips outputs that "
                    "already exist, so it will not overwrite them on its own."
                ),
            )
        )
    return issues


def _files_fingerprint(globs: Iterable[tuple[Path, str]]) -> str:
    """``<file count>:<newest mtime ns>`` over everything the globs match.

    The cheap identity of a check's inputs: stats only, never contents. The
    count is load-bearing alongside the mtime — deleting a file changes what a
    check would say but can never *raise* the newest mtime.
    """
    count, newest = 0, 0
    for root, pattern in globs:
        try:
            for p in root.glob(pattern):
                if p.is_file():
                    count += 1
                    newest = max(newest, p.stat().st_mtime_ns)
        except OSError:
            continue
    return f"{count}:{newest}"


def _sdc_fingerprint(config: Config) -> str:
    """The SDC check's inputs: the summary reportlets, and the BOLD sidecars
    whose intent gates it — so fixing a sidecar after a run marks the verdict
    stale even though no report changed."""
    paths = config.get("paths") or {}
    if not paths.get("derivatives_dir") or not paths.get("bids_dir"):
        return "0:0"
    reportlets = "sub-*/**/figures/*_desc-summary_bold.html"
    return _files_fingerprint(
        [
            (Path(paths["derivatives_dir"]) / "fmriprep", reportlets),
            (Path(_fmriprep_input_dir(config)), "sub-*/**/func/*_bold.json"),
        ]
    )


def _nordic_fingerprint(config: Config) -> str:
    """The NORDIC check's inputs: both sides of every comparison it makes."""
    paths = config.get("paths") or {}
    if not paths.get("derivatives_dir") or not paths.get("bids_dir"):
        return "0:0"
    return _files_fingerprint(
        [
            (Path(paths["derivatives_dir"]) / "nordic", "sub-*/**/func/*_bold.nii.gz"),
            (Path(paths["bids_dir"]), "sub-*/**/func/*_bold.nii.gz"),
        ]
    )


#: Ordered so the cockpit renders deterministically — project-level first, then
#: per-unit, matching how someone reads the board.
REGISTRY: tuple[Check, ...] = (
    Check("expected-roster", CHEAP, _check_roster),
    Check("expected-contents", CHEAP, _check_session_contents),
    Check("requested-spaces", CHEAP, _check_requested_spaces),
    Check("outcome-sdc", EXPENSIVE, _check_sdc_applied, _sdc_fingerprint),
    Check("outcome-nordic", EXPENSIVE, _check_nordic_denoised, _nordic_fingerprint),
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

    ``EXPENSIVE`` checks are excluded by default — the render path reads their
    persisted result via :func:`read_checks_snapshot` instead; only
    :func:`run_expensive_checks` (or an explicit ``include_expensive=True``)
    pays for a fresh measurement.
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


# ---- the snapshot — duckbrain's first (and only) state store ----------------


@dataclass(frozen=True)
class CheckSnapshot:
    """One persisted run of the expensive checks: when, against what, and what
    it found. ``fingerprint`` is per-check (slug → :func:`_files_fingerprint`
    string) — the inputs the verdict was measured from, which is what makes a
    cached verdict honest to render later."""

    ran_at: str
    fingerprint: dict[str, str]
    issues: tuple[ConsistencyIssue, ...]


def checks_snapshot_path(config: Config) -> Path:
    """Where the snapshot lives: ``<log_dir>/checks.json`` — shared FS, beside
    the submission log, for the same reason the logs are there."""
    return Path(_resolve_log_dir(config)) / "checks.json"


def expensive_fingerprint(config: Config) -> dict[str, str]:
    """Cheap identity of every expensive check's current inputs.

    Safe on the render path — stats and globs only. Comparing this against a
    snapshot's stored fingerprint is the staleness marker.
    """
    out: dict[str, str] = {}
    for check in REGISTRY:
        if check.cost != EXPENSIVE or check.fingerprint is None:
            continue
        try:
            out[check.slug] = check.fingerprint(config)
        except Exception:
            out[check.slug] = ""
    return out


def snapshot_is_stale(config: Config, snapshot: CheckSnapshot) -> bool:
    """True when any expensive check's inputs changed since *snapshot* ran."""
    return snapshot.fingerprint != expensive_fingerprint(config)


def run_expensive_checks(config: Config) -> CheckSnapshot:
    """Run the EXPENSIVE checks and persist the result to ``checks.json``.

    An explicit action, never a post-job hook — jobs die, get cancelled, and
    run outside duckbrain, so a hook would leave exactly the runs most worth
    checking unmeasured. The fingerprint is taken *before* the checks run:
    inputs changing mid-measurement then leave the snapshot marked stale
    rather than passing as current.

    Each check stays isolated (one blowing up cannot sink the rest), but the
    *write* is allowed to raise — this runs behind a button, and a snapshot
    that silently failed to persist would render as "not measured yet" while
    the user believes it was.
    """
    fingerprint = expensive_fingerprint(config)
    issues: list[ConsistencyIssue] = []
    for check in REGISTRY:
        if check.cost != EXPENSIVE:
            continue
        try:
            issues.extend(check.run(config))
        except Exception:
            continue
    snapshot = CheckSnapshot(
        ran_at=datetime.now().isoformat(timespec="seconds"),
        fingerprint=fingerprint,
        issues=tuple(issues),
    )
    path = checks_snapshot_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(
            {
                "ran_at": snapshot.ran_at,
                "fingerprint": snapshot.fingerprint,
                "issues": [asdict(i) for i in snapshot.issues],
            },
            f,
            indent=2,
        )
    return snapshot


def read_checks_snapshot(config: Config) -> CheckSnapshot | None:
    """The persisted snapshot, or ``None`` — absent or unreadable means "not
    measured yet", never a finding, the contract every reader here holds."""
    try:
        with open(checks_snapshot_path(config)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    fingerprint = data.get("fingerprint")
    raw_issues = data.get("issues")
    if not isinstance(fingerprint, dict) or not isinstance(raw_issues, list):
        return None
    known = {f.name for f in fields(ConsistencyIssue)}
    issues = []
    for entry in raw_issues:
        if not isinstance(entry, dict):
            continue
        try:
            issues.append(ConsistencyIssue(**{k: str(v) for k, v in entry.items() if k in known}))
        except TypeError:
            continue
    return CheckSnapshot(
        ran_at=str(data.get("ran_at", "")),
        fingerprint={str(k): str(v) for k, v in fingerprint.items()},
        issues=tuple(issues),
    )
