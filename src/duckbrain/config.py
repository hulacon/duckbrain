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
        # Kept under code/ (a BIDS-reserved dir) so no .bidsignore entry is needed
        # to stay validator-clean.
        "log_dir": str(project_dir / "code" / "logs"),
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


# Recently-opened projects live in the USER config, not a project's own: "which
# projects do I work on" is a property of the person at this machine, and a
# project can't sensibly list itself. Capped so the list stays a shortcut rather
# than a history.
_MAX_RECENT_PROJECTS = 8


def _normalized_project(project_dir: str | Path) -> str:
    """Collapse trailing slashes and redundant separators, WITHOUT resolving.

    Deliberately not ``resolve()``: on GPFS the user-facing ``/projects/...`` is a
    symlink to ``/gpfs/projects/...``, and rewriting a path the user chose (and
    that their config records) would be a surprise, not a normalization.
    """
    return str(Path(project_dir))


def recent_projects(existing_only: bool = True) -> list[str]:
    """Recently-opened project directories, most recent first.

    ``existing_only`` drops entries that no longer resolve to a directory, so a
    deleted or unmounted project quietly falls off the list instead of offering a
    dead shortcut. The stored list is left alone — an unmounted filesystem should
    not erase history.
    """
    stored = _load_toml(user_config_path()).get("recent", {})
    if not isinstance(stored, dict):
        return []
    out: list[str] = []
    for entry in stored.get("projects", []) or []:
        if not isinstance(entry, str) or not entry.strip():
            continue
        entry = _normalized_project(entry)
        if entry in out:
            continue
        if existing_only and not Path(entry).is_dir():
            continue
        out.append(entry)
    return out


def remember_project(
    project_dir: str | Path, limit: int = _MAX_RECENT_PROJECTS
) -> Path:
    """Push *project_dir* to the front of the recent-projects list (MRU).

    Read-modify-write so it only touches ``[recent]`` and preserves every other
    shared setting — same contract as :func:`save_project_task_map`.
    """
    entry = _normalized_project(project_dir)
    path = user_config_path()
    data = _load_toml(path)
    section = data.get("recent")
    if not isinstance(section, dict):
        section = {}
    previous = [
        p for p in (section.get("projects") or [])
        if isinstance(p, str) and _normalized_project(p) != entry
    ]
    section["projects"] = [entry, *previous][:limit]
    data["recent"] = section
    return _dump_toml(path, data)


def forget_project(project_dir: str | Path) -> Path:
    """Drop *project_dir* from the recent list (for a moved/retired project)."""
    entry = _normalized_project(project_dir)
    path = user_config_path()
    data = _load_toml(path)
    section = data.get("recent")
    if not isinstance(section, dict):
        return path
    section["projects"] = [
        p for p in (section.get("projects") or [])
        if isinstance(p, str) and _normalized_project(p) != entry
    ]
    data["recent"] = section
    return _dump_toml(path, data)


def save_project_task_map(project_dir: str | Path, rules: list) -> Path:
    """Persist project-wide task/run rules into the project config.

    Read-modify-write so it only touches the ``[task_mapping]`` section and
    preserves every other project setting. ``rules`` is a list of
    :class:`~duckbrain.core.dcm2bids_config.TaskRule`; an empty list removes the
    section entirely (reverting to the pure heuristic).
    """
    from .core.dcm2bids_config import task_rules_to_config_section

    path = project_config_path(project_dir)
    data = _load_toml(path)
    if rules:
        data["task_mapping"] = task_rules_to_config_section(rules)
    else:
        data.pop("task_mapping", None)
    return _dump_toml(path, data)


# Top-level directories duckbrain creates that are NOT BIDS-reserved names
# (BIDS reserves only sourcedata/, derivatives/, code/, phenotype/, stimuli/).
# Listing them in .bidsignore keeps the project-dir == BIDS-root layout
# validator-clean — the standards-alignment that lets us keep the single-dir
# layout instead of Nipoppy's nested bids/ envelope. See the
# nipoppy-status-tracking notes.
_BIDSIGNORE_ENTRIES = ("work/",)


def write_bidsignore(project_dir: str | Path) -> Path:
    """Ensure a ``.bidsignore`` at the project root covers duckbrain's non-BIDS dirs.

    Idempotent and non-destructive: preserves any user-added lines and only
    appends the duckbrain entries that are missing.
    """
    path = Path(project_dir) / ".bidsignore"
    existing = path.read_text().splitlines() if path.exists() else []
    present = {line.strip() for line in existing}
    missing = [e for e in _BIDSIGNORE_ENTRIES if e not in present]
    if not missing:
        return path

    lines = list(existing)
    if not existing:
        lines.append("# Non-BIDS working dirs created by duckbrain (keeps the")
        lines.append("# project-dir==BIDS-root layout validator-clean).")
    lines.extend(missing)
    path.write_text("\n".join(lines) + "\n")
    return path


def scaffold_project(project_dir: str | Path) -> Path:
    """Create the standard BIDS-ish project layout (sourcedata/derivatives/code).

    Returns the project directory. Idempotent.
    """
    project_dir = Path(project_dir)
    for sub in ("sourcedata", "derivatives", "code", "code/logs"):
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    write_bidsignore(project_dir)
    return project_dir


def save_local_config(config_dir: str | Path, data: dict) -> Path:
    """[legacy] Write local.toml next to base.toml. Prefer save_project_config."""
    return _dump_toml(Path(config_dir) / "local.toml", data)
