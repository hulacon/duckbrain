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

## Current status (as of 2026-07-09)

- **Feature-complete across all 3 planned phases**, plus extras:
  `core/bids_metadata.py`, `core/dicom_sorter.py`, a full Open OnDemand app
  (`ondemand/`), and bulk BIDS conversion.
- **69 unit tests pass** (`python -m pytest tests/ -v`), including AppTest-level
  smoke/interaction tests for GUI pages.
- **Committed and pushed** — `main` in sync with `origin` (HEAD `cead6af`; this
  hash drifts, treat as "latest").
- **DICOM→BIDS validated end-to-end on real data.** Real dcm2bids conversion of
  DIVATTEN subjects produces BIDS whose imaging filename set is **identical** to
  the canonical heudiconv output at `/projects/hulacon/shared/divatten/bids_data`.
  Validated through the GUI (job 45178139 completed clean).
- **fMRIPrep command validated against mmmdata** (`code/mmmdata/scripts/
  run_fmriprep.py`) — every substantive flag matches. **Not yet run live** —
  that's the main remaining validation (see "Next steps").
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
  login node / GUI. Those go to the derived `log_dir` (`<project>/logs`); all
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

DICOM→BIDS is validated end-to-end (see status). Remaining, roughly in order:

1. **Run fMRIPrep live** on one DIVATTEN subject (single-session, anat+func) and
   monitor via the Jobs page. The command is validated against mmmdata and the
   container + FS license are in place; this is the last unrun core stage.
2. Continue GUI dogfooding in `divatten_gui_beta` (bulk convert the remaining
   subjects, then MRIQC now that a container is present) and fix rough edges.
3. Onboarding: QUICKSTART + README refresh + the OOD distribution story
   (TODO #2).
4. Longer-term: per-subject pipeline status matrix (TODO #6) and the
   naming/discovery robustness items (TODO #4).
