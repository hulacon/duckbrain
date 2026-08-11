"""Requested fMRIPrep output spaces versus written — the request record's first
consumer (`docs/sanity-checks.md`, Slice B).

The gap this closes: ``surveyor._entity_key`` strips ``space-``/``res-``/
``den-`` when grading — deliberately — so a run that quietly dropped a requested
space reads COMPLETE everywhere. Only the request record states the ask; the
``requested-spaces`` check reads it back and compares.
"""

import json

from duckbrain.core.checks import run_checks
from duckbrain.core.pipeline import record_request, record_submission


def _config(root):
    return {
        "paths": {
            "bids_dir": str(root / "bids"),
            "sourcedata_dir": str(root / "sourcedata"),
            "derivatives_dir": str(root / "derivatives"),
            "log_dir": str(root / "code" / "logs"),
        }
    }


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _complete_fmriprep_unit(root, subject="01", spaces=("MNI152NLin2009cAsym_res-2",)):
    """A unit the surveyor grades COMPLETE: raw BOLD, anat, html, native preproc
    BOLD + confounds — plus one preproc BOLD per given ``space-`` filename infix."""
    _touch(root / "bids" / f"sub-{subject}" / "func" / f"sub-{subject}_task-a_bold.nii.gz")
    fp = root / "derivatives" / "fmriprep"
    _touch(fp / f"sub-{subject}.html")
    _touch(fp / f"sub-{subject}" / "anat" / f"sub-{subject}_desc-preproc_T1w.nii.gz")
    func = fp / f"sub-{subject}" / "func"
    _touch(func / f"sub-{subject}_task-a_desc-preproc_bold.nii.gz")
    _touch(func / f"sub-{subject}_task-a_desc-confounds_timeseries.tsv")
    for infix in spaces:
        if infix.startswith("space-fsaverage"):
            _touch(func / f"sub-{subject}_task-a_hemi-L_{infix}_bold.func.gii")
        else:
            _touch(func / f"sub-{subject}_task-a_{infix}_desc-preproc_bold.nii.gz")


def _launch(config, job_id, output_spaces, subject="01", with_record=True):
    """One recorded fMRIPrep launch, request record included unless declined."""
    request_path = ""
    if with_record:
        ctx = {"output_spaces": output_spaces, "subject": subject, "session": ""}
        request_path = str(record_request(config, "fmriprep", subject, "", job_id, ctx))
    record_submission(config, "fmriprep", subject, "", job_id, request_path=request_path)


def _spaces_issues(config):
    return [i for i in run_checks(config) if i.check == "requested-spaces"]


def test_no_derivatives_dir_configured_is_silent(tmp_path):
    config = _config(tmp_path)
    _launch(config, "899", ["fsaverage6"])
    del config["paths"]["derivatives_dir"]
    assert _spaces_issues(config) == []


def test_a_missing_requested_space_is_reported(tmp_path):
    _complete_fmriprep_unit(tmp_path, spaces=("space-MNI152NLin2009cAsym_res-2",))
    config = _config(tmp_path)
    _launch(config, "900", ["MNI152NLin2009cAsym:res-2", "fsaverage6"])
    (issue,) = _spaces_issues(config)
    assert issue.severity == "warning"
    assert issue.subject == "01"
    assert issue.stage == "fmriprep"
    assert "`fsaverage6`" in issue.message
    assert "requests/900.json" in issue.message


