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


def test_scaffold_writes_bidsignore(tmp_path):
    """scaffold_project drops a .bidsignore covering duckbrain's non-BIDS dirs."""
    from duckbrain.config import scaffold_project

    scaffold_project(tmp_path)
    entries = (tmp_path / ".bidsignore").read_text().split()
    assert "work/" in entries
    # logs live under code/ (BIDS-reserved) now, so they need no ignore entry.
    assert "logs/" not in entries
    assert (tmp_path / "code" / "logs").is_dir()


def test_write_bidsignore_idempotent_and_preserves_user_lines(tmp_path):
    from duckbrain.config import write_bidsignore

    (tmp_path / ".bidsignore").write_text("my_custom_scratch/\n")
    write_bidsignore(tmp_path)
    write_bidsignore(tmp_path)  # second call must not duplicate
    lines = [l for l in (tmp_path / ".bidsignore").read_text().splitlines() if l.strip()]
    assert "my_custom_scratch/" in lines
    assert lines.count("work/") == 1


# ---- recent-projects MRU -----------------------------------------------------
#
# Lives in the USER config: "which projects do I work on" is a property of the
# person at this machine, and a project cannot sensibly list itself.

import pytest


@pytest.fixture
def user_cfg(tmp_path, monkeypatch):
    path = tmp_path / "user.toml"
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(path))
    return path


def _mkproj(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return str(p)


def test_remember_project_is_mru_newest_first(user_cfg, tmp_path):
    from duckbrain.config import recent_projects, remember_project

    a, b = _mkproj(tmp_path, "a"), _mkproj(tmp_path, "b")
    remember_project(a)
    remember_project(b)
    assert recent_projects() == [b, a]
    remember_project(a)  # re-opening moves it to the front, never duplicates
    assert recent_projects() == [a, b]


def test_remember_project_caps_the_list(user_cfg, tmp_path):
    from duckbrain.config import recent_projects, remember_project

    for i in range(12):
        remember_project(_mkproj(tmp_path, f"p{i}"))
    got = recent_projects()
    assert len(got) == 8  # _MAX_RECENT_PROJECTS
    assert got[0].endswith("p11")  # newest kept, oldest dropped


def test_remember_project_preserves_other_user_settings(user_cfg, tmp_path):
    """Read-modify-write: the MRU must not clobber shared machine resources."""
    from duckbrain.config import _load_toml, remember_project, save_user_config

    save_user_config({"paths": {"fs_license": "/l/lic.txt"}, "containers": {"x": "y"}})
    remember_project(_mkproj(tmp_path, "a"))
    data = _load_toml(user_cfg)
    assert data["paths"]["fs_license"] == "/l/lic.txt"
    assert data["containers"] == {"x": "y"}
    assert len(data["recent"]["projects"]) == 1


def test_recent_projects_hides_but_does_not_erase_missing_dirs(user_cfg, tmp_path):
    """A deleted/unmounted project stops being offered but stays in the file.

    An unmounted filesystem is a temporary condition; erasing history over it
    would be destructive.
    """
    from duckbrain.config import _load_toml, recent_projects, remember_project

    gone = _mkproj(tmp_path, "gone")
    kept = _mkproj(tmp_path, "kept")
    remember_project(gone)
    remember_project(kept)
    Path(gone).rmdir()

    assert recent_projects() == [kept]
    assert recent_projects(existing_only=False) == [kept, gone]
    assert len(_load_toml(user_cfg)["recent"]["projects"]) == 2


def test_forget_project_removes_one_entry(user_cfg, tmp_path):
    from duckbrain.config import forget_project, recent_projects, remember_project

    a, b = _mkproj(tmp_path, "a"), _mkproj(tmp_path, "b")
    remember_project(a)
    remember_project(b)
    forget_project(a)
    assert recent_projects() == [b]


def test_recent_projects_tolerates_a_junk_section(user_cfg):
    """A hand-edited config must never take the GUI down."""
    from duckbrain.config import recent_projects, remember_project, save_user_config

    save_user_config({"recent": "not-a-table"})
    assert recent_projects() == []
    remember_project("/tmp")  # repairs the section rather than raising
    assert recent_projects(existing_only=False) == ["/tmp"]


def test_recent_projects_normalizes_without_resolving_symlinks(user_cfg, tmp_path):
    """Trailing slashes collapse, but a symlinked path is NOT rewritten.

    On GPFS the user-facing /projects/... is a symlink to /gpfs/projects/...;
    rewriting the path the user chose would be a surprise, not a normalization.
    """
    from duckbrain.config import recent_projects, remember_project

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    remember_project(f"{link}/")
    remember_project(str(link))  # same entry once slashes collapse
    assert recent_projects() == [str(link)]
