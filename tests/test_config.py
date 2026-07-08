"""Tests for duckbrain config loader."""

import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_config_env(monkeypatch, tmp_path):
    """Keep the developer's real ~/.config/duckbrain and env vars out of tests."""
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(tmp_path / "no_user_config.toml"))
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)
    monkeypatch.delenv("DUCKBRAIN_CONFIG_DIR", raising=False)


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary config directory with base.toml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    base_toml = config_dir / "base.toml"
    base_toml.write_text(
        """
[project]
name = ""

[paths]
bids_dir = ""
sourcedata_dir = ""
work_dir = ""
containers_dir = ""

[slurm]
partition = "medium"
time = "12:00:00"
memory = "16G"
cpus = "4"
email = ""

[slurm.overrides.fmriprep]
time = "48:00:00"
memory = "48G"
cpus = "8"
partition = "computelong"
"""
    )
    return config_dir


def test_load_config_base_only(tmp_config_dir):
    from duckbrain.config import load_config

    config = load_config(tmp_config_dir)
    assert config["slurm"]["partition"] == "medium"
    assert config["project"]["name"] == ""


def test_load_config_with_local_override(tmp_config_dir):
    from duckbrain.config import load_config

    local = tmp_config_dir / "local.toml"
    local.write_text(
        """
[project]
name = "test_project"

[slurm]
email = "test@example.com"
"""
    )

    config = load_config(tmp_config_dir)
    assert config["project"]["name"] == "test_project"
    assert config["slurm"]["email"] == "test@example.com"
    # Base values should still be present
    assert config["slurm"]["partition"] == "medium"


def test_deep_merge_preserves_nested(tmp_config_dir):
    from duckbrain.config import load_config

    local = tmp_config_dir / "local.toml"
    local.write_text(
        """
[slurm]
email = "override@example.com"

[slurm.overrides.fmriprep]
time = "72:00:00"
"""
    )

    config = load_config(tmp_config_dir)
    assert config["slurm"]["email"] == "override@example.com"
    # Overridden
    assert config["slurm"]["overrides"]["fmriprep"]["time"] == "72:00:00"
    # Preserved from base
    assert config["slurm"]["overrides"]["fmriprep"]["memory"] == "48G"


def test_get_slurm_resources(tmp_config_dir):
    from duckbrain.config import load_config, get_slurm_resources

    config = load_config(tmp_config_dir)
    res = get_slurm_resources(config, "fmriprep")
    assert res["time"] == "48:00:00"
    assert res["partition"] == "computelong"

    # Unknown step falls back to defaults
    res2 = get_slurm_resources(config, "unknown_step")
    assert res2["time"] == "12:00:00"
    assert res2["partition"] == "medium"


def test_missing_base_toml_raises(tmp_path):
    from duckbrain.config import load_config

    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent")


def test_user_config_merged(tmp_config_dir, tmp_path, monkeypatch):
    """Shared machine resources come from the user config layer."""
    from duckbrain.config import load_config

    user_cfg = tmp_path / "user.toml"
    user_cfg.write_text('[paths]\ncontainers_dir = "/shared/containers"\n')
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(user_cfg))

    config = load_config(tmp_config_dir)
    assert config["paths"]["containers_dir"] == "/shared/containers"
    assert config["slurm"]["partition"] == "medium"  # base still present


def test_project_config_and_derived_paths(tmp_config_dir, tmp_path):
    """Project config is merged and sourcedata/derivatives/code are derived."""
    from duckbrain.config import load_config, save_project_config

    project = tmp_path / "myproject"
    save_project_config(project, {"project": {"name": "myproject"}})

    config = load_config(tmp_config_dir, project_dir=project)
    assert config["project"]["name"] == "myproject"
    assert config["paths"]["bids_dir"] == str(project)
    assert config["paths"]["sourcedata_dir"] == str(project / "sourcedata")
    assert config["paths"]["derivatives_dir"] == str(project / "derivatives")
    assert config["paths"]["code_dir"] == str(project / "code")


def test_project_dir_from_env(tmp_config_dir, tmp_path, monkeypatch):
    from duckbrain.config import load_config

    project = tmp_path / "envproject"
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(project))
    config = load_config(tmp_config_dir)
    assert config["paths"]["bids_dir"] == str(project)


def test_derived_paths_dont_override_explicit(tmp_config_dir, tmp_path):
    """An explicit path in project config wins over the derived default."""
    from duckbrain.config import load_config, save_project_config

    project = tmp_path / "p"
    save_project_config(project, {"paths": {"sourcedata_dir": "/elsewhere/raw"}})
    config = load_config(tmp_config_dir, project_dir=project)
    assert config["paths"]["sourcedata_dir"] == "/elsewhere/raw"
    assert config["paths"]["derivatives_dir"] == str(project / "derivatives")
