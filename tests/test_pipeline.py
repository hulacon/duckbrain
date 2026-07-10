"""Pipeline controller — advance_one dispatch, job-naming, and error contract.

These lock in the behavior the Project Status cockpit will depend on: the
``{prefix}_{tag}`` job name (the squeue/sacct join key), export-vs-submit, and
that misconfigured / non-launchable stages raise ``PipelineError`` rather than
submitting junk.
"""

import pandas as pd
import pytest

import duckbrain.core.pipeline as P
from duckbrain.core.pipeline import (
    STAGE_SPECS,
    SLURM_STAGES,
    PipelineError,
    advance_one,
    stage_runnable,
    survey_live,
    tag_for,
)
from duckbrain.slurm.monitor import JobInfo


def _config(root):
    return {"paths": {
        "bids_dir": str(root),
        "sourcedata_dir": str(root / "sourcedata"),
        "derivatives_dir": str(root / "derivatives"),
        "log_dir": str(root / "code" / "logs"),
        "work_dir": "/tmp",
    }}


# ---- registry / naming ------------------------------------------------------

def test_tag_for_sessionless_and_multisession():
    assert tag_for("04", "") == "04"
    assert tag_for("04", "01") == "04_01"


def test_slurm_stages_all_have_builders():
    assert set(SLURM_STAGES) == {"converted", "fmriprep", "nordic", "mriqc"}
    for stage in SLURM_STAGES:
        assert STAGE_SPECS[stage].build is not None


def test_dependency_chain():
    assert STAGE_SPECS["converted"].depends_on == "ingested"
    assert STAGE_SPECS["fmriprep"].depends_on == "converted"
    assert STAGE_SPECS["mriqc"].depends_on == "converted"


# ---- non-launchable stages --------------------------------------------------

def test_unknown_stage_raises():
    with pytest.raises(PipelineError, match="Unknown stage"):
        advance_one({"paths": {}}, "bogus", "04", "")


def test_ingested_is_not_launchable():
    with pytest.raises(PipelineError, match="not launchable"):
        advance_one({"paths": {}}, "ingested", "04", "")


# ---- converted (dcm2bids): happy-path dispatch, naming, export --------------

def _patch_dcm2bids(monkeypatch, tmp_path, capture):
    import duckbrain.core.conversion as C
    monkeypatch.setattr(C, "get_container_path", lambda cfg: "cont.simg")
    monkeypatch.setattr(C, "resolve_dicom_dir", lambda sd, sub, ses: tmp_path / "dcm")
    monkeypatch.setattr(C, "generate_session_config", lambda d, sub, ses: {})
    monkeypatch.setattr(C, "save_dcm2bids_config", lambda cfg, path: None)
    monkeypatch.setattr(P, "render_sbatch", lambda template, ctx: f"#script:{template}")

    def fake_submit(script, job_name, scripts_dir=None):
        capture.update(script=script, job_name=job_name, scripts_dir=scripts_dir)
        return "JOB123"

    monkeypatch.setattr(P, "submit_job", fake_submit)


