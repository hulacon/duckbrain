"""The dcm2niix probe, and the plan-time phase-encoding checks it enables.

The probe shells out, so these tests split in two: the parsing and mapping logic
is exercised against synthetic sidecars with no dcm2niix at all, and a single
guarded test runs the real binary when one is present. That split is the point —
the plan checks have to keep working on a machine with no dcm2niix, and "no
probe" has to read as "not checked" rather than "checked and clean".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from duckbrain.core.dcm2niix_probe import (
    PE_FOR_DIR,
    ProbeResult,
    SeriesProbe,
    by_series_number,
    probe_runtime,
    probe_session,
    probe_unavailable_reason,
)

# ---- the probe itself ----


def test_pe_axis_strips_the_sign():
    assert SeriesProbe(phase_encoding_direction="j-").pe_axis == "j"
    assert SeriesProbe(phase_encoding_direction="j").pe_axis == "j"
    assert SeriesProbe().pe_axis == ""


def test_by_series_number_drops_probes_with_no_number():
    """A ``None`` key is worse than a missing one — nothing can look it up."""
    probes = {
        "Series_7_fieldmap": SeriesProbe(series_number=7),
        "Series_x_broken": SeriesProbe(series_number=None),
    }
    assert set(by_series_number(probes)) == {7}


def test_probe_reports_why_it_cannot_run(tmp_path, monkeypatch):
    """Absence must be *reportable*. A silent empty result reads as 'all clear'."""
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert "not on PATH" in probe_unavailable_reason()
    assert "not found" in probe_unavailable_reason(tmp_path / "missing.sif")


def test_probe_returns_nothing_when_dcm2niix_is_absent(tmp_path, monkeypatch):
    series = tmp_path / "Series_1_thing"
    series.mkdir()
    (series / "0001.dcm").write_bytes(b"not really a dicom")
    monkeypatch.setattr("shutil.which", lambda _: None)

    result = probe_session([series])
    assert result.probes == {}
    # Not merely empty — the caller is told, without having to know to ask
    # something else first.
    assert "not on PATH" in result.failure


def test_probe_never_raises_on_an_empty_series_directory(tmp_path, monkeypatch):
    """0.43% of the LCNI corpus is empty directories; they are a miss, not a crash.

    And a *miss* is what they are: ``ok`` stays true, because "dcm2niix had
    nothing to read here" is a real answer about this session and not a report
    that duckbrain couldn't look.

    ``which`` is pinned because that distinction only exists when there *is* a
    dcm2niix. With none, ``probe_unavailable_reason`` fires first and "couldn't
    look" is the honest answer — the branch this test is about is never reached.
    Left reading the ambient PATH it asserted about whichever machine ran it:
    green on Talapas, where dcm2niix is installed, red on CI, where it is not.
    """
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/dcm2niix")
    empty = tmp_path / "Series_1_empty"
    empty.mkdir()
    assert probe_session([empty]) == ProbeResult()
    assert probe_session([]) == ProbeResult()
    assert probe_session([empty]).ok


# ---- a run that did not complete ----
#
# Found 2026-08-20: `probe_unavailable_reason` says whether dcm2niix
# *exists*, not whether it *works*, and everything below is the gap between
# those two questions. Every one of these used to return the same bare `{}` a
# session of empty directories returns, so the conversion plan silently lost the
# only two fields the probe supplies — signed phase encoding and ShimSetting.


def _fake_dcm2niix(monkeypatch, returncode, stderr="", sidecars=()):
    """A dcm2niix that writes *sidecars* and then exits *returncode*."""
    import subprocess

    from duckbrain.core import dcm2niix_probe

    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        for name, payload in sidecars:
            (out / name).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)

    monkeypatch.setattr(dcm2niix_probe.shutil, "which", lambda _: "/usr/bin/dcm2niix")
    monkeypatch.setattr(dcm2niix_probe.subprocess, "run", fake_run)
    return dcm2niix_probe


def _one_series(tmp_path, name="Series_8_fieldmap1"):
    series = tmp_path / name
    series.mkdir()
    (series / "0001.dcm").write_bytes(b"x")
    return series


def test_a_non_zero_exit_is_not_the_same_answer_as_an_empty_session(tmp_path, monkeypatch):
    """The exact case that found this, reproduced.

    ``dcm2niix`` on the dev box is a pip console-script shim whose first line is
    ``from dcm2niix import main``; running the suite with ``PYTHONNOUSERSITE=1``
    (which ``memory/pythonnousersite-for-test-runs`` recommends, for good
    reasons) makes that module unimportable and the process exit 1. So
    availability was real and usability was not — and the empty map that came
    back was indistinguishable from a session whose series all legitimately
    yield nothing.
    """
    shim_traceback = (
        "Traceback (most recent call last):\n"
        '  File "/home/bhutch/.local/bin/dcm2niix", line 5, in <module>\n'
        "    from dcm2niix import main\n"
        "ModuleNotFoundError: No module named 'dcm2niix'\n"
    )
    probe = _fake_dcm2niix(monkeypatch, 1, stderr=shim_traceback)

    result = probe.probe_session([_one_series(tmp_path)])
    assert not result.ok
    assert "exited 1" in result.failure
    # The last line, not the whole traceback: this renders in a caption.
    assert "No module named 'dcm2niix'" in result.failure
    assert "Traceback" not in result.failure


def test_a_failed_run_that_read_something_reports_both(tmp_path, monkeypatch):
    """dcm2niix can write sidecars and *then* fail, so this is not either/or.

    Discarding the partial read would throw away real answers; reporting only
    the partial read would claim the session was fully checked. Both, and the
    caller decides.
    """
    probe = _fake_dcm2niix(
        monkeypatch,
        2,
        stderr="Error: Check sorted order\n",
        sidecars=[("Series_8_fieldmap1.json", {"SeriesNumber": 8, "PhaseEncodingDirection": "j-"})],
    )

    result = probe.probe_session([_one_series(tmp_path)])
    assert result.by_number[8].phase_encoding_direction == "j-"
    assert not result.ok
    assert "Check sorted order" in result.failure


def test_a_silent_non_zero_exit_still_names_the_code(tmp_path, monkeypatch):
    """Nothing on either stream is no excuse for saying nothing."""
    probe = _fake_dcm2niix(monkeypatch, 9)

    result = probe.probe_session([_one_series(tmp_path)])
    assert result.failure == "dcm2niix exited 9"


def test_a_timeout_says_what_the_budget_was(tmp_path, monkeypatch):
    """The page probes with 10 s, the module with 120 — 'timed out' alone is not enough."""
    import subprocess

    from duckbrain.core import dcm2niix_probe

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(dcm2niix_probe.shutil, "which", lambda _: "/usr/bin/dcm2niix")
    monkeypatch.setattr(dcm2niix_probe.subprocess, "run", fake_run)

    result = dcm2niix_probe.probe_session([_one_series(tmp_path)], timeout_s=10)
    assert "did not finish within 10s" in result.failure


def test_a_dcm2niix_that_cannot_be_executed_reports_the_os_error(tmp_path, monkeypatch):
    """`which` found it; exec is where a broken interpreter line or a mode bit shows up."""
    from duckbrain.core import dcm2niix_probe

    def fake_run(cmd, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(dcm2niix_probe.shutil, "which", lambda _: "/usr/bin/dcm2niix")
    monkeypatch.setattr(dcm2niix_probe.subprocess, "run", fake_run)

    result = dcm2niix_probe.probe_session([_one_series(tmp_path)])
    assert not result.ok
    assert "Permission denied" in result.failure


# ---- which dcm2niix would run ----
#
# Every one of these pins ``shutil.which`` and the container path. Left to the
# machine they would assert a property of it: the Talapas dev box has apptainer
# on PATH and a real containers_dir, the GitHub runners have neither, so the
# same test would take a different branch on each. See
# ``memory/local-tests-are-not-ci-tests``.


def _which(*present):
    return lambda name: f"/usr/bin/{name}" if name in present else None


def test_probe_runtime_prefers_the_pinned_image(tmp_path, monkeypatch):
    """The image holds the build that will convert; a host binary may not."""
    sif = tmp_path / "dcm2bids-3.2.0.sif"
    sif.write_bytes(b"")
    monkeypatch.setattr("shutil.which", _which("apptainer", "dcm2niix"))

    runtime = probe_runtime(sif)
    assert runtime.available
    assert runtime.container == sif
    assert runtime.fallback == ""


def test_probe_runtime_falls_back_to_a_host_dcm2niix_and_says_so(tmp_path, monkeypatch):
    """Falling back is fine; falling back silently is not."""
    monkeypatch.setattr("shutil.which", _which("dcm2niix"))

    runtime = probe_runtime(tmp_path / "missing.sif")
    assert runtime.available
    assert runtime.container is None
    assert "container image not found" in runtime.fallback


def test_probe_runtime_names_both_reasons_when_nothing_can_run(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)

    runtime = probe_runtime(tmp_path / "missing.sif")
    assert not runtime.available
    assert "container image not found" in runtime.reason
    assert "not on PATH" in runtime.reason


def test_probe_runtime_with_no_container_asks_only_about_the_host(monkeypatch):
    """No phantom 'container not found' for a project that never named one."""
    monkeypatch.setattr("shutil.which", lambda _: None)

    runtime = probe_runtime(None)
    assert not runtime.available
    assert "container" not in runtime.reason.replace("no container was given", "")
    assert runtime.fallback == ""


# ---- the plan-time checks, driven by synthetic probes ----


def _probes(**by_number):
    return {int(n): p for n, p in by_number.items()}


def test_a_pepolar_pair_encoded_the_same_way_is_an_error():
    """Two halves with one direction estimate nothing, and dcm2bids won't notice."""
    from duckbrain.core.conversion_plan import plan_warnings
    from test_conversion_plan import _bold, _plan, _series

    series = [
        _series(5, "se_epi_fieldmap_ap", n=3),
        _series(6, "se_epi_fieldmap_pa", n=3),
        _bold(9, "food", 1),
    ]
    plan, fieldmaps = _plan(series)
    # The scanner ran both halves anterior->posterior despite the naming.
    probes = _probes(
        **{
            "5": SeriesProbe(series_number=5, phase_encoding_direction="j-"),
            "6": SeriesProbe(series_number=6, phase_encoding_direction="j-"),
        }
    )
    warnings = plan_warnings(plan, fieldmaps, probes=probes)

    collinear = [w for w in warnings if w.kind == "pe-collinear"]
    assert len(collinear) == 1
    assert collinear[0].severity == "error"
    assert collinear[0].series == [5, 6]


