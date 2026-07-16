"""Smoke/interaction tests for the Project Status page (the pipeline cockpit)."""

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


def test_page_renders_matrix(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert {"Ingested", "Converted", "Fmriprep", "Mriqc"} <= set(labels)
    df = at.dataframe[0].value
    assert set(df["sub"]) == {"01", "02"}


def test_only_incomplete_filter(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # The "only unfinished" checkbox is the matrix filter.
    filter_cb = [c for c in at.checkbox if "unfinished" in c.label][0]
    filter_cb.set_value(True).run()
    assert not at.exception
    df = at.dataframe[0].value
    assert "02" in set(df["sub"])


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


def test_launch_offers_runnable_next_steps(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    opts = at.selectbox[0].options
    # sub-01 is converted → fmriprep runnable; sub-02 not converted → converted runnable.
    assert any("sub-01" in o and "run fmriprep" in o for o in opts)
    assert any("sub-02" in o and "run converted" in o for o in opts)


def test_run_button_invokes_advance_one(project, monkeypatch):
    calls = {}

    def fake_advance(config, stage, subject, session="", *, export_only=False, **params):
        calls.update(stage=stage, subject=subject, session=session, params=params)
        return "JOB1"

    monkeypatch.setattr(P, "advance_one", fake_advance)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    # Pick the sub-01 fmriprep option explicitly.
    target = [o for o in at.selectbox[0].options if "sub-01" in o and "run fmriprep" in o][0]
    at.selectbox[0].set_value(target).run()
    run_btn = [b for b in at.button if b.label.startswith("▶ Run")][0]
    run_btn.click().run()
    assert not at.exception
    assert calls["stage"] == "fmriprep"
    assert calls["subject"] == "01"
    assert calls["session"] == ""
    # fMRIPrep params are threaded through from the widgets.
    assert "nprocs" in calls["params"] and "output_spaces" in calls["params"]


def test_bulk_run_gated_by_confirm(project, monkeypatch):
    calls = []

    def fake_advance(config, stage, subject, session="", *, export_only=False, **params):
        calls.append((stage, subject, session))
        return "J"

    monkeypatch.setattr(P, "advance_one", fake_advance)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    bulk_btn = [b for b in at.button if b.label.startswith("▶▶ Run all")][0]
    assert bulk_btn.disabled  # gated until the confirm checkbox is ticked

    confirm = [c for c in at.checkbox if c.label.startswith("Yes —")][0]
    confirm.set_value(True).run()
    bulk_btn = [b for b in at.button if b.label.startswith("▶▶ Run all")][0]
    assert not bulk_btn.disabled
    bulk_btn.click().run()
    assert not at.exception
    # Default bulk stage is 'converted' (sorted first) → only sub-02 is ready.
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


def test_running_job_shows_badge_and_blocks_rerun(project, monkeypatch):
    monkeypatch.setattr(
        P, "list_jobs",
        lambda: [JobInfo(job_id="1", name="fmriprep_01", state="RUNNING", partition="c")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # Matrix cell shows the live badge…
    df = at.dataframe[0].value
    cell = df.loc[df["sub"] == "01", "fmriprep"].iloc[0]
    assert "running" in cell
    # …and the launch selector no longer offers to re-run sub-01 fmriprep.
    opts = at.selectbox[0].options
    assert not any("sub-01" in o and "run fmriprep" in o for o in opts)
