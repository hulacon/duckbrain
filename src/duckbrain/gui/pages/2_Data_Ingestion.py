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

# Build editable table
session_data = []
for s in sessions:
    session_data.append(
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
    )

df = pd.DataFrame(session_data)
st.markdown("Edit the **bids_subject** and **bids_session** columns to assign BIDS identifiers, then select sessions to ingest.")

edited_df = st.data_editor(
    df,
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
    key="session_editor",
)

# ---- Ingestion ----
selected = edited_df[edited_df["select"] == True]  # noqa: E712

if not selected.empty:
    # Validate all selected rows have BIDS mappings
    missing_mapping = selected[
        (selected["bids_subject"] == "") | (selected["bids_session"] == "")
    ]
    if not missing_mapping.empty:
        st.warning("Some selected sessions are missing BIDS subject/session assignments.")

    col1, col2 = st.columns(2)
    with col1:
        method = st.radio("Ingestion method", ["symlink", "copy"], index=0, horizontal=True)
    with col2:
        st.info(
            "**Symlink** saves disk space (recommended). "
            "**Copy** creates independent copies of DICOMs."
        )

    if st.button("Ingest Selected Sessions", type="primary"):
        valid = selected[
            (selected["bids_subject"] != "") & (selected["bids_session"] != "")
        ]
        if valid.empty:
            st.error("No sessions with complete BIDS mappings selected.")
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
