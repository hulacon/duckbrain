"""Provenance consistency checker (Phase B).

On-disk provenance is authoritative; the submission log is an overlay that only
adds cross-subject mixing. These lock in each check and, importantly, that
externally-produced derivatives (with on-disk provenance but no log rows) are
never flagged just for lacking a log row.
"""

import json

from duckbrain.core.consistency import (
    ConsistencyIssue,
    check_consistency,
    read_derivative_provenance,
)
from duckbrain.core.bids_metadata import write_derivative_description
from duckbrain.core.pipeline import record_submission


def _config(root, use_nordic=False, containers=None, containers_dir=None):
    cfg = {"paths": {
        "bids_dir": str(root),
        "sourcedata_dir": str(root / "sourcedata"),
        "derivatives_dir": str(root / "derivatives"),
        "log_dir": str(root / "code" / "logs"),
        "work_dir": "/tmp",
    }}
    if containers_dir:
        cfg["paths"]["containers_dir"] = containers_dir
    if use_nordic:
        cfg["nordic"] = {"use_nordic": True}
    if containers:
        cfg["containers"] = containers
    return cfg


def _containers(root, *images):
    """A containers dir holding *images*, so get_container_path resolves them."""
    d = root / "containers"
    d.mkdir(parents=True, exist_ok=True)
    for image in images:
        (d / image).write_text("img")
    return str(d)


def _fmriprep_unit(root, sub):
    """Make sub-*sub* read as having real fMRIPrep output on disk.

    Anat-only (no func in the BIDS unit), which is what the fMRIPrep tracker
    needs to grade the unit complete — the same shape the presence test uses.
    """
    fp = root / "derivatives" / "fmriprep"
    (fp / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)
    (fp / f"sub-{sub}.html").write_text("report")
    (fp / f"sub-{sub}" / "anat" / f"sub-{sub}_desc-preproc_T1w.nii.gz").write_text("x")
    (root / f"sub-{sub}" / "anat").mkdir(parents=True, exist_ok=True)


def _fmriprep_desc(root, *, raw_link=None, version="24.1.1"):
    """Write a fMRIPrep-style dataset_description.json (as fMRIPrep itself would)."""
    deriv = root / "derivatives" / "fmriprep"
    deriv.mkdir(parents=True, exist_ok=True)
    desc = {
        "Name": "fMRIPrep - fMRI PREProcessing workflow",
        "BIDSVersion": "1.9.0",
        "DatasetType": "derivative",
        "GeneratedBy": [{"Name": "fMRIPrep", "Version": version}],
    }
    if raw_link is not None:
        desc["DatasetLinks"] = {"raw": raw_link}
    (deriv / "dataset_description.json").write_text(json.dumps(desc))
    return deriv


def _codes(issues):
    return {i.check for i in issues}


# ---- reader -----------------------------------------------------------------

def test_read_derivative_provenance_parses_generatedby_and_link(tmp_path):
    _fmriprep_desc(tmp_path, raw_link="/proj/derivatives/nordic/bids_format")
    prov = read_derivative_provenance(_config(tmp_path), "fmriprep")
    assert prov.exists
    assert prov.tool_version("fMRIPrep") == "24.1.1"
    assert prov.tool_version("fmriprep") == "24.1.1"  # case-insensitive
    assert prov.raw_link.endswith("nordic/bids_format")


def test_read_derivative_provenance_absent(tmp_path):
    prov = read_derivative_provenance(_config(tmp_path), "fmriprep")
    assert not prov.exists
    assert prov.generated_by == []


# ---- config vs provenance ---------------------------------------------------

def test_use_nordic_but_fmriprep_from_raw_flags(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path))  # raw = project root, not nordic
    issues = check_consistency(_config(tmp_path, use_nordic=True))
    assert "config-vs-provenance" in _codes(issues)


def test_not_use_nordic_but_fmriprep_from_nordic_flags(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path / "derivatives" / "nordic" / "bids_format"))
    issues = check_consistency(_config(tmp_path, use_nordic=False))
    assert "config-vs-provenance" in _codes(issues)


def test_use_nordic_and_fmriprep_from_nordic_is_clean(tmp_path):
    _fmriprep_desc(tmp_path, raw_link=str(tmp_path / "derivatives" / "nordic" / "bids_format"))
    issues = check_consistency(_config(tmp_path, use_nordic=True))
    assert "config-vs-provenance" not in _codes(issues)


def test_external_fmriprep_without_link_not_flagged(tmp_path):
    # An externally-run fMRIPrep with provenance but no DatasetLinks and no log
    # rows must not trip config-vs-provenance or mixed-provenance.
    _fmriprep_desc(tmp_path, raw_link=None)
    issues = check_consistency(_config(tmp_path, use_nordic=False))
    assert issues == []


# ---- container drift --------------------------------------------------------

def test_container_drift_flagged_when_pin_bumped_without_rerun(tmp_path):
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "25.0.0"},
        containers_dir=_containers(tmp_path, "fmriprep-25.0.0.simg"),
    )
    record_submission(cfg, "fmriprep", "01", "", "J1",
                      tool="fmriprep", container="fmriprep-24.1.1.simg")
    assert "container-drift" in _codes(check_consistency(cfg))


