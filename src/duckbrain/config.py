"""Configuration loader — layered and project-dir-first.

Layers, deep-merged (later wins):

  1. base.toml       shipped defaults (repo ``config/``, or ``DUCKBRAIN_CONFIG_DIR``)
  2. user config     shared machine resources reused across projects — containers,
                     FreeSurfer license, NORDIC toolbox, SLURM account/email.
                     ``~/.config/duckbrain/config.toml`` (or ``DUCKBRAIN_USER_CONFIG``)
  3. local.toml      [legacy] optional overrides next to base.toml, if present
  4. project config  project-specific settings that live INSIDE the project:
                     ``<project_dir>/code/duckbrain.toml``

The **project directory is the anchor**: ``sourcedata/``, ``derivatives/`` and
``code/`` are derived from it automatically, so a user only has to point
duckbrain at one directory. The project is chosen via ``load_config(project_dir=...)``
or the ``DUCKBRAIN_PROJECT_DIR`` environment variable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]


PROJECT_ENV = "DUCKBRAIN_PROJECT_DIR"
USER_CONFIG_ENV = "DUCKBRAIN_USER_CONFIG"

# Keys under [paths] that name shared, machine-level resources — these come from
# the user config and are NOT derived from the project directory.
_SHARED_PATH_KEYS = ("containers_dir", "fs_license", "nordic_toolbox_dir")


def _deep_update(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (mutates base)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _find_config_dir() -> Path:
    """Locate the directory holding the shipped base.toml.

    Search order:
    1. DUCKBRAIN_CONFIG_DIR environment variable
    2. Walk up from this file's location looking for config/base.toml
    """
    env = os.environ.get("DUCKBRAIN_CONFIG_DIR")
    if env:
        p = Path(env)
        if p.is_dir() and (p / "base.toml").exists():
            return p
        raise FileNotFoundError(
            f"DUCKBRAIN_CONFIG_DIR={env} does not contain base.toml"
        )

    # Walk up from package location
    current = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = current / "config"
        if candidate.is_dir() and (candidate / "base.toml").exists():
            return candidate
        if current.parent == current:
            break
        current = current.parent

    raise FileNotFoundError(
        "Cannot find config/base.toml. Set DUCKBRAIN_CONFIG_DIR or run from the project root."
    )


def user_config_path() -> Path:
    """Path to the user-level config holding shared machine resources."""
    env = os.environ.get(USER_CONFIG_ENV)
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "duckbrain" / "config.toml"


def project_config_path(project_dir: str | Path) -> Path:
    """Path to a project's own config (lives inside the project's code/ dir)."""
    return Path(project_dir) / "code" / "duckbrain.toml"


def resolve_project_dir(project_dir: str | Path | None = None) -> Path | None:
    """Resolve the active project directory from an arg or the environment."""
    if project_dir:
        return Path(project_dir)
    env = os.environ.get(PROJECT_ENV)
    return Path(env) if env else None


def _load_toml(path: str | Path | None) -> dict:
    """Load a TOML file, or return {} if it is missing."""
    if path and Path(path).exists():
        with open(path, "rb") as f:
            return tomllib.load(f)
    return {}


def derive_paths(config: dict, project_dir: str | Path) -> dict:
    """Fill unset [paths] entries from the project directory (mutates config).

    The project directory *is* the BIDS root; sourcedata/derivatives/code sit
    directly under it. Shared resources (containers, licenses) are never derived.
    """
    project_dir = Path(project_dir)
    paths = config.setdefault("paths", {})
    derived = {
        "bids_dir": str(project_dir),
        "sourcedata_dir": str(project_dir / "sourcedata"),
        "derivatives_dir": str(project_dir / "derivatives"),
        "code_dir": str(project_dir / "code"),
        # SLURM logs + submitted scripts must live on shared FS (not node-local
        # work_dir=/tmp), or a failed job's log is stranded on the compute node.
        "log_dir": str(project_dir / "logs"),
    }
    for key, value in derived.items():
        if not paths.get(key):
            paths[key] = value
    return config


def load_config(
    config_dir: str | Path | None = None,
    project_dir: str | Path | None = None,
) -> dict:
    """Load and deep-merge the configuration layers.

    Parameters
    ----------
    config_dir : path, optional
        Directory containing base.toml (and legacy local.toml). Auto-discovered
        if None. (First positional for backward compatibility.)
    project_dir : path, optional
        The active project directory. Falls back to ``$DUCKBRAIN_PROJECT_DIR``.
        When known, the project config is merged and [paths] are derived from it.

    Returns
    -------
    dict
        Merged configuration dictionary.
    """
    if config_dir is not None:
        config_dir = Path(config_dir)
    else:
        config_dir = _find_config_dir()

    base_path = config_dir / "base.toml"
    if not base_path.exists():
        raise FileNotFoundError(f"base.toml not found in {config_dir}")

    config = _load_toml(base_path)
    _deep_update(config, _load_toml(user_config_path()))          # shared resources
    _deep_update(config, _load_toml(config_dir / "local.toml"))   # legacy overrides

    pd = resolve_project_dir(project_dir)
    if pd is not None:
        _deep_update(config, _load_toml(project_config_path(pd)))  # project specifics
        derive_paths(config, pd)

    return config


def get_slurm_resources(config: dict, step: str) -> dict:
    """Get SLURM resource settings for a pipeline step.

    Falls back to global slurm settings if no per-step override exists.
    """
    slurm = config.get("slurm", {})
    overrides = slurm.get("overrides", {}).get(step, {})
    return {
        "partition": overrides.get("partition", slurm.get("partition", "compute")),
        "time": overrides.get("time", slurm.get("time", "12:00:00")),
        "memory": overrides.get("memory", slurm.get("memory", "16G")),
        "cpus": overrides.get("cpus", slurm.get("cpus", "4")),
        "email": slurm.get("email", ""),
        "mail_type": slurm.get("mail_type", "END,FAIL"),
        "account": slurm.get("account", ""),
    }


def _dump_toml(path: str | Path, data: dict) -> Path:
    """Write *data* to a TOML file, creating parent dirs."""
    import tomli_w

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    return path


def save_user_config(data: dict) -> Path:
    """Write the user-level config (shared machine resources)."""
    return _dump_toml(user_config_path(), data)


def save_project_config(project_dir: str | Path, data: dict) -> Path:
    """Write a project's own config to ``<project_dir>/code/duckbrain.toml``."""
    return _dump_toml(project_config_path(project_dir), data)


def scaffold_project(project_dir: str | Path) -> Path:
    """Create the standard BIDS-ish project layout (sourcedata/derivatives/code).

    Returns the project directory. Idempotent.
    """
    project_dir = Path(project_dir)
    for sub in ("sourcedata", "derivatives", "code", "logs"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    return project_dir


def save_local_config(config_dir: str | Path, data: dict) -> Path:
    """[legacy] Write local.toml next to base.toml. Prefer save_project_config."""
    return _dump_toml(Path(config_dir) / "local.toml", data)
