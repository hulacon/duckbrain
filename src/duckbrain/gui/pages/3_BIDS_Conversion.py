"""Page 3: BIDS Conversion — DICOM inspection + dcm2bids config generation + submission."""

import json

import streamlit as st
import pandas as pd
from pathlib import Path


st.set_page_config(page_title="BIDS Conversion — duckbrain", layout="wide")
st.title("BIDS Conversion")
st.markdown("Inspect DICOMs, generate dcm2bids config, and convert to BIDS format.")

# ---- Load config ----
try:
    from duckbrain.config import load_config

    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
sourcedata_dir = paths.get("sourcedata_dir", "")

if not sourcedata_dir or not Path(sourcedata_dir).is_dir():
    st.error("Sourcedata directory not found. Please ingest data first.")
    st.stop()

# ---- Select subject + session from ingested sourcedata ----
from duckbrain.core.ingestion import list_ingested_sessions

ingested = list_ingested_sessions(sourcedata_dir)
if not ingested:
    st.warning("No ingested sessions found. Go to **Data Ingestion** first.")
    st.stop()

subjects = sorted(set(s["subject"] for s in ingested))
sessions_by_sub = {}
for s in ingested:
    sessions_by_sub.setdefault(s["subject"], []).append(s["session"])

# ---- Bulk conversion (skips per-session review) ----
bids_dir = paths.get("bids_dir", "")
from duckbrain.core.conversion import (
    resolve_dicom_dir,
    session_bids_exists,
    generate_session_config,
    save_dcm2bids_config,
    get_container_path,
)
from duckbrain.core.ingestion import sub_ses_relpath

# Compute conversion status once (rglob per session is not free on shared FS).
converted_map = {
    (s["subject"], s["session"]): session_bids_exists(bids_dir, s["subject"], s["session"])
    for s in ingested
}

with st.expander(f"⚡ Bulk convert all ingested sessions "
                 f"({sum(not v for v in converted_map.values())} unconverted of {len(ingested)})"):
    st.caption(
        "Submits one dcm2bids job per session using the **automatic** task/run "
        "mapping — no per-session review. A session that already has a saved "
        "`dcm2bids_config.json` reuses it (your review isn't overwritten). Good for "
        "dogfooding / large batches; for careful per-study work use the review flow below."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {"subject": s["subject"], "session": s["session"] or "(none)",
                 "converted": "✓" if converted_map[(s["subject"], s["session"])] else ""}
                for s in ingested
            ]
        ),
        width="stretch", hide_index=True,
    )

    bulk_force = st.checkbox(
        "Reconvert already-converted sessions (dcm2bids --force)", value=False, key="bulk_force"
    )
    target = [s for s in ingested if bulk_force or not converted_map[(s["subject"], s["session"])]]

    if st.button(f"Submit conversion for {len(target)} session(s)",
                 type="primary", key="bulk_submit", disabled=not target):
        from duckbrain.core.pipeline import advance_one, _resolve_log_dir

        log_dir = _resolve_log_dir(config)
        results = []
        prog = st.progress(0.0)
        for i, s in enumerate(target):
            sub, ses = s["subject"], s["session"]
            try:
                job_id = advance_one(config, "converted", sub, ses, force=bulk_force)
                results.append({"subject": sub, "session": ses or "(none)",
                                "job_id": job_id, "status": "submitted"})
            except Exception as e:
                results.append({"subject": sub, "session": ses or "(none)",
                                "job_id": "—", "status": f"error: {e}"})
            prog.progress((i + 1) / len(target))

        st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
        n_ok = sum(1 for r in results if r["status"] == "submitted")
        st.success(f"Submitted {n_ok}/{len(target)} job(s). Logs in `{log_dir}`.")

st.markdown("### Per-session review")
col1, col2 = st.columns(2)
with col1:
    subject = st.selectbox("Subject", subjects)
with col2:
    available_sessions = sorted(s for s in sessions_by_sub.get(subject, []) if s)
    if available_sessions:
        session = st.selectbox("Session", available_sessions)
    else:
        session = ""
        st.caption("Single-session study (no ses- entity)")

if not subject:
    st.stop()