def test_the_check_needs_no_expected_declaration(tmp_path):
    """The request record is duckbrain's own declaration — the L2 check must run
    for a project that never wrote an ``[expected]`` section. Pins the gate
    restructure that removed ``run_checks``'s global ``declared`` gate."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    assert "expected" not in config
    _launch(config, "901", ["fsaverage6"])
    assert len(_spaces_issues(config)) == 1


def test_every_requested_space_present_is_silent(tmp_path):
    _complete_fmriprep_unit(
        tmp_path, spaces=("space-MNI152NLin2009cAsym_res-2", "space-fsaverage6")
    )
    config = _config(tmp_path)
    _launch(config, "902", ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"])
    assert _spaces_issues(config) == []


def test_a_modifier_must_appear_in_the_same_filename(tmp_path):
    """`MNI152NLin2009cAsym:res-2` is not satisfied by a `space-MNI…` file
    without the `res-2` token — the resolution is part of the ask."""
    _complete_fmriprep_unit(tmp_path, spaces=("space-MNI152NLin2009cAsym",))
    config = _config(tmp_path)
    _launch(config, "903", ["MNI152NLin2009cAsym:res-2"])
    (issue,) = _spaces_issues(config)
    assert "res-2" in issue.message


def test_native_space_aliases_are_never_judged(tmp_path):
    """`func` writes no ``space-`` entity; the native preproc BOLD it names is
    already required by the surveyor's own completeness grade."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    _launch(config, "904", ["func"])
    assert _spaces_issues(config) == []


def test_more_spaces_than_requested_is_never_flagged(tmp_path):
    """The surveyor's asymmetry, held here too: a leftover from a previous
    config is a normal thing for real data to hold."""
    _complete_fmriprep_unit(
        tmp_path, spaces=("space-MNI152NLin2009cAsym_res-2", "space-fsaverage6")
    )
    config = _config(tmp_path)
    _launch(config, "905", ["MNI152NLin2009cAsym:res-2"])
    assert _spaces_issues(config) == []


def test_an_incomplete_unit_is_not_judged(tmp_path):
    """A PARTIAL unit's shortfall already shows on the board — and a running job
    would read as missing every space it hadn't written yet."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    # Remove the confounds: the unit now grades PARTIAL, not COMPLETE.
    func = tmp_path / "derivatives" / "fmriprep" / "sub-01" / "func"
    (func / "sub-01_task-a_desc-confounds_timeseries.tsv").unlink()
    _launch(config, "906", ["fsaverage6"])
    assert _spaces_issues(config) == []


def test_only_the_newest_attempt_is_judged(tmp_path):
    """A newer launch without a record (hand-run sbatch, an older duckbrain)
    supersedes the older record — judging by it would be the stale-crash-file
    mistake all over again (`test_a_crash_from_a_superseded_run_is_silent`)."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    _launch(config, "907", ["fsaverage6"])
    assert len(_spaces_issues(config)) == 1
    _launch(config, "908", ["fsaverage6"], with_record=False)
    assert _spaces_issues(config) == []


def test_a_malformed_request_record_is_silent(tmp_path):
    """An unreadable file is not a finding — the contract every provenance
    reader holds."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    _launch(config, "909", ["fsaverage6"])
    path = tmp_path / "code" / "logs" / "requests" / "909.json"
    path.write_text("not json{")
    assert _spaces_issues(config) == []


def test_a_request_without_spaces_is_silent(tmp_path):
    """A dcm2bids or NORDIC record has no `output_spaces`; nothing to judge."""
    _complete_fmriprep_unit(tmp_path, spaces=())
    config = _config(tmp_path)
    ctx = {"force": False, "subject": "01", "session": ""}
    path = record_request(config, "fmriprep", "01", "", "910", ctx)
    record_submission(config, "fmriprep", "01", "", "910", request_path=str(path))
    assert _spaces_issues(config) == []


def test_the_record_survives_a_string_valued_ask(tmp_path):
    """Defense in depth: the builder always resolves to a list, but the record
    is JSON anyone can write — a space-separated string still judges."""
    _complete_fmriprep_unit(tmp_path, spaces=("space-fsaverage6",))
    config = _config(tmp_path)
    path = tmp_path / "code" / "logs" / "requests" / "911.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"request": {"output_spaces": "fsaverage6 T1w"}}))
    record_submission(config, "fmriprep", "01", "", "911", request_path=str(path))
    (issue,) = _spaces_issues(config)
    assert "`T1w`" in issue.message
