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
from duckbrain.core.dicom_inspect import (
    list_series,
    classify_series,
    detect_fieldmaps,
    is_reproin_name,
)

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

# ReproIn-named sequences carry their BIDS entities explicitly, so duckbrain uses
# those instead of inferring them. Worth saying out loud: it tells the user the
# mapping below is read from the protocol names rather than guessed.
_reproin_count = sum(1 for s in series_list if is_reproin_name(s.description))
if _reproin_count:
    st.info(
        f"**ReproIn naming detected** in {_reproin_count} of {len(series_list)} series. "
        "Datatype, task, run, acq and dir are read from the sequence names rather "
        "than inferred, so the mapping below should need little or no correction."
    )

# ---- Fieldmap Detection ----
# Each group gets a colour here and keeps it everywhere else on the page (the
# plan table, the grouped relation view). That shared colour is the whole point:
# which pair corrects which run is a *relation* spanning three surfaces, and one
# stable token per group is what lets the eye join them. See TODO #13.
from duckbrain.gui.components import fmap_badge, fmap_swatches, fmap_token

fieldmaps = detect_fieldmaps(series_list)
fmap_colors = fmap_swatches(fieldmaps.groups)

st.subheader("Fieldmap Detection")
if fieldmaps.strategy == "none":
    st.info(
        "No fieldmaps detected — every run will convert without distortion "
        "correction."
    )
else:
    st.caption(
        f"Detected by **{fieldmaps.strategy}**. These colours identify each pair "
        "everywhere else on this page."
    )
    for group_name, dirs in fieldmaps.groups.items():
        ap, pa = dirs.get("ap"), dirs.get("pa")
        detail = (
            f"AP = Series {ap if ap is not None else '—'} &nbsp;·&nbsp; "
            f"PA = Series {pa if pa is not None else '—'}"
        )
        if ap is not None and pa is not None:
            st.markdown(f"{fmap_badge(group_name, fmap_colors)} &nbsp; {detail}")
        else:
            st.markdown(
                f"{fmap_badge(group_name, fmap_colors)} &nbsp; {detail} &nbsp; "
                "⚠️ **incomplete** — a pair needs both directions, so this one "
                "can't correct anything and isn't offered below."
            )

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
    FmapRule,
    TaskRunEntry,
    fmap_rules_from_config,
    resolve_fmap_assignments,
    task_rules_from_config,
    task_rules_from_mapping,
)
from duckbrain.core.dicom_inspect import sanitize_task_label

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

    # A BIDS task entity must be alphanumeric. The config generator sanitizes
    # anyway (so no invalid filename ever ships), but surface it here so the
    # rewrite isn't silent — an edit like "resting_test" becomes "restingTest".
    fixups = {
        e.task: sanitize_task_label(e.task)
        for e in edited_mapping
        if e.task and e.task != sanitize_task_label(e.task)
    }
    if fixups:
        st.warning(
            "Some task labels aren't valid BIDS entities (must be alphanumeric — "
            "no `_`, space, or `-`). They'll be written as: "
            + ", ".join(f"`{k}` → `{v}`" for k, v in fixups.items())
        )

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

# ---- Fieldmap binding (which pair each run's B0FieldIdentifier points at) ----
# The automatic rule sends every task whose name doesn't match a group to the
# *first* complete pair — there is no temporal-proximity logic — so this is where
# a session with a re-shot fieldmap gets corrected. "none" opts a run out of
# distortion correction entirely.
project_fmap_rules = fmap_rules_from_config(config)
complete_groups = [g for g, d in fieldmaps.groups.items() if "ap" in d and "pa" in d]
session_fmap_rules = project_fmap_rules

# Every task, not just the ones with a binding: a project rule this session can't
# honor must be fixable *here*, and it wouldn't be if the row were missing.
bold_tasks = list(
    dict.fromkeys(sanitize_task_label(e.task) for e in edited_mapping if e.role == "bold")
)

