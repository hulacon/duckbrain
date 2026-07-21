"""`use_sessions` accepts both a TOML boolean and the GUI's string form.

Two bugs, found by opening a real project (`mmm_fmap_check`, whose config carries
`use_sessions = true`) in the GUI:

1. The Setup page indexed the raw value into `["auto", "true", "false"]`, so a
   Python `True` raised ValueError and took the page down.
2. `bool("false")` is `True`, so a project that turned sessions *off* through the
   GUI got `ses-` entities anyway — the option silently did the opposite of what
   it said.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project
from duckbrain.core.ingestion import (
    SessionInfo,
    auto_number_sessions,
    normalize_use_sessions,
)

SETUP_PAGE = "src/duckbrain/gui/pages/1_Project_Setup.py"


def _sessions():
    """Two subjects, one session each — so "auto" would omit the ses- entity."""
    return [
        SessionInfo(
            folder_name=f"STUDY_{sub}_2022010{i}_100000",
            path=None,
            parsed_subject=sub,
            parsed_session="",
            date=f"2022010{i}",
        )
        for i, sub in enumerate(("001", "002"), start=1)
    ]


# ---- the normalizer ----


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "true"),
        (False, "false"),
        ("true", "true"),
        ("false", "false"),
        ("TRUE", "true"),
        (" False ", "false"),
        ("yes", "true"),
        ("no", "false"),
        ("auto", "auto"),
        ("", "auto"),
        (None, "auto"),
        ("nonsense", "auto"),  # unrecognized falls back to the safe default
    ],
)
def test_normalize_use_sessions(value, expected):
    assert normalize_use_sessions(value) == expected


# ---- the behaviour that was silently inverted ----


def test_string_false_turns_sessions_off():
    """The regression: bool("false") is True, so this used to emit ses- anyway."""
    mappings = auto_number_sessions(_sessions(), use_sessions="false")
    assert all(m.bids_session == "" for m in mappings)


def test_string_and_boolean_true_agree():
    for value in (True, "true"):
        mappings = auto_number_sessions(_sessions(), use_sessions=value)
        assert all(m.bids_session == "01" for m in mappings), value


def test_boolean_false_still_turns_sessions_off():
    mappings = auto_number_sessions(_sessions(), use_sessions=False)
    assert all(m.bids_session == "" for m in mappings)


def test_auto_is_unchanged_by_the_normalizer():
    # Single session per subject -> no ses- entity, as before.
    assert all(m.bids_session == "" for m in auto_number_sessions(_sessions()))


# ---- the page that crashed ----


@pytest.fixture
def project(tmp_path):
    def _make(use_sessions):
        proj = tmp_path / "proj"
        scaffold_project(str(proj))
        save_project_config(
            str(proj),
            {"project": {"name": "test", "use_sessions": use_sessions}},
        )
        os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
        return proj

    yield _make
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def _run_setup(proj):
    """Run the Setup page with *proj* already open.

    The page gates its settings section on ``session_state["project_dir"]`` (the
    env var alone only seeds the picker's default), so the test opens the project
    the same way clicking "Open / Create Project" would.
    """
    at = AppTest.from_file(SETUP_PAGE, default_timeout=60)
    at.session_state["project_dir"] = str(proj)
    return at.run()


def _use_sessions_widget(at):
    return next(s for s in at.selectbox if "session entity" in s.label)


@pytest.mark.parametrize(
    "stored,expected", [(True, "true"), (False, "false"), ("auto", "auto")]
)
def test_setup_page_loads_toml_boolean(project, stored, expected):
    at = _run_setup(project(stored))
    assert not at.exception
    assert _use_sessions_widget(at).value == expected


def test_setup_page_surfaces_an_unrecognized_value(project):
    at = _run_setup(project("ture"))  # a plausible typo
    assert not at.exception
    assert _use_sessions_widget(at).value == "auto"
    assert any("isn't a value duckbrain recognizes" in w.value for w in at.warning)
