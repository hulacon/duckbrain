"""Physio reality pass: does a recording contain a signal, or only its shape?

A BIDS physio recording is a file, and every layer above this one counts files.
The catalog's ``resolution`` view asks whether a ``*_physio.tsv.gz`` exists for a
bold unit; ``expectations`` declares that one should. Neither opens it. So a
recording whose sensor was unplugged — the file written, the right length, the
sidecar correct, the column full of one repeated number — reads *present*
everywhere, and the dataset reports physio it does not have.

That is the same circularity :mod:`duckbrain.core.expectations` exists to break,
one level further down: there the expectation was derived from the data, here the
*observation* is. This module is the observation done honestly. It reads each
recording and reports what is in it.

**It reports; it does not repair, and it does not decide.** The verdicts below
are facts about content, handed across the ingest boundary for the catalog to
resolve (contracts §3.2 — duckbrain contributes facts, the catalog ingests). No
file is rewritten, no exception is flipped, nothing is deleted. A dud recording
is evidence about an acquisition, and acquisitions are not fixable after the
fact.

Why the verdict vocabulary is three words and not two
----------------------------------------------------

"Real vs dud" was the brief (``TODO #7.5``), and measuring mmmdata's 766
recordings showed two ways to be a dud that want different answers:

``flat``
    Nothing changing. Either one value for the whole run, or one value held for
    long enough that the sensor plainly stopped (:data:`FLAT_FRACTION_MAX`).
    Eleven recordings in mmmdata, and nine of them are one session the dataset's
    own exceptions already explain — "no respiratory data (battery dead)".
    Agreeing with a declared answer, on a session declared independently of this
    code, is the closest thing to ground truth these rules get.

``trigger-only``
    Two levels, switching on a period a body does not hold. mmmdata's
    ``recording-cardiac`` files are 228-of-231 like this, and the period is
    1.500 s — the *TR*. The channel carries scanner volume triggers. The file is
    not empty and not broken; it is the wrong signal, which is harder to notice
    than emptiness, and a consumer reaching for cardiac phase would find 231
    present files and no heartbeat in any of them.

    What that verdict does *not* mean is that the session has no cardiac data.
    mmmdata's ``recording-pulse`` channel is a pulse-oximetry trace, 230-of-231
    usable, with a dominant frequency of 60–95 bpm that moves session to
    session. They recorded PPG rather than ECG, which is ordinary and is also
    what RETROICOR wants. The finding is that the *cardiac-named* channel is not
    where it lives.

``usable``
    The signal varies over the run. This says nothing about quality — see
    :attr:`ColumnMeasures.na_fraction` and :attr:`longest_flat_s`, which are
    reported for every column precisely so a consumer can be stricter than this
    module is.

Collapsing ``trigger-only`` into ``flat`` would have lost that distinction
entirely, and a "~50% empty" belief that only counts emptiness would have missed
it too: nothing here is empty. The measured split over mmmdata's 766 recordings
is 527 usable, 228 trigger-only, 11 flat.

Note what the ``usable`` count is not. It is not a quality grade — one of those
527 is a pulse recording that lost its sensor for 73 s. The verdict answers
"is there a signal here at all", and every measure behind it is in the artifact
so a consumer can hold a higher bar.

The regularity test, and why it needs no TR
-------------------------------------------

A two-level channel is judged by the *dispersion* of the interval between its
rising edges, never by the interval itself. A machine holds its period; a body
does not. mmmdata's trigger channels have an inter-onset IQR of exactly zero
against a 1.500 s median, and a heart that did that would be a medical
emergency.

This matters because the alternative test — compare the period to the bold
``RepetitionTime`` — needs the bold sidecar, ties the judgement to a file that
may not exist (mmmdata has physio whose bold is named without its ``run``
entity), and would call a *real* cardiac trigger channel healthy only by
accident. Beat-onset gating is genuine physiological data, and an R-wave gate is
two-level too: what separates it from a scanner trigger is that its intervals
scatter. Dispersion answers the question directly. The measured period is still
reported, because "1.500 s" is what makes the finding legible to a human.
"""

