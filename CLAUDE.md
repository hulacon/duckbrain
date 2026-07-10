# CLAUDE.md — duckbrain

Context for Claude Code sessions working in this repo. Read this first.

## What this is

**duckbrain** is a general-purpose neuroimaging toolbox with a Streamlit GUI for
LCNI/Talapas HPC users at the University of Oregon. It takes scanner users from
raw DICOMs → BIDS → preprocessing (fMRIPrep / NORDIC / MRIQC) → QC without
writing pipeline scripts, handling SLURM submission, dependency chaining, and
monitoring behind the scenes. It generalizes the `mmmdata` pipeline (see
`PLAN.md` for the full design and the mmmdata → duckbrain reuse map).

## Canonical location

**This checkout — `~/code/duckbrain` (= `/gpfs/home/$USER/code/duckbrain`) — is
the canonical one.** A duplicate previously existed at
`/gpfs/projects/hulacon/bhutch/duckbrain`; it was a byte-identical clone and is
being removed. All local dev, the venv, and the OnDemand app point here.
Distribution to other users is via `git clone` from
`git@github.com:hulacon/duckbrain.git`, so this directory is just the personal
dev/working copy.

## Current status (as of 2026-07-10)

- **Feature-complete across all 3 planned phases**, plus extras:
  `core/bids_metadata.py`, `core/dicom_sorter.py`, a full Open OnDemand app
  (`ondemand/`), bulk BIDS conversion, and a **project surveyor + actionable
  pipeline cockpit** (below).
