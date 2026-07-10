"""Smoke/interaction tests for the Project Status page (surveyor dashboard)."""

import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/0_Project_Status.py"


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    # sub-01: ingested + converted; sub-02: ingested only.
    _touch(proj / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(proj / "sourcedata" / "sub-02" / "dicom" / "0001.dcm")
    _touch(proj / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    save_project_config(str(proj), {"project": {"name": "test"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_page_renders_matrix(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    # Overview metrics: one per stage (ingested/converted/fmriprep/mriqc).
    labels = [m.label for m in at.metric]
    assert {"Ingested", "Converted", "Fmriprep", "Mriqc"} <= set(labels)
    # Both subjects present in the rendered matrix.
    df = at.dataframe[0].value
    assert set(df["sub"]) == {"01", "02"}


def test_only_incomplete_filter(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    at.checkbox[0].set_value(True).run()
    assert not at.exception
    # sub-02 (no BIDS) is unfinished, so it must survive the filter.
    df = at.dataframe[0].value
    assert "02" in set(df["sub"])


def test_empty_project_shows_guidance(tmp_path):
    proj = tmp_path / "empty"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"project": {"name": "empty"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    try:
        at = AppTest.from_file(PAGE, default_timeout=60).run()
        assert not at.exception
        assert any("No subjects found" in i.value for i in at.info)
    finally:
        os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)
