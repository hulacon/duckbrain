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


def _config(root, use_nordic=False, containers=None):
    cfg = {"paths": {
        "bids_dir": str(root),
        "sourcedata_dir": str(root / "sourcedata"),
        "derivatives_dir": str(root / "derivatives"),
        "log_dir": str(root / "code" / "logs"),
        "work_dir": "/tmp",
    }}
    if use_nordic:
        cfg["nordic"] = {"use_nordic": True}
    if containers:
        cfg["containers"] = containers
    return cfg


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


# ---- version drift ----------------------------------------------------------

def test_version_drift_flagged(tmp_path):
    _fmriprep_desc(tmp_path, version="24.1.1")
    cfg = _config(tmp_path, containers={"fmriprep_version": "25.0.0"})
    issues = check_consistency(cfg)
    assert "version-drift" in _codes(issues)


def test_version_match_is_clean(tmp_path):
    _fmriprep_desc(tmp_path, version="24.1.1")
    cfg = _config(tmp_path, containers={"fmriprep_version": "24.1.1"})
    assert "version-drift" not in _codes(check_consistency(cfg))


# ---- mixed provenance / version (log overlay) -------------------------------

def test_mixed_input_variant_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" in _codes(check_consistency(cfg))


def test_latest_run_supersedes_so_uniform_rerun_is_clean(tmp_path):
    cfg = _config(tmp_path)
    # sub-01 first ran raw, then re-ran nordic; sub-02 ran nordic. Latest is
    # uniformly nordic, so no mixing.
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", input_variant="raw")
    record_submission(cfg, "fmriprep", "01", "", "J2", tool="fmriprep", input_variant="nordic")
    record_submission(cfg, "fmriprep", "02", "", "J3", tool="fmriprep", input_variant="nordic")
    assert "mixed-provenance" not in _codes(check_consistency(cfg))


def test_mixed_tool_version_across_subjects_flagged(tmp_path):
    cfg = _config(tmp_path)
    record_submission(cfg, "fmriprep", "01", "", "J1", tool="fmriprep", tool_version="24.1.1")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep", tool_version="25.0.0")
    assert "mixed-version" in _codes(check_consistency(cfg))


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
