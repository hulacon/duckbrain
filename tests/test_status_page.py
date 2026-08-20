"""Smoke/interaction tests for the Project Status page (the pipeline cockpit).

The board is an actionable grid: each (unit, stage) cell is a status icon that
upgrades to a popover when it has an action — ``▶`` to launch (keys ``runbtn_*``),
``🔴`` to view the SLURM log + re-run a failed stage (``rerun_*`` / ``dl_*``), and a
per-column header popover for bulk (``bulk_run_<stage>`` / ``bulk_confirm_<stage>``).

A cell popover computes its body **only while open** (`#42.2`), so a test that
wants what is inside one opens it first — :func:`_open_cell`, which writes the
open flag Streamlit parks in session state under the popover's key. That is the
same channel the browser uses, and it is why the flag doubles as the assertion
that a cell offered a popover at all: a gated cell registers no key.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

import duckbrain.core.pipeline as P
from conftest import page_path
from duckbrain.config import USER_CONFIG_ENV, save_project_config, scaffold_project
from duckbrain.slurm.monitor import JobInfo

PAGE = page_path("src/duckbrain/gui/pages/0_Project_Status.py")


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _btn_keys(at):
    return {b.key for b in at.button if b.key}


def _markdowns(at):
    return [m.value for m in at.markdown]


def _cell_key(stage, subject, session=""):
    return f"cellpop_{stage}_{subject}_{session}"


def _open_cell(at, stage, subject, session=""):
    """Rerun with one board cell's popover open.

    **Call it before every run that needs the body**, not once. A browser sends
    the popover's open flag back with each interaction; AppTest models no
    popover element, so the flag is a plain session-state write that survives
    exactly one run — a click inside an open cell would otherwise land on a run
    where the cell had closed again. So the shape for interacting is
    ``at.button(...).click()`` followed by ``_open_cell(...)``, which supplies
    both the flag and the rerun.
    """
    key = _cell_key(stage, subject, session)
    assert key in at.session_state, f"no popover on the {stage} cell for sub-{subject}"
    at.session_state[key] = True
    return at.run()


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    # Never read the developer's real ~/.config/duckbrain — it names a
    # containers_dir that exists on Talapas and on no CI runner, so a test that
    # inherited it would assert a property of the machine and pass here while
    # failing there. That is exactly how the validator tests broke the build for
    # four commits. `test_config.py` and `test_setup_page.py` already do this.
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "user_config.toml"))
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
    # sub-01 is converted → fmriprep runnable; sub-02 not converted → converted runnable.
    # A runnable cell is a popover; a complete or gated one is a plain icon, so the
    # registered keys say which cells carry an action without opening any of them.
    assert _cell_key("fmriprep", "01") in at.session_state
    assert _cell_key("converted", "02") in at.session_state
    assert _cell_key("converted", "01") not in at.session_state, "complete cell offered an action"
    # Closed, so nothing inside has run yet.
    assert "runbtn_fmriprep_01_" not in _btn_keys(at)

    _open_cell(at, "fmriprep", "01")
    assert "runbtn_fmriprep_01_" in _btn_keys(at)


def test_cell_run_button_invokes_advance_one(project, monkeypatch):
    calls = {}

    def fake_advance(config, stage, subject, session="", *, export_only=False, **params):
        calls.update(stage=stage, subject=subject, session=session, params=params)
        return "JOB1"

    monkeypatch.setattr(P, "advance_one", fake_advance)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    # The sub-01 fmriprep cell's popover run button.
    _open_cell(at, "fmriprep", "01")
    at.button(key="runbtn_fmriprep_01_").click()
    _open_cell(at, "fmriprep", "01")
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
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

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

    save_project_config(str(project), {"project": {"name": "test"}, "nordic": {"use_nordic": True}})
    deriv = project / "derivatives" / "fmriprep"
    deriv.mkdir(parents=True, exist_ok=True)
    (deriv / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "fMRIPrep",
                "GeneratedBy": [{"Name": "fMRIPrep", "Version": "24.1.1"}],
                "DatasetLinks": {"raw": str(project)},  # raw = project root, not the nordic tree
            }
        )
    )
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
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "55123")
    monkeypatch.setattr(
        P,
        "list_jobs",
        lambda: [
            JobInfo(
                job_id="55123",
                name="fmriprep_01",
                state="RUNNING",
                partition="c",
                nodes="n0042",
                time_used="00:12:03",
            )
        ],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    _open_cell(at, "fmriprep", "01")
    # The cell popover references the exact job with live detail…
    caps = [c.value for c in at.caption]
    assert any("55123" in c for c in caps)
    assert any("n0042" in c for c in caps)  # live node from squeue
    # …and there is no launch action for sub-01 fmriprep (no double-submit).
    assert "runbtn_fmriprep_01_" not in _btn_keys(at)


def test_running_cell_cancel_gated_and_invokes_scancel(project, monkeypatch):
    import duckbrain.slurm.monitor as M
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "55123")
    monkeypatch.setattr(
        P,
        "list_jobs",
        lambda: [JobInfo(job_id="55123", name="fmriprep_01", state="RUNNING", partition="c")],
    )
    cancelled = {}
    monkeypatch.setattr(M, "cancel_job", lambda jid: cancelled.setdefault("id", jid))

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    _open_cell(at, "fmriprep", "01")
    # Cancel is gated until the confirm box is ticked…
    assert at.button(key="cancel_fmriprep_01_").disabled
    at.checkbox(key="cancelchk_fmriprep_01_").set_value(True)
    _open_cell(at, "fmriprep", "01")
    assert not at.button(key="cancel_fmriprep_01_").disabled
    at.button(key="cancel_fmriprep_01_").click()
    _open_cell(at, "fmriprep", "01")
    assert not at.exception
    assert cancelled.get("id") == "55123"


def test_all_jobs_panel_lists_orphan_jobs(project, monkeypatch):
    # A job whose name maps to no board cell must still appear in the all-jobs panel.
    monkeypatch.setattr(
        P,
        "list_jobs",
        lambda: [JobInfo(job_id="80001", name="some_manual_job", state="RUNNING", partition="c")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any((df.value.astype(str) == "80001").any().any() for df in at.dataframe)
    assert any((df.value.astype(str) == "some_manual_job").any().any() for df in at.dataframe)


def test_failed_cell_exposes_log_and_rerun(project, monkeypatch):
    # sub-01 fmriprep reported failed by SLURM, with a recorded job + log on disk.
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "77001")
    log_dir = project / "code" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "fmriprep_77001.out").write_text("boom: a distinctive failure line\n")
    # A failed state comes from sacct history (squeue lists only active jobs).
    monkeypatch.setattr(
        P,
        "job_history",
        lambda days=7: [JobInfo(job_id="77001", name="fmriprep_01", state="FAILED", partition="c")],
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    _open_cell(at, "fmriprep", "01")
    # The failed cell's popover surfaces the SLURM log tail…
    assert any("distinctive failure line" in c.value for c in at.code)
    # …and offers a re-run + a download of the log.
    keys = _btn_keys(at)
    assert "rerun_fmriprep_01_" in keys
    assert any(b.key == "dl_stdout_fmriprep_01_" for b in at.download_button if b.key)


def test_failed_cell_shows_stderr_even_when_stdout_is_not_empty(project, monkeypatch):
    """The popover chose `stdout or stderr`, so stderr appeared only when stdout
    was entirely empty — and fMRIPrep always writes a stdout banner. The reason
    the job died was unreachable from the cell reporting that it died."""
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "fmriprep", "01", "", "77002")
    log_dir = project / "code" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "fmriprep_77002.out").write_text("fMRIPrep starting: banner line\n")
    (log_dir / "fmriprep_77002.err").write_text("Traceback: the actual reason\n")
    monkeypatch.setattr(
        P,
        "job_history",
        lambda days=7: [JobInfo(job_id="77002", name="fmriprep_01", state="FAILED", partition="c")],
    )

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    _open_cell(at, "fmriprep", "01")

    rendered = [c.value for c in at.code]
    assert any("the actual reason" in c for c in rendered), "stderr was not shown"
    assert any("banner line" in c for c in rendered), "stdout was dropped instead"


def test_a_closed_cell_reads_no_logs_and_walks_no_derivatives(project, monkeypatch):
    """`#42.2`: the popover body is the expensive part of the board.

    Streamlit's default popover computes its content on every render and ships
    it closed, so a 100-subject board globbed and read SLURM logs for every
    running cell and walked the derivatives tree twice for every runnable
    fMRIPrep cell — all of it for content nobody had opened. Counted at the two
    filesystem calls rather than at a wall-clock number, which would only
    measure this machine.
    """
    import duckbrain.core.fmriprep as F
    import duckbrain.slurm.monitor as M
    from duckbrain.config import load_config
    from duckbrain.core.pipeline import record_submission

    cfg = load_config(project_dir=str(project))
    record_submission(cfg, "mriqc", "01", "", "88001")
    monkeypatch.setattr(
        P,
        "job_history",
        lambda days=7: [JobInfo(job_id="88001", name="mriqc_01", state="FAILED", partition="c")],
    )

    calls = []
    real_job_log, real_has_anat = M.job_log, F.has_anat_derivatives
    monkeypatch.setattr(
        M, "job_log", lambda *a, **k: (calls.append("job_log"), real_job_log(*a, **k))[1]
    )
    monkeypatch.setattr(
        F,
        "has_anat_derivatives",
        lambda *a, **k: (calls.append("has_anat"), real_has_anat(*a, **k))[1],
    )

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # Both cells are on the board — one failed (log), one runnable (anat reuse).
    assert _cell_key("mriqc", "01") in at.session_state
    assert _cell_key("fmriprep", "01") in at.session_state
    assert calls == [], f"a closed popover did the work anyway: {calls}"

    _open_cell(at, "fmriprep", "01")
    assert "has_anat" in calls
    assert "job_log" not in calls, "opening one cell ran another cell's body"

    _open_cell(at, "mriqc", "01")
    assert "job_log" in calls


# ---- Declared expectations (TODO #16 Slice A) --------------------------------
#
# The declaration panel itself lives on the Project page and its display
# tests live with it (``test_project_page.py``). What stays pinned HERE is the
# reading side: the warnings a declaration drives render on this page, next to
# the board they judge.


def test_a_declared_shortfall_is_reported_in_the_warnings_panel(project):
    """sub-01 has one T1w and no BOLD, so a declaration asking for two runs of
    `rest` must produce a visible error on the cockpit."""
    save_project_config(
        str(project),
        {"expected": {"session": {"anat": {"T1w": 1}, "task": {"rest": 2}}}},
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    # A task absent entirely is an error, not a warning — and it must reach the UI
    # as one, since severity is only meaningful if the widget honours it.
    errors = [e.value for e in at.error]
    assert any("expected-task" in e and "sub-01" in e for e in errors)


def test_no_declaration_adds_no_warnings(project):
    """Opt-out at the display layer: a project that declares nothing must not
    gain a single new line on the page."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not [e.value for e in at.error if "expected-" in e.value]
    assert not [w.value for w in at.warning if "expected-" in w.value]


