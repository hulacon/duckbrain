"""TODO #16.2 (Slice C): the outcome checks, and duckbrain's first cache.

The L3 layer asks what the tool actually *did* — fMRIPrep's own SDC verdict
read back from its report, NORDIC output compared against its input — where
everything before it asked what was declared or requested. These checks open
reports and image data, so they are ``EXPENSIVE``: never on the cockpit's
render path, run only through ``run_expensive_checks``, persisted to
``<log_dir>/checks.json`` with a fingerprint of the inputs they measured.

Two invariants here replace ``test_no_expensive_check_is_registered_yet``
(Slice A's tripwire, deliberately deleted): expensive checks exist now, and
what is pinned instead is the pair of conditions that made them admissible —
they never run on a plain ``run_checks``, and every one declares the
fingerprint that lets its cached verdict confess to being stale.
"""

import json
import os

import nibabel as nib
import numpy as np

import duckbrain.core.checks as checks
from duckbrain.core.checks import (
    CHEAP,
    EXPENSIVE,
    REGISTRY,
    Check,
    checks_snapshot_path,
    read_checks_snapshot,
    run_checks,
    run_expensive_checks,
    snapshot_is_stale,
)


def _config(root):
    return {
        "paths": {
            "bids_dir": str(root / "bids"),
            "sourcedata_dir": str(root / "sourcedata"),
            "derivatives_dir": str(root / "derivatives"),
            "log_dir": str(root / "code" / "logs"),
        },
        "nordic": {"use_nordic": False},
    }


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _nifti(path, offset=0.0):
    """A tiny real NIfTI whose voxel values are shifted by *offset*."""
    data = (np.arange(24, dtype="float32").reshape(2, 2, 2, 3)) + np.float32(offset)
    path.parent.mkdir(parents=True, exist_ok=True)
    nib.Nifti1Image(data, np.eye(4)).to_filename(str(path))


_SUMMARY = (
    "<ul><li>Slice timing correction: Applied</li>"
    "<li>Susceptibility distortion correction: {sdc}</li></ul>"
)


def _complete_fmriprep_unit(root, subject="01", session="", *, intent=True, sdc="None"):
    """A unit the surveyor grades COMPLETE, whose BOLD sidecar declares (or
    doesn't) fieldmap intent, and whose summary reportlet states *sdc*."""
    ses_dir = f"ses-{session}" if session else ""
    ses_tag = f"_ses-{session}" if session else ""
    func = root / "bids" / f"sub-{subject}" / ses_dir / "func"
    _touch(func / f"sub-{subject}{ses_tag}_task-a_bold.nii.gz")
    sidecar = {"B0FieldSource": "pair1"} if intent else {"PhaseEncodingDirection": "j-"}
    _write_json(func / f"sub-{subject}{ses_tag}_task-a_bold.json", sidecar)

    fp = root / "derivatives" / "fmriprep"
    _touch(fp / f"sub-{subject}.html")
    _touch(fp / f"sub-{subject}" / "anat" / f"sub-{subject}_desc-preproc_T1w.nii.gz")
    out = fp / f"sub-{subject}" / ses_dir / "func"
    _touch(out / f"sub-{subject}{ses_tag}_task-a_desc-preproc_bold.nii.gz")
    _touch(out / f"sub-{subject}{ses_tag}_task-a_desc-confounds_timeseries.tsv")
    if sdc is not None:
        reportlet = f"sub-{subject}{ses_tag}_task-a_desc-summary_bold.html"
        _touch(fp / f"sub-{subject}" / "figures" / reportlet, _SUMMARY.format(sdc=sdc))


def _sdc_issues(config):
    return [i for i in run_checks(config, include_expensive=True) if i.check == "outcome-sdc"]


# ---- outcome-sdc ------------------------------------------------------------


def test_sdc_none_with_declared_intent_is_flagged(tmp_path):
    """The run that motivated #16: sidecars state a fieldmap, the tree grades
    COMPLETE everywhere, and the only trace of no correction is one line in a
    report nobody reads. This reads it."""
    _complete_fmriprep_unit(tmp_path, sdc="None")
    issues = _sdc_issues(_config(tmp_path))
    assert len(issues) == 1
    assert issues[0].subject == "01"
    assert "None" in issues[0].message and "B0FieldSource" in issues[0].message


def test_sdc_applied_is_silent(tmp_path):
    _complete_fmriprep_unit(tmp_path, sdc="PEB/PEPOLAR (phase-encoding based / PE-POLARity)")
    assert _sdc_issues(_config(tmp_path)) == []


def test_no_declared_intent_is_silent(tmp_path):
    """Absent means off, per source: a dataset stating no fieldmap intent
    expects no correction, and `None` in the report is the truth, not a bug."""
    _complete_fmriprep_unit(tmp_path, intent=False, sdc="None")
    assert _sdc_issues(_config(tmp_path)) == []


def test_an_incomplete_unit_is_not_judged(tmp_path):
    """A PARTIAL unit's shortfall already shows on the board, and a running job
    would read `None` for work it hasn't done — the requested-spaces silence."""
    _complete_fmriprep_unit(tmp_path, sdc="None")
    confounds = (
        tmp_path / "derivatives" / "fmriprep" / "sub-01" / "func"
    ) / "sub-01_task-a_desc-confounds_timeseries.tsv"
    confounds.unlink()
    assert _sdc_issues(_config(tmp_path)) == []


def test_a_run_without_a_reportlet_is_silent(tmp_path):
    """No testimony either way — the tool left nothing to read back."""
    _complete_fmriprep_unit(tmp_path, sdc=None)
    assert _sdc_issues(_config(tmp_path)) == []


