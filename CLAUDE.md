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

## Working convention: stay on `main`

**Work directly on `main` whenever possible** (Ben's preference, 2026-07-15).
This is a single-maintainer personal working copy, and the OnDemand GUI serves
whatever is checked out here — so feature branches add ceremony and a stale-code
risk (the GUI keeps running old code until you merge back). Commit small,
verified changes straight to `main`. Only branch when a change is genuinely
risky/experimental and you want an easy bail-out; merge back and delete the
branch promptly. After committing, **push to `origin`** so the GitHub distribution
copy doesn't fall behind.

## Current status (as of 2026-07-10)

- **Feature-complete across all 3 planned phases**, plus extras:
  `core/bids_metadata.py`, `core/dicom_sorter.py`, a full Open OnDemand app
  (`ondemand/`), bulk BIDS conversion, and a **project surveyor + actionable
  pipeline cockpit** (below).
- **Pipeline cockpit (Project Status page, TODO #0).** The Project Status page
  fuses filesystem completion (`core/surveyor.py`, graded by expected-output
  globs) with live SLURM state (`core/pipeline.py` `survey_live`) and lets you
  **launch the next step per unit** — dependency-gated, no double-submit on a
  running job. **As of 2026-07-17 it is ONE actionable board** (usability pass,
  phase 5): the matrix cells *are* the controls — `▶` popover to launch (params
  inline), and a running/queued/failed cell opens a popover referencing the exact
  SLURM job (id + live squeue/sacct detail + log tail) with **cancel** (in-flight)
  / **re-run** (failed); column headers run a whole stage (guarded). **The
  standalone Job Monitor page is retired** — its squeue/sacct tables + log viewer
  are folded in as the "All SLURM jobs" panel, fed from
  `survey_live(config, with_jobs=True)` (one pull). Helpers: `cancel_job()`
  (scancel), `find_job_logs()` (resolves NORDIC array logs). Stages tracked:
  `ingested, converted, nordic, fmriprep, mriqc`. Full design + resumable status
  tracker in `docs/pipeline-cockpit.md` (phase 5 row).
- **288 unit tests pass** (`python -m pytest tests/ -v`), including AppTest-level
  smoke/interaction tests for GUI pages (the cockpit board, task-mapping wiring).
- **Committed + pushed.** Don't trust a commit hash written here — they go stale
  within a session (this file has been wrong about it before). Run `git log
  --oneline -1` and `git status`. Releases are tags: `git tag` (currently `v0.1.0`).
- **Licensed GPL-3.0-or-later; released + tagged from `v0.1.0` (2026-07-16).**
  Semver, git tags, `CHANGELOG.md`. Note the copyleft trade-off Ben accepted
  knowingly: duckbrain code **cannot be upstreamed** into the Apache-2.0 nipreps
  tools or MIT nipoppy, so the mooted `surveyor.py` → mmmdata port (TODO #6) would
  need dual-licensing. duckbrain orchestrates external tools at arm's length, so
  no licence crosses in either direction — users obtain each tool themselves
  (NORDIC especially: non-redistributable, see TODO §5c). Open: confirm with
  UO/RACS that Ben can license it (employee-IP policy).
- **Provenance stamps `git describe` of the checkout, not `__version__`.** duckbrain
  is served from a working copy, so users sit *between* releases; `__version__`
  marks the release only. Never treat it as what ran.
- **DICOM→BIDS validated end-to-end on real data.** Real dcm2bids conversion of
  DIVATTEN subjects produces BIDS whose imaging filename set is **identical** to
  the canonical heudiconv output at `/projects/hulacon/shared/divatten/bids_data`.
  Validated through the GUI (job 45178139 completed clean).
- **fMRIPrep + MRIQC validated live** (fMRIPrep 2026-07-10; MRIQC 2026-07-15).
  fMRIPrep: sub-04/sub-015 in `divatten_gui_beta`, launched via the GUI, command
  validated against mmmdata (`code/mmmdata/scripts/run_fmriprep.py`). MRIQC: all 9
  `divatten_gui_beta` subjects completed clean via the GUI bulk run — but only
  after fixing two bugs (commit `b364e26`): (1) an **OOM** — the sbatch set
  `#SBATCH --mem` and MRIQC `--mem-gb` from the same value, so MRIQC's soft
  scheduler target had no cgroup headroom and the func synthstrip node was
  OOM-killed; fixed by decoupling (`--mem-gb` = alloc − 8G) and raising the mriqc
  allocation to 32G. (2) a **surveyor false-green** — `_mriqc_status` graded a
  unit complete on the anat T1w json alone, so func-crashed subjects read 🟢;
  fixed to require func IQMs when the input BIDS has func. **NORDIC validated live
  end-to-end** (2026-07-15) — producer *and* fMRIPrep chaining:
  - **Producer:** all `divatten_gui_beta` subjects denoised clean via the
    GUI/`advance_one` path (outputs dim-matched, surveyor 🟢). Getting there fixed
    three latent bugs (m-file `ARG.DIROUT`/`fn_out` double-path, a `{#` Jinja
    collision in the sbatch template that meant it had never rendered, the
    sessionless `ses-/func` path); `nordic_toolbox_dir` set in user config
    (`/gpfs/projects/hulacon/shared/mmmdata/code/NORDIC_Raw`).
  - **Chaining (`use_nordic` toggle, TODO #5b Case 1):** a project-config
    `[nordic] use_nordic` flag routes fMRIPrep through the denoised data — NORDIC
    stays a pure producer, fMRIPrep's input is the only variable. `_build_fmriprep`
    assembles a self-contained `derivatives/nordic/bids_format` tree (denoised
    BOLDs hardlinked + anat/fmap/sidecars + root files) and points fMRIPrep there;
    `effective_depends_on` swings fMRIPrep's dep `converted → nordic`. Validated
    on sub-008 (fMRIPrep indexed the tree, built the full anat+func workflow, no
    BIDS errors). Case 2 (same-project raw-vs-NORDIC compare via a distinct
    `fmriprep-nordic/` derivative) is still deferred.
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
  sbatch templates' `--output` and the cockpit's log viewers (per-cell + the
  "All SLURM jobs" panel) point there.

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

## Next steps (in order)

All core stages are validated live: DICOM→BIDS, fMRIPrep, MRIQC, and NORDIC
(producer + `use_nordic` fMRIPrep chaining, 2026-07-15). Remaining, roughly in order:

1. ~~**Provenance recording + consistency checker**~~ — **✅ CLOSED 2026-07-16**
   (live-validated on-cluster; see TODO.md). Provenance recorded per run; BIDS
   `GeneratedBy` on every duckbrain-produced dataset (incl. the ingested root's
   dcm2bids converter and per-file NORDIC sidecars); `check_consistency()` surfaces
   seven checks in the cockpit. **The rule to know:** provenance for derivatives
   duckbrain *produces* lives in the data (sidecars → dataset stamp); for
   tool-produced derivatives (fMRIPrep/MRIQC) the submission log is the only
   channel. Never compare a config-pinned container *tag* to a tool's
   *self-reported* version — different namespaces. Residual: the mixing check has
   never been driven by two *completed* real fMRIPrep runs (hours of compute, and
   it works by corrupting a derivative) — accepted, close it free when a project
   genuinely mixes variants.
2. ~~**Cockpit usability pass**~~ — **✅ DONE 2026-07-17 (TODO #0, phase 5).** The
   three stacked blocks are now one actionable board; the "gated stage vanishes
   from the dropdown" gripe is fixed (action lives on the cell). Job Monitor page
   folded in (per-cell job reference + "All SLURM jobs" panel); per-cell
   cancel/re-run + failed-cell log. Residual: a human eyeball for column-width/feel
   at ~37-subject scale (AppTest can't judge it).
3. **Onboarding (TODO #2)** — QUICKSTART + README written (2026-07-16, refreshed
   2026-07-17); **MRIQC default pinned to `24.0.2`** (the validated *and*
   latest-stable version — there is no `24.1.0` release tag). Still open: the
   new-user path (`UNVALIDATED` install/container-build/launch on a clean account)
   and the OOD distribution story.
4. **Naming/discovery robustness (TODO #4) — 3 of 4 items DONE, on `main`.**
   `G##_S##` sessions, phantom/test-folder filtering, and multiple-fieldmap-pair
   splitting are built + unit-tested. **Deferred to on-cluster:** mmmdata-style
   nested multi-session discovery (needs a real source-layout example to implement
   verifiably). Then config/mapping niceties (TODO #5).
5. Pipeline-extras backlog (TODO #7, `docs/pipeline-extras.md`): de-identification
   (highest-value), DTI/DWI, physio, scanning-notes, QC dashboard, ReproIn,
   DeepMReye. NORDIC Case 2 (same-project raw-vs-NORDIC compare) when needed.

**Start here next session:** `docs/handoff-cluster-session.md` — its §2 (discovery
fixes against a real LCNI export) and §3 (multiple-fieldmap-pair conversion
end-to-end) are the only items left in it, never reached, and both need real data.
They pair naturally with eyeballing the new dcm2bids `GeneratedBy` on an ingested
root. That doc also carries a caution worth heeding: its previous version asserted
findings that turned out to be **wrong** on inspection, so treat its claims as
hypotheses to verify, not facts.
