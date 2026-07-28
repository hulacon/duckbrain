"""Page 5: QC Dashboard — read the QC report, and record keep/exclude decisions.

Thin on purpose. Everything that decides *what* is shown lives in
``core.qc_report`` and ``core.qc``, where a test can import it; this file only
wires widgets to those functions. The page is a Streamlit script no test
imports, so logic that lives here is logic nothing covers — which is exactly why
``core/qc.py`` was the only untested module in ``core/``.

One renderer, two deliveries: the report is embedded below, and offered as a
download / written to ``derivatives/``. They differ in one argument —
``report_base`` — because a relative link to MRIQC's own report resolves for the
exported file (which sits beside ``mriqc/``) and cannot resolve for the embedded
copy (a ``srcdoc`` iframe with no location of its own). MRIQC reports are opened
per run from the decisions panel instead, via ``components.embed_tool_report``.

The tools' own reports hang at the level each is written at: MRIQC's per run, in
the decisions panel; fMRIPrep's per subject, in a panel above the run table. The
anatomical checks a reviewer needs — tissue segmentation, spatial normalization,
surface reconstruction — are computed once per subject and appear in no per-run
view, so a page organised entirely around runs had nowhere to put them.

Recording a decision stays in Streamlit widgets outside that iframe, because
persisting one needs a server-side callback static HTML cannot make.
"""

import getpass
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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

from duckbrain.core import qc, qc_report, report_embed
from duckbrain.gui import components as components_mod

mriqc_dir = Path(derivatives_dir) / "mriqc"
fmriprep_dir = qc_report.resolve_fmriprep_dir(config)
decisions_dir = Path(derivatives_dir) / "preprocessing_qc"

settings = qc.qc_settings()

# ---- fMRIPrep's own reports ----
# Above the MRIQC gate below, deliberately: these exist whenever fMRIPrep has
# run, and stopping the page because MRIQC metrics are missing would hide a
# derivative that is present. Collapsed, because the run table is what the page
# is for and this is a per-subject document that does not belong in it.
fmriprep_reports = qc_report.find_fmriprep_reports(fmriprep_dir)
with st.expander("fMRIPrep report — segmentation, spatial normalization, SDC before/after"):
    if not fmriprep_reports:
        st.caption(f"No fMRIPrep reports in `{fmriprep_dir}`. Run fMRIPrep from **Preprocessing**.")
    else:
        subject = st.selectbox("Subject", sorted(fmriprep_reports), key="fmriprep_subject")
        report_path = fmriprep_dir / fmriprep_reports[subject]
        # Named before it is spent, not after: the figures are read into the
        # server's memory to be served, so an 80 MB subject report is a cost the
        # reader should choose knowingly (core.report_embed.payload_bytes).
        megabytes = report_embed.payload_bytes(report_path) / 1e6
        st.caption(f"`{report_path.name}` — {megabytes:.0f} MB of figures, loaded only when shown.")
        if st.toggle("Show fMRIPrep report", key=f"fmriprep_report_{subject}"):
            components_mod.embed_tool_report(report_path, height=1600)

# ---- Modality selector ----
modality = st.selectbox("Modality", ["bold", "T1w", "T2w"])
iqm_cols = qc.BOLD_IQMS if modality == "bold" else qc.ANAT_IQMS


@st.cache_data(show_spinner="Reading MRIQC output…")
def _load_metrics(mriqc_dir: str, modality: str, _fingerprint: tuple) -> pd.DataFrame:
    """Cached MRIQC load. ``_fingerprint`` changes when the derivative does."""
    return qc.load_mriqc_metrics(mriqc_dir, modality)


def _fingerprint_of(root: Path, pattern: str) -> tuple:
    """(count, newest mtime) of matching files — enough to invalidate the cache."""
    try:
        stats = [p.stat().st_mtime for p in root.rglob(pattern)]
    except OSError:
        return (0, 0.0)
    return (len(stats), max(stats, default=0.0))


metrics_df = _load_metrics(
    str(mriqc_dir), modality, _fingerprint_of(mriqc_dir, f"*_{modality}.json")
)

if metrics_df.empty:
    st.warning(f"No MRIQC metrics found for **{modality}** in `{mriqc_dir}`.")
    st.info("Run MRIQC first from the **Preprocessing** page.")
    st.stop()

# ---- Outlier detection ----
iqr_mult = st.slider(
    "IQR multiplier for outlier detection",
    1.0,
    3.0,
    float(settings["iqr_multiplier"]),
    0.1,
    help=(
        "Flags runs outside a Tukey fence computed across the runs shown — a "
        "comparison within this dataset, not an absolute cutoff. The starting "
        "value comes from [qc].iqr_multiplier."
    ),
)
metrics_df = qc.detect_outliers(metrics_df, iqm_columns=iqm_cols, iqr_multiplier=iqr_mult)

