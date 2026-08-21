"""TODO #7.5 first half: a recording that is present but carries no signal.

Every layer above `core.physio` counts physio *files*. The catalog's
`resolution` view asks whether a `*_physio.tsv.gz` exists for a bold unit and
the declaration says one should; neither opens it. mmmdata is the proof that
this matters — 766 recordings on disk, and 239 of them hold nothing a body
produced.

The load-bearing tests here are the two negative ones. `test_an_irregular_gate_is_not_a_trigger`
is the whole reason the trigger rule tests interval *dispersion* rather than
comparing the period to the TR: a real R-wave gate is two-level too, and a rule
that called it a machine would throw away the one kind of cardiac data this
dataset could still have had. `test_a_quiet_stretch_is_not_a_dead_sensor` pins
the other direction — the flat-fraction rule must not fire on a real recording
that went briefly still, which mmmdata has (a pulse recording with 3769 distinct
values and a 73 s dropout, `usable` with the dropout reported).

The threshold constants are asserted against the gap that set them, not just
read back, so that moving one fails here rather than silently reclassifying a
dataset.
"""

import gzip
import json

import numpy as np
import pytest

from duckbrain.core.physio import (
    ARTIFACT_COLUMNS,
    FLAT_FRACTION_MAX,
    MACHINE_REGULARITY_MAX,
    assess,
    judge,
    measure,
    sweep,
    write_artifact,
)

SF = 1000.0


def _square(period_s, jitter_s=0.0, duration_s=300.0, sf=SF, seed=0, width_s=0.05):
    """A two-level channel with rising edges every ``period_s`` (± jitter)."""
    rng = np.random.default_rng(seed)
    values = np.full(int(duration_s * sf), 2052.0)
    position = 0.0
    while position < duration_s - period_s:
        position += period_s + (rng.normal(0, jitter_s) if jitter_s else 0.0)
        start = int(position * sf)
        values[start : start + int(width_s * sf)] = 2064.0
    return values


def _waveform(rate_hz=1.1, duration_s=300.0, sf=SF, seed=0):
    """A plausible continuous physiological trace."""
    t = np.arange(0, duration_s, 1 / sf)
    rng = np.random.default_rng(seed)
    return 1000 + 300 * np.sin(2 * np.pi * rate_hz * t) + rng.normal(0, 5, t.size)


def _write_recording(directory, name, columns, data, sf=SF, extra=None):
    """Write a BIDS physio pair (headerless .tsv.gz + sidecar)."""
    directory.mkdir(parents=True, exist_ok=True)
    array = np.asarray(data, dtype=float)
    if array.ndim == 1:
        array = array[:, None]
    lines = ["\t".join("n/a" if not np.isfinite(v) else f"{v:g}" for v in row) for row in array]
    with gzip.open(directory / f"{name}_physio.tsv.gz", "wt") as handle:
        handle.write("\n".join(lines) + "\n")
    sidecar = {"SamplingFrequency": sf, "Columns": list(columns), **(extra or {})}
    (directory / f"{name}_physio.json").write_text(json.dumps(sidecar))


# --------------------------------------------------------------------------
# The verdicts
# --------------------------------------------------------------------------


def test_a_constant_column_is_flat():
    verdict = judge(measure(np.full(5000, 2052.0), 125.0, "respiratory"))
    assert verdict.verdict == "flat"
    assert "constant" in verdict.reason


def test_a_column_of_only_na_is_flat():
    verdict = judge(measure(np.full(5000, np.nan), 125.0, "respiratory"))
    assert verdict.verdict == "flat"
    assert verdict.measures.n_unique == 0


def test_a_metronomic_two_level_channel_is_trigger_only():
    """mmmdata's cardiac channels: 1.500 s apart, zero dispersion. The TR."""
    verdict = judge(measure(_square(1.5), SF, "cardiac"))
    assert verdict.verdict == "trigger-only"
    assert verdict.measures.onset_period_s == pytest.approx(1.5, abs=1e-3)
    assert verdict.measures.onset_period_dispersion == pytest.approx(0.0, abs=1e-9)
    # The reason has to carry the period: "1.500 s" is what lets a human
    # recognise their own TR and understand what went wrong at the console.
    assert "1.500" in verdict.reason