from duckbrain.core.ingestion import sub_ses_relpath

# ---- DICOM Inspection ----
dicom_dir = Path(sourcedata_dir) / sub_ses_relpath(subject, session) / "dicom"

if not dicom_dir.exists():
    # Handle symlinks — resolve target
    if dicom_dir.is_symlink():
        dicom_dir = dicom_dir.resolve()
    else:
        st.error(f"DICOM directory not found: `{dicom_dir}`")
        st.stop()

st.subheader("DICOM Series")
from duckbrain.core.dicom_inspect import list_series, classify_series, detect_fieldmaps

series_list = list_series(dicom_dir)
if not series_list:
    st.warning("No series directories found. Check that DICOMs are organized as Series_NN_description/")
    st.stop()

classify_series(series_list)

series_df = pd.DataFrame(
    [
        {
            "Series #": s.series_number,
            "Description": s.description,
            "Classification": s.classification,
            "# Files": s.file_count,
        }
        for s in series_list
    ]
)
st.dataframe(series_df, width="stretch", hide_index=True)

# ---- Fieldmap Detection ----
fieldmaps = detect_fieldmaps(series_list)
st.subheader("Fieldmap Detection")
if fieldmaps.strategy == "none":
    st.info("No fieldmaps detected.")
else:
    st.success(f"Strategy: **{fieldmaps.strategy}**")
    for group_name, dirs in fieldmaps.groups.items():
        label = group_name if group_name else "(unnamed)"
        ap = dirs.get("ap", "—")
        pa = dirs.get("pa", "—")
        st.markdown(f"- Group **{label}**: AP=Series {ap}, PA=Series {pa}")

if fieldmaps.warnings:
    with st.expander("Fieldmap warnings"):
        for w in fieldmaps.warnings:
            st.warning(w)

# ---- Task / Run mapping (source of truth for func naming) ----
st.subheader("Task / Run Mapping")
st.markdown(
    "Auto-detected task labels and run numbers for functional runs. **This table "
    "is the source of truth** — edit any row and the dcm2bids config below "
    "regenerates from it. SBRefs inherit their run's task/run."
)
from duckbrain.core.dcm2bids_config import (
    build_task_run_mapping,
    generate_config,
    config_to_json,
    TaskRunEntry,
    task_rules_from_config,
    task_rules_from_mapping,
)

template = st.text_input(
    "Naming template (optional)",
    value="",
    placeholder="e.g. {task}_r{run}",
    help="Glob-like seed for parsing: {task} and {run} placeholders. Leave blank "
    "to use the built-in heuristic. Editing the table below always wins.",
)

# Project-wide task rules (defined once, inherited by every subject) seed the
# mapping's task labels over the heuristic; this session's edits below still win
# as exceptions, and run numbers stay per-session.
project_rules = task_rules_from_config(config)
if project_rules:
    st.caption(
        f"↪ {len(project_rules)} project-wide task rule(s) applied as defaults. "
        "Edit any row below to override them for this session only."
    )

seed_mapping = build_task_run_mapping(
    series_list, template=template or None, rules=project_rules
)

if seed_mapping:
    mapping_df = st.data_editor(
        pd.DataFrame(
            [
                {
                    "Series #": e.series_number,
                    "Description": e.description,
                    "Role": e.role,
                    "task": e.task,
                    "run": e.run,
                }
                for e in seed_mapping
            ]
        ),
        width="stretch",
        hide_index=True,
        disabled=["Series #", "Description", "Role"],
        key="task_run_mapping_editor",
    )
    edited_mapping = [
        TaskRunEntry(
            series_number=int(row["Series #"]),
            description=row["Description"],
            role=row["Role"],
            task=str(row["task"]),
            run=int(row["run"]) if pd.notna(row["run"]) else None,
        )
        for _, row in mapping_df.iterrows()
    ]

    # Promote this reviewed mapping to the project-wide default so every other
    # subject inherits it (keyed on SeriesDescription; SBRefs inherit their BOLD).
    if st.button(
        "⭑ Save this mapping as the project default",
        key="save_project_task_map",
        help="Writes the BOLD task/run rows to the project config's "
        "[task_mapping]. Other subjects then seed from these instead of the "
        "heuristic. Per-session edits still override.",
    ):
        from duckbrain.config import resolve_project_dir, save_project_task_map

        project_dir = resolve_project_dir() or paths.get("bids_dir", "")
        if not project_dir:
            st.error("No project directory resolved — can't save the default.")
        else:
            rules = task_rules_from_mapping(edited_mapping)
            save_project_task_map(project_dir, rules)
            st.success(
                f"Saved {len(rules)} task rule(s) as the project default in "
                f"`{project_dir}/code/duckbrain.toml`."
            )
