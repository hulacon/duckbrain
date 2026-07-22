# Changelog

Notable changes to duckbrain. Format follows [Keep a Changelog](https://keepachangelog.com);
versioning follows [Semantic Versioning](https://semver.org).

duckbrain is distributed by `git clone` and served from a working copy, so most
users sit *between* releases. Provenance therefore records a `git describe` of the
actual checkout (e.g. `v0.1.0-3-gabc1234`), not the release number below — see
`core.bids_metadata._duckbrain_generated_by`.

## [Unreleased]

### Added
- **Declared study expectations, and the checks that read them** (`[expected]` in
  a project's `code/duckbrain.toml`). You can now state what a session of your
  study is *supposed* to contain — how many participants, how many T1w scans,
  how many fieldmap pairs, how many runs of each task — and duckbrain flags any
  session that falls short.

  This closes a gap that was invisible by construction. Every other expectation
  in duckbrain is worked out *from* the data it is judging: the subject list from
  what exists on disk, the expected runs from the runs that converted. So a run
  the scanner aborted, or a subject scanned but never ingested, shrinks the
  expectation to match and the status board reads complete. Validated on real
  data: with one task's BOLD removed, the status matrix still reported every
  subject **complete** while the new check caught it.

  Declare it from the Project Status page: pick a session you have reviewed and
  trust, and freeze what it contains as the study's rule. Genuine deviations —
  the subject whose last run was aborted — go under `[expected.exceptions]` with
  a reason, so they stop being reported without being forgotten.

  **Absent means off.** A project that declares nothing gets no expectation
  checks and no new warnings; removing the declaration turns them back off.
  Findings appear in the cockpit's existing warnings panel, which now
  distinguishes errors from warnings and notes. Nothing blocks: a shortfall is
  reported, never a gate on running a stage.
- **A consistency check for fieldmap intent (`fmap-intent`).** The inverted
  `B0FieldIdentifier`/`B0FieldSource` bug fixed on 2026-07-21 was invisible to
  every tool involved — the dataset validated, dcm2bids succeeded, and fMRIPrep
  exited 0 having quietly skipped susceptibility distortion correction. The
  cockpit now flags it directly, on the raw BIDS tree and on the NORDIC
  `bids_input` tree that fMRIPrep actually reads on the NORDIC path.

  It is deliberately wider than the bug it comes from. Inversion is only one way
  to end up with fieldmap metadata nothing can act on, so it also catches a
  `B0FieldSource` that no fieldmap declares as an identifier, a BOLD or SBRef
  with no source at all in a session that *has* fieldmaps, and a fieldmap no
  scan can reference. Each fails identically and silently. It reports and never
  repairs: whether to re-convert or swap the keys depends on what else those
  sidecars have been edited to say.
- **Continuous integration** — `ruff check`, `ruff format --check`, an import
  check and `pytest --cov` now run on every push and pull request, against
  Python 3.10 and 3.12. Nothing about duckbrain's behaviour changes; what changes
  is that a regression can no longer merge on the strength of one machine being
  green. Lint, formatter and coverage settings live in `pyproject.toml`, so a
  local run enforces exactly what CI does. The coverage floor starts at 60%
  (measured 61%) and only ever goes up.

  Two bugs fell out of the first lint run: a return annotation in
  `slurm/monitor.py` referenced `Path` with no such import (harmless until
  something introspected it), and `dcm2bids_config._fmap_description` looked up a
  series description it never used. Both fixed.
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

- **BIDS validation now runs automatically after every conversion.** dcm2bids has
  its own `--bids_validate`, and the validator already ships inside the dcm2bids
  container — so this costs nothing and needed no new install. On by default
  (`[conversion] bids_validate = true` to opt out); findings appear in the SLURM
  log the cockpit already shows. Worth knowing what it does *not* do: it checks
  structure and naming, not semantic intent, and would not have caught the
  fieldmap bug below.
- **New consistency check `fmap-pe-direction`** — flags a fieldmap whose `dir-AP`
  / `dir-PA` label disagrees with the `PhaseEncodingDirection` in its header. The
  header is authoritative, so the *label* is the suspect one, and a mismatch
  usually means the console protocol is misnamed — which every downstream
  assumption about that study would inherit.

### Fixed

*The block below answers an external code review of 2026-07-22
(`docs/code-review-260722.md`); see TODO `#18`.*

- **A stage is complete when every run is, not when one output matched a glob.**
  Conversion, NORDIC, fMRIPrep and MRIQC each graded complete off a single
  wildcard, so a unit with four BOLD runs where one succeeded read green at every
  stage. Not merely cosmetic: green unlocks the next stage and suppresses a real
  sacct failure, so one surviving run both hid three failures and let fMRIPrep
  start on a half-converted unit. Completion now compares the runs a unit has
  against the outputs they produced. **Expect cells that read green yesterday to
  turn yellow** — the run popover says "2 of 4 runs present" so a partial cell
  explains itself.
- **NORDIC's assembled input tree takes anatomy from every session of a subject.**
  It took anat only from the current session, contradicting fMRIPrep's own
  deliberately-unfiltered anat policy — so with `use_nordic`, a subject whose T1w
  was acquired once in `ses-01` gave fMRIPrep a `ses-02` tree containing no
  anatomical at all. ⚠️ **This can change anat handling for a NORDIC project
  already mid-study**, since fMRIPrep now sees every session's anat and makes its
  own selection, exactly as a non-NORDIC run always has.
- **That tree also converges now instead of only growing.** Every copy was
  skip-if-exists and nothing was ever removed, so an edited sidecar (fieldmap
  intent, task labels) or a deleted run stayed in the tree fMRIPrep reads
  indefinitely. Staged files are refreshed when their source changes and pruned
  when it is gone — scoped so concurrent per-unit jobs cannot delete each other's
  files. Concurrent builds no longer crash on a hardlink collision, and fall back
  to copying where hardlinks are unavailable (a different filesystem, some NFS).
- **The Setup page's save no longer deletes hand-written SLURM settings.**
  Saving replaced the whole `[slurm]` section while writing only four of its keys,
  so a hand-tuned `[slurm.overrides.fmriprep]` — live config — was deleted by a
  project rename, and later submissions silently used different resources. Each
  form now owns named fields; everything else in the section survives.
- **A failure that follows a success is visible again.** Seven days of job history
  reduced to "names that failed" and "names that completed", so once a job name
  had ever completed, no later failure could ever surface. The latest attempt
  decides.
- **A failed cell shows stderr.** It displayed stdout and fell back to stderr only
  when stdout was empty — and fMRIPrep always writes a stdout banner, so the
  traceback was unreachable from the cell reporting the failure. Log reads are
  also bounded now; the cockpit re-read complete multi-megabyte logs on every
  30-second refresh to show their last 4000 characters.
- **Per-session conversion records what it launched.** The Conversion page
  submitted its own job instead of going through the pipeline controller, so the
  most-used conversion path wrote no provenance row and left the cockpit with no
  job id — its cells read "No job id recorded" for every conversion started there.
- **Each submitted script is kept.** Retrying a stage overwrote the previous
  attempt's script, and the submission record held no parameters, so a failed
  attempt's exact command line was unrecoverable even with its log and its record
  still on disk. Scripts are archived per job id and referenced from the record.
- **Paths with spaces or shell metacharacters no longer break the sbatch
  scripts** — `/projects/lcni/dcm/hulacon/Hutchinson/New Program` is a real
  export. Paths are quoted as single shell arguments, and the NORDIC templates no
  longer interpolate them into Python and MATLAB string literals nested inside
  bash strings, where an apostrophe escaped the literal and a `$` was expanded
  before Python or MATLAB saw it.
- **The DICOM sorter no longer builds paths from unchecked scanner metadata.**
  `PatientName` / `StudyDescription` / `SeriesDescription` went into the
  destination unmodified: a name of `../../escape` wrote outside the project
  directory, and an absolute-looking `StudyDescription` part discarded the output
  root entirely. Components are sanitized and containment is enforced;
  overlapping input/output roots are refused, since with the default *move* the
  tool would rearrange the source tree into itself.
- **Re-ingesting a copied session is a no-op again**, not a collision with its own
  output — a regression in the previous commit's collision check, which compared
  resolved paths (right for a symlink, meaningless for a directory). Subject and
  session labels typed into the mapping table are validated before they become
  paths, and the whole selection is checked for duplicate destinations before
  anything is written.
- **The hand-edited config JSON now drives the whole Conversion page.** With the
  override on, the `task` / `run` / `fieldmap` columns kept showing table state
  and kept accepting edits, while a different config was submitted — three
  controls that silently did nothing, with the only notice inside a collapsed
  expander at the bottom of the page. Those columns are now read from the JSON and
  read-only while it drives, the state is announced above the table, and because
  everything downstream derives from the same frame, "Save as project default" now
  persists the bindings you reviewed rather than the table's.
- **A previously reviewed `dcm2bids_config.json` is surfaced.** That file — not
  the table — is what a bulk or cockpit convert consumes, but the page only ever
  wrote it, so a reviewed session reopened showing heuristic values and submitting
  overwrote the review without a word. It now reports the saved file, when it was
  saved, that submitting replaces it, and offers to load it into the table.
- **Pickers follow a project switch.** The directory picker committed its
  selection once per session, so after switching projects the DICOM-source and
  project-directory fields still showed the *previous* project's paths — under a
  green "✓ Selected:" — and saving wrote them into the new project.
- **"Shared resources" shows the shared value.** The section saves to the user
  config but was seeded from the fully merged config, so it displayed a project's
  own override under a heading that says "all your projects", and saving pushed
  that project's container versions onto every other project. A project that pins
  something different is now called out explicitly.
- **Ingestion no longer reports success for a session it didn't write.** Ingest is
  idempotent, and the page couldn't tell a real link from a no-op — so two scanner
  folders mapped to one subject/session both showed green while only the first was
  on disk. Re-ingesting the same folder is still a quiet no-op; a *different*
  folder colliding on an ingested subject/session is now refused and named.
- **The QC "Reason" field no longer records a verdict.** Typing a note on an
  undecided run saved `decision="investigate"` while the heading still read "no
  decision". The reason is carried into whichever verdict you click.
- **Saving on the Project Setup page no longer deletes the rest of the project
  config.** It wrote the file whole, so saving a SLURM account silently discarded
  the study's `[task_mapping]` and `[fmap_mapping]` — the task labels and fieldmap
  bindings defined on the Conversion page — along with `[fmriprep]`, `[nordic]`,
  `[conversion]` and any hand-written key, and reported success. Both project and
  user saves are now section-scoped read-modify-write, the contract
  `save_project_task_map` already had. The user config likewise keeps its
  `[recent]` projects.
- **The SLURM partition set on the Setup page now reaches jobs.** Every stage
  carried a shipped per-stage partition that outranked it, so the field was inert
  while looking functional (`account` and `email` did work). Stages now declare
  *which of two roles* they need — fMRIPrep is the long one — and both role names
  resolve from `[slurm] partition` / `partition_long`, which is also the first
  thing that has ever read `partition_long`. Per-stage `time`/`memory`/`cpus` are
  deliberately unchanged: those are tuned per stage and a project-wide default
  should not retune them.
  - ⚠️ **Check your project's partition.** duckbrain's default was `medium`, which
    is not a Talapas partition; projects created before this carry it, and it was
    harmless only while the field was inert. The Setup page now validates both
    partitions against `sinfo` and refuses to let a bad one pass unnoticed.
- **A BOLD is no longer bound to an incomplete fieldmap pair.** When a session had
  no complete pair, every incomplete one became a candidate, so an aborted lone AP
  got bound — contradicting the Fieldmap Detection panel, which says an incomplete
  pair isn't offered. The per-session page then hard-errored on a binding it had
  made itself, and the bulk path submitted it. No complete pair now means no
  binding, which is an honest "no distortion correction".
- **NORDIC no longer shows as unfinished work in projects that don't use it.**
  Without `use_nordic` nothing reads NORDIC output, but the stage graded *missing*
  for every unit: the rollup read `0/N`, the board offered a one-click "run all",
  and "every stage complete" could never be reached. It reads `—` / `n/a` now and
  is not launchable from the board. The Preprocessing page's NORDIC tab still runs
  it deliberately.
- **duckbrain no longer overwrites `PhaseEncodingDirection`.** It was forced to
  `j-`/`j` from the `_ap`/`_pa` token in the series name, clobbering the value
  dcm2niix derives from the DICOM header. That could only lose information — a
  no-op when they agree, and wrong when they don't — and a mis-signed phase
  encoding direction doesn't skip distortion correction, it applies it backwards,
  deforming the data while looking processed. The header is now left alone and
  disagreements are reported (see `fmap-pe-direction` above).
- **`.bidsignore` now covers `tmp_dcm2bids/`.** dcm2bids' working directory holds
  a log named `sub-XXX_ses-YY_*.log`, so the BIDS validator inferred a phantom
  subject with no valid data — three of the four errors on a real dataset. Only
  `work/`, which dcm2bids never writes to, was listed.
- 🔴 **Fieldmap intent was inverted, so susceptibility distortion correction never
  ran.** BIDS estimates the field from scans sharing a `B0FieldIdentifier` and
  applies it to scans sharing a `B0FieldSource`; duckbrain wrote the identifier on
  the **bold** and the source on the **fieldmap** — exactly backwards. Nothing
  errored: the dataset validates, dcm2bids is happy, and fMRIPrep simply reports
  *"Susceptibility distortion correction: None"* and preprocesses uncorrected.
  Confirmed on the real `divatten_gui_beta` runs, which have complete AP/PA pairs
  and no `--ignore` flags. **Datasets converted before this fix have unusable
  fieldmap metadata and their fMRIPrep derivatives ran without SDC** — re-convert
  (or patch the sidecars) and re-run fMRIPrep.
- **SBRefs are now bound to the same fieldmap pair as their BOLD.** They were
  written with no fieldmap association at all. This matters more than it looks:
  fMRIPrep uses an SBRef, when present, to build the BOLD reference that
  coregistration and SDC operate on, so an unassociated SBRef made that reference
  the one image in the chain nothing corrected.
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
