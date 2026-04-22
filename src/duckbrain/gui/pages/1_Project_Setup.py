"""Page 1: Project Setup — first-run wizard for configuring duckbrain."""

import streamlit as st
from pathlib import Path


st.set_page_config(page_title="Project Setup — duckbrain", layout="wide")
st.title("Project Setup")
st.markdown("Configure your project paths, SLURM settings, and container locations.")

# ---- Load existing config if available ----
existing_config = {}
try:
    from duckbrain.config import load_config, _find_config_dir

    existing_config = load_config()
    config_dir = _find_config_dir()
    st.success(f"Config loaded from: {config_dir}")
except FileNotFoundError:
    config_dir = None
    st.info("No existing configuration found. Fill in the fields below to get started.")


def _get(section: str, key: str, default: str = "") -> str:
    return str(existing_config.get(section, {}).get(key, default))


# ---- Project Info ----
st.header("Project")
project_name = st.text_input("Project name", value=_get("project", "name"), help="A short name for your project")

# ---- Paths ----
st.header("Paths")
col1, col2 = st.columns(2)
with col1:
    bids_dir = st.text_input("BIDS directory", value=_get("paths", "bids_dir"), help="Root BIDS dataset directory")
    sourcedata_dir = st.text_input(
        "Sourcedata directory",
        value=_get("paths", "sourcedata_dir") or (f"{bids_dir}/sourcedata" if bids_dir else ""),
        help="Where organized DICOMs live (usually <bids_dir>/sourcedata)",
    )
    derivatives_dir = st.text_input(
        "Derivatives directory",
        value=_get("paths", "derivatives_dir") or (f"{bids_dir}/derivatives" if bids_dir else ""),
        help="Usually <bids_dir>/derivatives",
    )
with col2:
    work_dir = st.text_input("Work directory", value=_get("paths", "work_dir"), help="Scratch space for fMRIPrep etc.")
    containers_dir = st.text_input("Containers directory", value=_get("paths", "containers_dir"), help="Singularity .sif images")
    nordic_toolbox_dir = st.text_input("NORDIC toolbox directory", value=_get("paths", "nordic_toolbox_dir"), help="Path to NORDIC_Raw MATLAB toolbox")
    fs_license = st.text_input("FreeSurfer license", value=_get("paths", "fs_license"), help="Path to FreeSurfer license.txt")

# ---- LCNI DICOM Source ----
st.header("LCNI DICOM Source")
col1, col2, col3 = st.columns(3)
with col1:
    dcm_base = st.text_input("Base directory", value=_get("dcm_source", "base_dir") or "/projects/lcni/dcm")
with col2:
    dcm_group = st.text_input("Group", value=_get("dcm_source", "group"), help='e.g., "hulacon"')
with col3:
    dcm_project = st.text_input("Project", value=_get("dcm_source", "project"), help='e.g., "mmmdata"')

# ---- Container Versions ----
st.header("Container Versions")
col1, col2, col3 = st.columns(3)
with col1:
    dcm2bids_ver = st.text_input("dcm2bids", value=_get("containers", "dcm2bids_version") or "3.2.0")
with col2:
    fmriprep_ver = st.text_input("fMRIPrep", value=_get("containers", "fmriprep_version") or "24.1.1")
with col3:
    mriqc_ver = st.text_input("MRIQC", value=_get("containers", "mriqc_version") or "24.1.0")

# ---- SLURM Settings ----
st.header("SLURM Settings")
col1, col2 = st.columns(2)
with col1:
    slurm_email = st.text_input("Email", value=_get("slurm", "email"))
    slurm_account = st.text_input("Account/allocation", value=_get("slurm", "account"))
    slurm_partition = st.text_input("Default partition", value=_get("slurm", "partition") or "medium")
with col2:
    slurm_partition_long = st.text_input("Long partition", value=_get("slurm", "partition_long") or "computelong")
    slurm_time = st.text_input("Default time limit", value=_get("slurm", "time") or "12:00:00")
    slurm_memory = st.text_input("Default memory", value=_get("slurm", "memory") or "16G")

# ---- Path Validation ----
st.header("Validation")
validation_issues = []
for label, path_str in [
    ("BIDS directory", bids_dir),
    ("Work directory", work_dir),
    ("Containers directory", containers_dir),
]:
    if path_str and not Path(path_str).exists():
        validation_issues.append(f"{label}: `{path_str}` does not exist")

if containers_dir and Path(containers_dir).is_dir():
    for name, ver in [("dcm2bids", dcm2bids_ver), ("fmriprep", fmriprep_ver), ("mriqc", mriqc_ver)]:
        found = any(
            (Path(containers_dir) / f"{name}-{ver}.{ext}").exists()
            for ext in ["sif", "simg"]
        )
        if not found:
            validation_issues.append(
                f"Container not found: `{name}-{ver}.sif` in `{containers_dir}`"
            )

if validation_issues:
    st.warning("Some paths need attention:")
    for issue in validation_issues:
        st.markdown(f"- {issue}")
else:
    if bids_dir:
        st.success("All paths look good!")

# ---- Missing Container Commands ----
if containers_dir:
    with st.expander("Container download commands (if needed)"):
        st.code(
            f"""# dcm2bids
singularity build {containers_dir}/dcm2bids-{dcm2bids_ver}.sif docker://unfmontreal/dcm2bids:{dcm2bids_ver}

# fMRIPrep
singularity build {containers_dir}/fmriprep-{fmriprep_ver}.sif docker://nipreps/fmriprep:{fmriprep_ver}

# MRIQC
singularity build {containers_dir}/mriqc-{mriqc_ver}.sif docker://nipreps/mriqc:{mriqc_ver}""",
            language="bash",
        )

# ---- Save Configuration ----
st.divider()
if st.button("Save Configuration", type="primary"):
    local_config = {
        "project": {"name": project_name},
        "paths": {
            "bids_dir": bids_dir,
            "sourcedata_dir": sourcedata_dir,
            "derivatives_dir": derivatives_dir,
            "work_dir": work_dir,
            "containers_dir": containers_dir,
            "nordic_toolbox_dir": nordic_toolbox_dir,
            "fs_license": fs_license,
        },
        "dcm_source": {
            "base_dir": dcm_base,
            "group": dcm_group,
            "project": dcm_project,
        },
        "containers": {
            "dcm2bids_version": dcm2bids_ver,
            "fmriprep_version": fmriprep_ver,
            "mriqc_version": mriqc_ver,
        },
        "slurm": {
            "email": slurm_email,
            "account": slurm_account,
            "partition": slurm_partition,
            "partition_long": slurm_partition_long,
            "time": slurm_time,
            "memory": slurm_memory,
        },
    }

    # Remove empty string values to keep local.toml clean
    def _clean(d):
        return {
            k: _clean(v) if isinstance(v, dict) else v
            for k, v in d.items()
            if v != "" and v != {}
        }

    local_config = _clean(local_config)

    try:
        from duckbrain.config import save_local_config, _find_config_dir

        if config_dir:
            save_local_config(config_dir, local_config)
        else:
            # Find config dir relative to package
            pkg_dir = Path(__file__).resolve().parents[4]
            save_local_config(pkg_dir / "config", local_config)

        st.success("Configuration saved to `config/local.toml`!")
        st.rerun()
    except Exception as e:
        st.error(f"Error saving config: {e}")
