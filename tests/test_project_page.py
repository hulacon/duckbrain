"""The Project page — the dataset-management surface.

The page collects what used to straddle Status and Ingestion: metadata-file
generation, the BIDS validation panel, and the declared-expectations panel.
The panel tests moved here with their panels (they were written for the
cockpit's copy — see the #17 lesson in ``test_status_page.py``: every finding
was a display or a control, so the tests assert on what the page shows). The
expensive-work-only-behind-the-button property is re-pinned here because the
page it now lives on is new; the *warnings* the expectation checks drive still
render on Status, so their tests stayed there.
"""

import os

import pytest
from streamlit.testing.v1 import AppTest

from conftest import page_path
from duckbrain.config import USER_CONFIG_ENV, save_project_config, scaffold_project

PAGE = page_path("src/duckbrain/gui/pages/3a_Project.py")


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _btn_keys(at):
    return {b.key for b in at.button if b.key}


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    # Never read the developer's real ~/.config/duckbrain — it names a
    # containers_dir that exists on Talapas and on no CI runner, so a test that
    # inherited it would assert a property of the machine and pass here while
    # failing there (the validator tests broke the build for four commits that way).
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "user_config.toml"))
    scaffold_project(str(proj))
    _touch(proj / "sourcedata" / "sub-01" / "dicom" / "0001.dcm")
    _touch(proj / "sub-01" / "anat" / "sub-01_T1w.nii.gz")
    save_project_config(str(proj), {"project": {"name": "test"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_page_renders_all_three_sections(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("participants.tsv" in label for label in labels)
    assert any("dataset_description.json" in label for label in labels)
    expanders = [e.label for e in at.expander]
    assert any("BIDS validation" in label for label in expanders)
    assert any("Declared expectations" in label for label in expanders)


# ---- BIDS metadata files ----


def test_generate_participants_writes_the_tsv(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    participants_btn = next(b for b in at.button if "participants.tsv" in b.label)
    participants_btn.click().run()
    assert not at.exception
    tsv = project / "participants.tsv"
    assert tsv.exists()
    assert "sub-01" in tsv.read_text()


def test_generate_dataset_description_writes_the_json(project):
    import json

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    desc_btn = next(b for b in at.button if "dataset_description.json" in b.label)
    desc_btn.click().run()
    assert not at.exception
    desc = json.loads((project / "dataset_description.json").read_text())
    assert desc["Name"] == "test"


def test_generate_participants_external_project_rosters_the_bids_tree(project):
    """#41.3: a declared-external project has no sourcedata DICOMs — the roster
    comes from the tree's own sub-* dirs, demographics at n/a, not from an
    error telling the user to ingest something that will never exist."""
    save_project_config(str(project), {"project": {"external_bids": True}})
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    next(b for b in at.button if "participants.tsv" in b.label).click().run()
    assert not at.exception
    assert not at.error
    text = (project / "participants.tsv").read_text()
    assert "sub-01" in text
    assert "n/a" in text


def test_generate_participants_guard_tests_for_subjects_not_the_dir(project):
    """scaffold_project creates sourcedata/ empty in every project, so its mere
    existence must not pass the guard — that defeated it, and the button ran
    against nothing while reporting a benign warning."""
    import shutil

    shutil.rmtree(project / "sourcedata" / "sub-01")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    next(b for b in at.button if "participants.tsv" in b.label).click().run()
    assert not at.exception
    assert any("No ingested subjects" in e.value for e in at.error)


# ---- Declared expectations ----


def test_expectations_panel_is_offered_and_says_checks_are_off(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any("Declared expectations" in label and "none set" in label for label in labels)


def test_a_declaration_is_summarized(project):
    save_project_config(
        str(project),
        {"expected": {"session": {"anat": {"T1w": 1}, "task": {"rest": 2}}}},
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert any("Declared expectations" in label and "none set" not in label for label in labels)
    assert any("2** run(s) of `rest`" in m.value for m in at.markdown)


def test_freezing_a_draft_writes_the_declaration(project):
    """The save control had no test while it lived on Status; the page move is
    when it gets one. sub-01 has a converted T1w, so the elicited draft is
    non-empty, the freeze button is enabled, and pressing it must land the
    `[expected]` section in the project config."""
    from duckbrain.config import load_config
    from duckbrain.core.expectations import declared

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    freeze = next(b for b in at.button if "Freeze" in b.label)
    assert not freeze.disabled
    freeze.click().run()
    assert not at.exception

    current = declared(load_config(project_dir=str(project))) or {}
    assert current.get("session", {}).get("anat", {}).get("T1w") == 1


# ---- BIDS validation panel ----


@pytest.fixture
def validator_ready(project, monkeypatch):
    """A project where the validator *could* run, so the button is enabled."""
    import duckbrain.core.validation as V

    monkeypatch.setattr(V, "validator_unavailable_reason", lambda container, bids: "")
    return project


def _counting_validator(monkeypatch, result=None):
    import subprocess

    import duckbrain.core.validation as V

    calls = []

    def fake(cmd, timeout_s):
        calls.append(cmd)
        payload = result if result is not None else '{"issues": {}, "summary": {"totalFiles": 3}}'
        return subprocess.CompletedProcess(cmd, 0, payload, "")

    monkeypatch.setattr(V, "_run_validator", fake)
    return calls


def test_the_validation_panel_runs_nothing_until_the_button_is_pressed(
    validator_ready, monkeypatch
):
    """A subprocess over the whole BIDS tree may only run when asked — a render
    does a session-state lookup and a couple of ``Path.exists()`` calls.
    `core/checks.py` states the constraint; this enforces it for the one
    genuinely expensive thing the page can do."""
    calls = _counting_validator(monkeypatch)

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert calls == [], "the validator ran on a plain render"

    at.run()  # a second render
    assert calls == [], "the validator ran on a re-render"

    assert "validate_bids_btn" in _btn_keys(at)
    at.button(key="validate_bids_btn").click().run()
    assert not at.exception
    assert len(calls) == 1
    assert "--ignoreSymlinks" in calls[0]


def test_the_panel_reports_when_the_validator_could_not_run(project, monkeypatch):
    """A missing container must read as "could not run", never as a clean dataset."""
    import duckbrain.core.validation as V

    monkeypatch.setattr(
        V, "validator_unavailable_reason", lambda container, bids: "container image not found"
    )

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    # No button to press, and the reason takes its place.
    assert "validate_bids_btn" not in _btn_keys(at)
    assert any("Can't run the validator" in i.value for i in at.info)


def test_a_result_carries_the_time_it_was_measured(validator_ready, monkeypatch):
    """A stale answer must not read as a current one — the reason this is not cached."""
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "bids_validator" / "dwi_eyeball.json"
    _counting_validator(monkeypatch, result=fixture.read_text())

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at.button(key="validate_bids_btn").click().run()
    assert not at.exception

    captions = [c.value for c in at.caption]
    assert any("measured" in c for c in captions)
    # And the findings themselves reach the panel.
    assert any("DATASET_DESCRIPTION_JSON_MISSING" in e.value for e in at.error)
    assert any("README_FILE_MISSING" in w.value for w in at.warning)