def test_an_irregular_gate_is_not_a_trigger():
    """A real R-wave gate is two-level too. Dispersion is what separates them.

    This is why the rule does not compare the period to `RepetitionTime`: that
    test would pass a scanner trigger whose TR happened to differ, and would
    have no opinion at all about a genuine beat gate.
    """
    verdict = judge(measure(_square(0.85, jitter_s=0.09, seed=1), SF, "cardiac"))
    assert verdict.verdict == "usable"
    assert verdict.measures.onset_period_dispersion > MACHINE_REGULARITY_MAX


def test_a_waveform_is_usable():
    assert judge(measure(_waveform(), SF, "pulse")).verdict == "usable"


def test_a_long_dead_stretch_is_flat_even_with_signal_around_it():
    """sub-04/ses-16: two values, one switch, still for a quarter of the run."""
    values = _waveform(duration_s=200.0)
    values[: int(0.3 * values.size)] = values[0]
    verdict = judge(measure(values, SF, "respiratory"))
    assert verdict.verdict == "flat"
    assert "30%" in verdict.reason


def test_a_quiet_stretch_is_not_a_dead_sensor():
    """The other direction, and mmmdata has a real case of it.

    A pulse recording with 3769 distinct values holds one for 73 s of a 1210 s
    run — 6%. That is a dropout worth reporting and not a dud, so the verdict
    stays `usable` and `longest_flat_s` carries the finding instead.
    """
    values = _waveform(duration_s=1200.0)
    flat_samples = int(73 * SF)
    values[:flat_samples] = values[0]
    verdict = judge(measure(values, SF, "pulse"))
    assert verdict.verdict == "usable"
    assert verdict.measures.longest_flat_s == pytest.approx(73, abs=1)
    assert verdict.measures.flat_fraction < FLAT_FRACTION_MAX


def test_the_flat_fraction_threshold_sits_in_the_measured_gap():
    """Not a tautology: it pins the empty span the threshold was placed in.

    Everything alive in mmmdata stays at or below 0.060. The lowest of the nine
    files in its declared battery-dead session sits at 0.194. A future edit that
    moves the threshold into either populated region fails here rather than
    silently reclassifying 766 recordings.

    The upper bound is 0.194 and not 0.25 for a reason worth keeping: the first
    version of this rule used 0.2, which cleared the three obvious dead files
    and missed the fourth by three percent. A bound written against the *easy*
    cases would have let that back in.
    """
    assert 0.06 < FLAT_FRACTION_MAX < 0.194


# --------------------------------------------------------------------------
# Reading real files
# --------------------------------------------------------------------------


def test_assess_reads_entities_and_sidecar(tmp_path):
    func = tmp_path / "sub-01" / "ses-02" / "func"
    _write_recording(
        func, "sub-01_ses-02_task-rest_run-03_recording-cardiac", ["cardiac"], _square(1.5)
    )
    result = assess(
        func / "sub-01_ses-02_task-rest_run-03_recording-cardiac_physio.tsv.gz", tmp_path
    )
    assert result.entities == {"sub": "01", "ses": "02", "task": "rest", "run": "03"}
    assert result.recording == "cardiac"
    assert result.sampling_frequency == SF
    assert result.verdict == "trigger-only"
    assert not result.is_usable