from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: A column is flat when every finite sample is the same value. No tolerance:
#: one repeated integer is what a disconnected sensor writes, and a signal with
#: any life in it clears this by orders of magnitude, so a threshold here would
#: only invent a grey zone the data does not have.
FLAT_N_UNIQUE = 1

#: Levels a channel may take before the square-wave tests stop applying. Two is
#: not a threshold but a definition: a binary channel is the only thing whose
#: rising edges are unambiguous.
BINARY_N_LEVELS = 2

#: Rising edges needed before an interval dispersion means anything. Two edges
#: give one interval and no dispersion at all.
MIN_ONSETS_FOR_PERIOD = 4

#: Share of a recording that may sit at one unchanging value before the sensor
#: is judged to have stopped rather than the signal to have been quiet.
#:
#: This is the rule that catches a *partly* dead recording, and mmmdata sets it
#: against a declared answer. sub-04/ses-16 carries the dataset's own exception
#: "no respiratory data (battery dead)", and nine files were written for it
#: anyway. Five are flat outright. The other four hold two values with one or
#: three switches between them and sit still for 62–64 s: three at 0.25–0.29 of
#: their run, and one — ``TBresting``, the longest of them — at 0.194.
#:
#: Everything in the dataset that is genuinely alive stays at or below 0.060,
#: and that ceiling is itself a real dropout rather than a healthy run (a pulse
#: recording with 3769 distinct values that lost its sensor for 73 s of 1210).
#: So the empty span is 0.060 to 0.194 and the threshold sits in the middle of
#: it. A first pass placed this at 0.2, which read the gap off a coarser
#: measurement and let ``TBresting`` through by three percent — a threshold set
#: just past the hardest case it had to catch, which is the way to get one
#: wrong.
#:
#: A quiet body does not do this. Respiration is the slowest channel here at
#: roughly a breath every four seconds, so an eighth of a run at one value is
#: still a dozen missed breaths.
FLAT_FRACTION_MAX = 0.12

#: Interquartile range of the inter-onset interval, over its median, below which
#: a two-level channel is machine-generated rather than physiological. mmmdata's
#: scanner triggers sit at exactly 0.0 and a resting human heart's IQR/median
#: runs a few percent even at its steadiest, so the boundary is wide on both
#: sides. Deliberately not 0: a recording clock that drops the odd sample would
#: put a machine slightly above zero, and that must not read as a heartbeat.
MACHINE_REGULARITY_MAX = 0.02

#: Columns whose name declares a physiological waveform. A ``trigger-only``
#: verdict is only meaningful against a column that claimed to be physiology —
#: a channel BIDS names as a trigger carrying triggers is doing its job.
PHYSIO_COLUMN_HINTS = ("cardiac", "respiratory", "pulse", "ppg", "ecg", "eye")

_RECORDING_RE = re.compile(r"_recording-([a-zA-Z0-9]+)")
_ENTITY_RE = re.compile(r"(?:^|_)(sub|ses|task|run|acq)-([a-zA-Z0-9]+)")


@dataclass(frozen=True)
class ColumnMeasures:
    """Neutral measurements of one column. No judgement lives here.

    Every field is a fact about the samples, computed without reference to what
    the column is called or what it was supposed to contain. :func:`judge`
    turns these into a verdict; keeping the two apart is what lets a consumer
    disagree with the verdict and still use the numbers.

    Parameters
    ----------
    name : str
        The column's declared name, from the sidecar's ``Columns``.
    n_samples : int
        Rows in the file, including non-finite ones.
    na_fraction : float
        Share of samples that are ``n/a`` or otherwise non-finite. For EyeLink
        this is blink and track loss and is expected to be substantial; for a
        scanner channel anything above zero is unusual.
    n_unique : int
        Distinct finite values.
    std : float
        Standard deviation of the finite samples. Reported, never thresholded:
        its scale is the sensor's arbitrary units, so it compares runs of the
        same channel and nothing else.
    longest_flat_s : float
        Longest unbroken stretch of one repeated value, in seconds. A recording
        can be ``usable`` overall and still have lost the sensor for a minute in
        the middle; this is where that shows, and mmmdata has exactly that case
        — a pulse recording with 3769 distinct values and a 73 s dead patch.
    flat_fraction : float
        :attr:`longest_flat_s` over the recording's duration. The scale-free
        form, and the one :func:`judge` thresholds against
        :data:`FLAT_FRACTION_MAX`; the seconds are kept because a human reading
        the artifact wants "73 s", not "0.06".
    levels : tuple[float, ...]
        The distinct values, but only when there are at most
        :data:`BINARY_N_LEVELS` of them — otherwise empty, since enumerating
        thousands of floats into an artifact helps nobody.
    n_onsets : int
        Rising edges, for a binary channel; 0 otherwise.
    onset_period_s : float | None
        Median interval between rising edges, in seconds.
    onset_period_dispersion : float | None
        Interquartile range of that interval over its median — the
        machine-vs-body discriminator described in the module docstring.
    """

    name: str
    n_samples: int
    na_fraction: float
    n_unique: int
    std: float
    longest_flat_s: float
    flat_fraction: float
    levels: tuple[float, ...] = ()
    n_onsets: int = 0
    onset_period_s: float | None = None
    onset_period_dispersion: float | None = None


