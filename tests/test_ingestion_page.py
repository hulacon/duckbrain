"""Regression test for the Data Ingestion page's session-editor state.

Auto-assigned BIDS subjects/sessions must survive an unrelated rerun (e.g. the
user ticking a checkbox); previously the table was rebuilt empty every rerun.
AppTest cannot drive st.data_editor directly, so we assert on the backing
session_state dataframe, which is what the editor renders from.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from conftest import page_path
from duckbrain.config import save_project_config, scaffold_project

PAGE = page_path("src/duckbrain/gui/views/2_Data_Ingestion.py")


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    src = proj / "dcmsrc"
    for sub, dt in [("001", "20220101_100000"), ("002", "20220102_100000")]:
        folder = src / f"TEST_{sub}_{dt}"
        (folder / "Series_01_T1w").mkdir(parents=True)
        (folder / "Series_02_bold").mkdir(parents=True)
    save_project_config(
        str(proj),
        {"project": {"name": "test", "use_sessions": "auto"}, "dcm_source": {"dir": str(src)}},
    )
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def _subjects(at):
    return list(at.session_state["ingest_df"]["bids_subject"])


def test_auto_assign_persists_across_rerun(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert _subjects(at) == ["", ""]

    next(b for b in at.button if "Auto-assign" in b.label).click().run()
    assert not at.exception
    assert _subjects(at) == ["01", "02"]
    rev = at.session_state["_editor_rev"]

    # An unrelated rerun must NOT clear the assignment (the reported bug).
    at.run()
    assert not at.exception
    assert _subjects(at) == ["01", "02"]
    # ...and the editor key stays stable so manual edits aren't dropped either.
    assert at.session_state["_editor_rev"] == rev


def test_the_auto_assign_message_survives_an_edit(project):
    """F27: the message vanished on the next rerun and the table jumped up
    under the pointer between two clicks."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    next(b for b in at.button if "Auto-assign" in b.label).click().run()
    assert any("Auto-assigned 2 subject(s)" in s.value for s in at.success)
    at.run()  # stands in for a cell edit
    assert any("Auto-assigned 2 subject(s)" in s.value for s in at.success)


def test_a_thin_pilot_folder_is_left_blank_and_says_why(project):
    pilot = project / "dcmsrc" / "TEST_000_20211231_100000" / "Series_01_localizer"
    pilot.mkdir(parents=True)
    for sub in ("001", "002"):
        for extra in ("Series_03_dwi", "Series_04_fmap", "Series_05_bold"):
            (next((project / "dcmsrc").glob(f"TEST_{sub}_*")) / extra).mkdir()
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    next(b for b in at.button if "Auto-assign" in b.label).click().run()
    assert not at.exception
    df = at.session_state["ingest_df"]
    row = df[df["folder_name"].str.startswith("TEST_000")].iloc[0]
    assert row["bids_subject"] == ""
    assert "Pilot or phantom" in row["notes"]
    assert sorted(df["bids_subject"]) == ["", "01", "02"]
    assert any("look like a pilot or phantom" in w.value for w in at.warning)


def test_single_session_leaves_bids_session_blank(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    next(b for b in at.button if "Auto-assign" in b.label).click().run()
    assert not at.exception
    assert list(at.session_state["ingest_df"]["bids_session"]) == ["", ""]
    assert any("single-session" in s.value.lower() for s in at.success)


def _ingest_first_folder(project):
    from duckbrain.core.ingestion import BidsMapping, SessionInfo, ingest_session

    src = next((project / "dcmsrc").glob("TEST_001_*"))
    session = SessionInfo(
        folder_name=src.name, parsed_subject="001", parsed_session="", date="", path=src
    )
    ingest_session(session, BidsMapping(src.name, "001", ""), project / "sourcedata")
    return src.name


def test_imported_badge_marks_already_ingested_rows(project):
    """#38: a source folder already in sourcedata badges with its destination."""
    ingested_folder = _ingest_first_folder(project)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    df = at.session_state["ingest_df"]
    badges = dict(zip(df["folder_name"], df["imported"], strict=True))
    assert "sub-001" in badges[ingested_folder]
    other = next(f for f in badges if f != ingested_folder)
    assert badges[other] == ""


def test_imported_badge_refreshes_without_a_table_rebuild(project):
    """An ingest changes sourcedata but not the discovered folder set, so the
    badge must update on a plain rerun rather than waiting for a rebuild."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert list(at.session_state["ingest_df"]["imported"]) == ["", ""]

    ingested_folder = _ingest_first_folder(project)

    at.run()
    assert not at.exception
    df = at.session_state["ingest_df"]
    badges = dict(zip(df["folder_name"], df["imported"], strict=True))
    assert "sub-001" in badges[ingested_folder]
