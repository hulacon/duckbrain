"""Pipeline controller — advance_one dispatch, job-naming, and error contract.

These lock in the behavior the Project Status cockpit will depend on: the
``{prefix}_{tag}`` job name (the squeue/sacct join key), export-vs-submit, and
that misconfigured / non-launchable stages raise ``PipelineError`` rather than
submitting junk.
"""

from pathlib import Path

import pandas as pd
import pytest

import duckbrain.core.pipeline as P
from duckbrain.core.pipeline import (
    STAGE_SPECS,
    SLURM_STAGES,
    PipelineError,
    advance_one,
    effective_depends_on,
    read_submissions,
    record_submission,
    run_provenance,
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
    monkeypatch.setattr(C, "generate_session_config", lambda d, sub, ses, **kw: {})
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


def test_nordic_launch_stamps_derivative_provenance(monkeypatch, tmp_path):
    import json
    import duckbrain.core.nordic as N
    monkeypatch.setattr(N, "get_bold_runs", lambda bids, sub, ses: [tmp_path / "a_bold.nii.gz"])
    monkeypatch.setattr(P, "build_context", lambda *a, **k: {})
    monkeypatch.setattr(P, "render_sbatch", lambda template, ctx: "#script")
    monkeypatch.setattr(P, "submit_job", lambda script, job_name, scripts_dir=None: "JOBN")
    cfg = _config(tmp_path)
    advance_one(cfg, "nordic", "008", "")
    # NORDIC writes no provenance itself, so duckbrain stamps the derivative root
    # in the same BIDS-Derivatives format the checker reads from other tools.
    desc = json.loads((tmp_path / "derivatives" / "nordic" / "dataset_description.json").read_text())
    assert desc["DatasetType"] == "derivative"
    assert [g["Name"] for g in desc["GeneratedBy"]] == ["duckbrain", "nordic"]
    assert desc["DatasetLinks"]["raw"] == cfg["paths"]["bids_dir"]


# ---- anat-derivatives reuse gating ------------------------------------------
#
# fMRIPrep accepts --derivatives pointing at a tree holding no anat for the
# subject: it rebuilds the anat workflow and logs nothing about the reuse it
# could not do. Requesting reuse must therefore fail loudly at submit time
# rather than burn hours pretending to have saved them.

def _write_anat_deriv(root, subject, session=""):
    """Lay down the marker a finished fMRIPrep anat leaves behind."""
    ss = f"sub-{subject}" + (f"/ses-{session}" if session else "")
    anat = Path(root) / "derivatives" / "fmriprep" / ss / "anat"
    anat.mkdir(parents=True, exist_ok=True)
    f = anat / f"sub-{subject}_desc-preproc_T1w.nii.gz"
    f.write_text("x")
    return f


def _patch_fmriprep(monkeypatch, tmp_path, cap):
    import duckbrain.core.fmriprep as F
    lic = tmp_path / "license.txt"
    lic.write_text("x")
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "cont.simg")
    monkeypatch.setattr(F, "find_fs_license", lambda cfg: lic)
    monkeypatch.setattr(F, "write_session_filter", lambda path, ses: path)
    monkeypatch.setattr(
        P, "render_sbatch", lambda template, ctx: cap.update(ctx=ctx) or "s")
    monkeypatch.setattr(P, "submit_job", lambda s, n, scripts_dir=None: "J")


def test_has_anat_derivatives_detects_finished_anat(tmp_path):
    from duckbrain.core.fmriprep import has_anat_derivatives
    deriv = str(tmp_path / "derivatives")
    assert has_anat_derivatives(deriv, "008") is False  # no tree at all
    _write_anat_deriv(tmp_path, "008")
    assert has_anat_derivatives(deriv, "008") is True
    assert has_anat_derivatives(deriv, "014") is False  # other subject's anat


def test_has_anat_derivatives_is_per_session(tmp_path):
    from duckbrain.core.fmriprep import has_anat_derivatives
    deriv = str(tmp_path / "derivatives")
    _write_anat_deriv(tmp_path, "008", "01")
    assert has_anat_derivatives(deriv, "008", "01") is True
    assert has_anat_derivatives(deriv, "008", "02") is False


