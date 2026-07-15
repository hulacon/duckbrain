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

## 5b. NORDIC — producer + fMRIPrep chaining (Case 1) VALIDATED LIVE 2026-07-15
`nordic` is a surveyor stage (STAGES column, live-state overlay, cockpit
launch + bulk) — completion = denoised BOLDs under
`derivatives/nordic/sub-XX[/ses-YY]/func/*_bold.nii.gz`. The **producer is now
validated end-to-end** on real data: sub-04 in `divatten_gui_beta` (sessionless,
13 BOLD runs) denoised clean via the GUI/`advance_one` path (array job 45428802,
all tasks COMPLETED, ~2–3 min & ~5.8 GB peak each), every output dim matching its
raw input, and the surveyor flips the cell 🟢. Getting there fixed three latent
bugs (all in this commit):
- **m-file output path** — `scripts/nordic_denoise.m` set `ARG.DIROUT = out_dir`
  *and* `fn_out = fullfile(out_dir, fname)`; `NIFTI_NORDIC` concatenates
  `DIROUT + fn_out`, so it would have written `out_dir/out_dir/…`. Aligned to
  mmmdata's validated form (`ARG.DIROUT = [out_dir '/']`, `fn_out = basename`).
- **template render** — `nordic_denoise.sbatch.j2` used a bash array-length
  expansion whose `{#` collided with Jinja's comment-open, so the template never
  rendered. Replaced with a `wc -l` count. (Proof it had never been run.)
- **sessionless paths** — `nordic_output_dir` / `build_nordic_bids_input` (and
  the latter's default `bids_input` location) hardcoded `ses-{session}`; now
  derived from `sub_ses_relpath`, so sessionless data writes `sub-XX/func` not
  `ses-/func`.
- **Config (done):** `nordic_toolbox_dir =
  /gpfs/projects/hulacon/shared/mmmdata/code/NORDIC_Raw` in user config; MATLAB
  module default `matlab/R2024a` is the cluster default — no change needed.
- **Chaining — Case 1 BUILT + VALIDATED LIVE 2026-07-15.** fMRIPrep now reads the
  NORDIC-denoised input when a project sets `[nordic] use_nordic = true`. Principle
  held: **NORDIC stays a pure independent producer** and **fMRIPrep's input source
  is the only variable.** Implementation (`core/pipeline.py`, `core/nordic.py`):
  `effective_depends_on()` swings fMRIPrep's dependency `converted → nordic` when
  the toggle is on; `stage_runnable(row, stage, config)` gates the cockpit
  accordingly; `_build_fmriprep()` assembles the unit's `bids_format` tree and
  points fMRIPrep at `derivatives/nordic/bids_format` (raises if no denoised BOLDs
  yet). `build_nordic_bids_input()` builds a **self-contained** tree (folder
  renamed `bids_input → bids_format`): denoised BOLDs hardlinked, anat included
  (nifti hardlinked, sidecars copied), fmap + func sidecars copied, dataset root
  files copied once. Same `fmriprep.sbatch.j2` — no `fmriprep_nordic.sbatch.j2`
  needed. **Validated:** sub-008 in `divatten_gui_beta` — tree assembled (13
  hardlinked denoised BOLDs + anat + fmap + `dataset_description.json`), cockpit
  gated fMRIPrep on `nordic`, and the live run (job 45452962) indexed the tree and
  built the full 2426-node anat+func workflow ("fMRIPrep started!", no BIDS
  errors) — confirming fMRIPrep consumes the denoised input. 141 tests pass.
  **Coexistence caveat:** flipping `use_nordic` on makes the *whole* project
  NORDIC; sub-04/sub-015 keep their old non-NORDIC `derivatives/fmriprep` (mixed
  provenance — a dogfooding artifact, not a real project). Remaining tiers:
  2. **Case 2 — same-project comparison (opt-in, defer until actually needed).**
     Needs two fMRIPrep results per subject, which breaks one-cell-per-stage. Do
     NOT branch the pipeline; instead use **distinct derivative names**
     (`derivatives/fmriprep/` vs `derivatives/fmriprep-nordic/`) — parameterize
     the hardcoded derivative dir in `_fmriprep_status` (and the builder) so a
     variant shows up as an **additive extra column**, only when the project opts
     in. Matches BIDS-derivatives provenance norms. **Zero-code fallback to try
     first:** two project dirs over the same BIDS, one with `use_nordic` on.
  3. **Full named-pipeline DAG — PARKED.** Only if branch count grows (multiple
     denoisers / fMRIPrep configs routinely). Cases 1+2 don't need it; this is
     the complexity to avoid for now.
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

## 7. Pipeline extras — candidate stages & integrations (backlog)
A set of odds-and-ends a typical pipeline involves, several with unknown fMRIPrep
interactions / pipeline placement. Captured 2026-07-15 with the NORDIC-work lens
(producer vs consumer vs orthogonal; placement vs fMRIPrep's resampling; does
fMRIPrep already do it / fight it). Full annotated backlog — candidate tools, ties
to existing duckbrain/mmmdata work, and open questions per item — in
**`docs/pipeline-extras.md`**. Each is its own focused effort; none started.
1. **DTI/DWI preprocessing** — orthogonal modality branch (candidate: QSIPrep).
2. **De-identification for sharing** (decided) — image defacing **+** metadata/header
   PII scrubbing (DICOM headers *and* BIDS sidecars), "derive-then-torch" policy
   (age ok, name/DOB auto-removed). Candidate combined tool: `bidsonym`. Precomputed
   -mask fast-track (2b) is a *different* feature, deferred.
3. **Eye-movement reconstruction from BOLD** (decided: DeepMReye-style) — orthogonal
   branch fMRIPrep *fights* (brain extraction removes the eyes); opt-in "preserve
   eyes" path off raw/minimal data. Low demand, unique requirements.
4. **Physiological data as BOLD regressors** — downstream consumer (PhysIO/TAPAS
   → confounds); fMRIPrep ingests physio but doesn't compute RETROICOR.
5. **Version/provenance documentation & metadata** — cross-cutting; extend the
   pinned versions + submission log + bagel into per-derivative provenance.
6. **Scanning-notes/metadata integration** — input-shaping producer (exclude bad
   runs via bids-filter/scans.tsv); reuse mmmdata build_manifest/sessions.tsv.
7. **QC norms & best-practice dashboard** — consumer of fMRIPrep+MRIQC (mmmdata
   open item); layer norms on the existing surveyor/QC pages.
8. **ReproIn evaluation** — upstream naming convention (ties to #4); adopt
   internally vs. recommend to LCNI users.

## 8. Visual identity & branding (someday — polish, low priority)
duckbrain will eventually want a real visual identity, not just functional UI.
Gated behind functionality + onboarding (#2); capture now so it isn't forgotten.
- **Logo / wordmark** — lean into the "duck brain" concept; needs a mark that
  works small (favicon / browser tab) and as a header banner.
- **GUI theming** — a considered Streamlit theme (palette, accent, fonts) instead
  of defaults; consistent iconography across pages.
- **Favicon** for the GUI browser tab + the OnDemand app tile.
- **README banner / docs polish** — a header image and consistent styling once the
  QUICKSTART/README refresh (#2) happens.
- Design flourishes generally (empty-state art, page headers) — tasteful, not
  over-designed; do after the product behavior is locked.
