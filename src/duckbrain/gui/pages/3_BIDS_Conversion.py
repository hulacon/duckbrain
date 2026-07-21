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

# ---- The single conversion table ----
# One row per DICOM series, carrying every decision that shapes the output *and*
# the output itself. This replaces three separate tables (DICOM Series, Task/Run
# Mapping, Fieldmap Binding) that shared a grain but not a surface, so the user
# had to join series numbers, task labels and group names by eye. See TODO #13 /
# docs/conversion-legibility.md.
from duckbrain.core.dcm2bids_config import (
    build_task_run_mapping,
    collapse_fmap_rules,
    generate_config,
    config_to_json,
    FmapRule,
    TaskRunEntry,
    fmap_rules_from_config,
    resolve_fmap_assignments,
    task_rules_from_config,
    task_rules_from_mapping,
)
from duckbrain.core.conversion_plan import (
    plan_conversion,
    plan_warnings,
    read_config_into_table,
)
from duckbrain.core.dicom_inspect import sanitize_task_label

# The editor's pending edits live in session_state *before* it renders, which is
# what lets `becomes` be computed from this run's edits rather than lagging a
# rerun behind them. Keyed per subject/session so switching units can't apply one
# unit's edits to another's rows.
EDITOR_KEY = f"conversion_editor_{subject}_{session}"
IMPORT_KEY = f"conversion_import_{subject}_{session}"

st.subheader("Conversion Plan")
st.markdown(
    "One row per DICOM series. **This table is the source of truth** — edit "
    "`task`, `run` or `fieldmap` and everything downstream regenerates from it. "
    "`becomes` is the BIDS file that will actually be written."
)

template = st.text_input(
    "Naming template (optional)",
    value="",
    placeholder="e.g. {task}_r{run}",
    help="Glob-like seed for parsing: {task} and {run} placeholders. Leave blank "
    "to use the built-in heuristic. Editing the table always wins.",
)

project_rules = task_rules_from_config(config)
project_fmap_rules = fmap_rules_from_config(config)
if project_rules or project_fmap_rules:
    st.caption(
        f"↪ {len(project_rules)} project-wide task rule(s) and "
        f"{len(project_fmap_rules)} fieldmap binding(s) applied as defaults. "
        "Edit any row to override them for this session only."
    )

seed_mapping = build_task_run_mapping(
    series_list, template=template or None, rules=project_rules
)
seed_by_series = {e.series_number: e for e in seed_mapping}

# Which pair each fieldmap series belongs to, so an fmap row shows its own group
# and the relation reads off a single row in both directions.
fmap_group_by_series = {
    num: group
    for group, dirs in fieldmaps.groups.items()
    for num in dirs.values()
}

complete_groups = [g for g, d in fieldmaps.groups.items() if "ap" in d and "pa" in d]
_NO_FMAP_TOKEN = fmap_token(None, fmap_colors)
_group_token = {g: fmap_token(g, fmap_colors) for g in fieldmaps.groups}
_token_group = {tok: g for g, tok in _group_token.items()}

# The automatic binding, used only to seed the column.
try:
    seed_binding = resolve_fmap_assignments(seed_mapping, fieldmaps, project_fmap_rules)
except ValueError as exc:
    # A project rule this session can't honor. Show it, then seed from the
    # automatic binding so the page stays usable and the row can be corrected
    # here rather than locking the user out.
    st.error(f"{exc}")
    seed_binding = resolve_fmap_assignments(seed_mapping, fieldmaps, None)


def _seed_fieldmap(series):
    """Seed value for the fieldmap cell of one series row."""
    if series.series_number in fmap_group_by_series:
        return _group_token[fmap_group_by_series[series.series_number]]
    entry = seed_by_series.get(series.series_number)
    if entry is None or entry.role != "bold":
        return ""
    group = seed_binding.get((sanitize_task_label(entry.task), entry.run))
    if group is None or group == "none":
        return _NO_FMAP_TOKEN if fieldmaps.groups else ""
    return _group_token.get(group, "")