def test_converted_submits_with_expected_job_name(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    jid = advance_one(_config(tmp_path), "converted", "008", "")
    assert jid == "JOB123"
    assert cap["job_name"] == "dcm2bids_008"
    assert cap["script"] == "#script:dcm2bids"
    # scripts/logs land in the shared log_dir, not node-local work_dir.
    assert cap["scripts_dir"].endswith("/code/logs")


def test_converted_multisession_job_name(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    advance_one(_config(tmp_path), "converted", "008", "01")
    assert cap["job_name"] == "dcm2bids_008_01"


def test_export_only_writes_script_and_does_not_submit(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    written = {}
    monkeypatch.setattr(
        P, "export_script",
        lambda content, path: written.update(content=content, path=str(path)) or path,
    )
    ref = advance_one(_config(tmp_path), "converted", "008", "", export_only=True)
    assert not cap  # submit_job never called
    assert str(ref).endswith("dcm2bids_008.sbatch")
    assert written["content"] == "#script:dcm2bids"


# ---- stage preconditions raise PipelineError --------------------------------

def test_fmriprep_missing_license_raises(monkeypatch, tmp_path):
    import duckbrain.core.fmriprep as F
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "cont.simg")
    monkeypatch.setattr(F, "find_fs_license", lambda cfg: None)
    with pytest.raises(PipelineError, match="FreeSurfer license"):
        advance_one(_config(tmp_path), "fmriprep", "008", "")


def test_nordic_no_bold_raises(monkeypatch, tmp_path):
    import duckbrain.core.nordic as N
    monkeypatch.setattr(N, "get_bold_runs", lambda bids, sub, ses: [])
    with pytest.raises(PipelineError, match="BOLD"):
        advance_one(_config(tmp_path), "nordic", "008", "")


# ---- params flow through to the rendered context ----------------------------

def test_fmriprep_params_reach_context(monkeypatch, tmp_path):
    import duckbrain.core.fmriprep as F
    (tmp_path / "fs").mkdir()
    lic = tmp_path / "fs" / "license.txt"
    lic.write_text("x")
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "cont.simg")
    monkeypatch.setattr(F, "find_fs_license", lambda cfg: lic)
    monkeypatch.setattr(F, "write_session_filter", lambda path, ses: path)

    cap = {}
    monkeypatch.setattr(P, "render_sbatch", lambda template, ctx: cap.update(template=template, ctx=ctx) or "s")
    monkeypatch.setattr(P, "submit_job", lambda s, n, scripts_dir=None: "J")

    advance_one(
        _config(tmp_path), "fmriprep", "008", "",
        nprocs=4, mem_gb=99, output_spaces="MNI152NLin2009cAsym T1w", anat_only=True,
    )
    assert cap["template"] == "fmriprep"
    ctx = cap["ctx"]
    assert ctx["fmriprep"]["nprocs"] == 4
    assert ctx["fmriprep"]["mem_gb"] == 99
    # A string of spaces is split into a list; anat_only flows through.
    assert ctx["output_spaces"] == ["MNI152NLin2009cAsym", "T1w"]
    assert ctx["anat_only"] is True
    assert ctx["derivatives"] == ""  # use_derivatives defaulted False


# ---- live-state fusion (survey_live) + run gating ---------------------------

_COLS = ["subject", "session", "ingested", "converted", "fmriprep", "mriqc"]


def _fake_matrix(row):
    return pd.DataFrame([row], columns=_COLS)


def _patch_survey(monkeypatch, row, active=None, hist=None):
    monkeypatch.setattr(P, "survey_project", lambda cfg: _fake_matrix(row))
    monkeypatch.setattr(P, "list_jobs", lambda: active or [])
    monkeypatch.setattr(P, "job_history", lambda days=7: hist or [])


def test_survey_live_overlays_running_and_blocks_run(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "partial", "mriqc": "missing"},
        active=[JobInfo(job_id="1", name="fmriprep_04", state="RUNNING", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == "running"
    # partial-on-disk but a live job → must NOT be runnable (no double-submit).
    assert stage_runnable(row, "fmriprep") is False


def test_survey_live_pending_reads_queued(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "missing", "mriqc": "missing"},
        active=[JobInfo(job_id="1", name="fmriprep_04", state="PENDING", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == "queued"
    assert stage_runnable(row, "fmriprep") is False


def test_survey_live_complete_not_downgraded_by_stale_failure(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "complete", "mriqc": "missing"},
        hist=[JobInfo(job_id="9", name="fmriprep_04", state="FAILED", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == ""  # filesystem COMPLETE wins over stale sacct FAIL
    assert stage_runnable(row, "fmriprep") is False


def test_survey_live_failed_overlay_is_runnable(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "missing", "mriqc": "missing"},
        hist=[JobInfo(job_id="9", name="fmriprep_04", state="TIMEOUT", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == "failed"
    assert stage_runnable(row, "fmriprep") is True


def test_survey_live_failed_but_later_completed_is_not_failed(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
        hist=[
            JobInfo(job_id="8", name="dcm2bids_04", state="FAILED", partition="c"),
            JobInfo(job_id="9", name="dcm2bids_04", state="COMPLETED", partition="c"),
        ],
    )
    row = survey_live({}).iloc[0]
    assert row["converted_job"] == ""  # a later COMPLETED clears the earlier FAILED


def test_stage_runnable_dependency_gating(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
    )
    row = survey_live({}).iloc[0]
    assert stage_runnable(row, "converted") is True   # ingested complete → go
    assert stage_runnable(row, "fmriprep") is False   # converted not complete → gated


def test_survey_live_multisession_join_key(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "01", "ingested": "complete",
         "converted": "complete", "fmriprep": "missing", "mriqc": "missing"},
        active=[JobInfo(job_id="1", name="fmriprep_04_01", state="RUNNING", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == "running"


def test_survey_live_graceful_when_slurm_unavailable(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("squeue: command not found")

    monkeypatch.setattr(P, "survey_project", lambda cfg: _fake_matrix(
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "missing", "mriqc": "missing"}))
    monkeypatch.setattr(P, "list_jobs", boom)
    monkeypatch.setattr(P, "job_history", boom)
    row = survey_live({}).iloc[0]
    assert row["fmriprep_job"] == ""            # no overlay, no crash
    assert stage_runnable(row, "fmriprep") is True
