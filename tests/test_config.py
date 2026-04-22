"""Tests for duckbrain config loader."""

import pytest
from pathlib import Path


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
