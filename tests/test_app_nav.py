"""Entrypoint navigation — declarative top nav + the active-project bar.

``gui/app.py`` moved off the filesystem ``pages/`` convention onto
``st.navigation(position="top")`` so the nav sits along the top and leaves the
left side free. These lock in the parts that would fail silently: that every
declared page file actually exists, that Status is the landing page, and that the
project bar (which replaced the sidebar indicator) renders and can switch.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import remember_project, scaffold_project
from duckbrain.gui.app import _PAGES, _PAGES_DIR, _shorten

APP = "src/duckbrain/gui/app.py"


@pytest.fixture
def user_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(tmp_path / "user.toml"))


@pytest.fixture(autouse=True)
def _no_ambient_project(monkeypatch):
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)


def test_every_declared_page_file_exists():
    """A typo'd filename would only surface as a 404 in the browser."""
    missing = [f for f, _ in _PAGES if not (_PAGES_DIR / f).is_file()]
    assert missing == []


def test_status_is_the_default_landing_page():
    # Status degrades gracefully with no project (it points at Setup), which is
    # what makes it safe as the default rather than a welcome screen detour.
    assert _PAGES[0][0] == "0_Project_Status.py"


def test_app_runs_and_shows_no_project_prompt(user_cfg):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("start in **Setup**" in c.value.lower() or
               "start in **setup**" in c.value.lower() for c in at.caption)


def test_project_bar_shows_the_active_project(user_cfg, tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(proj))

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any(str(proj) in c.value for c in at.caption)


def test_switcher_offers_other_recents_and_switches(user_cfg, tmp_path, monkeypatch):
    active, other = tmp_path / "active", tmp_path / "other"
    for p in (active, other):
        scaffold_project(str(p))
    remember_project(str(other))
    remember_project(str(active))
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(active))

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    keys = {b.key for b in at.button if b.key}
    assert f"_recent_{other}" in keys       # the other project is offered
    assert f"_recent_{active}" not in keys  # the active one is not

    at.button(key=f"_recent_{other}").click().run()
    assert not at.exception
    assert os.environ["DUCKBRAIN_PROJECT_DIR"] == str(other)


def test_shorten_keeps_enough_to_disambiguate():
    assert _shorten("/projects/hulacon/bhutch/divatten") == ".../bhutch/divatten"
    assert _shorten("/short") == "/short"
