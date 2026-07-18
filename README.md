# duckbrain

A general-purpose neuroimaging toolbox with a Streamlit GUI for [LCNI](https://lcni.uoregon.edu/)/[Talapas](https://hpcf.uoregon.edu/) HPC users at the University of Oregon.

Use outside of this environment is NOT supported at this time.

**duckbrain** lets any scanner user go from raw DICOMs to QC'd, preprocessed data without writing pipeline scripts. It provides a web-based interface for every step of the pipeline and handles SLURM job submission, dependency chaining, and monitoring behind the scenes.

**New here?** Start with the [Quickstart](QUICKSTART.md) — access, containers,
config, launch, and your first project, in order.

## Pipeline Overview

```
LCNI DICOMs ──► Ingest ──► BIDS Conversion ──► Preprocessing ──► QC
                  │              │                    │              │
            sourcedata/     dcm2bids           fMRIPrep          MRIQC
            sub-XX/ses-YY   (Singularity)      NORDIC            outlier detection
                                               MRIQC             keep/exclude decisions
```

| Step | Tool | What it does |
|------|------|-------------|
| **Ingestion** | Built-in | Discovers sessions from LCNI DICOM export (`/projects/lcni/dcm/`), maps to BIDS subject/session, symlinks into sourcedata |
| **BIDS Conversion** | [dcm2bids](https://unfmontreal.github.io/Dcm2Bids/) | Auto-inspects DICOMs, classifies series (anat/func/fmap/sbref), generates dcm2bids config JSON, runs conversion via Singularity |
| **fMRIPrep** | [fMRIPrep](https://fmriprep.org/) | Anatomical + functional preprocessing with session isolation, split anat/func pipelines, BIDS filter support |
| **NORDIC** | [NIFTI_NORDIC](https://github.com/SteenMoeller/NORDIC_Raw) | Thermal noise removal via MATLAB, then builds a BIDS-compatible input tree (hardlinked, no disk duplication) for fMRIPrep |
| **MRIQC** | [MRIQC](https://mriqc.readthedocs.io/) | Image quality metrics for anatomical and functional data |
| **QC** | Built-in | IQR-based outlier detection, motion summaries, per-run keep/exclude/investigate decisions with audit history |

## Getting Started

### Prerequisites

- Python 3.10+
- Access to Talapas HPC (an account and a PIRG to charge jobs against)
- Singularity/Apptainer container images for dcm2bids, fMRIPrep, and MRIQC
- A FreeSurfer license file (for fMRIPrep and MRIQC)
- Your own copy of the NORDIC toolbox, if you denoise (not redistributable — see
  the [Quickstart](QUICKSTART.md#2-acquire-the-containers-and-nordic))

### Installation

```bash
# Clone the repo
git clone git@github.com:hulacon/duckbrain.git
cd duckbrain

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"
```

### Container Setup

Download the required Singularity images into your containers directory:

```bash
CONTAINERS_DIR=/path/to/your/containers

# dcm2bids
singularity build $CONTAINERS_DIR/dcm2bids-3.2.0.sif docker://unfmontreal/dcm2bids:3.2.0

# fMRIPrep
singularity build $CONTAINERS_DIR/fmriprep-24.1.1.sif docker://nipreps/fmriprep:24.1.1

# MRIQC
singularity build $CONTAINERS_DIR/mriqc-24.0.2.sif docker://nipreps/mriqc:24.0.2
```

> **Note on the MRIQC version.** `24.0.2` is both the version validated
> end-to-end and MRIQC's latest stable release (there is no `24.1.0` release
> tag — that string is only what the `24.0.2` container self-reports internally).

Users also need a **FreeSurfer license file** for fMRIPrep and MRIQC (free from
<https://surfer.nmr.mgh.harvard.edu/registration.html>); point config's
`fs_license` at it. **NORDIC is not a container** and is not redistributable —
each user clones their own copy from
[upstream](https://github.com/SteenMoeller/NORDIC_Raw); see the
[Quickstart](QUICKSTART.md#2-acquire-the-containers-and-nordic).

duckbrain selects a container by **filename** (`<tool>-<pin>.sif`/`.simg`, built
from the `[containers]` version pins), so the filenames above must match your
pins.

### Launch the GUI

```bash
# On a compute node (recommended)
srun --partition=interactive --time=04:00:00 --mem=4G --cpus-per-task=2 \
  --pty bash scripts/launch.sh

# Or directly (for quick testing on a login node)
bash scripts/launch.sh
```

Then set up an SSH tunnel and open `http://localhost:8501` in your browser:

```bash
ssh -L 8501:<compute-node>:8501 youruser@talapas-login.uoregon.edu
```

The GUI will walk you through project setup on first launch.

> **How to launch is not yet a settled, one-click story for new users.** The
> OnDemand app under `ondemand/` is currently registered as one user's *personal
> sandbox*, so a new user today needs either their own OnDemand sandbox or the
> `scripts/launch.sh` + SSH-tunnel path shown above. A shared, RACS-published
> OnDemand app is the intended long-term answer but does not exist yet. The
> [Quickstart](QUICKSTART.md#the-distribution-question) lays out the options.

## Project Structure

```
duckbrain/
├── config/
│   ├── base.toml                   # Shipped defaults (SLURM, containers, etc.)
│   └── local.toml                  # Legacy overrides (gitignored; user + project config preferred)
├── src/duckbrain/
│   ├── config.py                   # Layered TOML config loader (base → user → project)
│   ├── core/
│   │   ├── ingestion.py            # LCNI DICOM export → sourcedata
│   │   ├── dicom_inspect.py        # Series enumeration + classification
│   │   ├── dcm2bids_config.py      # Auto-generate dcm2bids JSON config
│   │   ├── conversion.py           # dcm2bids orchestration (Singularity)
│   │   ├── fmriprep.py             # fMRIPrep command builder
│   │   ├── nordic.py               # NORDIC MATLAB wrapper + BIDS input builder
│   │   ├── mriqc.py                # MRIQC orchestration
│   │   ├── qc.py                   # QC metrics, outlier detection, decisions
│   │   ├── surveyor.py             # Per-unit × stage completion matrix
│   │   └── pipeline.py             # Stage controller (advance_one) + live SLURM-state fusion
│   ├── slurm/
│   │   ├── templates.py            # Jinja2 sbatch rendering
│   │   ├── submit.py               # Job submission + dependency chaining
│   │   └── monitor.py              # squeue/sacct job queries
│   └── gui/
│       ├── app.py                  # Streamlit main entrypoint
│       ├── components.py           # Shared widgets
│       └── pages/                  # 6 GUI pages (see below)
├── templates/sbatch/               # Jinja2 sbatch templates
├── scripts/
│   ├── launch.sh                   # Start Streamlit on a compute node
│   └── nordic_denoise.m            # MATLAB NORDIC function
└── tests/
```

## GUI Pages

| Page | Purpose |
|------|---------|
| **0. Project Status** | Pipeline cockpit — one actionable board. A per-`(subject, session)` × stage grid (ingested → converted → nordic → fmriprep → mriqc) grading completion by **expected outputs** (a crashed run reads *partial*, not done) fused with **live SLURM state**. Each cell *is* the control: **▶** launches the next step (params inline, dependency-gated, no double-submit); a running/queued/failed cell opens a reference to the **exact SLURM job** — id, live squeue/sacct detail, and log tail — with **cancel** for in-flight jobs and **re-run** for failed ones. Column headers run a whole stage (guarded). Job tracking (the former Job Monitor) is folded in as an **All SLURM jobs** panel — active + recent history + arbitrary-job-id log lookup — the catch-all for jobs not tied to a cell. Plus a durable submission log and provenance/consistency checks. See `docs/pipeline-cockpit.md`. |
| **1. Project Setup** | First-run wizard — pick the project directory, set SLURM settings and shared container/license locations. Writes shared settings to `~/.config/duckbrain/config.toml` and project settings to `<project>/code/duckbrain.toml`. |
| **2. Data Ingestion** | Browse LCNI DICOM sessions, auto-assign BIDS subject/session labels by date, symlink or copy into sourcedata, generate participants.tsv. |
| **3. BIDS Conversion** | Auto-inspect DICOMs, review series classifications and fieldmap detection, edit dcm2bids config, submit or export a conversion job — or bulk-convert all unconverted sessions at once. |
| **4. Preprocessing** | Tabbed interface for fMRIPrep, NORDIC, and MRIQC — select subjects/sessions, configure options, submit SLURM jobs or export scripts. |
| **5. QC Dashboard** | MRIQC metrics table with IQR outlier highlighting, Plotly distribution plots, motion summary, per-run keep/exclude/investigate decisions. |

*(Live job tracking is no longer a separate page — squeue/sacct tables and the log
viewer are folded into Project Status as its "All SLURM jobs" panel, and jobs are
inspectable per cell.)*

## Configuration

duckbrain uses a **layered, project-directory-first** TOML config. Later layers
deep-merge over earlier ones:

1. **`config/base.toml`** — shipped defaults (committed to git; don't edit).
2. **User config** — `~/.config/duckbrain/config.toml` (or
   `$DUCKBRAIN_USER_CONFIG`). Shared machine-level resources reused across every
   project: `containers_dir`, `fs_license`, `nordic_toolbox_dir`, container
   version pins, SLURM email.
3. **`config/local.toml`** — *legacy*, still merged if present but no longer the
   intended place for settings.
4. **Project config** — `<project_dir>/code/duckbrain.toml`. Everything specific
   to one study: name, `dcm_source`, `use_sessions`, SLURM account/partition.

The **project directory is the anchor** — `bids_dir`, `sourcedata_dir`,
`derivatives_dir`, `code_dir`, and `log_dir` are derived from it. Choose it via
the GUI's Project Setup page, the OnDemand form's "Project directory" field, or
the `DUCKBRAIN_PROJECT_DIR` environment variable.

The GUI's **Project Setup** page writes both the user and project config for you
(and validates that the containers and license actually exist), so hand-editing
is the fallback. Example shapes:

```toml
# ~/.config/duckbrain/config.toml  — shared across your projects
[paths]
containers_dir = "/projects/mylab/containers"
fs_license = "/home/me/licenses/fs_license.txt"
nordic_toolbox_dir = "/home/me/NORDIC_Raw"   # only if using NORDIC

[slurm]
email = "me@uoregon.edu"
```

```toml
# <project_dir>/code/duckbrain.toml  — one study
[project]
name = "my_study"

[dcm_source]
group = "mylab"
project = "my_study"

[slurm]
account = "mylab"
```

Per-step SLURM resource overrides are supported under `[slurm.overrides.<step>]`
(e.g., `[slurm.overrides.fmriprep]`). See `src/duckbrain/config.py` for the
loader (`load_config`, `save_user_config`, `save_project_config`,
`scaffold_project`, `derive_paths`).

## Running Tests

```bash
python -m pytest tests/ -v
```

## License

duckbrain is free software, licensed under the **GNU General Public License v3.0
or later** — see [LICENSE](LICENSE). It comes with no warranty; you are free to
use, modify, and redistribute it under the terms of that licence.

duckbrain *orchestrates* external tools (fMRIPrep, MRIQC, dcm2bids, the NORDIC
MATLAB toolbox) by invoking them at arm's length — it neither links nor
redistributes them, so duckbrain's licence does not extend to them, nor theirs to
duckbrain. **You obtain and license each tool yourself**, under its own terms.
Note in particular that [NORDIC](https://github.com/SteenMoeller/NORDIC_Raw) is
copyright the Regents of the University of Minnesota, is patent-encumbered, is
licensed for non-profit research and educational use only, and **may not be
redistributed** — so each user must obtain their own copy from upstream.

## Versioning

duckbrain follows [Semantic Versioning](https://semver.org); releases are git tags
and are recorded in [CHANGELOG.md](CHANGELOG.md).

Because duckbrain is distributed by `git clone` and served straight from a working
copy, most users run code *between* releases. Provenance therefore records a `git
describe` of the actual checkout (e.g. `v0.1.0-3-gabc1234`) rather than the release
number, so every derivative names the commit that really produced it.

## Acknowledgments

duckbrain was developed at the [University of Oregon](https://www.uoregon.edu/) for the [Lewis Center for Neuroimaging](https://lcni.uoregon.edu/) community, generalizing the [mmmdata](https://github.com/hulacon/mmmdata) pipeline infrastructure.