# ---- Consume a pending "load the JSON back into the table" request ----
# One-shot and explicit; see the Advanced expander below for why this is not
# continuous two-way sync.
_pending_import = st.session_state.pop("_pending_json_import", None)
if _pending_import is not None:
    try:
        _imported_config = json.loads(_pending_import)
    except json.JSONDecodeError as exc:
        st.error(f"Can't import — that JSON is invalid: {exc}")
    else:
        st.session_state[IMPORT_KEY] = read_config_into_table(
            _imported_config, series_list
        )
        # Stale row deltas would fight the imported values, and leaving the
        # override on would mean the import had no visible effect.
        st.session_state.pop(EDITOR_KEY, None)
        st.session_state.pop("dcm2bids_config_editor", None)
        st.session_state["dcm2bids_json_override"] = False

imported = st.session_state.get(IMPORT_KEY)
if imported is not None:
    st.info(
        "Values below were loaded from the hand-edited JSON. Edit any row to "
        "carry on from here."
    )
    if imported.unrepresentable:
        st.warning(
            "**The table can't represent everything that JSON contained.** These "
            "were left behind rather than dropped silently — turn the override "
            "back on if you need them:\n"
            + "\n".join(f"- {item}" for item in imported.unrepresentable)
        )

seed_rows = []
for s in series_list:
    entry = seed_by_series.get(s.series_number)
    task = entry.task if entry else ""
    run = entry.run if entry else None
    fieldmap = _seed_fieldmap(s)
    if imported is not None:
        task = imported.task_by_series.get(s.series_number, task)
        run = imported.run_by_series.get(s.series_number, run)
        group = imported.group_by_series.get(s.series_number)
        if group is not None:
            fieldmap = _group_token.get(group, fieldmap)
        elif s.series_number in imported.group_by_series and entry and entry.role == "bold":
            fieldmap = _NO_FMAP_TOKEN if fieldmaps.groups else ""
    seed_rows.append(
        {
            "Series #": s.series_number,
            "Description": s.description,
            "Type": s.classification,
            "# Files": s.file_count,
            "task": task,
            "run": run,
            "fieldmap": fieldmap,
            "becomes": "",
        }
    )
seed_df = pd.DataFrame(seed_rows)

def _apply_pending_edits(df, key):
    state = st.session_state.get(key)
    if not state:
        return df
    df = df.copy()
    for row_idx, changes in (state.get("edited_rows") or {}).items():
        idx = int(row_idx)
        if idx >= len(df):
            continue
        for col, value in changes.items():
            if col in df.columns:
                df.iat[idx, df.columns.get_loc(col)] = value
    return df


effective_df = _apply_pending_edits(seed_df, EDITOR_KEY)


def _row_run(value):
    return int(value) if pd.notna(value) else None


edited_mapping = [
    TaskRunEntry(
        series_number=int(row["Series #"]),
        description=row["Description"],
        role="bold" if row["Type"] == "func" else "sbref",
        task=str(row["task"]),
        run=_row_run(row["run"]),
    )
    for _, row in effective_df.iterrows()
    if row["Type"] in ("func", "sbref")
]

# Bindings come off the bold rows, one per run — the grain the table edits at.
# Non-func rows carry a fieldmap value too (an fmap row shows its own pair), but
# only a bold's is a *binding*, so the rest are read past rather than prevented:
# st.data_editor disables columns, not cells.
session_fmap_rules = []
for _, row in effective_df.iterrows():
    if row["Type"] != "func":
        continue
    token = str(row["fieldmap"] or "")
    if not token:
        continue
    group = "none" if token == _NO_FMAP_TOKEN else _token_group.get(token)
    if group is None:
        continue
    session_fmap_rules.append(
        FmapRule(task=str(row["task"]), group=group, run=_row_run(row["run"]))
    )

# A bold pointed at a half pair would hand fMRIPrep a correction it cannot run.
# generate_config raises on it; catching it here first gives the row and a fix
# rather than a stack of config-speak.
_half_bound = sorted(
    {r.group for r in session_fmap_rules if r.group not in complete_groups and r.group != "none"}
)
if _half_bound:
    st.error(
        "These runs are bound to a fieldmap pair that holds only one "
        f"phase-encoding direction: {', '.join(f'`{g}`' for g in _half_bound)}. "
        "A half pair can't correct anything — pick a complete pair or "
        f"`{_NO_FMAP_TOKEN}`."
    )
    st.stop()

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

