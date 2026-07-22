"""Interaction tests for the Project Setup page.

The thing under test is feedback on save, not the writing itself (``save_*_config``
is covered by ``test_config.py``). Both save buttons end in ``st.rerun()``, which
restarts the script and discards anything written before it — so the confirmation
has to be a *toast*, which survives a rerun, and an ``st.success`` box here is a
silent regression: the file is written, the user sees nothing, and the button
reads as broken. That was the reported bug (2026-07-22).
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import USER_CONFIG_ENV, load_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/1_Project_Setup.py"


@pytest.fixture
def project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(proj))
    # Never touch the developer's real ~/.config/duckbrain/config.toml.
    monkeypatch.setenv(USER_CONFIG_ENV, str(tmp_path / "user_config.toml"))
    return proj


def _open(project):
    """A page instance with *project* already open.

    The settings sections sit behind ``st.session_state["project_dir"]`` (the env
    var only seeds the picker's default), so seed session state directly rather
    than driving the picker widget.
    """
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["project_dir"] = str(project)
    return at.run()


def _button(at, label):
    for b in at.button:
        if b.label == label:
            return b
    raise AssertionError(f"no button labelled {label!r}; have {[b.label for b in at.button]}")


@pytest.mark.parametrize("label", ["Save project settings", "Save shared resources"])
def test_save_buttons_confirm_with_a_toast(project, label):
    at = _open(project)
    assert not at.exception
    _button(at, label).click().run()
    assert not at.exception
    assert any("Saved" in t.value for t in at.toast), (
        f"{label!r} gave no toast — a success box written before st.rerun() is "
        "discarded, so the save looks like it did nothing."
    )


def test_save_project_settings_persists(project):
    at = _open(project)
    for ti in at.text_input:
        if ti.label == "Project name":
            ti.set_value("toast-check")
    _button(at, "Save project settings").click().run()
    assert not at.exception
    assert (project / "code" / "duckbrain.toml").exists()
    assert load_config(project_dir=str(project))["project"]["name"] == "toast-check"


def test_save_project_settings_keeps_hand_written_slurm_overrides(project):
    """DB-001, end to end through the real button payload.

    The unit test in test_config.py pins `_save_sections`; this pins that the
    page actually declares its ownership. A project with a hand-tuned
    [slurm.overrides.fmriprep] lost it to any Setup save — a rename, a DICOM
    source change — and later submissions silently used different resources.
    """
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(str(project), {"slurm": {
        "account": "hulacon",
        "memory": "64G",
        "overrides": {"fmriprep": {"time": "48:00:00"}},
    }})

    at = _open(project)
    for ti in at.text_input:
        if ti.label == "Project name":
            ti.set_value("renamed")
    _button(at, "Save project settings").click().run()
    assert not at.exception

    stored = _load_toml(project_config_path(str(project)))["slurm"]
    assert stored["overrides"]["fmriprep"]["time"] == "48:00:00"
    assert stored["memory"] == "64G"


def test_save_shared_resources_keeps_user_level_slurm_keys(project, tmp_path):
    """The shared-resources button writes only [slurm].email — the rest is not its.

    A user-level `mail_type` or account applies to every project; the button that
    edits one email address must not be able to delete them.
    """
    from duckbrain.config import _load_toml, save_user_config

    save_user_config({"slurm": {"account": "hulacon", "mail_type": "END,FAIL"}})

    at = _open(project)
    # The email must be non-empty or `_clean_dict` drops [slurm] entirely and the
    # section is never rewritten — the bug would hide behind an accidental no-op.
    for ti in at.text_input:
        if ti.label == "SLURM email":
            ti.set_value("ben@example.edu")
    _button(at, "Save shared resources").click().run()
    assert not at.exception

    stored = _load_toml(tmp_path / "user_config.toml")["slurm"]
    assert stored["account"] == "hulacon"
    assert stored["mail_type"] == "END,FAIL"


def test_user_config_env_is_respected(project, tmp_path):
    """Guard on the fixture itself: a leaky test here would rewrite a real config."""
    real = Path.home() / ".config" / "duckbrain" / "config.toml"
    before = real.read_bytes() if real.exists() else None
    at = _open(project)
    _button(at, "Save shared resources").click().run()
    assert not at.exception
    assert (tmp_path / "user_config.toml").exists()
    assert (real.read_bytes() if real.exists() else None) == before


def test_setup_flags_a_partition_this_cluster_does_not_have(project, monkeypatch):
    """duckbrain shipped `medium` as its default partition and this cluster has
    no such partition. It was invisible while a per-stage default outranked it;
    now that the field reaches jobs, a stale value must be visible before it
    rejects every submission."""
    import duckbrain.gui.pages  # noqa: F401  (namespace exists before patching)
    import duckbrain.slurm.monitor as M

    monkeypatch.setattr(M, "known_partitions", lambda: {"compute", "computelong"})
    from duckbrain.config import save_project_config
    save_project_config(str(project), {"slurm": {"partition": "medium"}})

    at = _open(project)
    assert not at.exception
    assert any("Not a partition on this cluster" in e.value for e in at.error), (
        "a partition the cluster does not have must be flagged, not saved quietly"
    )


def test_no_partition_complaint_when_slurm_cannot_be_queried(project, monkeypatch):
    """Off-cluster, sinfo returns nothing — that is 'cannot validate', not
    'no partitions exist'. A false accusation would be worse than no check."""
    import duckbrain.slurm.monitor as M

    monkeypatch.setattr(M, "known_partitions", lambda: set())
    from duckbrain.config import save_project_config
    save_project_config(str(project), {"slurm": {"partition": "anything"}})

    at = _open(project)
    assert not at.exception
    assert not any("Not a partition" in e.value for e in at.error)


# ---- TODO #17.7 / #17.8: the page must describe the project it is on ---------

def test_pickers_follow_a_project_switch(project, tmp_path, monkeypatch):
    """A picker's committed selection is sticky per session; switching projects
    must re-seed it. It didn't, so the DICOM-source field kept showing the
    PREVIOUS project's path — with a green "✓ Selected:" on it — and saving wrote
    that path into the new project."""
    from duckbrain.config import save_project_config, scaffold_project

    other = tmp_path / "other"
    scaffold_project(str(other))
    save_project_config(str(project), {"dcm_source": {"dir": "/dicom/A"}})
    save_project_config(str(other), {"dcm_source": {"dir": "/dicom/B"}})

    at = AppTest.from_file(PAGE, default_timeout=60)
    at.session_state["project_dir"] = str(project)
    at.run()
    assert any(ti.value == "/dicom/A" for ti in at.text_input)

    # Same session, different project — the picker must not hold /dicom/A.
    at.session_state["project_dir"] = str(other)
    at.run()
    assert not at.exception
    assert any(ti.value == "/dicom/B" for ti in at.text_input), (
        "picker still shows the previous project's DICOM source"
    )
    assert not any(ti.value == "/dicom/A" for ti in at.text_input)


def test_shared_resources_show_the_shared_value_not_the_projects(project, tmp_path):
    """The section saves to the user config, so it must display the user config.

    Seeded from the merged config it showed the *project's* pin under a heading
    that says "all your projects", and saving pushed that pin onto every other
    project.
    """
    from duckbrain.config import USER_CONFIG_ENV, save_project_config, save_user_config

    save_user_config({"containers": {"fmriprep_version": "24.1.1"}})
    save_project_config(str(project), {"containers": {"fmriprep_version": "23.2.0"}})

    at = _open(project)
    assert not at.exception
    versions = [ti.value for ti in at.text_input if ti.label == "fMRIPrep version"]
    assert versions == ["24.1.1"], "shared field must show the shared value"
    # ...and the project's divergence is stated rather than hidden.
    assert any("23.2.0" in i.value for i in at.info)


def test_saving_shared_resources_keeps_the_recent_projects_list(project, tmp_path):
    from duckbrain.config import USER_CONFIG_ENV, _load_toml, save_user_config
    import os

    save_user_config({"recent": {"projects": ["/x", "/y"]}})
    at = _open(project)
    _button(at, "Save shared resources").click().run()
    assert not at.exception

    stored = _load_toml(os.environ[USER_CONFIG_ENV])
    assert stored["recent"]["projects"] == ["/x", "/y"]
