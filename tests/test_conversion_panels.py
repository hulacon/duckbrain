"""The Conversion page's probe cache and its "didn't run" reporting.

Driven directly rather than through ``AppTest``: these are the decisions the
page delegates, and a page is a script no test imports.
"""

from __future__ import annotations

from pathlib import Path

from duckbrain.core.dcm2niix_probe import ProbeResult, ProbeRuntime, SeriesProbe
from duckbrain.core.dicom_inspect import SeriesInfo
from duckbrain.gui.conversion_panels import probe_fingerprint, probe_note, session_probes


def _series(num, n=300, root="/nonexistent"):
    return SeriesInfo(
        series_number=num,
        description="thing",
        path=Path(root) / f"Series_{num:02d}_thing",
        file_count=n,
    )


# ---- the cache key ----


def test_the_fingerprint_costs_no_filesystem_walk():
    """An rglob of a session dir stats ~2000 files on GPFS — more than the probe.

    Pinned by pointing every series at a path that does not exist: a fingerprint
    that read the DICOMs could not be computed at all.
    """
    assert probe_fingerprint([_series(3), _series(4)], None)


def test_the_fingerprint_moves_when_a_series_gains_files():
    """A re-ingested session must re-probe rather than serve the old answer."""
    before = probe_fingerprint([_series(3, n=3), _series(4, n=3)], None)
    after = probe_fingerprint([_series(3, n=3), _series(4, n=4)], None)
    assert before != after


def test_the_fingerprint_ignores_the_order_the_series_arrive_in():
    """Same session, same answer — `list_series` order is not an input."""
    assert probe_fingerprint([_series(3), _series(4)], None) == probe_fingerprint(
        [_series(4), _series(3)], None
    )


def test_the_fingerprint_survives_an_image_that_vanished(tmp_path):
    """`probe_runtime` checked the .sif existed; this runs after that.

    A rebuild or a purge in between must not raise out of a page render — the
    key just degrades to one that cannot match a real image's.
    """
    assert probe_fingerprint([_series(3)], tmp_path / "gone.sif")


def test_the_fingerprint_moves_when_the_image_is_rebuilt(tmp_path):
    """A rebuilt .sif at the same path is a different dcm2niix.

    Same reason ``core.containers`` keys its provenance cache on
    ``(path, mtime, size)``.
    """
    sif = tmp_path / "dcm2bids-3.2.0.sif"
    sif.write_bytes(b"one")
    before = probe_fingerprint([_series(3)], sif)

    sif.write_bytes(b"a longer build entirely")
    assert probe_fingerprint([_series(3)], sif) != before


# ---- reporting what happened ----


def test_no_probing_happens_when_the_runtime_cannot_run(monkeypatch):
    """Not even a subprocess attempt: the caller already knows the answer."""
    import duckbrain.gui.conversion_panels as panels

    def _boom(*a, **kw):
        raise AssertionError("probe_session must not be called")

    monkeypatch.setattr(panels.dcm2niix_probe, "probe_session", _boom)
    result = session_probes([_series(3)], ProbeRuntime(reason="nothing on PATH"))
    assert result.probes == {}
    # Carried into the result, because this is the one failure the probe itself
    # can never report — it is never called.
    assert result.failure == "nothing on PATH"


def test_a_session_with_no_readable_series_directories_probes_nothing(monkeypatch):
    """`SeriesInfo.path` is None wherever a series was described but not walked."""
    import duckbrain.gui.conversion_panels as panels

    def _boom(*a, **kw):
        raise AssertionError("probe_session must not be called")

    monkeypatch.setattr(panels.dcm2niix_probe, "probe_session", _boom)
    pathless = SeriesInfo(series_number=3, description="thing", path=None, file_count=3)
    result = session_probes([pathless], ProbeRuntime(container=Path("/x.sif")))
    assert result.probes == {}
    # Nothing failed here: there was simply nothing to hand dcm2niix.
    assert result.ok


def _read(*numbers):
    return ProbeResult(probes={f"Series_{n}": SeriesProbe(n) for n in numbers})


def test_a_probe_that_could_not_run_is_reported_as_unchecked():
    runtime = ProbeRuntime(reason="dcm2niix is not on PATH")
    note = probe_note(runtime, ProbeResult(failure=runtime.reason))
    assert "not checked" in note
    assert "dcm2niix is not on PATH" in note


def test_a_probe_that_ran_and_failed_says_why_rather_than_reading_as_empty():
    """The other way to be unable to look: available runtime, non-zero exit.

    Before, this rendered the same "dcm2niix ran but read none of these series"
    a genuinely empty session gets — a sentence that is *false* here and names
    nothing anyone could act on.
    """
    note = probe_note(
        ProbeRuntime(container=Path("/x.sif")),
        ProbeResult(failure="dcm2niix exited 1: No module named 'dcm2niix'"),
    )
    assert "not checked" in note
    assert "exited 1" in note
    assert "read none of these series" not in note


def test_a_run_that_read_something_and_then_failed_is_still_unchecked():
    """Partial is not checked. The caveat outranks the fallback note below it."""
    result = ProbeResult(probes=_read(3).probes, failure="dcm2niix exited 2")
    note = probe_note(ProbeRuntime(fallback="container image not found: /x.sif"), result)
    assert "not checked" in note
    assert "exited 2" in note


def test_an_available_runtime_that_read_nothing_still_reads_as_unchecked():
    """A completed probe can still have read nothing — empty directories.

    Gating the panel on runtime availability rather than on the probes would
    print the green tick after a probe that read nothing.
    """
    note = probe_note(ProbeRuntime(container=Path("/x.sif")), ProbeResult())
    assert "not checked" in note
    assert "read none of these series" in note


def test_a_host_fallback_says_it_may_not_be_the_build_that_converts():
    runtime = ProbeRuntime(fallback="container image not found: /x.sif")
    note = probe_note(runtime, _read(3))
    assert "host" in note
    assert "build that converts" in note


def test_a_probe_through_the_pinned_image_adds_no_caveat():
    """Silence is the signal here — the success message already says it ran."""
    assert probe_note(ProbeRuntime(container=Path("/x.sif")), _read(3)) == ""
