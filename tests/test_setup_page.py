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
