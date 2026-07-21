# Changelog

Notable changes to duckbrain. Format follows [Keep a Changelog](https://keepachangelog.com);
versioning follows [Semantic Versioning](https://semver.org).

duckbrain is distributed by `git clone` and served from a working copy, so most
users sit *between* releases. Provenance therefore records a `git describe` of the
actual checkout (e.g. `v0.1.0-3-gabc1234`), not the release number below — see
`core.bids_metadata._duckbrain_generated_by`.

## [Unreleased]

### Added
- **The Conversion page is one table.** DICOM Series, Task/Run Mapping and
  Fieldmap Binding were three surfaces that shared a grain but not a table, so
  reviewing a session meant joining series numbers, task labels and group names by
  eye. They are now a single editor — one row per DICOM series, carrying every
  decision that shapes the output (`task`, `run`, `fieldmap`) next to the output
  itself (`becomes`). Fieldmap rows show the pair they belong to, so the
  run↔pair relation reads off a single row in both directions, and a **Preflight**
  panel sits above it.
- **Fieldmap bindings now attach per run, not per task.** A pair re-shot *within*
  one task — where the runs before and after it want different pairs — could not
  be expressed at all before. `FmapRule` takes an optional `run`, and a run-level
  rule beats a task-wide one. Every existing `[fmap_mapping]` keeps working
  unchanged: a rule with no `run` still means every run of that task. Saved
  project defaults collapse back to task-wide rows wherever all runs agree, so the
  config stays readable.
- **Load a hand-edited config JSON back into the table** — explicit and one-shot,
  and it *reports what it couldn't represent* (criteria beyond `SeriesNumber`,
  arbitrary `sidecar_changes`, custom ids, dcm2bids options) rather than dropping
  them. Continuous two-way sync was considered and rejected for exactly that
  reason; see `docs/conversion-legibility.md`.
- **Conversion Plan — the Conversion page now shows what it will produce.** It
  asked you to approve a transformation while showing only its *inputs*; the
  predicted BIDS filenames existed nowhere except as `custom_entities` fragments
  inside the generated JSON, so reviewing a mapping meant simulating the config
  generator in your head. A new section renders the other half: every series with
  the file it becomes (or an explicit **— not converted**), a **preflight** panel
  above it, and a **which pair corrects which run** view that reads the fieldmap
  relation the direction users actually ask about. The plan is derived from the
  generated config dict — the same one dcm2bids consumes, hand edits included — so
  it cannot drift from what actually runs.
- **Preflight checks before submitting a conversion** (`core.conversion_plan`):
  two series resolving to the same filename (an **error** — dcm2bids writes one
  and loses the other), a fieldmap group holding one phase-encoding direction, a
  series no description claims (an unmatched anat used to vanish silently and
  looked exactly like a dropped scout), and bolds that will be written without
  distortion correction while a usable pair exists. Reports, never repairs.
- **Stable colour tokens per fieldmap pair**, shared across every surface on the
  page, so the series↔pair↔task join is done by eye instead of working memory.
  Colour is always paired with the group's label — never the only channel.

### Fixed
- **`use_sessions` accepts both a TOML boolean and the GUI's string form.** A
  project config carrying `use_sessions = true` (which is what a hand-written one
  naturally has) crashed the whole Project Setup page with
  `ValueError: 'True' is not in list`. Worse and quieter: `bool("false")` is
  `True` in Python, so a project that turned the `ses-` entity **off** through the
  Setup page got session entities anyway — the option did the opposite of what it
  said. Both forms now normalize in one place in core
  (`ingestion.normalize_use_sessions`), and a value duckbrain doesn't recognize
  falls back to `auto` *and says so* on the Setup page instead of being swallowed.
- **The dcm2bids JSON editor no longer silently overrides the tables.** The text
  area held its own widget state, so once you typed in it the Task/Run Mapping and
  Fieldmap Binding tables stopped reconciling and nothing said which of the two
  would be submitted — despite the page declaring the tables the source of truth.
  Hand-editing is now an explicit, labelled opt-in with a revert.

## [0.2.0] — 2026-07-21

### Added
- **Project-wide fieldmap binding** — when a session holds more than one usable
  fieldmap pair, a study can now declare which pair corrects which task instead of
  accepting the automatic choice (name match, else the first pair — there is no
  temporal-proximity logic). Set it on the Conversion page's new **Fieldmap
  Binding** table, which also *shows* the binding for the first time: previously
  the func↔fmap link was only visible as `B0FieldIdentifier` strings inside the
  generated JSON. Persisted to the project config's `[fmap_mapping]` and threaded
  through bulk/cockpit conversion, so both paths agree. A binding naming a group a
  session doesn't have — or one holding a single phase-encoding direction, or any
  group at all in a session that collected no fieldmaps — **fails loudly**:
  quietly using a different pair, or none, is precisely what an explicit binding
  exists to prevent. The reserved group `none` binds a task to no fieldmap, for a
  run that shouldn't be distortion-corrected. A session with no fieldmaps and no
  binding is unchanged: no `B0FieldIdentifier`, no `fmap/`, fMRIPrep runs without
  susceptibility distortion correction.
- **Project-wide task mapping** — define a study's `SeriesDescription → task`
  mapping once and inherit it across every subject (per-session edits still
  override). Persisted to the project config's `[task_mapping]`; threaded through
  bulk/cockpit conversion. Live-validated through the Conversion page.
- **Actionable cockpit board** — the Project Status matrix cells are now the launch
  controls. A cell opens a popover: **▶** to launch the next step (params inline),
  or, when a job exists, a reference to the **exact SLURM job** (id + live
  squeue/sacct detail + log tail) with **cancel** for in-flight jobs and **re-run**
  for failed ones. Column headers run a whole stage (guarded). Replaces the former
  separate launch selectbox + bulk expander + read-only table.
- **Job tracking folded into Project Status** — the standalone Job Monitor page is
  retired; its squeue/sacct tables and log viewer live on as the cockpit's "All
  SLURM jobs" panel (the catch-all for jobs not tied to a board cell), fed from the
  same single SLURM pull. `survey_live(config, with_jobs=True)` exposes the job
  index; `cancel_job()` wraps `scancel`; `find_job_logs()` resolves array-job logs.
- **ReproIn console naming is understood** —
  [ReproIn](https://github.com/ReproNim/reproin) sequence names
  (`func-bold_ses-pre_task-faces_acq-1mm_run-01_dir-AP`) are parsed for their BIDS
  entities, and those are trusted ahead of the inferring heuristics: the seqtype
  sets the datatype, `acq-` names the fieldmap group, `run-` pairs the fieldmaps,
  and `task-`/`run-` set the func entities. duckbrain still converts with
  dcm2bids — only the convention is adopted, not heudiconv or the ReproIn
  heuristic. Without this, a ReproIn-named study converted with **no fieldmaps at
  all and no warning**. The Conversion page says when it detects the convention.
- **Sources that group sessions by protocol** — a DICOM source whose session
  folders sit one level down (mmmdata's `anat_session/`, `func_session_*/`) is now
  discovered; previously it produced an empty list. Descent only happens when the
  top level yields nothing parseable, so the flat LCNI layout is untouched, and the
  grouping folder is recorded as a protocol label, not part of the subject/session
  identity.
- **A Notes column on the ingestion table** — flags rows needing attention rather
  than accepting a guess silently: an unreadable folder, a subject that still reads
  as a session label or a date, and two folders claiming the same `sub-XX/ses-YY`
  (real in mmmdata, and ingestion is idempotent, so the second would have quietly
  resolved to the first).

### Changed
- **MRIQC default pinned to `24.0.2`** (was `24.1.0`) — `24.0.2` is both the
  validated version and MRIQC's latest stable release; there is no `24.1.0` Docker
  tag (that string is only the `24.0.2` container's internal self-report). The old
  default pointed the build command at a nonexistent tag.

### Fixed
- **Reacquired *named* fieldmap pairs were silently discarded.** A session that
  reshoots `se_epi_ap_encoding` between task blocks kept only the last pair — one
  real session shoots three and converted one. Named groups now pair by
  acquisition order exactly as unnamed pairs already did, emitting
  `acq-encoding_run-1` / `_run-2` / … instead of one overwritten `dir-AP`.
- **A bold could be linked to a fieldmap group with only one direction.** An
  aborted opening AP sorts first, and the first group won by default — giving
  fMRIPrep a distortion correction it cannot run. Only groups holding both AP and
  PA are candidates now.
- **A session label with a qualifier was adopted as the subject.** `sess04CR` (a
  condition tag) and `sess3.2` (a rescan) did not match the session pattern, so
  `MMM03_sess04CR` parsed as subject `sess04CR`: the real subject disappeared and
  its sessions became phantom subjects.
- **Discovery crashed on a session folder the user cannot read.** Shared LCNI
  exports hold other people's sessions with no group read bit, and one
  `PermissionError` took down the whole ingestion page. Such folders are now kept
  and annotated — dropping them would hide a real subject.
- **"Reuse anat derivatives" silently did nothing** when there were no anat
  derivatives to reuse. fMRIPrep accepts `--derivatives` pointing at a tree with no
  anat for the subject, rebuilds the whole anat workflow, and logs nothing about
  the reuse it could not do — so the option looked honoured while costing the hours
  it claimed to save. Requesting reuse without a prior anat-only run now fails at
  submit time; the cockpit disables the option per unit and says why.
- **fMRIPrep bind-mounted its output directory twice** (read-write, then read-only
  for `--derivatives`) whenever anat reuse was on. Singularity resolved the overlap
  by dropping one of the two; had it dropped the read-write bind, fMRIPrep could
  not have written its outputs.
- **Invalid BIDS task labels** — a user-entered task label (mapping-table edit or
  hand-written rule) was emitted verbatim, so `resting_test` produced the invalid
  `task-resting_test`. Labels are now sanitized to alphanumeric at the entity
  boundary for every path, with a GUI warning showing the rewrite.
- **NORDIC logs unresolvable** — `job_log` globbed `*_<id>.out` and missed NORDIC's
  array logs (`nordic_%A_%a.out`); a new `find_job_logs` adds the array pattern.

## [0.1.0] — 2026-07-16

First tagged release. Feature-complete across the three planned phases, with all
core stages validated live on Talapas against real data.

### Added
- **DICOM → BIDS ingestion and conversion** — DICOM sorter, inspector/classifier,
  and `dcm2bids` conversion. Validated end-to-end: output filename set is
  identical to canonical heudiconv output for the DIVATTEN dataset.
- **Preprocessing stages** — fMRIPrep, MRIQC, and NORDIC denoising, submitted via
  SLURM with dependency chaining. All validated live.
- **NORDIC → fMRIPrep chaining** — a per-project `[nordic] use_nordic` flag routes
  fMRIPrep through denoised data. NORDIC stays a pure producer; fMRIPrep's input
  is the only variable.
- **Pipeline cockpit (Project Status)** — a `(subject, session) × stage` matrix
  fusing filesystem completion with live SLURM state, with dependency-gated
  per-unit launching and a durable submission log.
- **Provenance recording** — every run records tool, version, runtime, and code
  source; duckbrain-produced derivatives carry BIDS `GeneratedBy`.
- **Consistency checker** — surfaces config-vs-provenance, container/toolbox/MATLAB
  drift, mixed provenance, staleness, and presence mismatches in the cockpit.
- **Open OnDemand app** — launches the GUI as a Batch Connect interactive app.
- **Streamlit GUI** — project setup, ingestion, conversion, preprocessing, QC, and
  job monitoring.

### Fixed
Notable bugs caught by live validation rather than unit tests:
- **MRIQC OOM** — the sbatch `--mem` and MRIQC `--mem-gb` came from one value, so
  MRIQC's soft target had no cgroup headroom. Decoupled (`--mem-gb` = alloc − 8G).
- **Surveyor false-green** — MRIQC graded complete on the anat T1w JSON alone, so
  func-crashed subjects read 🟢. Now requires func IQMs when the input has func.
- **NORDIC never ran** — three latent bugs: an m-file `DIROUT`/`fn_out` double
  path, a `{#` Jinja collision meaning the sbatch template had never rendered, and
  hardcoded `ses-` paths breaking sessionless data.
- **Provenance false positive** — drift compared a config-pinned container *tag*
  against a tool's *self-reported* version. Different namespaces: `mriqc-24.0.2.simg`
  reports `24.1.0.dev0+gd5b13cb5`. Now compares container identity.
- **Submission-log corruption** — appending a provenance row to a pre-provenance
  log made a ragged file `pd.read_csv` refuses, which would have taken down the
  log, Job Monitor, and every log-overlay check on the next launch. The header now
  migrates atomically before appending.

### Licensing
- Released under **GPL-3.0-or-later**. Supersedes an unbacked `license = "MIT"`
  claim in `pyproject.toml` (no `LICENSE` file had ever existed).

[Unreleased]: https://github.com/hulacon/duckbrain/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/hulacon/duckbrain/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hulacon/duckbrain/releases/tag/v0.1.0
