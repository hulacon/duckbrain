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

## Current status (as of 2026-07-08)

- **Feature-complete across all 3 planned phases.** Every file in `PLAN.md`'s
  structure exists, plus extras: `core/bids_metadata.py`, `core/dicom_sorter.py`,
  and a full Open OnDemand app (`ondemand/`).
- **20 unit tests pass** (`python -m pytest tests/ -v`). These are unit-level.
- **Committed and pushed** — `main` is in sync with `origin` (HEAD `c4b6310`).
- **Not yet validated end-to-end against real data.** There is no
  `config/local.toml` (only the shipped `config/base.toml`), so the pipeline has
  never been pointed at a real BIDS dir / LCNI DICOM source here. The remaining
  work is validation, not building — see "Next steps."

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
- **Config:** two-file TOML — `config/base.toml` (shipped defaults) deep-merged
  under `config/local.toml` (gitignored, user/project-specific). Loader honors
  the `DUCKBRAIN_CONFIG_DIR` env var. `local.toml` does not exist yet.

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

1. Create a `config/local.toml` for a real study; confirm `load_config()` and the
   Project Setup wizard work.
2. Launch the GUI (OnDemand sandbox app or `scripts/launch.sh`) and walk pages
   1→6 to catch render/runtime issues.
3. Dry-run one real LCNI DICOM session: ingestion → dcm2bids config generation,
   comparing output against a known-good mmmdata BIDS mapping.
4. Export (don't submit) one sbatch per step and diff against the mmmdata
   originals before any live SLURM submission.