def test_an_opposing_pair_raises_nothing():
    from duckbrain.core.conversion_plan import plan_warnings
    from test_conversion_plan import _bold, _plan, _series

    series = [
        _series(5, "se_epi_fieldmap_ap", n=3),
        _series(6, "se_epi_fieldmap_pa", n=3),
        _bold(9, "food", 1),
    ]
    plan, fieldmaps = _plan(series)
    probes = _probes(
        **{
            "5": SeriesProbe(series_number=5, phase_encoding_direction=PE_FOR_DIR["AP"]),
            "6": SeriesProbe(series_number=6, phase_encoding_direction=PE_FOR_DIR["PA"]),
        }
    )
    warnings = plan_warnings(plan, fieldmaps, probes=probes)
    assert not [w for w in warnings if w.kind in ("pe-collinear", "pe-direction")]


def test_a_dir_label_contradicting_the_scanner_is_reported():
    """The ``_ap``/``_pa`` token is the *only* thing duckbrain has; check it."""
    from duckbrain.core.conversion_plan import plan_warnings
    from test_conversion_plan import _bold, _plan, _series

    series = [
        _series(5, "se_epi_fieldmap_ap", n=3),
        _series(6, "se_epi_fieldmap_pa", n=3),
        _bold(9, "food", 1),
    ]
    plan, fieldmaps = _plan(series)
    # Named _ap but acquired posterior->anterior: the halves still oppose, so
    # only the label check can catch this one.
    probes = _probes(
        **{
            "5": SeriesProbe(series_number=5, phase_encoding_direction="j"),
            "6": SeriesProbe(series_number=6, phase_encoding_direction="j-"),
        }
    )
    warnings = plan_warnings(plan, fieldmaps, probes=probes)

    mismatches = [w for w in warnings if w.kind == "pe-direction"]
    assert len(mismatches) == 2
    assert all(w.severity == "warning" for w in mismatches)