@dataclass(frozen=True)
class ColumnVerdict:
    """One column's verdict, and the measurement that produced it."""

    name: str
    verdict: str
    reason: str
    measures: ColumnMeasures


@dataclass(frozen=True)
class RecordingAssessment:
    """Every column of one recording, plus the recording-level verdict.

    Parameters
    ----------
    relpath : str
        Path relative to the BIDS root — the artifact's join key, and the form
        the catalog's ``files`` rows use.
    recording : str
        The ``recording-`` entity (``cardiac``, ``pulse``, ``respiratory``,
        ``eye``), or ``''`` when the filename carries none.
    entities : dict[str, str]
        ``sub``/``ses``/``task``/``run``/``acq`` parsed from the filename, so a
        consumer can join to a bold unit without re-parsing.
    sampling_frequency : float | None
        From the sidecar. ``None`` makes every duration measure ``nan`` and is
        reported rather than guessed.
    columns : list[ColumnVerdict]
        One per data column, in file order.
    verdict : str
        The recording's verdict: the worst of its physiological columns, ranked
        ``flat`` < ``trigger-only`` < ``usable``. A recording is only as good as
        the signal it was collected for.
    """

    relpath: str
    recording: str
    entities: dict[str, str]
    sampling_frequency: float | None
    columns: list[ColumnVerdict] = field(default_factory=list)
    verdict: str = "usable"

    @property
    def is_usable(self) -> bool:
        """Whether any physiological signal survived in this recording."""
        return self.verdict == "usable"


#: Worst-first, which is the order :func:`assess` reduces a recording's columns
#: in. ``unreadable`` is first because a file that would not parse is a stronger
#: statement than any measurement taken from one that did.
VERDICT_RANK: tuple[str, ...] = ("unreadable", "flat", "trigger-only", "usable")


def measure(values: np.ndarray, sampling_frequency: float | None, name: str = "") -> ColumnMeasures:
    """Measure one column. Facts only — see :class:`ColumnMeasures`."""
    finite = values[np.isfinite(values)]
    n = int(values.size)
    na_fraction = 1.0 - (finite.size / n) if n else 1.0
    if finite.size == 0:
        return ColumnMeasures(
            name=name,
            n_samples=n,
            na_fraction=na_fraction,
            n_unique=0,
            std=float("nan"),
            longest_flat_s=float("nan"),
            flat_fraction=1.0,
        )

    distinct = np.unique(finite)
    # Longest constant run, converted to seconds. Computed on the finite
    # samples: a gap of n/a interrupts a flat stretch on disk but not in the
    # sensor, and it is the sensor being reported on.
    changes = np.flatnonzero(np.diff(finite)) + 1
    runs = np.diff(np.concatenate(([0], changes, [finite.size])))
    longest_flat = int(runs.max())

    measures: dict[str, Any] = {
        "name": name,
        "n_samples": n,
        "na_fraction": round(na_fraction, 6),
        "n_unique": int(distinct.size),
        "std": float(np.std(finite)),
        "longest_flat_s": _seconds(longest_flat, sampling_frequency),
        # Against the finite samples, not the file length: a column that is
        # half n/a and half a flat line is wholly dead, and dividing by the
        # file length would score it 0.5 and call it usable.
        "flat_fraction": longest_flat / finite.size,
    }

    if distinct.size <= BINARY_N_LEVELS:
        measures["levels"] = tuple(float(v) for v in distinct)
    if distinct.size == BINARY_N_LEVELS:
        high = finite > distinct[0]
        onsets = np.flatnonzero(np.diff(high.astype(np.int8)) == 1)
        measures["n_onsets"] = int(onsets.size)
        if onsets.size >= MIN_ONSETS_FOR_PERIOD and sampling_frequency:
            intervals = np.diff(onsets) / sampling_frequency
            median = float(np.median(intervals))
            iqr = float(np.percentile(intervals, 75) - np.percentile(intervals, 25))
            measures["onset_period_s"] = median
            # Guard the divide rather than the input: a degenerate median means
            # the dispersion is undefined, not zero, and zero would read as
            # "perfectly regular" — the exact wrong answer.
            measures["onset_period_dispersion"] = iqr / median if median > 0 else None

    return ColumnMeasures(**measures)


