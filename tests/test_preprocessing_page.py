"""The Preprocessing page: guards, target expansion, and what reaches ``advance_one``.

Almost every test here stubs ``advance_one``. The page's job is to call the right
stage, for the right units, with the parameters the user set — that boundary is
what a page test can assert and ``test_pipeline.py`` already covers what happens
on the far side of it. Going through the real ``advance_one`` for fMRIPrep would
drag in ``_fsaverage_preflight``, which shells into a container.

One test (``test_mriqc_submit_renders_a_real_sbatch``) does run the real thing,
via MRIQC — the only stage with no fsaverage preflight and no FreeSurfer licence
— so that the page-to-SLURM wiring is exercised end to end at least once.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import USER_CONFIG_ENV, save_project_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/4_Preprocessing.py"


def _bold(project, subject, session, count=1):
    """Create *count* BOLD files for a unit, making the sub-/ses- tree as needed."""
    func = project / f"sub-{subject}"
    if session:
        func = func / f"ses-{session}"
    func = func / "func"
    func.mkdir(parents=True, exist_ok=True)
    stem = f"sub-{subject}" + (f"_ses-{session}" if session else "")
    for run in range(1, count + 1):
        (func / f"{stem}_task-rest_run-{run}_bold.nii.gz").touch()


def _isolate(proj, tmp_path):
    """Point duckbrain at *proj* and away from the developer's own user config.

    The second half is not optional: this box has a real ``~/.config/duckbrain``
    naming a ``containers_dir`` that exists here and does not on a CI runner
    (``memory/local-tests-are-not-ci-tests``).
    """
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    os.environ[USER_CONFIG_ENV] = str(tmp_path / "no-such-user-config.toml")


def _clear():
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)
    os.environ.pop(USER_CONFIG_ENV, None)


@pytest.fixture
def project(tmp_path):
    """Two subjects that do NOT share a session — sub-01 has both, sub-02 only ses-02.

    The asymmetry is the point: it is what makes the target-expansion tests
    (a subject dropped because the selection misses its sessions) possible.
    """
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    _bold(proj, "01", "01", count=2)
    _bold(proj, "01", "02", count=1)
    _bold(proj, "02", "02", count=3)
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "yes"}})
    _isolate(proj, tmp_path)
    yield proj
    _clear()


@pytest.fixture
def single_session(tmp_path):
    """Two subjects with no ``ses-`` level at all."""
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    _bold(proj, "01", "")
    _bold(proj, "02", "")
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "no"}})
    _isolate(proj, tmp_path)
    yield proj
    _clear()


@pytest.fixture
def calls(monkeypatch):
    """Record every ``advance_one`` call and return a fake job id.

    Patched on the module, not on the page: the page does its
    ``from duckbrain.core.pipeline import advance_one`` inside the submit branch,
    at call time, so the module attribute is what it resolves.
    """
    recorded = []

    def _fake(config, stage, subject, session="", **params):
        recorded.append((stage, subject, session, params))
        return "424242"

    monkeypatch.setattr("duckbrain.core.pipeline.advance_one", _fake)
    return recorded


def _pick(at, key, values):
    """Set a multiselect and rerun, so widgets gated on it appear."""
    at.multiselect(key=key).set_value(values).run()
    return at


def _texts(elements):
    return [e.value for e in elements]


def _rows(at):
    """The results table, as a list of row dicts."""
    assert len(at.dataframe) == 1, f"expected one results table, got {len(at.dataframe)}"
    return at.dataframe[0].value.to_dict("records")


# ---- guards and early stops -------------------------------------------------


def test_missing_base_config_stops_before_the_tabs(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKBRAIN_CONFIG_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("Project Setup" in e.value for e in at.error)
    assert not at.tabs


def test_no_bids_dir_reports_it(tmp_path, monkeypatch):
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "no-such-user-config.toml"))
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("BIDS directory not found" in e.value for e in at.error)


def test_bids_tree_with_no_subjects_warns(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "test"}})
    _isolate(proj, tmp_path)
    try:
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert any("No subjects found" in w.value for w in at.warning)
    finally:
        _clear()


def test_render_creates_the_log_dir(project):
    logs = project / "code" / "logs"
    logs.rmdir()
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert logs.is_dir(), "log_dir must exist before any job writes a script into it"


def test_all_three_tabs_render(project):
    """Pins the get_slurm_resources import being above the tabs.

    It used to be imported inside the fMRIPrep tab and read by the other two, so
    an early exit there turned NORDIC and MRIQC into a NameError.
    """
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert len(at.tabs) == 3
    assert {b.label for b in at.button} >= {
        "Submit fMRIPrep Jobs",
        "Submit NORDIC Jobs",
        "Submit MRIQC Jobs",
    }


# ---- session pickers and target expansion -----------------------------------


def test_single_session_study_offers_no_session_picker(single_session):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01"])
    assert not at.exception
    assert any("Single-session study" in c.value for c in at.caption)
    with pytest.raises(KeyError):
        at.multiselect(key="fp_sessions")


def test_session_options_are_the_union_over_selected_subjects(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["02"])
    assert at.multiselect(key="fp_sessions").options == ["02"]

    _pick(at, "fp_subjects", ["01", "02"])
    assert at.multiselect(key="fp_sessions").options == ["01", "02"]


def test_submit_fans_out_over_every_subject_session_pair(project, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01", "02"])
    _pick(at, "fp_sessions", ["01", "02"])
    at.button(key="fp_submit").click().run()
    assert not at.exception
    # sub-01 has both sessions, sub-02 only ses-02 — so three units, not four.
    assert [(sub, ses) for _, sub, ses, _ in calls] == [("01", "01"), ("01", "02"), ("02", "02")]


def test_single_session_subject_submits_with_an_empty_session(single_session, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01"])
    at.button(key="fp_submit").click().run()
    assert not at.exception
    assert [(sub, ses) for _, sub, ses, _ in calls] == [("01", "")]


# ---- what reaches advance_one -----------------------------------------------


def test_fmriprep_submit_passes_every_option_the_user_set(project, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["02"])
    _pick(at, "fp_sessions", ["02"])
    at.text_input(key="fp_spaces").set_value("T1w fsnative")
    at.number_input(key="fp_nprocs").set_value(4)
    at.number_input(key="fp_mem").set_value(16)
    at.checkbox(key="fp_anat_only").set_value(True)
    at.checkbox(key="fp_use_derivatives").set_value(True)
    at.text_input(key="fp_extra_flags").set_value("--dummy-scans 2").run()

    at.button(key="fp_submit").click().run()
    assert not at.exception

    stage, sub, ses, params = calls[0]
    assert (stage, sub, ses) == ("fmriprep", "02", "02")
    assert params == {
        "export_only": False,
        "output_spaces": "T1w fsnative",
        "anat_only": True,
        "use_derivatives": True,
        "extra_flags": "--dummy-scans 2",
        "nprocs": 4,
        "mem_gb": 16,
    }


def test_export_sets_export_only_and_reports_a_path(project, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["02"])
    _pick(at, "fp_sessions", ["02"])
    at.button(key="fp_export").click().run()
    assert not at.exception

    assert calls[0][3]["export_only"] is True
    row = _rows(at)[0]
    assert row["status"] == "exported"
    assert row["path"] == "424242"
    assert "job_id" not in row


@pytest.mark.parametrize(
    ("stage", "subjects_key", "sessions_key", "submit_key"),
    [
        ("nordic", "nd_subjects", "nd_sessions", "nd_submit"),
        ("mriqc", "mq_subjects", "mq_sessions", "mq_submit"),
    ],
)
def test_nordic_and_mriqc_pass_nothing_but_export_only(
    project, calls, stage, subjects_key, sessions_key, submit_key
):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, subjects_key, ["02"])
    _pick(at, sessions_key, ["02"])
    at.button(key=submit_key).click().run()
    assert not at.exception
    assert calls == [(stage, "02", "02", {"export_only": False})]


# ---- validation -------------------------------------------------------------


def test_submit_without_a_subject_errors_and_launches_nothing(project, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at.button(key="fp_submit").click().run()
    assert not at.exception
    assert any("at least one subject" in e.value for e in at.error)
    assert calls == []


def test_submit_without_a_session_errors_and_launches_nothing(project, calls):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01"])
    at.button(key="fp_submit").click().run()
    assert not at.exception
    assert any("at least one session" in e.value for e in at.error)
    assert calls == []


# ---- failure reporting ------------------------------------------------------


def test_a_failing_unit_becomes_an_error_row_and_the_batch_goes_on(project, monkeypatch):
    """The anat-reuse precondition is the case this shape exists for.

    ``advance_one`` refuses rather than submitting a job that silently rebuilds
    the anat (``memory/silent-nooption-failures``). The page must surface that
    refusal per unit and still launch the units that are fine.
    """
    from duckbrain.core.pipeline import PipelineError

    def _fake(config, stage, subject, session="", **params):
        if subject == "01":
            raise PipelineError(f"sub-{subject} has no preprocessed anatomicals")
        return "424242"

    monkeypatch.setattr("duckbrain.core.pipeline.advance_one", _fake)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01", "02"])
    _pick(at, "fp_sessions", ["02"])
    at.checkbox(key="fp_use_derivatives").set_value(True).run()
    at.button(key="fp_submit").click().run()
    assert not at.exception

    rows = {r["subject"]: r for r in _rows(at)}
    assert rows["01"]["status"] == "error"
    assert "no preprocessed anatomicals" in rows["01"]["error"]
    assert rows["02"]["status"] == "submitted"
    assert rows["02"]["job_id"] == "424242"


def test_a_subject_the_selection_misses_is_named_not_dropped(project, calls):
    """sub-02 has only ses-02, so a ses-01 selection leaves it with no units.

    It used to vanish from the batch in silence: the user selected two subjects,
    one job was launched, and the table looked like a complete run. Naming it is
    the whole fix.
    """
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01", "02"])
    _pick(at, "fp_sessions", ["01"])
    at.button(key="fp_submit").click().run()
    assert not at.exception

    assert [(sub, ses) for _, sub, ses, _ in calls] == [("01", "01")]
    assert any("sub-02" in w.value for w in at.warning)
    assert [r["subject"] for r in _rows(at)] == ["01"]


def test_changing_subjects_clears_a_session_that_no_longer_applies(project, calls):
    """Streamlit's own doing, and it is why the all-dropped case has no page path.

    The session multiselect offers only the union of the selected subjects'
    sessions, so when the subject selection changes under it the old value stops
    being an option and Streamlit clears it. The "select a session" guard then
    catches the submit. ``run_batch``'s empty-batch branch is tested directly in
    ``test_preproc_panels.py`` instead.
    """
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "fp_subjects", ["01"])
    _pick(at, "fp_sessions", ["01"])
    _pick(at, "fp_subjects", ["02"])
    assert not at.exception
    assert at.session_state["fp_sessions"] == []

    at.button(key="fp_submit").click().run()
    assert any("at least one session" in e.value for e in at.error)
    assert calls == []


# ---- tab-specific display ---------------------------------------------------


def test_use_nordic_banner_appears_only_when_the_project_sets_it(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not any("use_nordic" in i.value for i in at.info)

    save_project_config(
        str(project),
        {"project": {"name": "test", "use_sessions": "yes"}, "nordic": {"use_nordic": True}},
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert any("use_nordic" in i.value for i in at.info)


def test_nordic_tab_previews_the_bold_count_per_unit(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "nd_subjects", ["01", "02"])
    _pick(at, "nd_sessions", ["01", "02"])
    assert not at.exception

    md = _texts(at.markdown)
    assert any("sub-01/ses-01: **2 BOLD runs**" in m for m in md)
    assert any("sub-01/ses-02: **1 BOLD runs**" in m for m in md)
    assert any("sub-02/ses-02: **3 BOLD runs**" in m for m in md)


# ---- one real trip through advance_one --------------------------------------


def test_mriqc_submit_renders_a_real_sbatch(project, tmp_path, monkeypatch):
    """Page -> advance_one -> rendered script -> submission log, for real.

    MRIQC because it is the only stage with neither an fsaverage preflight nor a
    FreeSurfer licence requirement, so a container image and a runtime on PATH
    are the whole of what has to be pinned.
    """
    import duckbrain.core.pipeline as P

    containers = tmp_path / "containers"
    containers.mkdir()
    (containers / "mriqc-24.0.2.sif").write_bytes(b"")
    user_config = tmp_path / "user.toml"
    user_config.write_text(
        f'[paths]\ncontainers_dir = "{containers}"\n\n[containers]\nmriqc_version = "24.0.2"\n'
    )
    os.environ[USER_CONFIG_ENV] = str(user_config)
    monkeypatch.setattr(
        "shutil.which", lambda name: f"/usr/bin/{name}" if name == "apptainer" else None
    )

    submitted = []

    def _fake_submit(script, job_name, scripts_dir=None):
        submitted.append((script, job_name))
        return "55123"

    monkeypatch.setattr(P, "submit_job", _fake_submit)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    _pick(at, "mq_subjects", ["02"])
    _pick(at, "mq_sessions", ["02"])
    at.button(key="mq_submit").click().run()
    assert not at.exception

    assert len(submitted) == 1, "one unit selected, so exactly one job"
    script, job_name = submitted[0]
    assert job_name == "mriqc_02_02"
    assert "#!/bin/bash" in script
    assert "sub-02" in script
    assert str(containers / "mriqc-24.0.2.sif") in script

    assert _rows(at)[0]["job_id"] == "55123"
    log = project / "code" / "logs" / "submissions.tsv"
    assert log.exists(), "a submission must leave a durable record"
    assert "55123" in log.read_text()
