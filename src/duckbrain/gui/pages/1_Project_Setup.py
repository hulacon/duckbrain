"""Page 1: Project Setup — project-dir-first configuration.

The project directory is the single anchor: sourcedata/derivatives/code are
derived from it, project-specific settings live inside the project
(<project>/code/duckbrain.toml), and shared machine resources (containers,
licenses, container versions) live in the user config (~/.config/duckbrain/).
"""

import os
from pathlib import Path
from typing import Any

import streamlit as st

from duckbrain.config import (
    _SHARED_PATH_KEYS,
    PROJECT_ENV,
    _load_toml,
    forget_project,
    load_config,
    project_config_path,
    recent_projects,
    remember_project,
    save_project_config,
    save_user_config,
    scaffold_project,
    user_config_path,
)
from duckbrain.gui.components import directory_picker, flush_toasts, queue_toast
from duckbrain.slurm.monitor import known_partitions

st.set_page_config(page_title="Project Setup — duckbrain", layout="wide")
st.title("Project Setup")

# A save on the previous run confirms itself here; see `components.queue_toast`
# for why it cannot confirm itself next to the save.
flush_toasts()


def _split_authors(text: str) -> list[str]:
    """One author per line, blanks dropped, order and duplicates-once preserved."""
    seen: list[str] = []
    for line in (text or "").splitlines():
        name = line.strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def _clean_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Drop empty strings and empty sub-dicts so saved TOML stays minimal."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = _clean_dict(v)
            if v:
                out[k] = v
        elif v != "":
            out[k] = v
    return out


# Which keys each save button OWNS. Everything else in these sections belongs to
# whoever wrote it — a hand-tuned `[slurm.overrides.fmriprep]`, a `slurm.memory`,
# a `dcm_source.base_dir` — and must survive a save from this page. Without this
# the section-level replace in `_save_sections` deleted all of it while the page
# said "Saved" (TODO #17.1, reopened by the 2026-07-22 review as DB-001).
#
# Adding a widget here without adding its key raises on save rather than
# silently dropping the value one save later. That is the whole point; don't
# "fix" such an error by widening the list without checking the widget writes
# what you think it writes.
_PROJECT_OWNED = {
    "project": ("name", "use_sessions", "authors"),
    "dcm_source": ("dir",),
    # One key of [nordic] only. The rest (magnitude_only, matlab_module,
    # excluded_nodes) is shared machine config a project may override by hand.
    "nordic": ("use_nordic",),
    "slurm": ("account", "partition", "partition_long", "time"),
}

_USER_OWNED = {
    "paths": _SHARED_PATH_KEYS,
    "containers": ("dcm2bids_version", "fmriprep_version", "mriqc_version"),
    "slurm": ("email",),
}

# ---- Choose the project directory (the anchor for everything) ----
st.header("Project directory")
st.markdown(
    "Point duckbrain at one **project directory** (your BIDS dataset root). "
    "`sourcedata/`, `derivatives/`, and `code/` are created and used under it."
)

current_project = st.session_state.get("project_dir") or os.environ.get(PROJECT_ENV, "")


def _open_project(path: str) -> None:
    """Make *path* active for this session and record it as most-recently-used."""
    scaffold_project(path)  # idempotent: makes sourcedata/derivatives/code
    st.session_state["project_dir"] = path
    os.environ[PROJECT_ENV] = path  # visible to other pages this session
    remember_project(path)


# Re-picking the same directory every session was the main friction with the
# picker, so recent projects are one click. Entries that no longer resolve are
# hidden by recent_projects(), and ✕ drops one for good.
_recents = [p for p in recent_projects() if p != current_project]
if _recents:
    st.caption("Recent projects")
    for _path in _recents:
        _open_col, _drop_col = st.columns([12, 1], vertical_alignment="center")
        with _open_col:
            if st.button(_path, key=f"open_recent_{_path}", width="stretch"):
                _open_project(_path)
                st.rerun()
        with _drop_col:
            if st.button("✕", key=f"drop_recent_{_path}", help="Forget this project"):
                forget_project(_path)
                st.rerun()
    st.divider()

project_dir = directory_picker(
    "Project directory",
    key="project_dir_pick",
    default=current_project or "/projects",
    allow_create=True,
    reset_on=current_project,
    help="Browse to (or create) your BIDS project directory. Use the ➕ expander "
    "to make a new folder for a new project.",
)

