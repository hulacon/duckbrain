"""Page 5: QC Dashboard — review MRIQC metrics, motion, and make keep/exclude decisions."""

import streamlit as st
import pandas as pd
from pathlib import Path


st.set_page_config(page_title="QC Dashboard — duckbrain", layout="wide")
st.title("QC Dashboard")

# ---- Load config ----
try:
    from duckbrain.config import load_config
    config = load_config()
except FileNotFoundError:
    st.error("Configuration not found. Please complete **Project Setup** first.")
    st.stop()

paths = config.get("paths", {})
derivatives_dir = paths.get("derivatives_dir", "")

if not derivatives_dir:
    st.error("Derivatives directory not set. Check Project Setup.")
    st.stop()

mriqc_dir = Path(derivatives_dir) / "mriqc"
fmriprep_dir = Path(derivatives_dir) / "fmriprep"
decisions_dir = Path(derivatives_dir) / "preprocessing_qc"

# ---- Modality selector ----
modality = st.selectbox("Modality", ["bold", "T1w", "T2w"])

# ---- Load MRIQC metrics ----
from duckbrain.core.qc import (
    load_mriqc_metrics,
    detect_outliers,
    summarize_motion,
    load_decisions,
    save_decision,
    BOLD_IQMS,
    ANAT_IQMS,
)

metrics_df = load_mriqc_metrics(mriqc_dir, modality)

if metrics_df.empty:
    st.warning(f"No MRIQC metrics found for **{modality}** in `{mriqc_dir}`.")
    st.info("Run MRIQC first from the **Preprocessing** page.")
    st.stop()

st.subheader(f"MRIQC Metrics — {modality} ({len(metrics_df)} runs)")

# ---- Outlier detection ----
iqm_cols = BOLD_IQMS if modality == "bold" else ANAT_IQMS
iqr_mult = st.slider("IQR multiplier for outlier detection", 1.0, 3.0, 1.5, 0.1)
metrics_with_outliers = detect_outliers(metrics_df, iqm_columns=iqm_cols, iqr_multiplier=iqr_mult)

# Show summary
n_outliers = metrics_with_outliers["is_outlier"].sum()
st.metric("Outlier runs", n_outliers, delta=None)

# ---- Metrics table ----
# Select display columns
id_cols = [c for c in ["sub", "ses", "task", "run", "_source_file"] if c in metrics_with_outliers.columns]
available_iqms = [c for c in iqm_cols if c in metrics_with_outliers.columns]
display_cols = id_cols + available_iqms + ["is_outlier"]

st.dataframe(
    metrics_with_outliers[display_cols].style.apply(
        lambda row: [
            "background-color: #ffcccc" if row.get("is_outlier", False) else ""
            for _ in row
        ],
        axis=1,
    ),
    width="stretch",
    hide_index=True,
)

# ---- IQM Distribution Plots ----
st.subheader("IQM Distributions")

try:
    import plotly.express as px

    for iqm in available_iqms:
        if iqm in metrics_with_outliers.columns:
            fig = px.box(
                metrics_with_outliers,
                y=iqm,
                x="sub" if "sub" in metrics_with_outliers.columns else None,
                points="all",
                title=iqm,
                hover_data=id_cols,
            )
            fig.update_layout(height=300)
            st.plotly_chart(fig, width="stretch")
except ImportError:
    st.info("Install plotly for interactive distribution charts.")

# ---- Motion Summary (BOLD only) ----
if modality == "bold" and fmriprep_dir.is_dir():
    st.subheader("Motion Summary")
    motion_df = summarize_motion(fmriprep_dir)
    if not motion_df.empty:
        motion_id_cols = [c for c in ["sub", "ses", "task", "run"] if c in motion_df.columns]
        motion_display = motion_id_cols + ["mean_fd", "max_fd", "pct_high_motion", "n_volumes"]
        motion_display = [c for c in motion_display if c in motion_df.columns]
        st.dataframe(motion_df[motion_display], width="stretch", hide_index=True)

        # Motion scatter plot
        try:
            if "mean_fd" in motion_df.columns:
                fig = px.scatter(
                    motion_df,
                    x="mean_fd",
                    y="pct_high_motion",
                    color="sub" if "sub" in motion_df.columns else None,
                    hover_data=motion_id_cols,
                    title="Motion: Mean FD vs % High Motion Frames",
                )
                st.plotly_chart(fig, width="stretch")
        except Exception:
            pass
    else:
        st.info("No fMRIPrep confounds files found.")

# ---- QC Decisions ----
st.subheader("QC Decisions")
st.markdown("Review runs and mark them as **keep**, **exclude**, or **investigate**.")

existing_decisions = load_decisions(decisions_dir)

# Build run key column
if "sub" in metrics_with_outliers.columns:
    metrics_with_outliers["run_key"] = metrics_with_outliers.apply(
        lambda row: "_".join(
            f"{k}-{row[k]}"
            for k in ["sub", "ses", "task", "run"]
            if k in row and pd.notna(row[k])
        ) + f"_{modality}",
        axis=1,
    )

    # Add existing decisions
    metrics_with_outliers["current_decision"] = metrics_with_outliers["run_key"].map(
        lambda k: existing_decisions.get(k, {}).get("latest", {}).get("decision", "—")
    )

    for idx, row in metrics_with_outliers.iterrows():
        run_key = row["run_key"]
        current = existing_decisions.get(run_key, {}).get("latest", {})

        with st.expander(f"{run_key} — {current.get('decision', 'no decision')}"):
            col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
            with col1:
                if st.button("Keep", key=f"keep_{run_key}"):
                    save_decision(decisions_dir, run_key, "keep")
                    st.rerun()
            with col2:
                if st.button("Exclude", key=f"excl_{run_key}"):
                    save_decision(decisions_dir, run_key, "exclude")
                    st.rerun()
            with col3:
                if st.button("Investigate", key=f"inv_{run_key}"):
                    save_decision(decisions_dir, run_key, "investigate")
                    st.rerun()
            with col4:
                reason = st.text_input("Reason", key=f"reason_{run_key}", value=current.get("reason", ""))
                if reason and reason != current.get("reason", ""):
                    decision = current.get("decision", "investigate")
                    save_decision(decisions_dir, run_key, decision, reason=reason)

            # Show relevant IQMs
            for iqm in available_iqms:
                if iqm in row and pd.notna(row[iqm]):
                    outlier_flag = " (OUTLIER)" if row.get(f"{iqm}_outlier", False) else ""
                    st.markdown(f"  - **{iqm}**: {row[iqm]:.4f}{outlier_flag}")
