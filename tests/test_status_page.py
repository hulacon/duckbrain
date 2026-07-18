"""Smoke/interaction tests for the Project Status page (the pipeline cockpit).

The board is an actionable grid: each (unit, stage) cell is a status icon that
upgrades to a popover when it has an action — ``▶`` to launch (keys ``runbtn_*``),
``🔴`` to view the SLURM log + re-run a failed stage (``rerun_*`` / ``dl_*``), and a
per-column header popover for bulk (``bulk_run_<stage>`` / ``bulk_confirm_<stage>``).
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

import duckbrain.core.pipeline as P
from duckbrain.config import save_project_config, scaffold_project
from duckbrain.slurm.monitor import JobInfo

PAGE = "src/duckbrain/gui/pages/0_Project_Status.py"


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _btn_keys(at):
    return {b.key for b in at.button if b.key}


def _markdowns(at):
    return [m.value for m in at.markdown]


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    # sub-01: ingested + converted (so fmriprep/mriqc are runnable); sub-02: ingested only.
    _touch(proj / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(proj / "sourcedata" / "sub-02" / "dicom" / "0001.dcm")
    _touch(proj / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    save_project_config(str(proj), {"project": {"name": "test"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    # Deterministic: no real SLURM state unless a test says otherwise.
    monkeypatch.setattr(P, "list_jobs", lambda: [])
    monkeypatch.setattr(P, "job_history", lambda days=7: [])
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_page_renders_board(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert {"Ingested", "Converted", "Fmriprep", "Mriqc"} <= set(labels)
    # Both units render as rows in the grid (row label is a markdown cell).
    mds = _markdowns(at)
    assert "sub-01" in mds and "sub-02" in mds


def test_only_incomplete_filter_present_and_default_on(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    filt = [c for c in at.checkbox if "unfinished" in c.label][0]
    assert filt.value is True  # on by default so the board shows what needs action
    # Both fixture units are incomplete → shown; toggling off must not error.
    assert "sub-02" in _markdowns(at)
    filt.set_value(False).run()
    assert not at.exception
    assert "sub-02" in _markdowns(at)


def test_empty_project_shows_guidance(tmp_path, monkeypatch):
    proj = tmp_path / "empty"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "empty"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    monkeypatch.setattr(P, "list_jobs", lambda: [])
    monkeypatch.setattr(P, "job_history", lambda days=7: [])
    try:
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert any("No subjects found" in i.value for i in at.info)
    finally:
        os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_cells_offer_runnable_next_steps(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    keys = _btn_keys(at)
    # sub-01 is converted → fmriprep runnable; sub-02 not converted → converted runnable.
    assert "runbtn_fmriprep_01_" in keys
    assert "runbtn_converted_02_" in keys


def test_cell_run_button_invokes_advance_one(project, monkeypatch):
    calls = {}

    def fake_advance(config, stage, subject, session="", *, export_only=False, **params):
        calls.update(stage=stage, subject=subject, session=session, params=params)
        return "JOB1"

    monkeypatch.setattr(P, "advance_one", fake_advance)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    # The sub-01 fmriprep cell's popover run button.
    at.button(key="runbtn_fmriprep_01_").click().run()
    assert not at.exception
    assert calls["stage"] == "fmriprep"
    assert calls["subject"] == "01"
    assert calls["session"] == ""
    # fMRIPrep params are threaded through from the popover widgets.
    assert "nprocs" in calls["params"] and "output_spaces" in calls["params"]


def test_column_bulk_run_gated_by_confirm(project, monkeypatch):
    calls = []

    def fake_advance(config, stage, subject, session="", *, export_only=False, **params):
        calls.append((stage, subject, session))
        return "J"

    monkeypatch.setattr(P, "advance_one", fake_advance)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    # The 'converted' column header bulk popover: only sub-02 is ready.
    assert at.button(key="bulk_run_converted").disabled  # gated until confirmed
    at.checkbox(key="bulk_confirm_converted").set_value(True).run()
    assert not at.button(key="bulk_run_converted").disabled
    at.button(key="bulk_run_converted").click().run()
    assert not at.exception
    assert ("converted", "02", "") in calls


def test_submission_log_panel_renders(project):
    # Pre-seed the durable log; the cockpit should surface it.
    from duckbrain.core.pipeline import record_submission
    from duckbrain.config import load_config
    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "999001")

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any((df.value.astype(str) == "999001").any().any() for df in at.dataframe)


def test_consistency_warning_panel_renders(project):
    # use_nordic on, but the fMRIPrep derivative was generated from raw data —
    # check_consistency should flag it and the cockpit should surface the ⚠️.
    import json
    from duckbrain.config import save_project_config
    save_project_config(str(project), {"project": {"name": "test"},
                                        "nordic": {"use_nordic": True}})
    deriv = project / "derivatives" / "fmriprep"
    deriv.mkdir(parents=True, exist_ok=True)
    (deriv / "dataset_description.json").write_text(json.dumps({
        "Name": "fMRIPrep", "GeneratedBy": [{"Name": "fMRIPrep", "Version": "24.1.1"}],
        "DatasetLinks": {"raw": str(project)},  # raw = project root, not the nordic tree
    }))
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("config-vs-provenance" in w.value for w in at.warning)


def test_no_consistency_warning_when_clean(project):
    # The stock fixture project has no derivatives → nothing to contradict.
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not any("provenance" in w.value.lower() for w in at.warning)


def test_running_cell_links_to_job_with_detail(project, monkeypatch):
    # A running job, recorded in the durable log so the cell can reference its id.
    from duckbrain.core.pipeline import record_submission
    from duckbrain.config import load_config
    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "55123")
    monkeypatch.setattr(
        P, "list_jobs",
        lambda: [JobInfo(job_id="55123", name="fmriprep_01", state="RUNNING",
                         partition="c", nodes="n0042", time_used="00:12:03")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # The cell popover references the exact job with live detail…
    caps = [c.value for c in at.caption]
    assert any("55123" in c for c in caps)
    assert any("n0042" in c for c in caps)  # live node from squeue
    # …and there is no launch action for sub-01 fmriprep (no double-submit).
    assert "runbtn_fmriprep_01_" not in _btn_keys(at)


def test_running_cell_cancel_gated_and_invokes_scancel(project, monkeypatch):
    from duckbrain.core.pipeline import record_submission
    from duckbrain.config import load_config
    import duckbrain.slurm.monitor as M
    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "55123")
    monkeypatch.setattr(
        P, "list_jobs",
        lambda: [JobInfo(job_id="55123", name="fmriprep_01", state="RUNNING", partition="c")],
    )
    cancelled = {}
    monkeypatch.setattr(M, "cancel_job", lambda jid: cancelled.setdefault("id", jid))

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # Cancel is gated until the confirm box is ticked…
    assert at.button(key="cancel_fmriprep_01_").disabled
    at.checkbox(key="cancelchk_fmriprep_01_").set_value(True).run()
    assert not at.button(key="cancel_fmriprep_01_").disabled
    at.button(key="cancel_fmriprep_01_").click().run()
    assert not at.exception
    assert cancelled.get("id") == "55123"


def test_all_jobs_panel_lists_orphan_jobs(project, monkeypatch):
    # A job whose name maps to no board cell must still appear in the all-jobs panel.
    monkeypatch.setattr(
        P, "list_jobs",
        lambda: [JobInfo(job_id="80001", name="some_manual_job", state="RUNNING",
                         partition="c")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any((df.value.astype(str) == "80001").any().any() for df in at.dataframe)
    assert any((df.value.astype(str) == "some_manual_job").any().any() for df in at.dataframe)


def test_failed_cell_exposes_log_and_rerun(project, monkeypatch):
    # sub-01 fmriprep reported failed by SLURM, with a recorded job + log on disk.
    from duckbrain.core.pipeline import record_submission
    from duckbrain.config import load_config
    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "77001")
    log_dir = project / "code" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "fmriprep_77001.out").write_text("boom: a distinctive failure line\n")
    # A failed state comes from sacct history (squeue lists only active jobs).
    monkeypatch.setattr(
        P, "job_history",
        lambda days=7: [JobInfo(job_id="77001", name="fmriprep_01", state="FAILED", partition="c")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # The failed cell's popover surfaces the SLURM log tail…
    assert any("distinctive failure line" in c.value for c in at.code)
    # …and offers a re-run + a download of the full log.
    keys = _btn_keys(at)
    assert "rerun_fmriprep_01_" in keys
    assert any(b.key == "dl_fmriprep_01_" for b in at.download_button if b.key)
