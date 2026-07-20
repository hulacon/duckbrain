# Changelog

Notable changes to duckbrain. Format follows [Keep a Changelog](https://keepachangelog.com);
versioning follows [Semantic Versioning](https://semver.org).

duckbrain is distributed by `git clone` and served from a working copy, so most
users sit *between* releases. Provenance therefore records a `git describe` of the
actual checkout (e.g. `v0.1.0-3-gabc1234`), not the release number below — see
`core.bids_metadata._duckbrain_generated_by`.

## [Unreleased]

### Added
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

### Changed
- **MRIQC default pinned to `24.0.2`** (was `24.1.0`) — `24.0.2` is both the
  validated version and MRIQC's latest stable release; there is no `24.1.0` Docker
  tag (that string is only the `24.0.2` container's internal self-report). The old
  default pointed the build command at a nonexistent tag.

### Fixed
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

[Unreleased]: https://github.com/hulacon/duckbrain/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/hulacon/duckbrain/releases/tag/v0.1.0