def test_has_anat_derivatives_ignores_empty_file(tmp_path):
    from duckbrain.core.fmriprep import has_anat_derivatives
    f = _write_anat_deriv(tmp_path, "008")
    f.write_text("")  # a crashed run can leave a zero-byte stub
    assert has_anat_derivatives(str(tmp_path / "derivatives"), "008") is False


def test_fmriprep_reuse_without_prior_anat_raises(monkeypatch, tmp_path):
    cap = {}
    _patch_fmriprep(monkeypatch, tmp_path, cap)
    with pytest.raises(PipelineError, match="no preprocessed anatomicals"):
        advance_one(_config(tmp_path), "fmriprep", "014", "", use_derivatives=True)
    assert not cap  # nothing rendered or submitted


def test_fmriprep_reuse_with_prior_anat_passes_derivatives_path(monkeypatch, tmp_path):
    cap = {}
    _patch_fmriprep(monkeypatch, tmp_path, cap)
    _write_anat_deriv(tmp_path, "008")
    advance_one(_config(tmp_path), "fmriprep", "008", "", use_derivatives=True)
    assert cap["ctx"]["derivatives"] == str(tmp_path / "derivatives" / "fmriprep")


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
    """A later COMPLETED clears the earlier FAILED — and the sacct rows are given
    newest-first, so this fails if the reduction is order-insensitive.

    The version of this test that shipped listed them oldest-first, which the
    old two-unordered-sets implementation passed either way round. It asserted
    the right answer while proving nothing about chronology.
    """
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
        hist=[
            JobInfo(job_id="9", name="dcm2bids_04", state="COMPLETED", partition="c",
                    submit_time="2026-07-22T11:00:00"),
            JobInfo(job_id="8", name="dcm2bids_04", state="FAILED", partition="c",
                    submit_time="2026-07-22T09:00:00"),
        ],
    )
    row = survey_live({}).iloc[0]
    assert row["converted_job"] == ""


def test_survey_live_completed_then_failed_shows_the_failure(monkeypatch):
    """The chronology nobody tested (DB-006).

    History reduced to "names that failed" and "names that completed", and a
    failure was reported only when a name was in the first and not the second.
    So once a job name had ever completed, no later failure could ever surface —
    for the remaining seven days of the sacct window the retry's failure was
    invisible and the cell read as quietly idle.
    """
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
        hist=[
            JobInfo(job_id="8", name="dcm2bids_04", state="COMPLETED", partition="c",
                    submit_time="2026-07-22T09:00:00"),
            JobInfo(job_id="9", name="dcm2bids_04", state="FAILED", partition="c",
                    submit_time="2026-07-22T11:00:00"),
        ],
    )
    row = survey_live({}).iloc[0]
    assert row["converted_job"] == "failed"


def test_survey_live_orders_attempts_by_job_id_without_timestamps(monkeypatch):
    """sacct can report Submit as 'Unknown'; the numeric job id still orders."""
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
        hist=[
            JobInfo(job_id="120", name="dcm2bids_04", state="FAILED", partition="c",
                    submit_time="Unknown"),
            JobInfo(job_id="99", name="dcm2bids_04", state="COMPLETED", partition="c",
                    submit_time="Unknown"),
        ],
    )
    # 120 > 99 numerically; a string compare would put "99" last and hide the fail.
    assert survey_live({}).iloc[0]["converted_job"] == "failed"


def test_survey_live_an_active_retry_outranks_any_history(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
        active=[JobInfo(job_id="10", name="dcm2bids_04", state="RUNNING", partition="c")],
        hist=[JobInfo(job_id="9", name="dcm2bids_04", state="FAILED", partition="c",
                      submit_time="2026-07-22T09:00:00")],
    )
    assert survey_live({}).iloc[0]["converted_job"] == "running"


def test_survey_live_with_jobs_returns_single_pull_index(monkeypatch):
    active = [JobInfo(job_id="1", name="fmriprep_04", state="RUNNING", partition="c")]
    hist = [JobInfo(job_id="9", name="mriqc_04", state="COMPLETED", partition="c")]
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "partial", "mriqc": "complete"},
        active=active, hist=hist,
    )
    matrix, jobs = survey_live({}, with_jobs=True)
    assert matrix.iloc[0]["fmriprep_job"] == "running"
    # the raw JobInfo lists and an id-index come from the SAME pull
    assert {j.job_id for j in jobs["active"]} == {"1"}
    assert {j.job_id for j in jobs["history"]} == {"9"}
    assert jobs["by_id"]["1"].name == "fmriprep_04"
    assert jobs["by_id"]["9"].state == "COMPLETED"


