"""Entrypoint navigation — declarative top nav + the active-project bar.

``gui/app.py`` moved off the filesystem ``pages/`` convention onto
``st.navigation(position="top")`` so the nav sits along the top and leaves the
left side free. These lock in the parts that would fail silently: that every
declared page file actually exists, that the landing page is computed (Status
with a project open, Setup without), and that the project bar (which replaced
the sidebar indicator) renders and can switch.
"""

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import page_path
from duckbrain.config import remember_project, scaffold_project
from duckbrain.gui.app import _BIDS_PAGES, _PAGES, _PAGES_DIR, _QC_PAGES, _shorten

APP = page_path("src/duckbrain/gui/app.py")


@pytest.fixture
def user_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(tmp_path / "user.toml"))


@pytest.fixture(autouse=True)
def _no_ambient_project(monkeypatch):
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)


def test_every_declared_page_file_exists():
    """A typo'd filename would only surface as a 404 in the browser."""
    missing = [f for f, _ in [*_PAGES, *_BIDS_PAGES, *_QC_PAGES] if not (_PAGES_DIR / f).is_file()]
    assert missing == []


def test_the_bidsification_group_is_ingestion_conversion_project():
    """DICOMs in, a valid managed BIDS tree out — the two pages that do the
    work, then the one that manages what they produce. The deep
    links on Status and Ingestion navigate into the group, so a page falling
    out of it fails at click time on a page nobody tests by hand."""
    assert [f for f, _ in _BIDS_PAGES] == [
        "2_Data_Ingestion.py",
        "3_BIDS_Conversion.py",
        "3a_Project.py",
    ]

    import re

    declared = {f for f, _ in [*_PAGES, *_BIDS_PAGES, *_QC_PAGES]}
    for source_file in ("pages/0_Project_Status.py", "pages/2_Data_Ingestion.py"):
        source = (Path(__file__).parent.parent / "src/duckbrain/gui" / source_file).read_text()
        targeted = {Path(m).name for m in re.findall(r'"pages/([^"]+\.py)"', source)}
        assert targeted <= declared, f"navigated-to but not in the nav: {targeted - declared}"


def test_the_qc_group_is_exactly_overview_and_inspect():
    """Two QC pages since the rework: the cohort worklist and the run inspector.

    The domain taxonomy no longer maps to pages — it structures the inspector's
    sections instead — so what must not drift now is the pair of navigation
    targets the pages hand each other: ``st.switch_page``/``st.page_link`` to an
    unregistered page fails at click time, on a page nobody tests by hand.
    """
    assert [f for f, _ in _QC_PAGES] == ["5_QC_Overview.py", "5a_QC_Inspect.py"]

    import re

    declared = {f for f, _ in _QC_PAGES}
    source = (Path(__file__).parent.parent / "src/duckbrain/gui/qc_panels.py").read_text()
    targeted = {Path(m).name for m in re.findall(r'"pages/(5[^"]+\.py)"', source)}
    assert targeted <= declared, f"navigated-to but not in the nav: {targeted - declared}"


def test_the_qc_group_leads_with_the_overview():
    """It is the only QC page that shows the whole cohort, so it is the way in."""
    assert _QC_PAGES[0][0] == "5_QC_Overview.py"


def test_status_leads_the_bar():
    # The cockpit is the daily page, so it leads the bar even when a
    # project-less session lands on Setup instead.
    assert _PAGES[0][0] == "0_Project_Status.py"


def test_a_projectless_session_lands_on_setup(user_cfg):
    """The default page is computed, not fixed. With nothing open there
    is no cockpit to show, so the landing is the page that can open one."""
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Project Setup" in t.value for t in at.title)


def test_a_session_with_a_project_lands_on_status(user_cfg, tmp_path, monkeypatch):
    """The other half of the computed default: a returning user with an active
    project wants the cockpit, not a Setup detour."""
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(proj))

    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Project Status" in t.value for t in at.title)


def test_app_runs_and_shows_no_project_prompt(user_cfg):
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any(
        "start in **Setup**" in c.value.lower() or "start in **setup**" in c.value.lower()
        for c in at.caption
    )


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
    assert f"_recent_{other}" in keys  # the other project is offered
    assert f"_recent_{active}" not in keys  # the active one is not

    at.button(key=f"_recent_{other}").click().run()
    assert not at.exception
    assert os.environ["DUCKBRAIN_PROJECT_DIR"] == str(other)


def test_the_bar_shows_which_version_is_running(user_cfg):
    """The checkout is what runs, and it is what a bug report has to quote.

    Distribution is ``git clone`` from a working copy, so "which duckbrain" has no
    answer short of the commit — ``__version__`` names only the last release.
    """
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception

    from duckbrain.core.bids_metadata import duckbrain_version

    assert any(duckbrain_version() in c.value for c in at.caption)


def test_a_newer_release_becomes_a_link_and_silence_stays_silent(monkeypatch):
    """The notice appears only when something newer is *known* to exist.

    ``update_available`` returns ``None`` for "current" and for "could not reach
    GitHub" alike, so the bar must never render an all-clear off it — a user told
    they are up to date by a check that failed is worse off than one told nothing.
    """
    from duckbrain.gui import app

    monkeypatch.setattr(app, "_newer_release", lambda: ("v9.9.0", "https://example.invalid/r"))
    note = app._version_note()
    assert "v9.9.0" in note and "https://example.invalid/r" in note

    monkeypatch.setattr(app, "_newer_release", lambda: None)
    quiet = app._version_note()
    assert "available" not in quiet
    assert "up to date" not in quiet.lower()


def test_shorten_keeps_enough_to_disambiguate():
    assert _shorten("/projects/hulacon/bhutch/divatten") == ".../bhutch/divatten"
    assert _shorten("/short") == "/short"
