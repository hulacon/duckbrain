"""Conversion page: the plan surfaces the outcome, and the JSON override is explicit.

Covers TODO #13. Two things worth a regression test rather than an eyeball:
the page must show the *predicted BIDS filenames* alongside the inputs, and the
raw-JSON editor must not silently take over from the tables (it used to, because
the text area kept its own widget state).
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/3_BIDS_Conversion.py"

# One anat, a complete AP/PA pair, and a bold the classifier reads as func on its
# own — the minimum that exercises naming, the fieldmap relation, and a drop.
SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_ap"),
    ("04", "se_epi_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
]


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(
        str(proj),
        {"project": {"name": "test", "use_sessions": "auto"}},
    )
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def _tables(at):
    return [df.value for df in at.dataframe]


def _plan_table(at):
    """The Conversion Plan table — the only one carrying a 'becomes' column."""
    for table in _tables(at):
        if "becomes" in getattr(table, "columns", []):
            return table
    raise AssertionError("no plan table rendered")


def test_page_shows_predicted_bids_filenames(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    plan = _plan_table(at)
    becomes = dict(zip(plan["Series #"], plan["becomes"]))

    assert becomes[2] == "sub-001_ses-01_T1w.nii.gz"
    assert becomes[9] == "sub-001_ses-01_task-perFace_run-1_bold.nii.gz"
    # The scout is claimed by no description, and says so rather than vanishing.
    assert becomes[1] == "— not converted"


def test_plan_shows_which_pair_corrects_the_run(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    plan = _plan_table(at)
    fmap = dict(zip(plan["Series #"], plan["fieldmap"]))

    # One unnamed pair: the bold and both fieldmaps carry the same token.
    assert fmap[9] == fmap[3] == fmap[4]
    assert fmap[9].startswith("🔵")
    # Colour is never the only channel — the label rides along with it.
    assert "unnamed" in fmap[9]
    # Anat has no fieldmap relation at all, so no token.
    assert fmap[2] == ""


def test_clean_session_reports_no_blocking_problem(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not at.error
    assert any("will be written" in s.value for s in at.success)


def test_json_override_is_off_by_default_and_must_be_opted_into(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    override = next(
        c for c in at.checkbox if c.key == "dcm2bids_json_override"
    )
    assert override.value is False
    # Off: no editable text area, so the tables cannot be silently overridden.
    assert not [t for t in at.text_area if t.key == "dcm2bids_config_editor"]

    override.set_value(True).run()
    assert not at.exception
    assert [t for t in at.text_area if t.key == "dcm2bids_config_editor"]
    # And the takeover is stated rather than left to be discovered.
    assert any("no longer drive" in w.value for w in at.warning)


# ---- the unified table (TODO #13 phase 6) ----

TWO_PAIR_SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_ap"),
    ("04", "se_epi_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
    ("19", "cmrr_mbep2d_bold_task-perFace_run-2"),
    ("30", "se_epi_ap"),
    ("32", "se_epi_pa"),
]
EDITOR_KEY = "conversion_editor_001_01"


@pytest.fixture
def two_pair_project(tmp_path):
    """A pair re-shot mid-task: run 1 before it, run 2 after."""
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in TWO_PAIR_SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "auto"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_one_table_carries_every_decision_and_the_outcome(two_pair_project):
    """The three per-series tables are now one; these are its columns."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert not at.exception
    assert list(_plan_table(at).columns) == [
        "Series #", "Description", "Type", "# Files",
        "task", "run", "fieldmap", "becomes",
    ]


def test_fieldmap_rows_carry_their_own_pair_token(two_pair_project):
    """The relation reads off a single row in both directions, not across tables."""
    plan = _plan_table(at := AppTest.from_file(PAGE, default_timeout=90).run())
    assert not at.exception
    fmap = dict(zip(plan["Series #"], plan["fieldmap"]))

    # The two pairs get distinct, stable tokens...
    assert fmap[3] == fmap[4]
    assert fmap[30] == fmap[32]
    assert fmap[3] != fmap[30]
    # ...and by default both runs take the first complete pair.
    assert fmap[9] == fmap[19] == fmap[3]


def test_two_runs_of_one_task_can_take_different_pairs(two_pair_project):
    """The case the granularity decision was made for, end to end through the GUI."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    second_pair = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[30]

    # Row 5 is series 19 — run 2, acquired after the re-shoot.
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"fieldmap": second_pair}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert not at.error

    fmap = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))
    assert fmap[19] == second_pair
    assert fmap[9] != second_pair  # run 1 keeps the original pair


def test_editing_a_task_updates_becomes_in_the_same_rerun(two_pair_project):
    """`becomes` is computed from this run's edits, not a rerun behind them."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"task": "renamed"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[9] == "sub-001_ses-01_task-renamed_run-1_bold.nii.gz"