def test_survey_live_default_return_is_matrix_only(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
    )
    out = survey_live({})  # no with_jobs → bare DataFrame, back-compat
    assert isinstance(out, pd.DataFrame)


def test_stage_runnable_dependency_gating(monkeypatch):
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "missing", "fmriprep": "missing", "mriqc": "missing"},
    )
    row = survey_live({}).iloc[0]
    assert stage_runnable(row, "converted") is True   # ingested complete → go
    assert stage_runnable(row, "fmriprep") is False   # converted not complete → gated


def test_effective_depends_on_use_nordic():
    off = {}
    on = {"nordic": {"use_nordic": True}}
    # fMRIPrep swings from converted -> nordic when use_nordic is on.
    assert effective_depends_on(off, "fmriprep") == "converted"
    assert effective_depends_on(on, "fmriprep") == "nordic"
    # Other stages are unaffected; NORDIC stays a converted producer.
    assert effective_depends_on(on, "mriqc") == "converted"
    assert effective_depends_on(on, "nordic") == "converted"
    assert effective_depends_on(on, "converted") == "ingested"


def test_stage_runnable_use_nordic_gates_fmriprep_on_nordic():
    # converted done, nordic not yet: fMRIPrep is runnable normally but gated
    # when use_nordic is on (its input doesn't exist yet).
    row = {"subject": "08", "session": "", "ingested": "complete",
           "converted": "complete", "nordic": "missing",
           "fmriprep": "missing", "mriqc": "missing",
           "converted_job": "", "nordic_job": "", "fmriprep_job": "", "mriqc_job": ""}
    assert stage_runnable(row, "fmriprep") is True                 # static dep = converted
    assert stage_runnable(row, "fmriprep", {}) is True             # config off = converted
    assert stage_runnable(row, "fmriprep", {"nordic": {"use_nordic": True}}) is False
    # Once NORDIC completes, the use_nordic gate opens.
    row2 = {**row, "nordic": "complete"}
    assert stage_runnable(row2, "fmriprep", {"nordic": {"use_nordic": True}}) is True


def _patch_fmriprep_deps(monkeypatch, tmp_path, denoised):
    """Stub fMRIPrep + NORDIC deps; capture the rendered context. Returns cap dict."""
    import duckbrain.core.fmriprep as F
    import duckbrain.core.nordic as N
    (tmp_path / "fs").mkdir()
    lic = tmp_path / "fs" / "license.txt"
    lic.write_text("x")
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "cont.simg")
    monkeypatch.setattr(F, "find_fs_license", lambda cfg: lic)
    monkeypatch.setattr(F, "write_session_filter", lambda path, ses: path)
    monkeypatch.setattr(N, "get_bold_runs", lambda root, sub, ses: denoised)
    built = {}
    monkeypatch.setattr(N, "build_nordic_bids_input",
                        lambda **kw: built.update(kw) or tmp_path)
    cap = {"built": built}
    monkeypatch.setattr(P, "render_sbatch",
                        lambda t, ctx: cap.update(ctx=ctx) or "s")
    monkeypatch.setattr(P, "submit_job", lambda s, n, scripts_dir=None: "J")
    return cap


def test_fmriprep_use_nordic_swaps_input_to_bids_format(monkeypatch, tmp_path):
    cap = _patch_fmriprep_deps(monkeypatch, tmp_path, denoised=[tmp_path / "b_bold.nii.gz"])
    cfg = _config(tmp_path)
    cfg["nordic"] = {"use_nordic": True}
    advance_one(cfg, "fmriprep", "008", "")
    # fMRIPrep reads the assembled bids_format tree, not raw BIDS.
    assert cap["ctx"]["bids_dir"].endswith("/derivatives/nordic/bids_format")
    assert cap["built"]["subject"] == "008"


