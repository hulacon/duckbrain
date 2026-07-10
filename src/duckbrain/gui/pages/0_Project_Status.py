"""Page 0: Project Status — per-subject pipeline completion matrix.

The one place that answers "what's done, what's half-done, what's left" across
the whole project. Unlike the other pages (which list whatever files exist),
this grades each stage by its *expected outputs* via ``core.surveyor`` — so a
crashed fMRIPrep reads as **partial**, not done.
"""

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Project Status — duckbrain", layout="wide")
st.title("Project Status")
st.caption(
    "Completion by expected outputs, not folder presence — a crashed run shows "
    "as *partial*, not done."
)

# ---- Load config ----
try:
    from duckbrain.config import load_config
    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
if not paths.get("bids_dir"):
    st.error("Project directory not set. Start with **Project Setup**.")
    st.stop()

project_name = config.get("project", {}).get("name", "")
if project_name:
    st.caption(f"Project: **{project_name}** — `{paths['bids_dir']}`")

if st.button("↻ Refresh", help="Re-scan the filesystem"):
    st.rerun()

# ---- Survey ----
from duckbrain.core.surveyor import STAGES, Status, survey_project, summarize

with st.spinner("Surveying project…"):
    matrix = survey_project(config)

if matrix.empty:
    st.info(
        "No subjects found yet. Ingest DICOMs on the **Data Ingestion** page, or "
        "point Project Setup at a directory that already contains BIDS data."
    )
    st.stop()

# ---- Per-stage rollup ----
summary = summarize(matrix)
st.subheader("Overview")
cols = st.columns(len(STAGES))
for col, stage in zip(cols, STAGES):
    counts = summary[stage]
    done = counts[Status.COMPLETE.value]
    partial = counts[Status.PARTIAL.value]
    missing = counts[Status.MISSING.value]
    col.metric(stage.capitalize(), f"{done}/{len(matrix)}", help="complete / total")
    bits = []
    if partial:
        bits.append(f"⚠ {partial} partial")
    if missing:
        bits.append(f"○ {missing} missing")
    col.caption(" · ".join(bits) if bits else "✓ all complete")

# ---- Status matrix ----
st.subheader("Subjects")

only_incomplete = st.checkbox(
    "Show only units with unfinished stages", value=False,
    help="Hide subject/sessions where every stage is complete.",
)

view = matrix.copy()
view["session"] = view["session"].replace("", "—")

if only_incomplete:
    incomplete_mask = matrix[list(STAGES)].apply(
        lambda r: any(v != Status.COMPLETE.value for v in r), axis=1
    )
    view = view[incomplete_mask.values]
    if view.empty:
        st.success("Every subject/session is complete across all stages. 🎉")
        st.stop()

_ICON = {
    Status.COMPLETE.value: "🟢 complete",
    Status.PARTIAL.value: "🟡 partial",
    Status.MISSING.value: "⚪ missing",
    Status.NA.value: "— n/a",
}
_BG = {
    Status.COMPLETE.value: "background-color: #1b5e2033; color: inherit",
    Status.PARTIAL.value: "background-color: #f9a82533; color: inherit",
    Status.MISSING.value: "color: #888",
    Status.NA.value: "color: #888",
}


def _style_cell(val):
    # val is the icon-decorated string; grade off its trailing word.
    for status, label in _ICON.items():
        if val == label:
            return _BG[status]
    return ""


display = view.rename(columns={"subject": "sub", "session": "ses"})
for stage in STAGES:
    display[stage] = display[stage].map(lambda v: _ICON.get(v, v))

st.dataframe(
    display.style.map(_style_cell, subset=list(STAGES)),
    width="stretch",
    hide_index=True,
)

st.caption(
    "🟢 all expected outputs present · 🟡 started but incomplete (or crashed) · "
    "⚪ not started. Stages: ingested (DICOMs) → converted (BIDS) → fmriprep → mriqc."
)

# ---- Nipoppy interop export ----
with st.expander("Export Nipoppy bagel (processing_status.tsv)"):
    st.caption(
        "Emit the neurobagel/Nipoppy imaging-bagel TSV — for a neurobagel "
        "dashboard or consortium sharing. duckbrain stays BIDS-native; this is "
        "an on-demand view, not a dependency."
    )
    from duckbrain.core.surveyor import to_bagel

    bagel = to_bagel(matrix, config)
    st.dataframe(bagel, width="stretch", hide_index=True)
    st.download_button(
        "⬇ Download processing_status.tsv",
        data=bagel.to_csv(sep="\t", index=False),
        file_name="processing_status.tsv",
        mime="text/tab-separated-values",
    )
