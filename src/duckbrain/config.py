"""Configuration loader — deep-merges base.toml + local.toml."""

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


def _deep_update(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (mutates base)."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _find_config_dir() -> Path:
    """Locate the config directory.

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


def load_config(config_dir: str | Path | None = None) -> dict:
    """Load and merge configuration from base.toml + local.toml.

    Parameters
    ----------
    config_dir : path, optional
        Explicit config directory. If None, auto-discovers.

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
    local_path = config_dir / "local.toml"

    with open(base_path, "rb") as f:
        config = tomllib.load(f)

    if local_path.exists():
        with open(local_path, "rb") as f:
            local = tomllib.load(f)
        _deep_update(config, local)

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


def save_local_config(config_dir: str | Path, data: dict) -> Path:
    """Write local.toml with user-specific configuration.

    Parameters
    ----------
    config_dir : path
        Config directory (must exist).
    data : dict
        Configuration to write.

    Returns
    -------
    Path
        Path to the written local.toml.
    """
    import tomli_w

    config_dir = Path(config_dir)
    local_path = config_dir / "local.toml"
    with open(local_path, "wb") as f:
        tomli_w.dump(data, f)
    return local_path