def test_fmriprep_use_nordic_without_denoised_raises(monkeypatch, tmp_path):
    _patch_fmriprep_deps(monkeypatch, tmp_path, denoised=[])
    cfg = _config(tmp_path)
    cfg["nordic"] = {"use_nordic": True}
    with pytest.raises(PipelineError, match="no NORDIC-denoised"):
        advance_one(cfg, "fmriprep", "008", "")


def test_fmriprep_without_use_nordic_reads_raw_bids(monkeypatch, tmp_path):
    cap = _patch_fmriprep_deps(monkeypatch, tmp_path, denoised=[])
    cfg = _config(tmp_path)  # no [nordic] -> use_nordic defaults off
    advance_one(cfg, "fmriprep", "008", "")
    assert cap["ctx"]["bids_dir"] == str(tmp_path)  # raw bids_dir, tree never built
    assert cap["built"] == {}


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


# ---- durable submission log -------------------------------------------------

def test_advance_one_records_submission(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    cfg = _config(tmp_path)
    advance_one(cfg, "converted", "008", "01")
    subs = read_submissions(cfg)
    assert len(subs) == 1
    r = subs.iloc[0]
    assert (r["stage"], r["subject"], r["session"], r["job_id"]) == ("converted", "008", "01", "JOB123")
    assert r["timestamp"]  # non-empty ISO stamp
    # Provenance is captured alongside the launch (container from the stubbed
    # get_container_path; no version key in the test config, so tool_version is "").
    assert (r["tool"], r["runtime"]) == ("dcm2bids", "cont.simg")


# ---- run provenance ---------------------------------------------------------

def test_run_provenance_reads_version_and_container(monkeypatch, tmp_path):
    import duckbrain.core.fmriprep as F
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "/imgs/fmriprep-24.1.1.sif")
    cfg = _config(tmp_path)
    cfg["containers"] = {"fmriprep_version": "24.1.1"}
    prov = run_provenance(cfg, "fmriprep")
    assert prov["tool"] == "fmriprep"
    assert prov["tool_version"] == "24.1.1"
    assert prov["runtime"] == "fmriprep-24.1.1.sif"  # basename only
    assert prov["input_variant"] == "raw"


def test_run_provenance_fmriprep_input_variant_nordic(monkeypatch, tmp_path):
    import duckbrain.core.fmriprep as F
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "fmriprep.sif")
    cfg = _config(tmp_path)
    cfg["nordic"] = {"use_nordic": True}
    assert run_provenance(cfg, "fmriprep")["input_variant"] == "nordic"


def test_run_provenance_degrades_when_container_unresolvable(tmp_path):
    # No containers config and no stubbed resolver — every field falls back to "",
    # never raising, so provenance can't sink a submission.
    prov = run_provenance(_config(tmp_path), "mriqc")
    assert prov["tool"] == "mriqc"
    assert prov["tool_version"] == ""
    assert prov["runtime"] == ""
    assert prov["input_variant"] == "raw"


def test_run_provenance_nordic_without_a_toolbox_has_no_version(tmp_path):
    prov = run_provenance(_config(tmp_path), "nordic")
    assert prov["tool"] == "nordic"
    assert prov["tool_version"] == ""  # no toolbox configured: unknowable, not guessed
    assert prov["runtime"] == ""     # NORDIC runs no container, ever
    assert prov["code_source"] == ""
    assert prov["input_variant"] == "raw"


def test_unset_toolbox_never_describes_the_current_directory(monkeypatch, tmp_path):
    """Regression: Path("") is `.`, so an unset nordic_toolbox_dir used to
    resolve to the CWD and record *duckbrain's own* git version as the
    toolbox's. Silently wrong provenance is worse than none."""
    monkeypatch.chdir(tmp_path)  # any repo-like CWD must not leak in
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = ""
    prov = run_provenance(cfg, "nordic")
    assert prov["tool_version"] == ""
    assert prov["code_source"] == ""


def test_run_provenance_nordic_reads_the_toolbox_checkout(tmp_path):
    repo = _git_repo(tmp_path / "NORDIC_Raw", remote="https://github.com/SteenMoeller/NORDIC_Raw.git")
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(repo)
    prov = run_provenance(cfg, "nordic")
    sha = _sha(repo)
    assert prov["tool"] == "nordic"
    assert prov["tool_version"] == sha            # no tags yet: --always gives the sha
    assert prov["code_source"] == f"SteenMoeller/NORDIC_Raw@{sha}"
    assert prov["runtime"] == ""