col_open, col_info = st.columns([1, 2])
with col_open:
    if st.button("Open / Create Project", type="primary", disabled=not project_dir):
        _open_project(project_dir)
        st.success(f"Active project: `{project_dir}`")

active_project = st.session_state.get("project_dir")
if not active_project:
    st.info("Open or create a project above to configure it.")
    st.stop()

os.environ[PROJECT_ENV] = active_project
config = load_config(project_dir=active_project)
paths = config.get("paths", {})


def _get(section: str, key: str, default: str = "") -> str:
    return str(config.get(section, {}).get(key, default))


def _get_bool(section: str, key: str) -> bool:
    """A toggle's stored value. Not ``_get``: that stringifies, and ``"False"``
    is truthy, so a toggle seeded through it would read *on* when it is off."""
    return bool(config.get(section, {}).get(key, False))


def _get_list(section: str, key: str) -> list[str]:
    """A list-valued setting. Not ``_get``: that stringifies, so a stored
    ``["Jane Doe"]`` would seed a widget as the literal ``['Jane Doe']``.
    Tolerates a hand-written scalar by treating it as a one-element list."""
    value = config.get(section, {}).get(key, [])
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


# The "Shared resources" section below saves to the USER config, so it must be
# seeded from the user config too. Seeding it from the merged config showed the
# *project's* override under a heading that says "all your projects", and saving
# then pushed that project's value onto every other one (TODO #17.8).
_user_cfg = _load_toml(user_config_path())


def _get_user(section: str, key: str, default: str = "") -> str:
    return str((_user_cfg.get(section) or {}).get(key, default))


def _project_overrides(section: str, key: str) -> str | None:
    """The project-layer value when it differs from the shared one, else None."""
    effective, shared = _get(section, key), _get_user(section, key)
    return effective if shared and effective and effective != shared else None


# ---- Derived layout (read-only) ----
st.header("Layout (derived from the project directory)")
st.code(
    f"bids_dir        {paths.get('bids_dir', '')}\n"
    f"sourcedata_dir  {paths.get('sourcedata_dir', '')}\n"
    f"derivatives_dir {paths.get('derivatives_dir', '')}\n"
    f"code_dir        {paths.get('code_dir', '')}\n"
    f"work_dir        {paths.get('work_dir', '')}   (scratch; not under the project)",
    language="text",
)

# ---- Project-specific settings (saved INSIDE the project) ----
st.header("Project settings")
st.caption(f"Saved to `{project_config_path(active_project)}`")
project_name = st.text_input("Project name", value=_get("project", "name"))
# A hand-written config may hold the TOML boolean `use_sessions = true` rather
# than the string this selectbox writes; both are legitimate, so normalize before
# looking up the index. Indexing the raw value crashed the whole page.
from duckbrain.core.ingestion import USE_SESSIONS_CHOICES, normalize_use_sessions

_stored_use_sessions = _get("project", "use_sessions", "auto")
_use_sessions_default = normalize_use_sessions(_stored_use_sessions)
use_sessions = st.selectbox(
    "Use BIDS session entity (ses-)",
    options=list(USE_SESSIONS_CHOICES),
    index=USE_SESSIONS_CHOICES.index(_use_sessions_default),
    help="auto = include ses- only when a subject has more than one session",
)
if (
    _stored_use_sessions not in ("", None)
    and _use_sessions_default == "auto"
    and (str(_stored_use_sessions).strip().lower() != "auto")
):
    # Don't silently swallow a value nobody can act on — a typo here decides
    # whether the dataset gets ses- entities at all.
    st.warning(
        f"`use_sessions = {_stored_use_sessions!r}` in the project config isn't a "
        "value duckbrain recognizes, so **auto** is being used. Save below to "
        "replace it."
    )

# One author per line, not comma-separated: comma-splitting guesses wrong on
# "Doe, Jane", and a list is the shape BIDS `Authors` wants anyway, so the split
# happens once here rather than in every reader.
authors_text = st.text_area(
    "Authors",
    value="\n".join(_get_list("project", "authors")),
    help=(
        "One per line. Written to `dataset_description.json` as BIDS `Authors`, "
        "which the validator warns about when absent."
    ),
)