def test_the_verdict_is_scoped_to_its_session(tmp_path):
    """Reportlets sit at *subject* level in longitudinal trees; the `ses-`
    entity in the filename is what keeps one session's `None` from convicting
    its sibling."""
    _complete_fmriprep_unit(tmp_path, subject="02", session="01", sdc="None")
    _complete_fmriprep_unit(tmp_path, subject="02", session="02", sdc="PEB/PEPOLAR")
    issues = _sdc_issues(_config(tmp_path))
    assert len(issues) == 1
    assert "ses-01" in issues[0].message


# ---- outcome-nordic ---------------------------------------------------------


def _nordic_issues(config):
    return [i for i in run_checks(config, include_expensive=True) if i.check == "outcome-nordic"]


def test_an_identical_nordic_output_is_flagged(tmp_path):
    """Denoising's whole product is a difference; equal data is a run that
    silently did nothing, about to be preprocessed as if it hadn't."""
    _nifti(tmp_path / "bids" / "sub-01" / "func" / "sub-01_task-a_bold.nii.gz")
    _nifti(tmp_path / "derivatives" / "nordic" / "sub-01" / "func" / "sub-01_task-a_bold.nii.gz")
    issues = _nordic_issues(_config(tmp_path))
    assert len(issues) == 1
    assert "identical" in issues[0].message


def test_a_denoised_output_is_silent(tmp_path):
    _nifti(tmp_path / "bids" / "sub-01" / "func" / "sub-01_task-a_bold.nii.gz")
    _nifti(
        tmp_path / "derivatives" / "nordic" / "sub-01" / "func" / "sub-01_task-a_bold.nii.gz",
        offset=0.5,
    )
    assert _nordic_issues(_config(tmp_path)) == []


def test_a_missing_raw_input_is_silent(tmp_path):
    """Presence and counts are the surveyor's job; this only compares content
    where both sides exist."""
    _nifti(tmp_path / "derivatives" / "nordic" / "sub-01" / "func" / "sub-01_task-a_bold.nii.gz")
    assert _nordic_issues(_config(tmp_path)) == []


# ---- the snapshot -----------------------------------------------------------


def test_run_expensive_checks_persists_and_reads_back(tmp_path):
    _complete_fmriprep_unit(tmp_path, sdc="None")
    config = _config(tmp_path)
    snap = run_expensive_checks(config)
    assert [i.check for i in snap.issues] == ["outcome-sdc"]
    assert snap.ran_at and snap.fingerprint

    read = read_checks_snapshot(config)
    assert read is not None
    assert read.ran_at == snap.ran_at
    assert read.fingerprint == snap.fingerprint
    assert [i.message for i in read.issues] == [i.message for i in snap.issues]
    assert read.issues[0].severity == "warning"


def test_the_snapshot_goes_stale_when_an_input_changes(tmp_path):
    """The fingerprint is what makes a cached verdict honest: a re-run, a fixed
    sidecar, or a new run must flip the marker without a re-measure."""
    _complete_fmriprep_unit(tmp_path, sdc="None")
    config = _config(tmp_path)
    snap = run_expensive_checks(config)
    assert not snapshot_is_stale(config, snap)

    sidecar = tmp_path / "bids" / "sub-01" / "func" / "sub-01_task-a_bold.json"
    stat = sidecar.stat()
    os.utime(sidecar, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert snapshot_is_stale(config, snap)


def test_a_deleted_input_also_goes_stale(tmp_path):
    """Deletion can never raise the newest mtime — the file *count* in the
    fingerprint is what catches it."""
    _complete_fmriprep_unit(tmp_path, sdc="None")
    config = _config(tmp_path)
    snap = run_expensive_checks(config)
    (tmp_path / "bids" / "sub-01" / "func" / "sub-01_task-a_bold.json").unlink()
    assert snapshot_is_stale(config, snap)


def test_an_unreadable_snapshot_is_not_measured_yet(tmp_path):
    config = _config(tmp_path)
    assert read_checks_snapshot(config) is None  # absent
    path = checks_snapshot_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert read_checks_snapshot(config) is None  # corrupt
    path.write_text(json.dumps(["wrong", "shape"]))
    assert read_checks_snapshot(config) is None  # valid JSON, wrong shape


# ---- the registry contract --------------------------------------------------


def test_expensive_checks_never_run_on_the_render_path(tmp_path, monkeypatch):
    """The cockpit re-renders every 30 s; a plain `run_checks` must not pay for
    a single expensive measurement, ever."""
    calls = []

    def spy(config):
        calls.append("ran")
        return []

    monkeypatch.setattr(
        checks,
        "REGISTRY",
        (*REGISTRY, Check("spy", EXPENSIVE, spy, lambda config: "0:0")),
    )
    run_checks(_config(tmp_path))
    assert calls == []
    run_checks(_config(tmp_path), include_expensive=True)
    assert calls == ["ran"]


def test_every_expensive_check_declares_a_fingerprint():
    """What replaced Slice A's `no expensive check is registered yet` tripwire:
    the admission condition itself. A cached verdict without a fingerprint
    cannot say when it has gone stale, which is how a state store rots."""
    expensive = [c for c in REGISTRY if c.cost == EXPENSIVE]
    assert expensive, "Slice C registered the outcome family"
    assert all(c.fingerprint is not None for c in expensive)
    assert {c.cost for c in REGISTRY} == {CHEAP, EXPENSIVE}