- **Pipeline cockpit (Project Status page, TODO #0).** The Project Status page
  fuses filesystem completion (`core/surveyor.py`, graded by expected-output
  globs) with live SLURM state (`core/pipeline.py` `survey_live`) and lets you
  **launch the next step per unit** — dependency-gated, no double-submit on a
  running job. Built in 4 phases: controller extraction (`advance_one` +
  `STAGE_SPECS`, which the stage pages now also call), live-state fusion,
  cockpit UI, and polish (guarded bulk run, opt-in 30s auto-refresh, durable
  submission log `code/logs/submissions.tsv`, deep-links). Stages tracked:
  `ingested, converted, nordic, fmriprep, mriqc`. Full design + resumable status
  tracker in `docs/pipeline-cockpit.md`.
- **130 unit tests pass** (`python -m pytest tests/ -v`), including AppTest-level
  smoke/interaction tests for GUI pages.
- **Committed and pushed** — `main` in sync with `origin` (HEAD drifts; latest
  ~`957e49b`, treat as "latest").
- **DICOM→BIDS validated end-to-end on real data.** Real dcm2bids conversion of
  DIVATTEN subjects produces BIDS whose imaging filename set is **identical** to
  the canonical heudiconv output at `/projects/hulacon/shared/divatten/bids_data`.
  Validated through the GUI (job 45178139 completed clean).
- **fMRIPrep now running live** (2026-07-10) — sub-04 and sub-015 in
  `divatten_gui_beta`, launched via the GUI, past the FreeSurfer stage; 9 MRIQC
  jobs also running in parallel (MRIQC depends only on `converted`, not fMRIPrep).
  Command was validated against mmmdata (`code/mmmdata/scripts/run_fmriprep.py`);
  this is the first live run. **NORDIC is wired into the surveyor/cockpit but
  parked — unconfigured/unvalidated** (needs `nordic_toolbox_dir` + MATLAB + a
  validation run; see TODO #5b).
- **Validation projects** (real data, on Talapas):
  - Source DICOMs: `/projects/lcni/dcm/hulacon/Hutchinson/divatten` (37 subj,
    single-session, read-only).
  - BIDS projects: `/projects/hulacon/bhutch/divatten` (sub-001 done) and
    `/projects/hulacon/bhutch/divatten_gui_beta` (GUI dogfooding).
- See `TODO.md` for the prioritized backlog and `memory/` (via MEMORY.md) for
  detailed findings from each validation session.

## Environment / setup

- Python **3.10+**. A virtualenv lives at `.venv/` (gitignored).
- Set up / repair it with:
  ```bash
  python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
  ```
- Dependencies: streamlit, jinja2, pandas, nibabel, plotly, pydicom (+ pytest for dev).

## Running it

- **Tests:** `python -m pytest tests/ -v`
- **GUI locally (SSH-tunnel workflow):** `bash scripts/launch.sh` — starts
  Streamlit on port 8501; the script prints the exact `ssh -L` tunnel command.
  Activates `.venv` automatically if present and sets `DUCKBRAIN_CONFIG_DIR`.
- **Config (project-dir-first, layered):** deep-merged in order —
  1. `config/base.toml` (shipped defaults; located via `DUCKBRAIN_CONFIG_DIR`)
  2. **user config** `~/.config/duckbrain/config.toml` (or `$DUCKBRAIN_USER_CONFIG`) —
     shared machine resources reused across projects (containers, FS license,
     NORDIC toolbox, container versions, SLURM email)
  3. `config/local.toml` — *legacy*, still merged if present (no longer used)
  4. **project config** `<project_dir>/code/duckbrain.toml` — project-specific
     (name, `dcm_source`, `use_sessions`, SLURM account/partition)

  The **project directory is the anchor**: `bids_dir`/`sourcedata_dir`/
  `derivatives_dir`/`code_dir`/`log_dir` are derived from it. Choose it via
  `load_config(project_dir=...)` or the `DUCKBRAIN_PROJECT_DIR` env var (the GUI
  Setup page and the OOD form's "Project directory" field both set it). See
  `src/duckbrain/config.py`: `load_config`, `save_user_config`,
  `save_project_config`, `scaffold_project`, `derive_paths`.

  **Scratch vs. shared-FS split (important):** `work_dir` defaults to `/tmp`
  (node-local scratch — correct for heavy fMRIPrep intermediates). But SLURM
  **logs, submitted sbatch scripts, and BIDS filter files must live on shared FS**,
  or a failed job's log is stranded on the compute node and unreadable from the
  login node / GUI. Those go to the derived `log_dir` (`<project>/code/logs`,
  kept under the BIDS-reserved `code/` so no `.bidsignore` entry is needed); all
  sbatch templates' `--output` and the Job Monitor's log viewer point there.

## Open OnDemand app (primary way to launch on Talapas)

The `ondemand/` directory is a complete OnDemand Batch Connect interactive app
(`manifest.yml`, `form.yml`, `submit.yml.erb`, `template/`).

**It is registered as a personal sandbox app via a symlink:**
```
~/ondemand/dev/duckbrain  ->  ~/code/duckbrain/ondemand
```
So it appears in the Talapas OnDemand dashboard under **Develop → My Sandbox
Apps** (Interactive Apps → Neuroimaging). Launch it there; once the SLURM
session starts, OnDemand exposes a "Connect to duckbrain" gateway link to the
Streamlit GUI.

Key behaviors to know when editing the app:
- The launch form's `duckbrain_dir` field **defaults to
  `/gpfs/home/$USER/code/duckbrain`** — i.e. this checkout. If the canonical
  location ever moves, update BOTH the symlink target and this form default in
  `ondemand/form.yml`.
- `ondemand/template/script.sh.erb` activates `${DUCKBRAIN_DIR}/.venv` if it
  exists, otherwise falls back to `module load python3` + `pip install -e` on the
  compute node (fragile — depends on module Python + network). **Keeping `.venv`
  present is what makes launches reliable.**
- Because the OnDemand app runs THIS checkout's code, changes made elsewhere only
  take effect here after commit/push/pull into `~/code/duckbrain`.

## Next steps (validation, in order)

DICOM→BIDS is validated; fMRIPrep + MRIQC are now running live (see status).
Remaining, roughly in order:

1. **Confirm the live fMRIPrep + MRIQC runs complete clean** (sub-04/sub-015
   fMRIPrep + the 9 MRIQC jobs in `divatten_gui_beta`); check outputs and that the
   cockpit flips them 🟢. First live run of both stages.
2. **Cockpit usability pass** (TODO #0) — functionally working but Ben finds it
   "a little clunky"; deferred until behavior is locked. Concrete gripe captured:
   gated stages vanish from the launch dropdown (per-cell action would fix it).
3. **NORDIC validation** (TODO #5b) — it's wired into the cockpit but parked:
   set `nordic_toolbox_dir` + MATLAB, do one live run, fix the sessionless
   `ses-` path bug, and decide on fMRIPrep chaining.
4. Onboarding: QUICKSTART + README refresh + the OOD distribution story (TODO #2).
5. Longer-term: naming/discovery robustness (TODO #4).