if bold_tasks and (complete_groups or project_fmap_rules):
    st.subheader("Fieldmap Binding")
    if len(complete_groups) > 1:
        st.markdown(
            "This session has **more than one usable fieldmap pair**, so which "
            "pair corrects which run is a real choice — and unless a task's name "
            "matches a group's, it defaults to the first pair. Set it below."
        )
    elif complete_groups:
        st.markdown(
            "One usable fieldmap pair, so every run gets it. Set a run to "
            "**none** to leave it without distortion correction."
        )
    else:
        st.markdown(
            "**No usable fieldmap pair in this session.** A project binding that "
            "names a group can't be honored here — set those runs to **none** to "
            "convert them without distortion correction."
        )

    try:
        resolved = resolve_fmap_assignments(edited_mapping, fieldmaps, project_fmap_rules)
    except ValueError as exc:
        # A project rule naming a group this session lacks. Show it, then fall
        # back to the automatic binding so the page stays usable and the user can
        # correct the row rather than being locked out.
        st.error(f"{exc}")
        resolved = resolve_fmap_assignments(edited_mapping, fieldmaps, None)

    bound = {sanitize_task_label(r.task) for r in project_fmap_rules}
    binding_df = st.data_editor(
        pd.DataFrame(
            [
                {
                    "task": task,
                    # A task with nothing to bind to reads as "none" — which is
                    # exactly what gets written for it either way.
                    "fieldmap group": resolved.get(task, "none"),
                    "source": "project rule" if task in bound else "automatic",
                }
                for task in bold_tasks
            ]
        ),
        width="stretch",
        hide_index=True,
        disabled=["task", "source"],
        column_config={
            "fieldmap group": st.column_config.SelectboxColumn(
                "fieldmap group",
                options=[*complete_groups, "none"],
                required=True,
                help="Only pairs holding both AP and PA are offered — a half pair "
                "would give fMRIPrep a correction it cannot run. 'none' writes no "
                "B0FieldIdentifier, so the run is preprocessed uncorrected.",
            )
        },
        key="fmap_binding_editor",
    )
    # Said out loud because the plan below lists individual runs under each pair,
    # which could read as a per-run choice. It isn't: the binding is keyed on the
    # task label, so every run of a task gets the same pair. Settling that
    # granularity is TODO #13's blocker (it changes the [fmap_mapping] schema).
    st.caption(
        "Binding is per **task**, so every run of a task gets the same pair. A "
        "session where a pair was re-shot midway — later runs wanting the second "
        "pair — can't be expressed here yet; see TODO #13."
    )
    session_fmap_rules = [
        FmapRule(task=str(row["task"]), group=str(row["fieldmap group"]))
        for _, row in binding_df.iterrows()
    ]

    if st.button(
        "⭑ Save this binding as the project default",
        key="save_project_fmap_map",
        help="Writes these task → fieldmap group rows to the project config's "
        "[fmap_mapping]. Every other subject and any bulk convert then uses "
        "them instead of the automatic rule.",
    ):
        from duckbrain.config import resolve_project_dir, save_project_fmap_map

        project_dir = resolve_project_dir() or paths.get("bids_dir", "")
        if not project_dir:
            st.error("No project directory resolved — can't save the default.")
        else:
            save_project_fmap_map(project_dir, session_fmap_rules)
            st.success(
                f"Saved {len(session_fmap_rules)} fieldmap binding(s) as the "
                f"project default in `{project_dir}/code/duckbrain.toml`. A group "
                "named here must exist in every session — one that's missing it "
                "fails loudly rather than silently using a different pair. Use "
                "`none` for a task that shouldn't be distortion-corrected."
            )

# ---- Auto-generate dcm2bids config ----
try:
    auto_config = generate_config(
        series_list,
        fieldmaps,
        subject=subject,
        session=session,
        mapping=edited_mapping,
        fmap_rules=session_fmap_rules,
    )
except ValueError as exc:
    # An unsatisfiable fieldmap binding. Refuse to show a config rather than
    # generate one that quietly uses a different pair than the project asked for.
    st.error(f"Cannot generate a config: {exc}")
    st.stop()
auto_json = config_to_json(auto_config)

# ---- Advanced: hand-edit the JSON ----
# Behind an explicit opt-in, because the text area keeps its *own* widget state:
# left always-on, it silently stopped tracking the tables above the moment anyone
# typed in it, and nothing on the page said which of the two would be submitted.
# That is the silently-degrading behavior CLAUDE.md forbids, so the override is
# now stated, visible, and revertible.
with st.expander("⚙️ Advanced — edit the dcm2bids config JSON by hand"):
    override_json = st.checkbox(
        "Edit the JSON directly instead of using the tables above",
        value=False,
        key="dcm2bids_json_override",
        help="While this is off, the config is regenerated from the Task/Run "
        "Mapping and Fieldmap Binding tables on every change. Turn it on to "
        "hand-edit; the tables then stop driving the config until you turn it "
        "back off or revert.",
    )
    if override_json:
        st.warning(
            "**The tables above no longer drive the config.** Your edits below "
            "are what gets submitted."
        )
        edited_json = st.text_area(
            "dcm2bids config JSON", value=auto_json, height=400,
            key="dcm2bids_config_editor",
        )
        if edited_json.strip() != auto_json.strip():
            st.caption("✏️ Edited — this differs from what the tables would generate.")
            if st.button("↺ Revert to the generated config", key="revert_json"):
                st.session_state.pop("dcm2bids_config_editor", None)
                st.rerun()
    else:
        edited_json = auto_json
        st.caption(
            "Generated from the tables above. Read-only while the override is off."
        )
        st.code(auto_json, language="json")