else:
    st.info("No functional runs detected in this session.")
    edited_mapping = []

# ---- Auto-generate dcm2bids config ----
st.subheader("dcm2bids Configuration")

auto_config = generate_config(
    series_list, fieldmaps, subject=subject, session=session, mapping=edited_mapping
)
auto_json = config_to_json(auto_config)

st.markdown("Review and edit the auto-generated dcm2bids config below:")
edited_json = st.text_area(
    "dcm2bids config JSON",
    value=auto_json,
    height=400,
    key="dcm2bids_config_editor",
)

# Validate JSON
try:
    parsed_config = json.loads(edited_json)
    st.success(f"{len(parsed_config.get('descriptions', []))} descriptions defined")
except json.JSONDecodeError as e:
    st.error(f"Invalid JSON: {e}")
    parsed_config = None

# ---- Save config / Convert / Export ----
st.divider()

col1, col2, col3 = st.columns(3)

with col1:
    save_config_btn = st.button("Save Config JSON")
with col2:
    convert_btn = st.button("Submit Conversion Job", type="primary")
with col3:
    export_btn = st.button("Export SBATCH Script")

force = st.checkbox("Force overwrite existing BIDS output", value=False)

if parsed_config is None and (save_config_btn or convert_btn or export_btn):
    st.error("Fix the JSON errors above before proceeding.")
    st.stop()

# Save config
config_json_path = Path(sourcedata_dir) / sub_ses_relpath(subject, session) / "dcm2bids_config.json"

if save_config_btn and parsed_config:
    from duckbrain.core.conversion import save_dcm2bids_config

    save_dcm2bids_config(parsed_config, config_json_path)
    st.success(f"Config saved to: `{config_json_path}`")

# Build sbatch context
from duckbrain.slurm.templates import render_sbatch, build_context
from duckbrain.core.conversion import get_container_path

container_path = get_container_path(config)
ctx = build_context(
    config,
    "dcm2bids",
    subject=subject,
    session=session,
    dicom_dir=str(dicom_dir),
    config_json=str(config_json_path),
    config_json_dir=str(config_json_path.parent),
    container_path=str(container_path),
    force=force,
)

# Logs + submitted scripts go to the project's shared log_dir (not node-local
# work_dir=/tmp), so a failed job's log stays reachable from the GUI/login node.
log_dir = paths.get("log_dir", "") or f"{paths.get('work_dir', '/tmp')}/logs"
job_tag = f"{subject}_{session}" if session else subject

# Submit conversion
if convert_btn and parsed_config:
    # Save config first if not already saved
    from duckbrain.core.conversion import save_dcm2bids_config
    save_dcm2bids_config(parsed_config, config_json_path)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)  # SLURM won't create --output dir
        sbatch_content = render_sbatch("dcm2bids", ctx)
        from duckbrain.slurm.submit import submit_job

        job_id = submit_job(sbatch_content, f"dcm2bids_{job_tag}", scripts_dir=log_dir)
        st.success(f"Job submitted! Job ID: **{job_id}** — logs will appear in `{log_dir}`")
    except Exception as e:
        st.error(f"Submission failed: {e}")

# Export script
if export_btn and parsed_config:
    try:
        sbatch_content = render_sbatch("dcm2bids", ctx)
        export_path = Path(log_dir) / f"dcm2bids_{job_tag}.sbatch"
        from duckbrain.slurm.submit import export_script

        export_script(sbatch_content, export_path)
        st.success(f"Script exported to: `{export_path}`")
        with st.expander("View script"):
            st.code(sbatch_content, language="bash")
    except Exception as e:
        st.error(f"Export failed: {e}")