st.subheader("LCNI DICOM source")
# Legacy configs used base_dir/group/project; if one is present, seed from it.
_legacy_dcm = _get("dcm_source", "dir") or "/".join(
    p
    for p in (
        _get("dcm_source", "base_dir"),
        _get("dcm_source", "group"),
        _get("dcm_source", "project"),
    )
    if p
)
# The picker needs somewhere to start, but the starting point is not a choice the
# user made: saving it as `dcm_source.dir` pointed Ingestion at the root of every
# LCNI study and defeated build_dcm_source_path's "set dcm_source.dir" error.
_DCM_BROWSE_ROOT = "/projects/lcni/dcm"
dcm_dir = directory_picker(
    "DICOM source directory",
    key="dcm_source_pick",
    default=_legacy_dcm or _DCM_BROWSE_ROOT,
    must_exist=True,
    help="Full path to this study's DICOM export folder (the one containing the "
    "session folders, e.g. .../hulacon/Hutchinson/divatten).",
    reset_on=active_project,
)

st.subheader("NORDIC")
use_nordic = st.toggle(
    "fMRIPrep reads NORDIC-denoised data",
    value=_get_bool("nordic", "use_nordic"),
    help="Off: fMRIPrep reads the raw BIDS tree, and the Project Status board "
    "marks NORDIC **n/a** — launch it deliberately from Preprocessing → NORDIC. "
    "On: fMRIPrep reads derivatives/nordic/bids_format instead and waits for the "
    "NORDIC stage to finish for each subject.",
)
st.caption(
    "NORDIC runs as a producer either way; this only decides whether anything "
    "**consumes** what it produces. The setting is what the cockpit reads to "
    "decide the stage applies to this project at all, which is why it lives "
    "here rather than only in the config file."
)

st.subheader("SLURM (project)")
st.caption(
    "Every stage runs on **Default partition** except fMRIPrep, the one long "
    "stage, which runs on **Long partition**. Per-stage time/memory/CPU stay "
    "tuned per stage — the time limit here is only the fallback for a stage "
    "without one."
)
c1, c2 = st.columns(2)
with c1:
    slurm_account = st.text_input("Account / PIRG", value=_get("slurm", "account"))
    slurm_partition = st.text_input(
        "Default partition", value=_get("slurm", "partition") or "compute"
    )
with c2:
    slurm_partition_long = st.text_input(
        "Long partition", value=_get("slurm", "partition_long") or "computelong"
    )
    slurm_time = st.text_input("Default time limit", value=_get("slurm", "time") or "12:00:00")

# A partition name is the one SLURM setting duckbrain can't check against itself,
# and a wrong one is only discovered when sbatch rejects the job. It bites for
# real: duckbrain shipped `medium` as its default for months — not a partition
# this cluster has — and the projects set up in that window still carry it.
# Silent while a per-stage default outranked it; now that the field works
# (TODO #17.2), a stale value would reject every job.
_known = known_partitions()
if _known:
    _bad = [p for p in (slurm_partition, slurm_partition_long) if p and p not in _known]
    if _bad:
        st.error(
            "Not a partition on this cluster: "
            + ", ".join(f"`{p}`" for p in _bad)
            + ". sbatch will reject every job submitted with it. Available: "
            + ", ".join(f"`{p}`" for p in sorted(_known))
        )

if st.button("Save project settings"):
    _authors = _split_authors(authors_text)
    project_cfg = {
        "project": {
            "name": project_name,
            "use_sessions": use_sessions,
            # `or ""` is load-bearing: _clean_dict drops on `v != ""`, so an empty
            # *list* survives it and _save_sections would then write `authors = []`
            # rather than removing the key — which reads as "declared none" and
            # would blank an existing Authors list in dataset_description.json.
            # Coercing empty to "" lets the existing drop-the-empties rule delete
            # it, without touching _clean_dict, which four other sections share.
            "authors": _authors or "",
        },
        # An unchanged browse root is not a DICOM source — see _DCM_BROWSE_ROOT.
        "dcm_source": {"dir": "" if dcm_dir == _DCM_BROWSE_ROOT else dcm_dir},
        # Written even when false. It reads as noise next to _clean_dict's
        # drop-the-empties rule, but "off" here is a statement, not an absence:
        # off is what makes the board show NORDIC as n/a, and a project that
        # can't say so in its own config is the state this toggle exists to
        # escape. Omitting it would also *delete* the key on save — an owned
        # section reconciles field by field against what it is handed.
        "nordic": {"use_nordic": use_nordic},
        "slurm": {
            "account": slurm_account,
            "partition": slurm_partition,
            "partition_long": slurm_partition_long,
            "time": slurm_time,
        },
    }
    path = save_project_config(active_project, _clean_dict(project_cfg), owned=_PROJECT_OWNED)
    queue_toast(f"Saved project settings to {path}")
    st.rerun()