# Validate JSON
try:
    parsed_config = json.loads(edited_json)
except json.JSONDecodeError as e:
    st.error(f"Invalid JSON: {e}")
    parsed_config = None

# ---- Conversion Plan: what this config will actually produce ----
# The page used to show only the *inputs* and ask the user to approve a
# transformation, leaving them to simulate generate_config() in their head. This
# renders the other half. It is derived from parsed_config — the same dict
# dcm2bids consumes — so it cannot drift from what actually runs, and it reflects
# a hand-edited override too. See docs/conversion-legibility.md (TODO #13).
if parsed_config is not None:
    from duckbrain.core.conversion_plan import plan_conversion, plan_warnings

    st.subheader("Conversion Plan")

    plan = plan_conversion(
        parsed_config, series_list, subject=subject, session=session
    )
    findings = plan_warnings(plan, fieldmaps)
    blocking = [w for w in findings if w.severity == "error"]
    suspect = [w for w in findings if w.severity == "warning"]
    notes = [w for w in findings if w.severity == "info"]

    # --- Preflight. Deliberately above the tables: this is the part that helps a
    # user who doesn't yet know what to scan for, which is most of them.
    for w in blocking:
        st.error(w.message)
    for w in suspect:
        st.warning(w.message)
    if not blocking and not suspect:
        st.success(
            f"{len(plan.files)} file(s) will be written, nothing collides, and "
            "every series is accounted for."
        )
    for w in notes:
        st.caption(f"ℹ️ {w.message}")

    # --- Per-series outcome. Every series appears, including the ones nothing
    # claims — a dropped series is invisible in a table built from the plan alone.
    planned_by_series = plan.by_series
    plan_rows = []
    for s in series_list:
        produced = planned_by_series.get(s.series_number, [])
        if not produced:
            plan_rows.append(
                {
                    "Series #": s.series_number,
                    "Description": s.description,
                    "Type": s.classification,
                    "becomes": "— not converted",
                    "fieldmap": "",
                }
            )
            continue
        for f in produced:
            if f.fmap_group is not None:
                token = fmap_token(f.fmap_group, fmap_colors)
            elif f.is_bold:
                token = fmap_token(None, fmap_colors)
            else:
                token = ""
            plan_rows.append(
                {
                    "Series #": s.series_number,
                    "Description": s.description,
                    "Type": f.datatype,
                    "becomes": f.filename,
                    "fieldmap": token,
                }
            )

    st.dataframe(
        pd.DataFrame(plan_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "becomes": st.column_config.TextColumn(
                "becomes",
                help="The BIDS file dcm2bids will write for this series.",
                width="large",
            ),
            "fieldmap": st.column_config.TextColumn(
                "fieldmap",
                help="The pair that will correct this run (bolds), or the pair "
                "this file belongs to (fieldmaps).",
            ),
        },
    )

    # --- The relation, read the other way round: pair → the runs it corrects.
    # A table can only show one direction of an edge; this is the direction the
    # user actually asks about, and it was previously nowhere on the page.
    if fieldmaps.groups:
        st.markdown("**Which pair corrects which run**")
        for group_name, dirs in fieldmaps.groups.items():
            bound = plan.bolds_for_group(group_name)
            ap, pa = dirs.get("ap"), dirs.get("pa")
            with st.container(border=True):
                st.markdown(
                    f"{fmap_badge(group_name, fmap_colors)} &nbsp; "
                    f"AP = Series {ap if ap is not None else '—'} &nbsp;·&nbsp; "
                    f"PA = Series {pa if pa is not None else '—'}"
                )
                if bound:
                    for f in bound:
                        st.markdown(f"&nbsp;&nbsp;↳ `{f.filename}`")
                elif ap is None or pa is None:
                    st.caption("Incomplete pair — corrects nothing.")
                else:
                    st.caption("No runs bound to this pair.")

        unbound = [f for f in plan.files if f.is_bold and f.fmap_group is None]
        if unbound:
            with st.container(border=True):
                st.markdown(f"{fmap_badge(None, fmap_colors)} &nbsp; no distortion correction")
                for f in unbound:
                    st.markdown(f"&nbsp;&nbsp;↳ `{f.filename}`")

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