# The hand-edited JSON override (in the Advanced expander below) is read out of
# widget state *before* that widget renders, so `becomes`, the preflight and the
# relation view all describe what will actually be submitted rather than what the
# table alone would produce. Same trick as the editor's pending edits above.
_override_on = bool(st.session_state.get("dcm2bids_json_override"))
_override_text = st.session_state.get("dcm2bids_config_editor") or ""
effective_config = auto_config
_override_error = None
if _override_on and _override_text.strip():
    try:
        effective_config = json.loads(_override_text)
    except json.JSONDecodeError as exc:
        _override_error = str(exc)

# `becomes` is filled from the plan, which reads the config dict dcm2bids will
# consume — so the column cannot promise a filename the tool won't write.
plan = plan_conversion(
    effective_config, series_list, subject=subject, session=session
)
_planned = plan.by_series
effective_df["becomes"] = [
    " + ".join(f.filename for f in _planned[num]) if num in _planned else "— not converted"
    for num in effective_df["Series #"]
]

# ---- Preflight ----
# Above the table on purpose: this is the part that helps a user who doesn't yet
# know what to scan for, which is most of them.
findings = plan_warnings(plan, fieldmaps)
_blocking = [w for w in findings if w.severity == "error"]
_suspect = [w for w in findings if w.severity == "warning"]
_notes = [w for w in findings if w.severity == "info"]

with st.container(border=True):
    st.markdown("**Preflight**")
    if _override_error:
        st.error(f"The hand-edited JSON is invalid, so the table below still "
                 f"reflects the generated config: {_override_error}")
    for w in _blocking:
        st.error(w.message)
    for w in _suspect:
        st.warning(w.message)
    if not _blocking and not _suspect and not _override_error:
        st.success(
            f"{len(plan.files)} file(s) will be written, nothing collides, and "
            "every series is accounted for."
        )
    for w in _notes:
        st.caption(f"ℹ️ {w.message}")

st.data_editor(
    effective_df,
    width="stretch",
    hide_index=True,
    disabled=["Series #", "Description", "Type", "# Files", "becomes"],
    column_config={
        "run": st.column_config.NumberColumn("run", min_value=1, step=1, format="%d"),
        "fieldmap": st.column_config.SelectboxColumn(
            "fieldmap",
            options=["", *_group_token.values(), _NO_FMAP_TOKEN],
            help="For a functional run: which pair corrects it. Bindings are "
            "per-run, so two runs of one task may differ — the case a fieldmap "
            "re-shot mid-task creates. Fieldmap rows show the pair they belong "
            "to. Everything else leaves this blank.",
        ),
        "becomes": st.column_config.TextColumn(
            "becomes",
            help="The BIDS file dcm2bids will write for this series.",
            width="large",
        ),
    },
    key=EDITOR_KEY,
)

# A BIDS task entity must be alphanumeric. The config generator sanitizes anyway
# (so no invalid filename ever ships), but surface it so the rewrite isn't silent.
fixups = {
    e.task: sanitize_task_label(e.task)
    for e in edited_mapping
    if e.task and e.task != sanitize_task_label(e.task)
}
if fixups:
    st.warning(
        "Some task labels aren't valid BIDS entities (must be alphanumeric — no "
        "`_`, space, or `-`). They'll be written as: "
        + ", ".join(f"`{k}` → `{v}`" for k, v in fixups.items())
    )

# ---- Promote this session's review to project-wide defaults ----
_save_task_col, _save_fmap_col = st.columns(2)

with _save_task_col:
    if st.button(
        "⭑ Save task/run mapping as project default",
        key="save_project_task_map",
        width="stretch",
        help="Writes the BOLD task rows to the project config's [task_mapping]. "
        "Other subjects then seed from these instead of the heuristic. "
        "Per-session edits still override.",
    ):
        from duckbrain.config import resolve_project_dir, save_project_task_map

        project_dir = resolve_project_dir() or paths.get("bids_dir", "")
        if not project_dir:
            st.error("No project directory resolved — can't save the default.")
        else:
            rules = task_rules_from_mapping(edited_mapping)
            save_project_task_map(project_dir, rules)
            st.success(
                f"Saved {len(rules)} task rule(s) to "
                f"`{project_dir}/code/duckbrain.toml`."
            )