def judge(measures: ColumnMeasures) -> ColumnVerdict:
    """Turn one column's measurements into a verdict and a stated reason.

    The reason is not decoration. A verdict that cannot say why is one a human
    has to re-derive by opening the file, which is the work this module exists
    to have already done.
    """
    m = measures
    if m.n_unique == 0:
        return ColumnVerdict(m.name, "flat", "no finite samples", m)
    if m.n_unique <= FLAT_N_UNIQUE:
        value = m.levels[0] if m.levels else float("nan")
        return ColumnVerdict(m.name, "flat", f"constant at {value:g} for the whole run", m)

    # Order matters: regularity is tested before the flat-stretch rule, because
    # a trigger channel is a more specific finding than a dead one and both can
    # be true of the same column. "Carries the scanner's triggers" tells you the
    # cable was in the wrong socket; "went flat" tells you only that it stopped.
    if (
        m.n_unique == BINARY_N_LEVELS
        and m.onset_period_dispersion is not None
        and m.onset_period_dispersion <= MACHINE_REGULARITY_MAX
    ):
        period = m.onset_period_s or float("nan")
        return ColumnVerdict(
            m.name,
            "trigger-only",
            f"two levels switching every {period:.3f} s "
            f"(interval IQR/median {m.onset_period_dispersion:.4f}) — "
            "a machine's period, not a body's",
            m,
        )

    if m.flat_fraction >= FLAT_FRACTION_MAX:
        return ColumnVerdict(
            m.name,
            "flat",
            f"held one value for {m.longest_flat_s:.1f} s, {m.flat_fraction:.0%} of the recording",
            m,
        )

    return ColumnVerdict(m.name, "usable", f"{m.n_unique} distinct values over the run", m)