# ---- Shared machine resources (saved to the USER config) ----
st.divider()
st.header("Shared resources (all your projects)")
st.caption(f"Saved to `{user_config_path()}` — reused across every project.")
containers_dir = directory_picker(
    "Containers directory",
    key="containers_pick",
    default=_get_user("paths", "containers_dir") or str(Path.home() / "containers"),
    must_exist=True,
    help="Directory holding the Singularity .sif / .simg images.",
    reset_on=active_project,
)
c1, c2 = st.columns(2)
with c1:
    fs_license = st.text_input("FreeSurfer license (file)", value=_get_user("paths", "fs_license"))
    nordic_toolbox_dir = st.text_input(
        "NORDIC toolbox directory", value=_get_user("paths", "nordic_toolbox_dir")
    )
    slurm_email = st.text_input("SLURM email", value=_get_user("slurm", "email"))
with c2:
    dcm2bids_ver = st.text_input(
        "dcm2bids version", value=_get_user("containers", "dcm2bids_version") or "3.2.0"
    )
    fmriprep_ver = st.text_input(
        "fMRIPrep version", value=_get_user("containers", "fmriprep_version") or "24.1.1"
    )
    mriqc_ver = st.text_input(
        "MRIQC version", value=_get_user("containers", "mriqc_version") or "24.0.2"
    )

# A project may pin a different value on top of any of these. The fields above are
# the shared ones (that is what they save), so say plainly where this project
# actually differs rather than quietly displaying one and using the other.
_overridden = {
    label: value
    for label, value in (
        ("containers directory", _project_overrides("paths", "containers_dir")),
        ("FreeSurfer license", _project_overrides("paths", "fs_license")),
        ("NORDIC toolbox", _project_overrides("paths", "nordic_toolbox_dir")),
        ("dcm2bids version", _project_overrides("containers", "dcm2bids_version")),
        ("fMRIPrep version", _project_overrides("containers", "fmriprep_version")),
        ("MRIQC version", _project_overrides("containers", "mriqc_version")),
    )
    if value is not None
}
if _overridden:
    st.info(
        "**This project overrides some of these**, so it will use the value on "
        "the right regardless of what is saved here:\n"
        + "\n".join(f"- {label} → `{value}`" for label, value in _overridden.items())
    )

# Validate shared resources
issues = []
if containers_dir and not Path(containers_dir).is_dir():
    issues.append(f"Containers directory `{containers_dir}` does not exist")
elif containers_dir:
    for name, ver in [("dcm2bids", dcm2bids_ver), ("fmriprep", fmriprep_ver), ("mriqc", mriqc_ver)]:
        if not any(
            (Path(containers_dir) / f"{name}-{ver}.{ext}").exists() for ext in ("sif", "simg")
        ) and not any((Path(containers_dir) / f"{name}.{ext}").exists() for ext in ("sif", "simg")):
            issues.append(f"Container not found: `{name}` ({ver}) in `{containers_dir}`")
if fs_license and not Path(fs_license).exists():
    issues.append(f"FreeSurfer license `{fs_license}` does not exist")
if issues:
    st.warning("Attention:")
    for i in issues:
        st.markdown(f"- {i}")

if st.button("Save shared resources"):
    user_cfg = {
        "paths": {
            "containers_dir": containers_dir,
            "fs_license": fs_license,
            "nordic_toolbox_dir": nordic_toolbox_dir,
        },
        "containers": {
            "dcm2bids_version": dcm2bids_ver,
            "fmriprep_version": fmriprep_ver,
            "mriqc_version": mriqc_ver,
        },
        "slurm": {"email": slurm_email},
    }
    path = save_user_config(_clean_dict(user_cfg), owned=_USER_OWNED)
    queue_toast(f"Saved shared resources to {path}")
    st.rerun()