def test_a_gradient_echo_group_is_not_read_as_a_pepolar_pair():
    """A GRE magnitude and its phasediff share a direction *by construction*.

    They are two reconstructions of one acquisition, so they cannot oppose and
    asking whether they do can only produce a false error. Before ``_fmap_halves``
    filtered on ``suffix == "epi"`` this raised ``pe-collinear`` — an *error*,
    which on the bulk path refuses the conversion outright — for every
    gradient-echo session. ``"i"`` is the value the LCNI corpus's canonical BIDS
    actually carries for both halves.
    """
    from duckbrain.core import dcm2bids_config, dicom_inspect
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings
    from test_series_classification import _gre_session

    series = _gre_session()
    detection = dicom_inspect.detect_fieldmaps(series)
    config = dcm2bids_config.generate_config(series, detection, subject="CC052", session="1")
    plan = plan_conversion(config, series, subject="CC052", session="1")
    probes = _probes(
        **{
            "5": SeriesProbe(series_number=5, phase_encoding_direction="i"),
            "6": SeriesProbe(series_number=6, phase_encoding_direction="i"),
        }
    )

    warnings = plan_warnings(plan, detection, probes=probes)
    assert not [w for w in warnings if w.kind == "pe-collinear"]
    # Free regression pin: the GRE trio carries no ``dir-`` entity, so the label
    # check has nothing to compare and must stay silent too.
    assert not [w for w in warnings if w.kind == "pe-direction"]