def test_run_provenance_nordic_records_matlab_as_its_runtime(tmp_path):
    """NORDIC's two axes land in the same pair of slots a container stage uses:
    the runtime slot is free precisely because NORDIC runs no image."""
    repo = _git_repo(tmp_path / "NORDIC_Raw", remote="https://github.com/SteenMoeller/NORDIC_Raw.git")
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(repo)
    cfg["nordic"] = {"matlab_module": "matlab/R2024a"}
    prov = run_provenance(cfg, "nordic")
    assert prov["runtime"] == "matlab/R2024a"                       # what ran it
    assert prov["code_source"].startswith("SteenMoeller/NORDIC_Raw@")  # where code came from


def test_run_provenance_container_stage_runtime_is_the_image(monkeypatch, tmp_path):
    """The mirror: for a container the image *is* the runtime."""
    import duckbrain.core.fmriprep as F
    monkeypatch.setattr(F, "get_container_path", lambda cfg: tmp_path / "fmriprep-24.1.1.sif")
    prov = run_provenance(_config(tmp_path), "fmriprep")
    assert prov["runtime"] == "fmriprep-24.1.1.sif"


def test_nordic_stamp_records_matlab_as_its_own_generatedby_entry(monkeypatch, tmp_path):
    import json
    import duckbrain.core.nordic as N
    monkeypatch.setattr(N, "get_bold_runs", lambda bids, sub, ses: [tmp_path / "a_bold.nii.gz"])
    monkeypatch.setattr(P, "build_context", lambda *a, **k: {})
    monkeypatch.setattr(P, "render_sbatch", lambda template, ctx: "#script")
    monkeypatch.setattr(P, "submit_job", lambda script, job_name, scripts_dir=None: "JOBN")
    cfg = _config(tmp_path)
    cfg["nordic"] = {"matlab_module": "matlab/R2024a"}
    advance_one(cfg, "nordic", "008", "")
    desc = json.loads((tmp_path / "derivatives" / "nordic" / "dataset_description.json").read_text())
    # GeneratedBy is a list, so MATLAB — a genuine second tool in the chain, with
    # no dedicated BIDS field — earns its own entry.
    assert [g["Name"] for g in desc["GeneratedBy"]] == ["duckbrain", "nordic", "matlab"]
    assert desc["GeneratedBy"][2]["Version"] == "R2024a"


def test_run_provenance_nordic_marks_a_locally_edited_toolbox_dirty(tmp_path):
    """A hand-edited NIFTI_NORDIC.m makes results unreproducible — that belongs
    in the record."""
    repo = _git_repo(tmp_path / "NORDIC_Raw")
    (repo / "NIFTI_NORDIC.m").write_text("% locally hacked\n")
    cfg = _config(tmp_path)
    cfg["paths"]["nordic_toolbox_dir"] = str(repo)
    assert run_provenance(cfg, "nordic")["tool_version"].endswith("-dirty")


def test_read_submissions_backfills_legacy_columns(tmp_path):
    # A log written before provenance columns existed still reads back with the
    # full schema (new columns empty), so consumers can rely on it.
    cfg = _config(tmp_path)
    log = tmp_path / "code" / "logs" / "submissions.tsv"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("timestamp\tsubject\tsession\tstage\tjob_id\n2026-01-01\t01\t\tfmriprep\tJ1\n")
    df = read_submissions(cfg)
    assert list(df.columns) == list(P._SUBMISSION_COLUMNS)
    assert df.iloc[0]["tool"] == ""
    assert df.iloc[0]["job_id"] == "J1"


