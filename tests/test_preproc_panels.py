"""The selection helpers, driven directly — no Streamlit, no AppTest.

These are the functions the extraction out of ``4_Preprocessing.py`` was for.
They used to close over a module global in a page script, which meant the only
way to reach them was to render the whole page; taking ``bids_path`` as an
argument is what makes a directory and three lines enough.
"""

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.gui import preproc_panels as P


@pytest.fixture
def bids(tmp_path):
    """sub-01 with two sessions, sub-02 with one, sub-03 with no ses- level."""
    for rel in ("sub-01/ses-01", "sub-01/ses-02", "sub-02/ses-02", "sub-03/func"):
        (tmp_path / rel).mkdir(parents=True)
    (tmp_path / "sourcedata").mkdir()
    (tmp_path / "derivatives").mkdir()
    return tmp_path


def test_list_subjects_ignores_everything_that_is_not_a_subject(bids):
    assert P.list_subjects(bids) == ["01", "02", "03"]


def test_get_sessions_reads_the_ses_level(bids):
    assert P.get_sessions(bids, "01") == ["01", "02"]
    assert P.get_sessions(bids, "02") == ["02"]


def test_get_sessions_is_empty_without_a_ses_level(bids):
    assert P.get_sessions(bids, "03") == []


def test_get_sessions_of_an_absent_subject_is_empty(bids):
    """A stale selection must not raise; the subject dir may be gone."""
    assert P.get_sessions(bids, "99") == []


def test_targets_of_a_single_session_subject_is_one_unnamed_session(bids):
    assert P.targets(bids, "03", []) == [""]
    # The user's session selection is irrelevant to a subject that has none.
    assert P.targets(bids, "03", ["01", "02"]) == [""]


def test_targets_intersects_the_selection_with_what_the_subject_has(bids):
    assert P.targets(bids, "01", ["01", "02"]) == ["01", "02"]
    assert P.targets(bids, "01", ["02"]) == ["02"]


def test_targets_is_empty_when_the_selection_misses_the_subject(bids):
    """sub-02 has only ses-02, so a ses-01 selection leaves it with nothing.

    ``run_batch`` is what has to say so — see the reporting tests in
    ``test_preprocessing_page.py``.
    """
    assert P.targets(bids, "02", ["01"]) == []


def _batch(root, subjects, sessions, study_sessions):
    """Run in a fresh module by AppTest, so it closes over nothing and imports its own."""
    from pathlib import Path

    from duckbrain.gui import preproc_panels

    preproc_panels.run_batch(
        {},
        "mriqc",
        Path(root),
        subjects,
        sessions,
        study_sessions,
        submit=True,
        export=False,
    )


def test_a_batch_with_no_units_left_refuses_instead_of_rendering_an_empty_table(bids):
    """Driven directly: the Preprocessing page cannot reach this state.

    Its session multiselect only ever offers the union of the selected subjects'
    sessions, so a selection that matches no subject is caught by the earlier
    "select at least one session" guard (pinned in ``test_preprocessing_page.py``).
    ``run_batch`` is a module function, though, and any other caller can hand it
    this — an empty ``st.dataframe`` would say nothing at all.
    """
    at = AppTest.from_function(
        _batch,
        kwargs={
            "root": str(bids),
            "subjects": ["02"],
            "sessions": ["01"],
            "study_sessions": ["01"],
        },
        default_timeout=30,
    ).run()
    assert not at.exception

    assert any("sub-02" in w.value for w in at.warning)
    assert any("Nothing to launch" in e.value for e in at.error)
    assert not at.dataframe, "an empty results table explains nothing; don't render one"