def test_matching_container_is_clean(tmp_path):
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    record_submission(cfg, "fmriprep", "01", "", "J1",
                      tool="fmriprep", container="fmriprep-24.1.1.simg")
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_container_tag_differing_from_self_reported_version_is_clean(tmp_path):
    """Regression (real data, 2026-07-16): a container tag and the tool's own
    version legitimately differ — ``mriqc-24.0.2.simg`` self-reports
    ``24.1.0.dev0+gd5b13cb5.d20240826``. That must not read as drift.
    """
    _fmriprep_desc(tmp_path, version="24.1.0.dev0+gd5b13cb5.d20240826")
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.0.2"},
        containers_dir=_containers(tmp_path, "fmriprep-24.0.2.simg"),
    )
    record_submission(cfg, "fmriprep", "01", "", "J1",
                      tool="fmriprep", container="fmriprep-24.0.2.simg")
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_on_disk_container_tag_beats_log_overlay(tmp_path):
    """On-disk provenance is authoritative: a duckbrain-stamped Container.Tag
    decides, even when the log's container disagrees."""
    deriv = tmp_path / "derivatives" / "fmriprep"
    write_derivative_description(
        deriv, "fmriprep", tool="fMRIPrep", tool_version="24.1.1",
        container="fmriprep-24.1.1.simg",
    )
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "24.1.1"},
        containers_dir=_containers(tmp_path, "fmriprep-24.1.1.simg"),
    )
    # Log claims a different container; on-disk agrees with config, so: clean.
    record_submission(cfg, "fmriprep", "01", "", "J1",
                      tool="fmriprep", container="fmriprep-99.9.9.simg")
    assert "container-drift" not in _codes(check_consistency(cfg))


def test_external_derivative_without_recorded_container_never_flagged(tmp_path):
    """No Container.Tag and no log rows — an externally-produced derivative.
    Unknowable provenance must degrade to silence, not a warning."""
    _fmriprep_desc(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    cfg = _config(
        tmp_path,
        containers={"fmriprep_version": "25.0.0"},
        containers_dir=_containers(tmp_path, "fmriprep-25.0.0.simg"),
    )
    assert "container-drift" not in _codes(check_consistency(cfg))


# ---- mixed provenance / version (log overlay) -------------------------------

def test_mixed_input_variant_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" in _codes(check_consistency(cfg))


def test_latest_run_supersedes_so_uniform_rerun_is_clean(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    # sub-01 first ran raw, then re-ran nordic; sub-02 ran nordic. Latest is
    # uniformly nordic, so no mixing.
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "01", "", "J2", tool="fmriprep", input_variant="nordic")
    record_submission(cfg, "fmriprep", "02", "", "J3", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" not in _codes(check_consistency(cfg))


def test_mixed_tool_version_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")
    _fmriprep_unit(tmp_path, "02")
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", tool_version="24.1.1")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", tool_version="25.0.0")
    assert "mixed-version" in _codes(check_consistency(cfg))


def test_submission_without_output_on_disk_contributes_no_provenance(tmp_path):
    """The log tracks submissions; the files record what was produced. A run that
    was cancelled (or deleted, or is still in flight) leaves a log row but no
    output — it must not claim provenance for a subject the derivative lacks.

    Real case (2026-07-16): divatten_gui_beta's only fMRIPrep log row is sub-008,
    a NORDIC-chained run that was cancelled and its partial output removed.
    """
    cfg = _config(tmp_path)
    _fmriprep_unit(tmp_path, "01")  # only sub-01 actually has output
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" not in _codes(check_consistency(cfg))


# ---- staleness --------------------------------------------------------------

def test_nordic_newer_than_fmriprep_flags_staleness(tmp_path):
    import os
    cfg = _config(tmp_path, use_nordic=True)
    deriv = tmp_path / "derivatives"
    fp = deriv / "fmriprep" / "sub-01" / "func"
    nd = deriv / "nordic" / "sub-01" / "func"
    fp.mkdir(parents=True)
    nd.mkdir(parents=True)
    fp_bold = fp / "sub-01_task-x_desc-preproc_bold.nii.gz"
    nd_bold = nd / "sub-01_task-x_bold.nii.gz"
    fp_bold.write_text("x")
    nd_bold.write_text("x")
    # Force NORDIC output to be newer than the fMRIPrep output.
    os.utime(fp_bold, (1000, 1000))
    os.utime(nd_bold, (2000, 2000))
    assert "staleness" in _codes(check_consistency(cfg))


# ---- presence ---------------------------------------------------------------

def test_presence_fmriprep_without_nordic_in_nordic_project(tmp_path):
    cfg = _config(tmp_path, use_nordic=True)
    # A complete-looking fMRIPrep unit, no NORDIC output, no func in BIDS so the
    # fMRIPrep tracker is satisfied by the anat+html markers.
    fp = tmp_path / "derivatives" / "fmriprep"
    (fp / "sub-01" / "anat").mkdir(parents=True)
    (fp / "sub-01.html").write_text("report")
    (fp / "sub-01" / "anat" / "sub-01_desc-preproc_T1w.nii.gz").write_text("x")
    (tmp_path / "sub-01" / "anat").mkdir(parents=True)  # BIDS unit exists, anat-only
    issues = check_consistency(cfg)
    assert "presence" in _codes(issues)
    assert any(i.subject == "01" for i in issues if i.check == "presence")


# ---- clean project ----------------------------------------------------------

def test_clean_project_has_no_issues(tmp_path):
    assert check_consistency(_config(tmp_path)) == []


def test_consistency_issue_is_frozen_dataclass():
    i = ConsistencyIssue("presence", "msg", subject="01")
    assert i.severity == "warning"
    assert (i.check, i.subject) == ("presence", "01")