def read_recording(path: str | pathlib.Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a ``*_physio.tsv.gz`` and its sidecar. Returns (samples, sidecar).

    BIDS physio TSVs are headerless by specification — the sidecar's ``Columns``
    names them — so a header row is never skipped, and ``n/a`` is the spec's
    missing-value token rather than an empty field.
    """
    path = pathlib.Path(path)
    sidecar_path = path.with_name(path.name.replace(".tsv.gz", ".json"))
    sidecar: dict[str, Any] = {}
    if sidecar_path.is_file():
        sidecar = json.loads(sidecar_path.read_text())

    # pandas rather than a comprehension: mmmdata's longest recording is 2.03
    # million rows and there are 766 of them, so the parse is the whole cost of
    # this pass. A pure-Python split over that is minutes per file.
    import pandas as pd

    frame = pd.read_csv(
        path,
        sep="\t",
        header=None,
        na_values=["n/a", "N/A"],
        dtype="float64",
        comment=None,
    )
    if frame.empty:
        return np.empty((0, 0)), sidecar
    return frame.to_numpy(dtype=float), sidecar


def _seconds(n_samples: int, sampling_frequency: float | None) -> float:
    """Samples to seconds, or ``nan`` when the sidecar declared no rate."""
    if not sampling_frequency:
        return float("nan")
    return n_samples / sampling_frequency


def _entities(name: str) -> dict[str, str]:
    """BIDS entities from a filename, for joining without re-parsing."""
    return {key: value for key, value in _ENTITY_RE.findall(name)}


def _is_physiological(column_name: str, recording: str) -> bool:
    """Whether a column claimed to carry physiology.

    A ``trigger-only`` verdict against a column that never claimed to be a
    waveform is not a finding, so the recording-level reduction ignores those.
    The declared column name is the claim; the ``recording-`` entity is the
    fallback for a sidecar that named its columns something local.
    """
    haystack = f"{column_name} {recording}".lower()
    return any(hint in haystack for hint in PHYSIO_COLUMN_HINTS)


def assess(path: str | pathlib.Path, root: str | pathlib.Path) -> RecordingAssessment:
    """Measure and judge one recording, end to end."""
    path = pathlib.Path(path)
    relpath = str(path.relative_to(root))
    match = _RECORDING_RE.search(path.name)
    recording = match.group(1) if match else ""

    try:
        samples, sidecar = read_recording(path)
    except (OSError, ValueError) as exc:
        # A file that will not parse is a stronger statement than any
        # measurement, and it must not be silently skipped into a clean report.
        return RecordingAssessment(
            relpath=relpath,
            recording=recording,
            entities=_entities(path.name),
            sampling_frequency=None,
            columns=[
                ColumnVerdict(
                    "", "unreadable", f"{type(exc).__name__}: {exc}", measure(np.empty(0), None)
                )
            ],
            verdict="unreadable",
        )

    sfreq = sidecar.get("SamplingFrequency")
    names = list(sidecar.get("Columns", []))
    n_cols = samples.shape[1] if samples.ndim == 2 and samples.size else 0

    verdicts: list[ColumnVerdict] = []
    for index in range(n_cols):
        name = names[index] if index < len(names) else f"col{index}"
        verdicts.append(judge(measure(samples[:, index], sfreq, name)))

    physiological = [v for v in verdicts if _is_physiological(v.name, recording)] or verdicts
    worst = (
        "unreadable"
        if not verdicts
        else min((v.verdict for v in physiological), key=VERDICT_RANK.index)
    )
    return RecordingAssessment(
        relpath=relpath,
        recording=recording,
        entities=_entities(path.name),
        sampling_frequency=sfreq,
        columns=verdicts,
        verdict=worst,
    )


def sweep(root: str | pathlib.Path) -> list[RecordingAssessment]:
    """Assess every ``*_physio.tsv.gz`` under a BIDS root, in path order.

    Walks the raw tree only. Derivatives may copy or resample physio, and a
    reality pass over a copy answers a question nobody asked — what was
    *acquired* is the raw file.
    """
    root = pathlib.Path(root)
    found = sorted(root.glob("sub-*/**/*_physio.tsv.gz"))
    return [assess(path, root) for path in found]


def _row(assessment: RecordingAssessment) -> dict[str, Any]:
    """One artifact row per recording. Flat on purpose — this is a TSV."""
    worst = min(assessment.columns, key=lambda c: VERDICT_RANK.index(c.verdict), default=None)
    entities = assessment.entities
    return {
        "relpath": assessment.relpath,
        "sub": entities.get("sub", ""),
        "ses": entities.get("ses", ""),
        "task": entities.get("task", ""),
        "run": entities.get("run", ""),
        "recording": assessment.recording,
        "verdict": assessment.verdict,
        "reason": worst.reason if worst else "",
        "n_columns": len(assessment.columns),
        "sampling_frequency": assessment.sampling_frequency,
        "n_samples": worst.measures.n_samples if worst else 0,
        "na_fraction": worst.measures.na_fraction if worst else "",
        "n_unique": worst.measures.n_unique if worst else "",
        "longest_flat_s": worst.measures.longest_flat_s if worst else "",
        "flat_fraction": worst.measures.flat_fraction if worst else "",
        "onset_period_s": worst.measures.onset_period_s if worst else "",
        "onset_period_dispersion": worst.measures.onset_period_dispersion if worst else "",
    }


#: The artifact's columns, in order. Fixed here rather than derived from the
#: first row so a run over a tree whose recordings all happen to be flat still
#: writes the full header — a consumer must not have to guess whether a missing
#: column means "no such measure" or "no such recording".
ARTIFACT_COLUMNS: tuple[str, ...] = (
    "relpath",
    "sub",
    "ses",
    "task",
    "run",
    "recording",
    "verdict",
    "reason",
    "n_columns",
    "sampling_frequency",
    "n_samples",
    "na_fraction",
    "n_unique",
    "longest_flat_s",
    "flat_fraction",
    "onset_period_s",
    "onset_period_dispersion",
)

#: Where the pass writes, under the BIDS root. Beneath ``derivatives/duckbrain``
#: with everything else duckbrain authors, and named for what it is rather than
#: for the item that asked for it.
ARTIFACT_SUBDIR = "physio"
ARTIFACT_NAME = "physio_reality.tsv"


def write_artifact(
    assessments: list[RecordingAssessment],
    out_dir: str | pathlib.Path,
) -> pathlib.Path:
    """Write the per-recording artifact plus its provenance sidecar.

    Two files, because they answer different questions and one of them must
    survive being read by something that knows no duckbrain: the TSV is the
    facts, the JSON says which duckbrain produced them and against what rules.
    The rule *values* are stamped, not just the version — a threshold that moves
    silently would make two artifacts incomparable with nothing on either to
    say so.
    """
    import csv

    from .bids_metadata import duckbrain_version

    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = out_dir / ARTIFACT_NAME

    with tsv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=ARTIFACT_COLUMNS, delimiter="\t", extrasaction="ignore"
        )
        writer.writeheader()
        for assessment in assessments:
            writer.writerow(_row(assessment))

    tally: dict[str, int] = {}
    for assessment in assessments:
        tally[assessment.verdict] = tally.get(assessment.verdict, 0) + 1

    sidecar = {
        "GeneratedBy": [{"Name": "duckbrain", "Version": duckbrain_version()}],
        "Description": (
            "Per-recording reality pass over raw BIDS physio: whether each "
            "recording contains a signal, only a scanner trigger, or nothing. "
            "Derived and regenerable; the catalog ingests it, nothing reads it "
            "as canonical."
        ),
        "Rules": {
            "FLAT_N_UNIQUE": FLAT_N_UNIQUE,
            "FLAT_FRACTION_MAX": FLAT_FRACTION_MAX,
            "MACHINE_REGULARITY_MAX": MACHINE_REGULARITY_MAX,
            "MIN_ONSETS_FOR_PERIOD": MIN_ONSETS_FOR_PERIOD,
        },
        "Tally": tally,
        "RecordingCount": len(assessments),
    }
    (out_dir / ARTIFACT_NAME.replace(".tsv", ".json")).write_text(
        json.dumps(sidecar, indent=2) + "\n"
    )
    return tsv_path


def main(argv: list[str] | None = None) -> int:
    """``python -m duckbrain.core.physio --root <bids_root>``.

    A verb of its own rather than a catalog tier, because the pass reads the
    *raw recordings* and the catalog reads artifacts. It is also far too slow to
    belong in a rebuild — mmmdata's 766 recordings are 336 MB compressed and
    take minutes, against the catalog's forty seconds — and forcing a rebuild to
    carry that cost is how a cheap idempotent command becomes one nobody runs.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m duckbrain.core.physio", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument("--root", required=True, type=pathlib.Path, help="BIDS root")
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        default=None,
        help="where the artifact lands (default <root>/derivatives/duckbrain/physio)",
    )
    args = parser.parse_args(argv)

    root: pathlib.Path = args.root.resolve()
    out_dir: pathlib.Path = args.out_dir or (root / "derivatives" / "duckbrain" / ARTIFACT_SUBDIR)

    assessments = sweep(root)
    if not assessments:
        # Not an error: a tree with no physio is a normal tree. But say so,
        # because an empty artifact and a tree that was never walked look
        # identical afterwards.
        print(f"no *_physio.tsv.gz found under {root}")
    path = write_artifact(assessments, out_dir)

    tally: dict[str, int] = {}
    for assessment in assessments:
        tally[assessment.verdict] = tally.get(assessment.verdict, 0) + 1
    print(f"{len(assessments)} recordings -> {path}")
    for verdict in VERDICT_RANK:
        if verdict in tally:
            print(f"  {verdict:13s} {tally[verdict]:4d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
