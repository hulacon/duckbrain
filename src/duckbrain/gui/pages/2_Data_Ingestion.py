"""Page 2: Data Ingestion — import DICOMs from LCNI export into sourcedata."""

import streamlit as st
import pandas as pd
from pathlib import Path


st.set_page_config(page_title="Data Ingestion — duckbrain", layout="wide")
st.title("Data Ingestion")
st.markdown("Import DICOM sessions from the LCNI export directory into your BIDS sourcedata.")

# ---- Load config ----
try:
    from duckbrain.config import load_config

    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

# ---- Show current paths ----
dcm_source = config.get("dcm_source", {})
paths = config.get("paths", {})
sourcedata_dir = paths.get("sourcedata_dir", "")

dcm_source_dir = None
try:
    from duckbrain.core.ingestion import build_dcm_source_path

    dcm_source_dir = build_dcm_source_path(config)
    st.info(f"DICOM source: `{dcm_source_dir}`")
except ValueError as e:
    st.error(str(e))
    st.stop()

if not dcm_source_dir.is_dir():
    st.error(f"DICOM source directory not found: `{dcm_source_dir}`")
    st.stop()

if not sourcedata_dir:
    st.error("sourcedata_dir not set in config. Please complete Project Setup.")
    st.stop()

# ---- Already ingested sessions ----
from duckbrain.core.ingestion import discover_sessions, list_ingested_sessions, ingest_session, BidsMapping

ingested = list_ingested_sessions(sourcedata_dir)
if ingested:
    st.subheader("Already Ingested")
    ingested_df = pd.DataFrame(ingested)
    ingested_df["path"] = ingested_df["path"].astype(str)
    st.dataframe(ingested_df, use_container_width=True, hide_index=True)

# ---- Discover available sessions ----
st.subheader("Available DICOM Sessions")
sessions = discover_sessions(dcm_source_dir)

if not sessions:
    st.warning("No session folders found in the DICOM source directory.")
    st.stop()

# Build the editable table once and keep it in session_state so programmatic
# edits (auto-assign) and manual edits survive reruns. Rebuild only when the
# set of discovered folders changes, so a rerun (e.g. ticking a checkbox)
# never wipes assigned subjects/sessions.
folder_key = tuple(s.folder_name for s in sessions)
if st.session_state.get("_ingest_folders") != folder_key:
    st.session_state["_ingest_folders"] = folder_key
    st.session_state["ingest_df"] = pd.DataFrame(
        [
            {
                "select": False,
                "folder_name": s.folder_name,
                "parsed_subject": s.parsed_subject,
                "parsed_session": s.parsed_session,
                "date": s.date,
                "series_count": s.series_count,
                "bids_subject": "",
                "bids_session": "",
            }
            for s in sessions
        ]
    )
    st.session_state["_editor_rev"] = 0

# ---- Auto-session numbering ----
if st.button("Auto-assign session numbers by date"):
    from duckbrain.core.ingestion import auto_number_sessions

    mappings = auto_number_sessions(
        sessions, use_sessions=config.get("project", {}).get("use_sessions", "auto")
    )
    mapping_lookup = {m.folder_name: m for m in mappings}
    base = st.session_state["ingest_df"]
    for i, row in base.iterrows():
        m = mapping_lookup.get(row["folder_name"])
        if m:
            base.at[i, "bids_subject"] = m.bids_subject
            base.at[i, "bids_session"] = m.bids_session
    # Bump the editor key so it reloads from the freshly-populated base.
    st.session_state["_editor_rev"] += 1
    n_subj = len(set(m.bids_subject for m in mappings))
    used_sessions = any(m.bids_session for m in mappings)
    msg = f"Auto-assigned {n_subj} subject(s)"
    if not used_sessions:
        msg += " — single-session study, so BIDS Session is left blank (by design)."
    st.success(msg)

st.markdown("Edit the **bids_subject** and **bids_session** columns to assign BIDS identifiers, then select sessions to ingest.")

edited_df = st.data_editor(
    st.session_state["ingest_df"],
    column_config={
        "select": st.column_config.CheckboxColumn("Select", default=False),
        "folder_name": st.column_config.TextColumn("Folder Name", disabled=True),
        "parsed_subject": st.column_config.TextColumn("Parsed Subject", disabled=True),
        "parsed_session": st.column_config.TextColumn("Parsed Session", disabled=True),
        "date": st.column_config.TextColumn("Date", disabled=True),
        "series_count": st.column_config.NumberColumn("# Series", disabled=True),
        "bids_subject": st.column_config.TextColumn("BIDS Subject", help="e.g., 01"),
        "bids_session": st.column_config.TextColumn("BIDS Session", help="e.g., 01"),
    },
    use_container_width=True,
    hide_index=True,
    key=f"session_editor_{st.session_state['_editor_rev']}",
)

# ---- Ingestion ----
selected = edited_df[edited_df["select"] == True]  # noqa: E712

