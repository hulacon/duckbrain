# duckbrain — TODO

Prioritized backlog. Newest priorities at the top. See `PLAN.md` for the
original design and `CLAUDE.md` for current status.

## 1. Folder picker UX — reworked 2026-07-09, needs live look

`components.directory_picker` was rebuilt (still in-house: `streamlit-explorer`'s
`DirPicker` was evaluated — it IS lazy/HPC-safe, but v0.1.0 with 2 commits and
no `must_exist`/create-folder/default-path support; we adopted its good ideas
instead of the dependency). Still lazy, one `iterdir` per level. New model:

- Text field = **committed** selection; browsing lives in a collapsed
  "📂 Browse" expander whose body is an `st.fragment` — folder clicks rerun
  only the fragment, not the page (fixes sluggishness/scroll loss).
- Clickable **breadcrumb** jumps up any number of levels; single-column list of
  tertiary `📁` buttons in a scrollable container (lighter than the old grid).
- Explicit **"✓ Use this folder"** commits (via `on_click` callback +
  `st.rerun(scope="app")`); typing/pasting a path still commits directly.
- Requires Streamlit ≥ 1.48 (horizontal containers) — pyproject bumped.
- Covered by `tests/test_gui_components.py` (AppTest: navigate/commit/
  breadcrumb/filter/create/must_exist).

Remaining: eyeball it in a real browser session (AppTest can't judge feel);
file-mode for fs_license deliberately deferred — dirs-only is all we need for
now, fs_license stays a text field.

## 2. Onboarding for external users
- Dogfood the GUI new-user path fully, fix rough edges, then write a lean
  QUICKSTART (access, container acquisition, launch) + refresh the README.
- Add in-GUI guidance at friction points (Setup, ingestion mapping, conversion).
- Resolve the **launch/distribution story**: OOD app is currently bhutch's
  personal sandbox; a new user needs their own OOD sandbox or `launch.sh` +
  tunnel. A shared/RACS-published OOD app is the long-term answer.

## 3. fMRIPrep step — run live (last unrun core stage)
- Command validated against mmmdata's `run_fmriprep.py` (every substantive flag
  matches); container `fmriprep-24.1.1.simg` present; FS license now in user
  config (`/home/bhutch/licenses/fs_license.txt`). Blocker is just the live run:
  submit one DIVATTEN subject (single-session, anat+func) via SLURM and monitor
  via the Jobs page. Runs via SLURM, not inline.

## 4. Naming / discovery robustness (from the LCNI survey)
- `G##_S##` session style not recognized (parser needs "ses" prefix).
- Phantom/test-folder filtering (skip `test`/`phantom`/`demo`/QA, space-containing).
- Multiple fieldmap pairs per session collapse into one group ("Duplicate AP").
- mmmdata-style nested multi-session org (`func_session_*/anat_session/` under
  the source) breaks `discover_sessions`, which expects session folders directly
  under the source dir.

## 5. Config / mapping niceties
- Project-wide (vs per-subject/session) task/run mapping option: define once,
  inherit across subjects; per-subject override for exceptions.
- MRIQC now runnable — `mriqc-24.0.2.simg` present, user config aligned to
  `mriqc_version = "24.0.2"`. Still needs a live end-to-end run + QC-dashboard
  validation.

## 6. Per-subject pipeline status matrix (state awareness) — IMPLEMENTED 2026-07-10
**Done:** `core/surveyor.py` (`survey_project` → matrix, `summarize`) grades each
`(subject, session)` × stage (ingested/converted/fmriprep/mriqc) as
complete/partial/missing by **expected-output globs**, not folder presence —
borrowing Nipoppy's tracker idea but for duckbrain's flat layout, with the
sessionless-glob and layout-shim pain points designed out. Surfaced in the new
`gui/pages/0_Project_Status.py` dashboard (color matrix + rollup). Validated on
`divatten_gui_beta` (correctly flags mid-run fMRIPrep as partial). 19 new tests.
Remaining ideas: durable submission log (Job Monitor is still ephemeral); a
`nipoppy`-compatible `processing_status.tsv` export; port `surveyor.py` back to
mmmdata. Original rationale below.

duckbrain keeps **no state store** — every page re-derives "what exists" live
from the filesystem via BIDS naming (ingestion reads `sourcedata/sub-XX/dicom`,
preprocessing globs `bids_dir/sub-*`, QC reads `derivatives/{fmriprep,mriqc}`).
This is nicely tool-agnostic (external heudiconv/fMRIPrep output is picked up so
long as it lands in the standard paths), but it has real gaps:
- **Presence ≠ completion.** A crashed/half-finished fMRIPrep leaves a
  `derivatives/fmriprep/sub-XX` dir that looks identical to a complete one.
  Nothing checks a success/completion marker.
- **No done-vs-todo view.** Pages list all candidates; they don't tell you which
  subjects still need conversion / fMRIPrep / MRIQC. User has to eyeball it.
- **Job Monitor is ephemeral** — only what SLURM still remembers, no durable
  record of what duckbrain submitted.

Proposal: a dashboard status matrix (rows = subjects, cols = ingested /
converted / fMRIPrep / MRIQC) computed from **completion markers**, not mere
folder presence — e.g. dcm2bids success, fMRIPrep's `.html` report or
`dataset_description.json` in the derivative, MRIQC group TSV. Distinguish
complete / partial-or-failed / missing. This is the concrete form of the
long-mooted "pipeline DAG/dependency tracking" idea.