# ---- Outcome checks panel ----


def test_the_outcome_panel_measures_nothing_until_the_button_is_pressed(project, monkeypatch):
    """Same constraint as the validator panel, for the checks that open image
    data and parse reports: the fragment re-runs every 30 s, and a render may
    only read the snapshot and a fingerprint of stats."""
    import duckbrain.core.checks as C

    calls = []

    def fake(config):
        calls.append("ran")
        return C.CheckSnapshot(ran_at="2026-08-16T00:00:00", fingerprint={}, issues=())

    monkeypatch.setattr(C, "run_expensive_checks", fake)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert calls == [], "the outcome checks ran on a plain render"

    at.run()  # a second render, standing in for an auto-refresh tick
    assert calls == [], "the outcome checks ran on a re-render"

    assert "outcome_checks_btn" in _btn_keys(at)
    at.button(key="outcome_checks_btn").click().run()
    assert not at.exception
    assert calls == ["ran"]


def test_a_persisted_snapshot_renders_with_its_staleness_confessed(project):
    """The snapshot is duckbrain's only state store, and this is the term of its
    admission: a cached verdict whose inputs moved must say so on screen, never
    pass as current."""
    import json as J

    snap = {
        "ran_at": "2026-08-16T10:00:00",
        "fingerprint": {"outcome-sdc": "9:9", "outcome-nordic": "9:9"},  # matches nothing
        "issues": [
            {
                "check": "outcome-sdc",
                "message": "sub-01: preprocessed uncorrected",
                "severity": "warning",
                "subject": "01",
                "stage": "fmriprep",
            }
        ],
    }
    path = project / "code" / "logs" / "checks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(J.dumps(snap))

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    warnings = [w.value for w in at.warning]
    assert any("preprocessed uncorrected" in w for w in warnings)
    assert any("Inputs have changed since" in w for w in warnings)