def test_na_is_read_as_missing_not_as_a_value(tmp_path):
    """EyeLink writes `n/a` through every blink; it must not become a level."""
    func = tmp_path / "sub-01" / "ses-01" / "func"
    gaze = _waveform(duration_s=60.0)
    gaze[: gaze.size // 4] = np.nan
    _write_recording(func, "sub-01_ses-01_task-movie_recording-eye", ["eye1_x_coordinate"], gaze)
    result = assess(func / "sub-01_ses-01_task-movie_recording-eye_physio.tsv.gz", tmp_path)
    assert result.verdict == "usable"
    assert result.columns[0].measures.na_fraction == pytest.approx(0.25, abs=0.01)


def test_a_recording_is_only_as_good_as_its_worst_physiological_column(tmp_path):
    """Three columns, one dead: the recording is not usable."""
    func = tmp_path / "sub-01" / "ses-01" / "func"
    n = int(60 * SF)
    data = np.column_stack(
        [_waveform(duration_s=60.0), _waveform(duration_s=60.0, seed=2), np.full(n, 512.0)]
    )
    _write_recording(
        func,
        "sub-01_ses-01_task-movie_recording-eye",
        ["eye1_x_coordinate", "eye1_y_coordinate", "eye1_pupil_size"],
        data,
    )
    result = assess(func / "sub-01_ses-01_task-movie_recording-eye_physio.tsv.gz", tmp_path)
    assert result.verdict == "flat"
    assert [c.verdict for c in result.columns] == ["usable", "usable", "flat"]


def test_an_unreadable_file_says_so_rather_than_being_skipped(tmp_path):
    """A parse failure must not land in a clean report as an absence."""
    func = tmp_path / "sub-01" / "ses-01" / "func"
    func.mkdir(parents=True)
    path = func / "sub-01_ses-01_task-rest_recording-cardiac_physio.tsv.gz"
    path.write_bytes(b"not a gzip stream at all")
    result = assess(path, tmp_path)
    assert result.verdict == "unreadable"
    assert result.columns[0].reason


# --------------------------------------------------------------------------
# The artifact
# --------------------------------------------------------------------------


def test_sweep_covers_the_raw_tree_only(tmp_path):
    """Derivatives may hold copies; the acquisition is what is being judged."""
    _write_recording(
        tmp_path / "sub-01" / "ses-01" / "func",
        "sub-01_ses-01_task-rest_recording-pulse",
        ["pulse"],
        _waveform(duration_s=30.0),
    )
    _write_recording(
        tmp_path / "derivatives" / "other" / "sub-01" / "ses-01" / "func",
        "sub-01_ses-01_task-rest_recording-pulse",
        ["pulse"],
        _waveform(duration_s=30.0),
    )
    found = sweep(tmp_path)
    assert len(found) == 1
    assert not found[0].relpath.startswith("derivatives")


def test_the_artifact_stamps_the_rules_it_applied(tmp_path):
    """A threshold that moved silently would make two artifacts incomparable."""
    _write_recording(
        tmp_path / "sub-01" / "ses-01" / "func",
        "sub-01_ses-01_task-rest_recording-cardiac",
        ["cardiac"],
        _square(1.5),
    )
    out = tmp_path / "derivatives" / "duckbrain" / "physio"
    tsv = write_artifact(sweep(tmp_path), out)

    header = tsv.read_text().splitlines()[0].split("\t")
    assert tuple(header) == ARTIFACT_COLUMNS

    sidecar = json.loads((out / "physio_reality.json").read_text())
    assert sidecar["Rules"]["FLAT_FRACTION_MAX"] == FLAT_FRACTION_MAX
    assert sidecar["Rules"]["MACHINE_REGULARITY_MAX"] == MACHINE_REGULARITY_MAX
    assert sidecar["Tally"] == {"trigger-only": 1}
    assert sidecar["GeneratedBy"][0]["Name"] == "duckbrain"


def test_the_artifact_header_is_written_even_when_nothing_was_found(tmp_path):
    """A consumer must never have to guess whether a column is absent or empty."""
    tsv = write_artifact(sweep(tmp_path), tmp_path / "out")
    assert tuple(tsv.read_text().splitlines()[0].split("\t")) == ARTIFACT_COLUMNS
    assert json.loads((tmp_path / "out" / "physio_reality.json").read_text())["Tally"] == {}