def test_export_only_is_not_recorded(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    monkeypatch.setattr(P, "export_script", lambda content, path: path)
    cfg = _config(tmp_path)
    advance_one(cfg, "converted", "008", "", export_only=True)
    assert read_submissions(cfg).empty


def test_read_submissions_limit_and_order(tmp_path):
    cfg = _config(tmp_path)
    for i in range(5):
        record_submission(cfg, "fmriprep", f"{i:03d}", "", f"J{i}")
    recent = read_submissions(cfg, limit=3)
    assert list(recent["subject"]) == ["002", "003", "004"]  # tail, oldest-first


# ---- legacy submission-log migration ----------------------------------------
#
# Provenance columns were added after logs existed in the wild. Real case
# (divatten_gui_beta, 2026-07-16): a log with the original 5-column header
# `timestamp/subject/session/stage/job_id`. Appending a wider provenance row
# under that narrower header produces a ragged file that pd.read_csv refuses
# outright — taking the log, the Job Monitor, and every log-overlay consistency
# check down with it on the next launch.

def _git_repo(path, remote=None):
    """A throwaway git checkout, standing in for a user's NORDIC_Raw clone."""
    import subprocess
    path.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True,
                                    capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "NIFTI_NORDIC.m").write_text("% stub\n")
    run("add", "-A")
    run("commit", "-qm", "initial")
    if remote:
        run("remote", "add", "origin", remote)
    return path