if not selected.empty:
    # Validate all selected rows have BIDS mappings
    missing_mapping = selected[selected["bids_subject"] == ""]
    if not missing_mapping.empty:
        st.warning("Some selected sessions are missing a BIDS subject assignment.")

    col1, col2 = st.columns(2)
    with col1:
        method = st.radio("Ingestion method", ["symlink", "copy"], index=0, horizontal=True)
    with col2:
        st.info(
            "**Symlink** saves disk space (recommended). "
            "**Copy** creates independent copies of DICOMs."
        )

    if st.button("Ingest Selected Sessions", type="primary"):
        valid = selected[selected["bids_subject"] != ""]
        if valid.empty:
            st.error("No sessions with a BIDS subject assignment selected.")
        else:
            progress = st.progress(0)
            results = []
            for i, (_, row) in enumerate(valid.iterrows()):
                # Find matching SessionInfo
                session = next(
                    s for s in sessions if s.folder_name == row["folder_name"]
                )
                mapping = BidsMapping(
                    folder_name=row["folder_name"],
                    bids_subject=row["bids_subject"],
                    bids_session=row["bids_session"],
                )
                try:
                    target = ingest_session(session, mapping, sourcedata_dir, method=method)
                    results.append(
                        {"folder": row["folder_name"], "status": "success", "path": str(target)}
                    )
                except Exception as e:
                    results.append(
                        {"folder": row["folder_name"], "status": "error", "path": str(e)}
                    )
                progress.progress((i + 1) / len(valid))

            st.subheader("Ingestion Results")
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

# ---- BIDS Metadata Generation ----
st.divider()
st.subheader("BIDS Metadata")
st.markdown("Generate `participants.tsv` and `dataset_description.json` from DICOM demographics.")

bids_dir = paths.get("bids_dir", "")
col1, col2 = st.columns(2)
with col1:
    if st.button("Generate participants.tsv"):
        if not bids_dir:
            st.error("BIDS directory not set in config.")
        elif not sourcedata_dir or not Path(sourcedata_dir).is_dir():
            st.error("No sourcedata found.")
        else:
            from duckbrain.core.bids_metadata import generate_participants_from_sourcedata

            try:
                tsv_path = generate_participants_from_sourcedata(sourcedata_dir, bids_dir)
                participants_df = pd.read_csv(tsv_path, sep="\t")
                if participants_df.empty:
                    st.warning(
                        f"No ingested subjects found under `{sourcedata_dir}` — "
                        "ingest sessions above first. Wrote a header-only "
                        f"`{tsv_path}`."
                    )
                else:
                    st.success(f"Written: `{tsv_path}` ({len(participants_df)} subjects)")
                    st.dataframe(participants_df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Error: {e}")

with col2:
    if st.button("Generate dataset_description.json"):
        if not bids_dir:
            st.error("BIDS directory not set in config.")
        else:
            from duckbrain.core.bids_metadata import write_dataset_description

            project_name = config.get("project", {}).get("name", "")
            try:
                desc_path = write_dataset_description(bids_dir, name=project_name)
                st.success(f"Written: `{desc_path}`")
            except Exception as e:
                st.error(f"Error: {e}")

# ---- DICOM Sorter (for non-LCNI data) ----
st.divider()
with st.expander("DICOM Sorter (for unsorted DICOM files)"):
    st.markdown(
        "If your DICOMs are not already organized into `Series_NN_Description/` directories "
        "(e.g., a flat dump from a CD or PACS export), use this tool to sort them first."
    )
    sort_input = st.text_input("Input directory (unsorted DICOMs)", key="sort_input")
    sort_output = st.text_input("Output directory (organized DICOMs)", key="sort_output")
    sort_col1, sort_col2 = st.columns(2)
    with sort_col1:
        sort_copy = st.checkbox("Copy files (instead of moving)", value=False, key="sort_copy")
        sort_study = st.checkbox("Group by StudyDescription", value=False, key="sort_study")
    with sort_col2:
        sort_dry_run = st.checkbox("Dry run (preview only)", value=True, key="sort_dry_run")

    if st.button("Sort DICOMs"):
        if not sort_input or not sort_output:
            st.error("Provide both input and output directories.")
        elif not Path(sort_input).is_dir():
            st.error(f"Input directory not found: `{sort_input}`")
        else:
            from duckbrain.core.dicom_sorter import sort_dicoms

            with st.spinner("Scanning DICOMs..."):
                result = sort_dicoms(
                    sort_input,
                    sort_output,
                    include_study_dir=sort_study,
                    copy=sort_copy,
                    dry_run=sort_dry_run,
                )
            action = "Would sort" if sort_dry_run else "Sorted"
            st.success(
                f"{action} **{result.sorted_files}** of {result.total_files} files. "
                f"Skipped: {result.skipped_files} (not DICOM). "
                f"Duplicates: {result.duplicates}."
            )
            if result.errors:
                with st.expander(f"{len(result.errors)} errors"):
                    for err in result.errors:
                        st.text(err)
