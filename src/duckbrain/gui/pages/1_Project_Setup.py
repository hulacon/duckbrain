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
    load_config,
    project_config_path,
    save_project_config,
    save_user_config,
    scaffold_project,
    user_config_path,
)

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
project_dir = st.text_input(
    "Project directory",
    value=current_project,
    placeholder="/projects/<pirg>/<user>/<study>",
)

col_open, col_info = st.columns([1, 2])
with col_open:
    if st.button("Open / Create Project", type="primary", disabled=not project_dir):
        scaffold_project(project_dir)  # idempotent: makes sourcedata/derivatives/code
        st.session_state["project_dir"] = project_dir
        os.environ[PROJECT_ENV] = project_dir  # visible to other pages this session
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
use_sessions = st.selectbox(
    "Use BIDS session entity (ses-)",
    options=["auto", "true", "false"],
    index=["auto", "true", "false"].index(_get("project", "use_sessions", "auto")),
    help="auto = include ses- only when a subject has more than one session",
)

st.subheader("LCNI DICOM source")
c1, c2, c3 = st.columns(3)
with c1:
    dcm_base = st.text_input("Base directory", value=_get("dcm_source", "base_dir") or "/projects/lcni/dcm")
with c2:
    dcm_group = st.text_input("Group", value=_get("dcm_source", "group"), help='e.g. "hulacon"')
with c3:
    dcm_project = st.text_input("Project", value=_get("dcm_source", "project"), help='e.g. "Hutchinson/divatten"')

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
        "dcm_source": {"base_dir": dcm_base, "group": dcm_group, "project": dcm_project},
        "slurm": {
            "account": slurm_account,
            "partition": slurm_partition,
            "partition_long": slurm_partition_long,
            "time": slurm_time,
        },
    }
    path = save_project_config(active_project, _clean_dict(project_cfg))
    st.success(f"Saved project settings to `{path}`")
    st.rerun()

# ---- Shared machine resources (saved to the USER config) ----
st.divider()
st.header("Shared resources (all your projects)")
st.caption(f"Saved to `{user_config_path()}` — reused across every project.")
c1, c2 = st.columns(2)
with c1:
    containers_dir = st.text_input("Containers directory", value=_get("paths", "containers_dir"))
    fs_license = st.text_input("FreeSurfer license", value=_get("paths", "fs_license"))
    nordic_toolbox_dir = st.text_input("NORDIC toolbox directory", value=_get("paths", "nordic_toolbox_dir"))
with c2:
    dcm2bids_ver = st.text_input("dcm2bids version", value=_get("containers", "dcm2bids_version") or "3.2.0")
    fmriprep_ver = st.text_input("fMRIPrep version", value=_get("containers", "fmriprep_version") or "24.1.1")
    mriqc_ver = st.text_input("MRIQC version", value=_get("containers", "mriqc_version") or "24.1.0")
    slurm_email = st.text_input("SLURM email", value=_get("slurm", "email"))

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
    st.success(f"Saved shared resources to `{path}`")
    st.rerun()
