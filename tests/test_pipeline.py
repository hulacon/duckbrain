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
    assert (r["tool"], r["container"]) == ("dcm2bids", "cont.simg")


# ---- run provenance ---------------------------------------------------------

def test_run_provenance_reads_version_and_container(monkeypatch, tmp_path):
    import duckbrain.core.fmriprep as F
    monkeypatch.setattr(F, "get_container_path", lambda cfg: "/imgs/fmriprep-24.1.1.sif")
    cfg = _config(tmp_path)
    cfg["containers"] = {"fmriprep_version": "24.1.1"}
    prov = run_provenance(cfg, "fmriprep")
    assert prov["tool"] == "fmriprep"
    assert prov["tool_version"] == "24.1.1"
    assert prov["container"] == "fmriprep-24.1.1.sif"  # basename only
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
    assert prov["container"] == ""
    assert prov["input_variant"] == "raw"


def test_run_provenance_nordic_has_no_version(tmp_path):
    prov = run_provenance(_config(tmp_path), "nordic")
    assert prov["tool"] == "nordic"
    assert prov["tool_version"] == ""  # MATLAB toolbox stage, no [containers] version
    assert prov["input_variant"] == "raw"


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
                      tool="fmriprep", container="fmriprep-24.1.1.simg",
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
    assert legacy["container"] == ""
    assert legacy["container_source"] == ""


def test_migration_is_idempotent(tmp_path):
    cfg = _config(tmp_path)
    _write_legacy_log(cfg)
    record_submission(cfg, "fmriprep", "01", "", "J1")
    record_submission(cfg, "fmriprep", "02", "", "J2")
    path = Path(cfg["paths"]["log_dir"]) / "submissions.tsv"
    header_lines = [ln for ln in path.read_text().splitlines() if ln.startswith("timestamp\t")]
    assert len(header_lines) == 1
    assert len(read_submissions(cfg)) == 4


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