def test_no_probes_means_the_pe_checks_are_skipped_not_passed():
    """The checks must be absent without a probe, not silently satisfied."""
    from duckbrain.core.conversion_plan import plan_warnings
    from test_conversion_plan import _bold, _plan, _series

    series = [
        _series(5, "se_epi_fieldmap_ap", n=3),
        _series(6, "se_epi_fieldmap_pa", n=3),
        _bold(9, "food", 1),
    ]
    plan, fieldmaps = _plan(series)
    assert not [
        w for w in plan_warnings(plan, fieldmaps) if w.kind in ("pe-collinear", "pe-direction")
    ]


def test_the_plan_and_post_conversion_checks_share_one_convention():
    """Two copies of this table would let a plan pass preflight and fail after."""
    from duckbrain.core.consistency import _PE_FOR_DIR

    assert _PE_FOR_DIR is PE_FOR_DIR


def test_the_table_covers_the_four_directions_duckbrain_labels():
    """The RL/LR rows are *measured*, not derived — R→L phase encoding is −x,
    which would imply `i-`, yet both /projects/hulacon/shared/mmmsourcedata and
    the LCNI corpus's `Round_Robin` diffusion read `rl`→`i`. Two agreeing sites is
    the whole basis for these two values, so they are worth spelling out where a
    future edit will see the claim."""
    assert PE_FOR_DIR == {"AP": "j-", "PA": "j", "RL": "i", "LR": "i-"}


# ---- against the real binary, when there is one ----


@pytest.mark.skipif(probe_unavailable_reason() != "", reason="no dcm2niix on PATH to probe with")
def test_probe_reads_a_real_dicom_when_dcm2niix_is_available(tmp_path):
    """One file per series is enough for the fields the plan checks read.

    Uses the LCNI repository when it is mounted; skips rather than fails
    elsewhere, since the corpus is Talapas-only and read-only.
    """
    corpus = Path("/projects/lcni/dcm/repository/dicoms/REV/REV055_20150811_135636")
    if not corpus.is_dir():
        pytest.skip("LCNI repository corpus not mounted")

    series_dirs = sorted(p for p in corpus.iterdir() if p.is_dir())
    result = probe_session(series_dirs)
    # The guard above asks whether dcm2niix *exists*; this asks whether it
    # works, which is the distinction that matters here. On this dev box the two
    # disagree — `dcm2niix` on PATH is a pip console-script shim that
    # PYTHONNOUSERSITE=1 makes unimportable — and a machine whose dcm2niix
    # cannot run is a machine this test has nothing to say about.
    if not result.ok:
        pytest.skip(f"dcm2niix on PATH could not run: {result.failure}")
    probes = result.by_number

    # The BOLD runs: signed phase encoding, which no raw tag carries.
    assert probes[9].phase_encoding_direction == "j-"
    assert probes[9].multiband_factor == 3
    # ShimSetting, which pydicom cannot reach — it lives in the CSA ASCCONV blob.
    assert len(probes[9].shim_setting) == 8
    # And the finding that settled TODO #19.3: both fieldmap pairs in this
    # session share one shim, so shim cannot tell them apart. If this ever
    # fails, the acquisition-time binding rationale needs revisiting.
    assert probes[7].shim_setting == probes[13].shim_setting


def test_sidecar_suffixes_still_map_back_to_their_series(tmp_path, monkeypatch):
    """dcm2niix appends ``_e2_ph`` to a phase image; equality matching drops it.

    That would silently exclude exactly the gradient-echo fieldmaps the checks
    exist to look at, so the mapping is longest-prefix rather than equality.
    """
    from duckbrain.core import dcm2niix_probe

    series = tmp_path / "Series_8_fieldmap1"
    series.mkdir()
    (series / "0001.dcm").write_bytes(b"x")

    def fake_run(cmd, **kwargs):
        out = Path(cmd[cmd.index("-o") + 1])
        (out / "Series_8_fieldmap1_e2_ph.json").write_text(
            json.dumps({"SeriesNumber": 8, "PhaseEncodingDirection": "i", "ImageType": ["P"]})
        )

        class Done:
            returncode = 0

        return Done()

    monkeypatch.setattr(dcm2niix_probe.shutil, "which", lambda _: "/usr/bin/dcm2niix")
    monkeypatch.setattr(dcm2niix_probe.subprocess, "run", fake_run)

    result = dcm2niix_probe.probe_session([series])
    assert set(result.probes) == {"Series_8_fieldmap1"}
    assert result.probes["Series_8_fieldmap1"].phase_encoding_direction == "i"
    assert result.ok