with _save_fmap_col:
    if st.button(
        "⭑ Save fieldmap bindings as project default",
        key="save_project_fmap_map",
        width="stretch",
        disabled=not session_fmap_rules,
        help="Writes these bindings to the project config's [fmap_mapping]. A "
        "task whose runs all use the same pair is saved as one task-wide rule; "
        "only a task that genuinely differs run to run keeps per-run rows.",
    ):
        from duckbrain.config import resolve_project_dir, save_project_fmap_map

        project_dir = resolve_project_dir() or paths.get("bids_dir", "")
        if not project_dir:
            st.error("No project directory resolved — can't save the default.")
        else:
            collapsed = collapse_fmap_rules(session_fmap_rules)
            save_project_fmap_map(project_dir, collapsed)
            _per_run = sum(1 for r in collapsed if r.run is not None)
            st.success(
                f"Saved {len(collapsed)} binding(s) to "
                f"`{project_dir}/code/duckbrain.toml`"
                + (f", {_per_run} of them run-specific." if _per_run else ".")
                + " A group named here must exist in every session — one that's "
                "missing it fails loudly rather than silently using a different "
                "pair."
            )

# ---- The relation, read the other way round: pair -> the runs it corrects ----
# A table can only show one direction of an edge. This is the direction the user
# actually asks about, and it was previously nowhere on the page.
if fieldmaps.groups:
    with st.expander("🔗 Which pair corrects which run", expanded=len(complete_groups) > 1):
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
                st.markdown(
                    f"{fmap_badge(None, fmap_colors)} &nbsp; no distortion correction"
                )
                for f in unbound:
                    st.markdown(f"&nbsp;&nbsp;↳ `{f.filename}`")

# ---- Advanced: hand-edit the JSON ----
# Behind an explicit opt-in, because the text area keeps its *own* widget state:
# left always-on, it silently stopped tracking the table above the moment anyone
# typed in it, and nothing on the page said which of the two would be submitted.
# That is the silently-degrading behavior CLAUDE.md forbids, so the override is
# stated, visible, and revertible.
#
# Deliberately NOT two-way-synced with the table. Two editable representations of
# one thing means something has to lose when both change, and the table is *lossy*
# relative to the JSON — criteria beyond SeriesNumber, arbitrary sidecar_changes,
# custom ids and dcm2bids options have no column. A continuous round trip would
# drop them silently. The back-import below is the honest version: explicit,
# one-shot, and it reports what it could not represent.
with st.expander("⚙️ Advanced — edit the dcm2bids config JSON by hand"):
    override_json = st.checkbox(
        "Edit the JSON directly instead of using the table above",
        value=False,
        key="dcm2bids_json_override",
        help="While this is off, the config is regenerated from the Conversion "
        "Plan table on every change. Turn it on to hand-edit; the table then "
        "stops driving the config until you turn it back off or revert.",
    )
    if override_json:
        st.warning(
            "**The table above no longer drives the config.** Your edits below "
            "are what gets submitted."
        )
        edited_json = st.text_area(
            "dcm2bids config JSON", value=auto_json, height=400,
            key="dcm2bids_config_editor",
        )
        if edited_json.strip() != auto_json.strip():
            st.caption("✏️ Edited — this differs from what the table would generate.")
            c_revert, c_import = st.columns(2)
            with c_revert:
                if st.button("↺ Revert to the generated config", key="revert_json",
                             width="stretch"):
                    st.session_state.pop("dcm2bids_config_editor", None)
                    st.rerun()
            with c_import:
                if st.button("⇧ Load these edits back into the table",
                             key="import_json", width="stretch",
                             help="Reads task, run and fieldmap group back out of "
                             "the JSON and applies them to the table, then turns "
                             "the override off. Anything the table has no column "
                             "for is reported rather than dropped silently."):
                    st.session_state["_pending_json_import"] = edited_json
                    st.rerun()
    else:
        edited_json = auto_json
        st.caption(
            "Generated from the table above. Read-only while the override is off."
        )
        st.code(auto_json, language="json")

# The config that actually gets saved and submitted.
parsed_config = None if _override_error else effective_config

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
