"""Every page that cannot run yet says so the same way (usability F15).

One plain sentence naming the missing step, and a link to the page that does
it, through ``components.not_ready``. Before the helper, Ingestion named config
keys (``dcm_source.dir``) and Conversion said "ingest data first" with no
project open, the first two pages a course student meets.
"""

import pytest
from streamlit.testing.v1 import AppTest

from conftest import page_path
from duckbrain.config import USER_CONFIG_ENV, save_project_config, scaffold_project

PAGES = [
    "0_Project_Status.py",
    "2_Data_Ingestion.py",
    "3_BIDS_Conversion.py",
    "3a_Project.py",
    "4_Preprocessing.py",
    "5_QC_Overview.py",
    "5a_QC_Inspect.py",
]
INGESTION = page_path("src/duckbrain/gui/views/2_Data_Ingestion.py")


def _run(page):
    return AppTest.from_file(page, default_timeout=60).run()


def _infos(at):
    return [i.value for i in at.info]


def _captions(at):
    return [c.value for c in at.caption]


@pytest.fixture
def no_project(tmp_path, monkeypatch):
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "no-such-user-config.toml"))


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "no-such-user-config.toml"))
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(proj))
    return proj


@pytest.mark.parametrize("filename", PAGES)
def test_with_no_project_open_every_page_points_at_setup(no_project, filename):
    at = _run(page_path(f"src/duckbrain/gui/views/{filename}"))
    assert not at.exception
    assert any("No project is open yet" in i for i in _infos(at)), _infos(at)
    assert "Go to Project Setup" in _captions(at)
    assert not at.error, [e.value for e in at.error]


def test_ingestion_without_a_dicom_source_asks_in_plain_words(project):
    save_project_config(str(project), {"project": {"name": "t"}})
    at = _run(INGESTION)
    assert not at.exception
    assert any("doesn't say where its DICOMs are" in i for i in _infos(at))
    assert "Go to Project Setup" in _captions(at)
    # The old message named config keys a student has never seen.
    assert not any("dcm_source" in m for m in _infos(at) + [e.value for e in at.error])


def test_ingestion_on_an_existing_bids_project_says_there_is_nothing_to_import(project):
    save_project_config(str(project), {"project": {"name": "t", "external_bids": True}})
    at = _run(INGESTION)
    assert not at.exception
    assert any("no DICOMs to import" in i for i in _infos(at))
    assert "Go to Status" in _captions(at)
    assert not at.error
