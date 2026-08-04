"""The selection helpers, driven directly — no Streamlit, no AppTest.

These are the functions the extraction out of ``4_Preprocessing.py`` was for.
They used to close over a module global in a page script, which meant the only
way to reach them was to render the whole page; taking ``bids_path`` as an
argument is what makes a directory and three lines enough.
"""

import pytest

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
