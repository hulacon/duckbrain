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