def _sha(path):
    import subprocess
    return subprocess.run(["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


_LEGACY_HEADER = "timestamp\tsubject\tsession\tstage\tjob_id"
_LEGACY_ROWS = [
    "2026-07-10T13:56:08\t008\t\tconverted\t45191143",
    "2026-07-15T13:31:43\t04\t\tnordic\t45428802",
]


def _write_legacy_log(cfg):
    path = Path(cfg["paths"]["log_dir"]) / "submissions.tsv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([_LEGACY_HEADER, *_LEGACY_ROWS]) + "\n")
    return path


def test_appending_to_a_legacy_log_keeps_it_readable(tmp_path):
    cfg = _config(tmp_path)
    _write_legacy_log(cfg)
    record_submission(cfg, "fmriprep", "099", "", "J999",
                      tool="fmriprep", runtime="fmriprep-24.1.1.simg",
                      input_variant="raw")
    df = read_submissions(cfg)  # must not raise
    assert len(df) == 3
    assert list(df["job_id"]) == ["45191143", "45428802", "J999"]


def test_migration_preserves_legacy_rows_by_column_name(tmp_path):
    cfg = _config(tmp_path)
    _write_legacy_log(cfg)
    record_submission(cfg, "fmriprep", "099", "", "J999", tool="fmriprep")
    df = read_submissions(cfg)
    legacy = df.iloc[0]
    # No data shifted columns; new fields fill empty rather than borrowing values.
    assert legacy["subject"] == "008"
    assert legacy["stage"] == "converted"
    assert legacy["job_id"] == "45191143"
    assert legacy["runtime"] == ""
    assert legacy["code_source"] == ""


def test_migration_is_idempotent(tmp_path):
    cfg = _config(tmp_path)
    _write_legacy_log(cfg)
    record_submission(cfg, "fmriprep", "01", "", "J1")
    record_submission(cfg, "fmriprep", "02", "", "J2")
    path = Path(cfg["paths"]["log_dir"]) / "submissions.tsv"
    header_lines = [ln for ln in path.read_text().splitlines() if ln.startswith("timestamp\t")]
    assert len(header_lines) == 1
    assert len(read_submissions(cfg)) == 4


_RENAMED_HEADER = ("timestamp\tsubject\tsession\tstage\ttool\ttool_version\t"
                   "container\tcontainer_source\tinput_variant\tjob_id")
_RENAMED_ROW = ("2026-07-16T10:00:00\t01\t\tfmriprep\tfmriprep\t24.1.1\t"
                "fmriprep-24.1.1.simg\tnipreps/fmriprep:24.1.1\traw\tJ1")


def test_migration_carries_renamed_columns_rather_than_dropping_them(tmp_path):
    """container/container_source were renamed to runtime/code_source. The
    migration maps rows by *name* and rewrites the file in place, so without a
    rename map those values would be silently and permanently lost."""
    cfg = _config(tmp_path)
    path = Path(cfg["paths"]["log_dir"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "submissions.tsv").write_text(_RENAMED_HEADER + "\n" + _RENAMED_ROW + "\n")

    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep")
    df = read_submissions(cfg)
    old = df.iloc[0]
    assert old["runtime"] == "fmriprep-24.1.1.simg"
    assert old["code_source"] == "nipreps/fmriprep:24.1.1"
    assert old["tool_version"] == "24.1.1"


def test_read_submissions_renames_without_migrating(tmp_path):
    """Reading alone must not require a write — an old-named log still reads."""
    cfg = _config(tmp_path)
    path = Path(cfg["paths"]["log_dir"])
    path.mkdir(parents=True, exist_ok=True)
    (path / "submissions.tsv").write_text(_RENAMED_HEADER + "\n" + _RENAMED_ROW + "\n")
    df = read_submissions(cfg)
    assert df.iloc[0]["runtime"] == "fmriprep-24.1.1.simg"
    assert df.iloc[0]["code_source"] == "nipreps/fmriprep:24.1.1"


def test_migration_rewrites_a_stale_named_header(tmp_path):
    """Same width, old names: still needs rewriting, or the header stays wrong
    on disk forever (the parser renames on read, hiding it)."""
    cfg = _config(tmp_path)
    path = Path(cfg["paths"]["log_dir"])
    path.mkdir(parents=True, exist_ok=True)
    log = path / "submissions.tsv"
    log.write_text(_RENAMED_HEADER + "\n" + _RENAMED_ROW + "\n")
    record_submission(cfg, "fmriprep", "02", "", "J2", tool="fmriprep")
    assert log.read_text().splitlines()[0].split("\t")[6:8] == ["runtime", "code_source"]


def test_read_submissions_tolerates_an_already_ragged_log(tmp_path):
    """A log corrupted by a pre-migration append still reads best-effort — a
    durable record is worth more read imperfectly than not at all."""
    cfg = _config(tmp_path)
    path = _write_legacy_log(cfg)
    with open(path, "a") as f:  # the wide row that used to break the parser
        f.write("2026-07-16T10:00:00\t099\t\tfmriprep\tfmriprep\t24.1.1\t"
                "fmriprep-24.1.1.simg\tnipreps/fmriprep:24.1.1\traw\tJ999\n")
    df = read_submissions(cfg)
    assert len(df) == 3
    assert list(df["subject"]) == ["008", "04", "099"]


def test_submission_log_write_failure_never_sinks_submit(monkeypatch, tmp_path):
    cap = {}
    _patch_dcm2bids(monkeypatch, tmp_path, cap)
    monkeypatch.setattr(P, "record_submission", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    # Submission still returns its job id despite the logging blowup.
    assert advance_one(_config(tmp_path), "converted", "008", "") == "JOB123"


# ---- DB-002: PARTIAL is the state that lets real failures through ------------

def test_partial_stage_lets_a_failed_badge_through(monkeypatch):
    """COMPLETE suppresses a stale sacct failure — and that rule was only safe
    once COMPLETE stopped meaning "one output exists".

    While a 1-of-4 conversion graded COMPLETE, the suppression hid the three
    genuine failures. Now that shortfall grades PARTIAL, which never reaches the
    suppression branch, so the badge appears with no change to the rule itself.
    """
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "partial", "fmriprep": "missing", "mriqc": "missing"},
        hist=[JobInfo(job_id="9", name="dcm2bids_04", state="FAILED", partition="c")],
    )
    row = survey_live({}).iloc[0]
    assert row["converted_job"] == "failed"


def test_complete_stage_still_suppresses_a_stale_failure(monkeypatch):
    """The other half of the rule, pinned so nobody re-derives it.

    A failed run followed by a successful re-run leaves a real FAILED record and
    a complete tree; the tree is the truth.
    """
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "complete", "fmriprep": "missing", "mriqc": "missing"},
        hist=[JobInfo(job_id="9", name="dcm2bids_04", state="FAILED", partition="c")],
    )
    assert survey_live({}).iloc[0]["converted_job"] == ""


def test_a_partial_dependency_blocks_the_downstream_stage(monkeypatch):
    """The reason DB-002 was more than a display bug: a green-but-partial
    conversion unlocked preprocessing on a half-converted unit."""
    _patch_survey(
        monkeypatch,
        {"subject": "04", "session": "", "ingested": "complete",
         "converted": "partial", "fmriprep": "missing", "mriqc": "missing"},
    )
    row = survey_live({}).iloc[0]
    assert stage_runnable(row, "fmriprep") is False
