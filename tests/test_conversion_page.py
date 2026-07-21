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
