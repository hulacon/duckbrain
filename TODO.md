# duckbrain — TODO

Prioritized backlog. Newest priorities at the top. See `PLAN.md` for the
original design and `CLAUDE.md` for current status.

## 0. Pipeline cockpit — actionable Project Status board — BUILT 2026-07-10 (phases 1–4)
The Project Status matrix is actionable: each `(subject, session) × stage` cell
shows filesystem status fused with live SLURM state (🔵 running / ⏳ queued /
🔴 failed), and a dependency-gated "Launch a step" strip runs the next stage per
unit via `core.pipeline.advance_one`. A running/queued job is never offered for
re-run (no double-submit); ingestion is read-only here by design (Ben agreed).
Built in four committed phases — controller extraction (`core/pipeline.py`),
live-state fusion (`survey_live`/`stage_runnable`), cockpit UI, and polish
(guarded bulk "run whole stage", opt-in 30s auto-refresh, durable submission log
`code/logs/submissions.tsv`, deep-links to full pages). 126 tests pass. Full plan
+ status tracker: **`docs/pipeline-cockpit.md`**.
Dogfooded 2026-07-10: **functionally working** end-to-end. Remaining:
- **Usability pass (deferred until functionality stable).** Ben's dogfood read:
  the interface is "a little clunky." Do this once behavior is locked; collect
  specific pain points before starting. Likely targets: the stacked
  selectbox → params → button launch flow (lots of vertical scanning); single
  launch vs. bulk vs. matrix reading as three separate blocks rather than one
  board; per-cell action being indirect (choose from a dropdown vs. acting on the
  cell you're looking at). Candidate directions: clickable/actionable matrix
  cells, per-cell popover for the run controls, tighter layout density.
  - **Concrete confusion caught 2026-07-10:** the "Ready to run" dropdown only
    lists *currently-runnable* (unit, stage) pairs, so a stage that's supported
    but momentarily gated disappears entirely — e.g. with MRIQC running on every
    subject, the dropdown showed only fMRIPrep and it read as "you can't run
    MRIQC from here." The matrix still shows 🔵 running for it, but the *launch*
    control hides it. A per-cell action (button on the cell you see, disabled +
    labelled "running"/"needs converted") would remove this ambiguity.

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

## 5b. NORDIC — wired into surveyor/cockpit 2026-07-10, still needs real validation
`nordic` is now a surveyor stage (STAGES column, live-state overlay, cockpit
launch + bulk) — completion = denoised BOLDs under
`derivatives/nordic/sub-XX[/ses-YY]/func/*_bold.nii.gz`. Code (`core/nordic.py`,
`scripts/nordic_denoise.m`, `templates/sbatch/nordic_denoise.sbatch.j2`, the
Preprocessing NORDIC tab) is all present but **never run/validated in duckbrain**.
Before NORDIC is real:
- **Configure it:** `nordic_toolbox_dir` (NORDIC_Raw MATLAB toolbox) is unset in
  user/project config; also needs MATLAB module on the compute node. Until set,
  clicking "run nordic" in the cockpit produces a failed job (caught/shown).
- **Validate:** one live run on a converted subject (mirror the fMRIPrep effort).
- **Fix sessionless path bug:** `nordic_output_dir` / `build_nordic_bids_input`
  hardcode `ses-{session}`, so sessionless data writes a malformed `ses-/func`
  dir. The surveyor tracker tolerates it (wildcards), but a real run wouldn't.
- **Decide chaining:** fMRIPrep currently depends only on `converted`, NOT on
  `nordic` — so it runs on raw BIDS, not NORDIC-denoised input. If NORDIC→fMRIPrep
  should chain, wire fmriprep's input to the nordic `bids_input` tree + add the
  dependency. Left independent (optional branch) for now.
- Optional: NORDIC column is always-on; for non-NORDIC projects it's a column of
  ⚪. Fine for LCNI/mmmdata (NORDIC-common), revisit if noisy elsewhere.

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