def test_a_task_run_collision_is_reported_as_an_error(two_pair_project):
    """Two runs given the same number would silently lose one file."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"run": 1}},  # series 19 -> run 1, colliding with series 9
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert any("same file" in e.value for e in at.error)


# ---- TODO #17.5 / #17.6: the page must describe the config that will ship -----

def _override_with(at, config_dict):
    """Turn the hand-edit override on and put *config_dict* in the text area."""
    import json

    at.session_state["dcm2bids_json_override"] = True
    at.session_state["dcm2bids_config_editor"] = json.dumps(config_dict)
    return at.run()


def test_override_reconciles_the_table_instead_of_leaving_it_stale(project):
    """With the JSON driving, the decision columns must show what the JSON says.

    They used to keep showing table state and stayed editable, so `task`, `run`
    and `fieldmap` were three controls that silently did nothing while a
    different config shipped.
    """
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    baseline = _plan_table(at)
    assert "perFace" in list(baseline["task"])

    at = _override_with(at, {"descriptions": [{
        "id": "func-bold-renamed", "datatype": "func", "suffix": "bold",
        "criteria": {"SeriesNumber": 9},
        "custom_entities": "task-renamed_run-1",
        "sidecar_changes": {"TaskName": "renamed"},
    }]})
    assert not at.exception

    table = _plan_table(at)
    assert "renamed" in list(table["task"]), (
        "the table still shows its own task while the JSON ships a different one"
    )
    # And `becomes` agrees with it — both now read from the same config.
    assert any("task-renamed" in str(b) for b in table["becomes"])


def test_override_state_is_announced_above_the_table(project):
    """The only notice used to live inside a collapsed expander at the bottom."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at = _override_with(at, {"descriptions": []})
    assert not at.exception
    blurb = " ".join(i.value for i in at.info) + " ".join(m.value for m in at.markdown)
    assert "hand-edited JSON" in blurb


def test_a_saved_config_is_surfaced_because_bulk_convert_uses_it(project):
    """`_build_dcm2bids` reuses a saved dcm2bids_config.json and only generates
    one when absent, so a saved review is what actually runs. The page wrote that
    file and never read it, so a reviewed session reopened looking unreviewed."""
    import json

    saved = (project / "sourcedata" / "sub-001" / "ses-01" / "dcm2bids_config.json")
    saved.write_text(json.dumps({"descriptions": []}))

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("reviewed config" in i.value for i in at.info), (
        "a saved config on disk — the one bulk convert will use — is not mentioned"
    )


# ---- DB-005: per-session submit is the same operation as bulk submit ---------

def _button(at, label):
    for b in at.button:
        if b.label == label:
            return b
    raise AssertionError(f"no button {label!r}; have {[b.label for b in at.button]}")


def test_per_session_submit_records_provenance_like_the_bulk_path(project, monkeypatch):
    """The most-used conversion path wrote no submission record at all.

    This page rendered and submitted its own sbatch, skipping `advance_one` and
    so `record_submission` — so the run had no provenance row, and the cockpit
    had no job id to hang a log viewer or a cancel button off. Its cells said
    "No job id recorded for this unit/stage" for every conversion launched here.
    """
    import duckbrain.slurm.submit as S

    monkeypatch.setattr(S, "submit_job", lambda *a, **kw: "424242")
    import duckbrain.core.pipeline as P
    monkeypatch.setattr(P, "submit_job", lambda *a, **kw: "424242")

    at = AppTest.from_file(PAGE, default_timeout=90).run()
    _button(at, "Submit Conversion Job").click().run()
    assert not at.exception

    log = project / "code" / "logs" / "submissions.tsv"
    assert log.exists(), "no durable submission record was written"
    rows = log.read_text().strip().splitlines()
    assert len(rows) >= 2                       # header + the run
    assert "424242" in rows[-1]
    assert "dcm2bids" in rows[-1]


def test_export_only_submits_nothing_and_records_nothing(project, monkeypatch):
    """Export is a dry run; it must not look like a launch in the record."""
    import duckbrain.core.pipeline as P

    def _boom(*a, **kw):
        raise AssertionError("export must not submit")

    monkeypatch.setattr(P, "submit_job", _boom)

    at = AppTest.from_file(PAGE, default_timeout=90).run()
    _button(at, "Export SBATCH Script").click().run()
    assert not at.exception

    assert not (project / "code" / "logs" / "submissions.tsv").exists()
    assert list((project / "code" / "logs").glob("dcm2bids_*.sbatch"))