motion_df = None
if modality == "bold" and fmriprep_dir.is_dir():
    motion_df = qc.summarize_motion(fmriprep_dir, fd_threshold=settings["fd_threshold"])

runs = qc_report.build_run_rows(
    metrics_df,
    modality,
    iqm_cols,
    motion_df=motion_df,
    decisions=qc.load_decisions(decisions_dir),
    reports=qc_report.find_mriqc_reports(mriqc_dir, modality),
)


motion_status = qc_report.describe_motion_source(fmriprep_dir, runs, modality)


def _render(report_base):
    return qc_report.render_report(
        runs,
        modality,
        iqm_cols,
        fd_threshold=settings["fd_threshold"],
        iqr_multiplier=iqr_mult,
        project_name=config.get("project", {}).get("name", ""),
        fmriprep_variant=qc_report.fmriprep_input_variant(config),
        report_base=report_base,
        motion_status=motion_status,
    )


# One renderer, two deliveries — and they differ in exactly one thing, which is
# whether a relative link to MRIQC's report can resolve. The exported file sits
# beside mriqc/ and its links work; the embedded copy is a srcdoc iframe with no
# location of its own, so it names each report instead and the panel below opens
# it. Rendering twice costs little: the ~4.9 MB of Plotly is cached.
exported_html = _render("../mriqc")

# ---- Export ----
filename = qc_report.report_filename(modality)
col_dl, col_save = st.columns(2)
with col_dl:
    st.download_button(
        "Download report",
        data=exported_html,
        file_name=filename,
        mime="text/html",
        width="stretch",
    )
with col_save:
    if st.button("Save to derivatives", width="stretch"):
        saved = qc_report.write_report(exported_html, derivatives_dir, filename)
        st.success(f"Wrote `{saved}`")

# ---- The report ----
components.html(_render(None), height=1400, scrolling=True)

# ---- QC Decisions ----
st.subheader("QC Decisions")
st.markdown("Review runs and mark them as **keep**, **exclude**, or **investigate**.")

# Taken from the session rather than typed. Under OnDemand the session owner is
# already known, so asking would add a step and an honour-system field that can
# be left blank — which is how every decision written before now ended up
# anonymous and unattributable.
reviewer = getpass.getuser()
st.caption(f"Signing off as **{reviewer}**, recorded with each decision.")

counts = qc.decision_counts(qc.load_decisions(decisions_dir))
if counts["unattributed"]:
    st.warning(
        f"{counts['unattributed']} decision(s) were recorded before duckbrain "
        f"captured a reviewer, so no one can be identified as having made them. "
        f"They are shown as unattributed and do not count as signed off — "
        f"re-record any you still stand behind."
    )

for run in runs:
    run_key = run["run_key"]
    header = f"{run_key} — {run['decision'] or 'no decision'}"
    if run["is_outlier"]:
        header += "  ⚠️"
    with st.expander(header):
        # The reason is carried into whichever verdict is clicked rather than
        # saved on its own. Typing a note used to write a decision by itself,
        # defaulting to "investigate" — so a run the reviewer had only jotted
        # a reminder against acquired a verdict they never made, while the
        # header above still read "no decision" (TODO #17.10).
        st.text_input(
            "Reason",
            key=f"reason_{run_key}",
            value=run["reason"],
            help="Saved with the decision you pick — a note on its own is not a verdict.",
        )

        def _record(verdict, _key=run_key, _reason_key=f"reason_{run_key}"):
            qc.save_decision(
                decisions_dir,
                _key,
                verdict,
                reason=st.session_state.get(_reason_key, ""),
                reviewer=reviewer,
            )
            st.toast(f"{_key}: {verdict}", icon="✅")

        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Keep", key=f"keep_{run_key}", width="stretch"):
                _record("keep")
                st.rerun()
        with col2:
            if st.button("Exclude", key=f"excl_{run_key}", width="stretch"):
                _record("exclude")
                st.rerun()
        with col3:
            if st.button("Investigate", key=f"inv_{run_key}", width="stretch"):
                _record("investigate")
                st.rerun()

        for metric, value in run["iqms"].items():
            if value is None:
                continue
            flag = " (OUTLIER)" if metric in run["flagged_metrics"] else ""
            st.markdown(f"  - **{metric}**: {value:.4f}{flag}")

        # MRIQC's own report for this run, shown here rather than linked from the
        # table above: its figures are several MB each (a T1w report is 15 MB),
        # so they are fetched only for the run actually being looked at.
        if run["report"]:
            if st.toggle("Show MRIQC report", key=f"mriqc_{run_key}"):
                components_mod.embed_tool_report(mriqc_dir / run["report"])
        else:
            st.caption("No MRIQC report on disk for this run.")
