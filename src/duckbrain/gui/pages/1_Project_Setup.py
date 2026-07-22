"""Page 1: Project Setup — project-dir-first configuration.

The project directory is the single anchor: sourcedata/derivatives/code are
derived from it, project-specific settings live inside the project
(<project>/code/duckbrain.toml), and shared machine resources (containers,
licenses, container versions) live in the user config (~/.config/duckbrain/).
"""

import os
from pathlib import Path

import streamlit as st

from duckbrain.config import (
    PROJECT_ENV,
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
from duckbrain.gui.components import directory_picker

st.set_page_config(page_title="Project Setup — duckbrain", layout="wide")
st.title("Project Setup")


def _clean_dict(d: dict) -> dict:
    """Drop empty strings and empty sub-dicts so saved TOML stays minimal."""
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = _clean_dict(v)
            if v:
                out[k] = v
        elif v != "":
            out[k] = v
    return out

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


# ---- Derived layout (read-only) ----
st.header("Layout (derived from the project directory)")
st.code(
    f"bids_dir        {paths.get('bids_dir','')}\n"
    f"sourcedata_dir  {paths.get('sourcedata_dir','')}\n"
    f"derivatives_dir {paths.get('derivatives_dir','')}\n"
    f"code_dir        {paths.get('code_dir','')}\n"
    f"work_dir        {paths.get('work_dir','')}   (scratch; not under the project)",
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
if _stored_use_sessions not in ("", None) and _use_sessions_default == "auto" and (
    str(_stored_use_sessions).strip().lower() != "auto"
):
    # Don't silently swallow a value nobody can act on — a typo here decides
    # whether the dataset gets ses- entities at all.
    st.warning(
        f"`use_sessions = {_stored_use_sessions!r}` in the project config isn't a "
        "value duckbrain recognizes, so **auto** is being used. Save below to "
        "replace it."
    )

st.subheader("LCNI DICOM source")
# Legacy configs used base_dir/group/project; if one is present, seed from it.
_legacy_dcm = _get("dcm_source", "dir") or "/".join(
    p for p in (_get("dcm_source", "base_dir"), _get("dcm_source", "group"), _get("dcm_source", "project")) if p
) or "/projects/lcni/dcm"
dcm_dir = directory_picker(
    "DICOM source directory",
    key="dcm_source_pick",
    default=_legacy_dcm,
    must_exist=True,
    help="Full path to this study's DICOM export folder (the one containing the "
    "session folders, e.g. .../hulacon/Hutchinson/divatten).",
)

st.subheader("SLURM (project)")
c1, c2 = st.columns(2)
with c1:
    slurm_account = st.text_input("Account / PIRG", value=_get("slurm", "account"))
    slurm_partition = st.text_input("Default partition", value=_get("slurm", "partition") or "medium")
with c2:
    slurm_partition_long = st.text_input("Long partition", value=_get("slurm", "partition_long") or "computelong")
    slurm_time = st.text_input("Default time limit", value=_get("slurm", "time") or "12:00:00")

if st.button("Save project settings"):
    project_cfg = {
        "project": {"name": project_name, "use_sessions": use_sessions},
        "dcm_source": {"dir": dcm_dir},
        "slurm": {
            "account": slurm_account,
            "partition": slurm_partition,
            "partition_long": slurm_partition_long,
            "time": slurm_time,
        },
    }
    path = save_project_config(active_project, _clean_dict(project_cfg))
    # Must be a toast, not st.success: the rerun below restarts the script from the
    # top and wipes any element written before it, so a success box would flash for
    # zero frames. Nothing else on this page changes visibly after a save (the
    # widgets already show what you typed), so without this the button looked inert.
    st.toast(f"Saved project settings to {path}", icon="✅")
    st.rerun()

# ---- Shared machine resources (saved to the USER config) ----
st.divider()
st.header("Shared resources (all your projects)")
st.caption(f"Saved to `{user_config_path()}` — reused across every project.")
containers_dir = directory_picker(
    "Containers directory",
    key="containers_pick",
    default=_get("paths", "containers_dir") or str(Path.home() / "containers"),
    must_exist=True,
    help="Directory holding the Singularity .sif / .simg images.",
)
c1, c2 = st.columns(2)
with c1:
    fs_license = st.text_input("FreeSurfer license (file)", value=_get("paths", "fs_license"))
    nordic_toolbox_dir = st.text_input("NORDIC toolbox directory", value=_get("paths", "nordic_toolbox_dir"))
    slurm_email = st.text_input("SLURM email", value=_get("slurm", "email"))
with c2:
    dcm2bids_ver = st.text_input("dcm2bids version", value=_get("containers", "dcm2bids_version") or "3.2.0")
    fmriprep_ver = st.text_input("fMRIPrep version", value=_get("containers", "fmriprep_version") or "24.1.1")
    mriqc_ver = st.text_input("MRIQC version", value=_get("containers", "mriqc_version") or "24.0.2")

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
    path = save_user_config(_clean_dict(user_cfg))
    st.toast(f"Saved shared resources to {path}", icon="✅")  # see note on the save above
    st.rerun()
