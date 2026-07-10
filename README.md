# duckbrain

A general-purpose neuroimaging toolbox with a Streamlit GUI for [LCNI](https://lcni.uoregon.edu/)/[Talapas](https://hpcf.uoregon.edu/) HPC users at the University of Oregon.

Use outside of this environment is NOT supported at this time.

**duckbrain** lets any scanner user go from raw DICOMs to QC'd, preprocessed data without writing pipeline scripts. It provides a web-based interface for every step of the pipeline and handles SLURM job submission, dependency chaining, and monitoring behind the scenes.

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
| **NORDIC** | [NIFTI_NORDIC](https://github.com/SteenMoworCortx/NORDIC_Raw) | Thermal noise removal via MATLAB, then builds a BIDS-compatible input tree (hardlinked, no disk duplication) for fMRIPrep |
| **MRIQC** | [MRIQC](https://mriqc.readthedocs.io/) | Image quality metrics for anatomical and functional data |
| **QC** | Built-in | IQR-based outlier detection, motion summaries, per-run keep/exclude/investigate decisions with audit history |

## Getting Started

### Prerequisites

- Python 3.10+
- Access to Talapas HPC
- Singularity container images for dcm2bids, fMRIPrep, and MRIQC

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
singularity build $CONTAINERS_DIR/mriqc-24.1.0.sif docker://nipreps/mriqc:24.1.0
```

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

## Project Structure

```
duckbrain/
├── config/
│   ├── base.toml                   # Shipped defaults (SLURM, containers, etc.)
│   └── local.toml                  # Your overrides (gitignored)
├── src/duckbrain/
│   ├── config.py                   # TOML config loader (base + local deep-merge)
│   ├── core/
│   │   ├── ingestion.py            # LCNI DICOM export → sourcedata
│   │   ├── dicom_inspect.py        # Series enumeration + classification
│   │   ├── dcm2bids_config.py      # Auto-generate dcm2bids JSON config
│   │   ├── conversion.py           # dcm2bids orchestration (Singularity)
│   │   ├── fmriprep.py             # fMRIPrep command builder
│   │   ├── nordic.py               # NORDIC MATLAB wrapper + BIDS input builder
│   │   ├── mriqc.py                # MRIQC orchestration
│   │   ├── qc.py                   # QC metrics, outlier detection, decisions
│   │   ├── surveyor.py             # Per-unit × stage completion matrix (+ Nipoppy bagel)
│   │   └── pipeline.py             # Stage controller (advance_one) + live SLURM-state fusion
│   ├── slurm/
│   │   ├── templates.py            # Jinja2 sbatch rendering
│   │   ├── submit.py               # Job submission + dependency chaining
│   │   └── monitor.py              # squeue/sacct job queries
│   └── gui/
│       ├── app.py                  # Streamlit main entrypoint
│       ├── components.py           # Shared widgets
│       └── pages/                  # 7 GUI pages (see below)
├── templates/sbatch/               # Jinja2 sbatch templates
├── scripts/
│   ├── launch.sh                   # Start Streamlit on a compute node
│   └── nordic_denoise.m            # MATLAB NORDIC function
└── tests/
```

## GUI Pages

| Page | Purpose |
|------|---------|
| **0. Project Status** | Pipeline cockpit. Per-`(subject, session)` × stage matrix (ingested → converted → nordic → fmriprep → mriqc) grading completion by **expected outputs** (a crashed run reads *partial*, not done) fused with **live SLURM state** (a running job reads *running*, never re-runnable). Launch the next step per unit — dependency-gated, with a guarded bulk run, opt-in auto-refresh, a durable submission log, and a Nipoppy bagel export. See `docs/pipeline-cockpit.md`. |
| **1. Project Setup** | First-run wizard — pick the project directory, set SLURM settings and shared container/license locations. Writes shared settings to `~/.config/duckbrain/config.toml` and project settings to `<project>/code/duckbrain.toml`. |
| **2. Data Ingestion** | Browse LCNI DICOM sessions, auto-assign BIDS subject/session labels by date, symlink or copy into sourcedata, generate participants.tsv. |
| **3. BIDS Conversion** | Auto-inspect DICOMs, review series classifications and fieldmap detection, edit dcm2bids config, submit or export a conversion job — or bulk-convert all unconverted sessions at once. |
| **4. Preprocessing** | Tabbed interface for fMRIPrep, NORDIC, and MRIQC — select subjects/sessions, configure options, submit SLURM jobs or export scripts. |
| **5. QC Dashboard** | MRIQC metrics table with IQR outlier highlighting, Plotly distribution plots, motion summary, per-run keep/exclude/investigate decisions. |
| **6. Job Monitor** | Live squeue table, sacct job history, log viewer with stdout/stderr. |

## Configuration

duckbrain uses a two-file TOML config system:

- **`config/base.toml`** — shipped defaults (committed to git)
- **`config/local.toml`** — your project-specific overrides (gitignored)

Values in `local.toml` are deep-merged over `base.toml`. The GUI's Project Setup page writes `local.toml` for you, or you can edit it directly:

```toml
[project]
name = "my_study"

[paths]
bids_dir = "/projects/mylab/my_study"
sourcedata_dir = "/projects/mylab/my_study/sourcedata"
derivatives_dir = "/projects/mylab/my_study/derivatives"
work_dir = "/gpfs/mylab/work/my_study"
containers_dir = "/gpfs/mylab/containers"
fs_license = "/home/me/license.txt"

[dcm_source]
group = "mylab"
project = "my_study"

[slurm]
email = "me@uoregon.edu"
account = "mylab"
```

Per-step SLURM resource overrides are supported under `[slurm.overrides.<step>]` (e.g., `[slurm.overrides.fmriprep]`).

## Running Tests

```bash
python -m pytest tests/ -v
```

## Acknowledgments

duckbrain was developed at the [University of Oregon](https://www.uoregon.edu/) for the [Lewis Center for Neuroimaging](https://lcni.uoregon.edu/) community, generalizing the [mmmdata](https://github.com/hulacon/mmmdata) pipeline infrastructure.
