# duckbrain — Implementation Plan

## Context

Build a general-purpose neuroimaging toolbox with a Streamlit GUI for LCNI/Talapas HPC users at UO. The tool generalizes the mmmdata pipeline (DICOM ingestion → BIDS conversion → NORDIC → fMRIPrep → QC) so any scanner user can go from raw DICOMs to QC'd preprocessed data without writing pipeline scripts themselves.

---

## Project Structure

```
duckbrain/
├── pyproject.toml                  # Package definition (pip-installable)
├── config/
│   ├── base.toml                   # Shipped defaults (SLURM partitions, container versions, etc.)
│   └── local.toml                  # User overrides (gitignored) — paths, email, project-specific
├── src/
│   └── duckbrain/
│       ├── __init__.py
│       ├── config.py               # TOML loader (adapted from mmmdata core/config.py)
│       ├── core/
│       │   ├── __init__.py
│       │   ├── ingestion.py        # LCNI DICOM export → sourcedata organization
│       │   ├── dicom_inspect.py    # Scan DICOM dirs for series descriptions, fieldmaps
│       │   ├── dcm2bids_config.py  # Auto-generate dcm2bids JSON config from DICOM inspection
│       │   ├── conversion.py       # Orchestrate dcm2bids (Singularity) runs
│       │   ├── nordic.py           # NORDIC MATLAB wrapper + BIDS input tree builder
│       │   ├── fmriprep.py         # fMRIPrep orchestration (adapted from mmmdata run_fmriprep.py)
│       │   ├── mriqc.py            # MRIQC orchestration
│       │   └── qc.py               # QC metrics loading + decision tracking
│       ├── slurm/
│       │   ├── __init__.py
│       │   ├── templates.py        # Jinja2 sbatch template rendering
│       │   ├── submit.py           # sbatch submission + dependency chaining
│       │   └── monitor.py          # squeue/sacct job status queries
│       └── gui/
│           ├── app.py              # Main Streamlit entrypoint (multipage)
│           ├── pages/
│           │   ├── 1_Project_Setup.py
│           │   ├── 2_Data_Ingestion.py
│           │   ├── 3_BIDS_Conversion.py
│           │   ├── 4_Preprocessing.py
│           │   ├── 5_QC_Dashboard.py
│           │   └── 6_Job_Monitor.py
│           └── components.py       # Shared Streamlit widgets (job card, progress bar, etc.)
├── templates/
│   └── sbatch/
│       ├── dcm2bids.sbatch.j2
│       ├── mriqc.sbatch.j2
│       ├── nordic_denoise.sbatch.j2
│       ├── nordic_bids_input.sbatch.j2
│       ├── fmriprep.sbatch.j2
│       └── fmriprep_nordic.sbatch.j2
├── scripts/
│   ├── nordic_denoise.m            # MATLAB function (copied from mmmdata, made generic)
│   └── launch.sh                   # Helper: starts Streamlit on a compute node
├── .gitignore
└── tests/
    ├── test_config.py
    ├── test_ingestion.py
    └── test_dicom_inspect.py
```

---

## Configuration Schema (`config/base.toml`)

```toml
[project]
name = ""  # User fills in during setup

[paths]
bids_dir = ""              # Root BIDS dataset directory
sourcedata_dir = ""        # Where organized DICOMs live (usually <bids_dir>/sourcedata)
derivatives_dir = ""       # Usually <bids_dir>/derivatives
work_dir = ""              # Scratch for fMRIPrep etc. (outside BIDS tree)
containers_dir = ""        # Singularity .sif/.simg images
nordic_toolbox_dir = ""    # Path to NORDIC_Raw MATLAB toolbox
fs_license = ""            # FreeSurfer license file path

[dcm_source]
# LCNI DICOM export location
base_dir = "/projects/lcni/dcm"
group = ""                 # e.g., "hulacon"
project = ""               # e.g., "mmmdata"
# Derived: <base_dir>/<group>/<project>/ contains session folders

[containers]
dcm2bids_version = "3.2.0"
fmriprep_version = "24.1.1"
mriqc_version = "24.1.0"

[fmriprep]
output_spaces = ["MNI152NLin2009cAsym:res-2", "fsaverage6", "func"]
nprocs = 8
mem_gb = 32

[nordic]
magnitude_only = true
matlab_module = "matlab/R2024a"
excluded_nodes = ""        # Comma-separated SLURM node exclusions

[slurm]
partition = "medium"
partition_long = "computelong"
time = "12:00:00"
memory = "16G"
cpus = "4"
email = ""
mail_type = "END,FAIL"
account = ""               # SLURM account/allocation (optional)

[slurm.overrides]
# Per-step resource overrides
dcm2bids = { time = "03:00:00", memory = "8G", cpus = "1", partition = "compute" }
mriqc = { time = "06:00:00", memory = "16G", cpus = "4", partition = "compute" }
nordic = { time = "02:00:00", memory = "32G", cpus = "4", partition = "compute" }
fmriprep = { time = "48:00:00", memory = "48G", cpus = "8", partition = "computelong" }
```

---

## Core Modules

### `config.py` — Configuration Loader
Adapted from `mmmdata/src/python/core/config.py`. Same `base.toml` + `local.toml` deep-merge pattern.
- Env var: `DUCKBRAIN_CONFIG_DIR`
- Auto-discovers config dir by walking up from package location
- Validates required paths exist on load

### `core/ingestion.py` — Data Ingestion from LCNI
Scans the LCNI DICOM export directory (`/projects/lcni/dcm/<group>/<project>/`) and helps users:
1. **Discover sessions**: List available session folders (e.g., `MMM_003_sess19_20250401_121707`)
2. **Parse naming**: Extract subject ID, session label, date from folder name
3. **Map to BIDS**: User provides a mapping (or the GUI helps build one) from scanner session names → BIDS `sub-XX/ses-YY`
4. **Organize**: Symlink or copy DICOM session into `sourcedata/sub-XX/ses-YY/dicom/`

Key function: `discover_sessions(dcm_source_dir) → list[SessionInfo]` where `SessionInfo` has `folder_name`, `parsed_subject`, `parsed_session`, `date`, `series_list`.

### `core/dicom_inspect.py` — DICOM Series Inspection
Adapted from `mmmdata/src/python/dcm2bids_config/dicom_inspect.py`, generalized:
- `list_series(dicom_session_dir) → list[SeriesInfo]`: Enumerate all `Series_NN_description/` dirs
- `classify_series(series_list) → dict`: Classify each series as anat/func/fmap/sbref/physio/scout
- `detect_fieldmaps(series_list) → FieldmapDetection`: Find SE-EPI AP/PA pairs (reuse existing logic)
- Classification uses SeriesDescription patterns: T1w, T2w, bold, sbref, se_epi, physio, scout

### `core/dcm2bids_config.py` — Auto-Generate dcm2bids Config
Given classified series from `dicom_inspect`, generates a dcm2bids-compatible JSON config:
- Maps each functional series to `func/bold` with task label extracted from description
- Maps anatomicals to `anat/T1w` or `anat/T2w`
- Maps SBRef to `func/sbref`
- Maps fieldmaps to `fmap/epi` with `IntendedFor` patterns
- Returns a JSON dict that can be edited in the GUI before saving

### `core/conversion.py` — dcm2bids Orchestration
Runs dcm2bids via Singularity container:
- `run_dcm2bids(subject, session, config_json, bids_dir, ...) → CompletedProcess`
- Builds Singularity exec command with bind mounts
- Supports dry-run mode

### `core/nordic.py` — NORDIC Denoising
Adapted from mmmdata's `nordic_denoise.sbatch` + `nordic_denoise.m` + `nordic_build_bids_input.sh`:
- `get_bold_runs(bids_dir, subject, session) → list[Path]`: Discover BOLD NIfTIs
- `build_nordic_bids_input(bids_dir, subject, session, nordic_out_dir)`: Hardlink denoised BOLDs + copy sidecars (reimplements `nordic_build_bids_input.sh` in Python)
- MATLAB function `nordic_denoise.m` ships in `scripts/` (generic, no mmmdata references)

### `core/fmriprep.py` — fMRIPrep Orchestration
Adapted from `mmmdata/scripts/run_fmriprep.py`:
- `build_fmriprep_command(bids_dir, output_dir, ...) → list[str]`: Construct Singularity exec command
- Supports session filtering via `--bids-filter-file`
- Supports running on NORDIC input tree (`derivatives/nordic/bids_input/`)
- Auto-detects FreeSurfer license

### `core/mriqc.py` — MRIQC Orchestration
- `build_mriqc_command(bids_dir, output_dir, subject, session) → list[str]`

### `core/qc.py` — QC Metrics & Decisions
Adapted from `mmmdata/src/python/neuroimaging/qc_dashboard.py`:
- `load_mriqc_metrics(mriqc_dir, modality) → pd.DataFrame`
- `save_decision(decisions_dir, run_key, decision, reason, reviewer)`
- `load_decisions(decisions_dir) → dict`
- `detect_outliers(metrics_df, iqr_multiplier) → DataFrame with outlier flags`

### `slurm/templates.py` — Jinja2 SBATCH Rendering
- `render_sbatch(step_name, context_dict) → str`: Load `templates/sbatch/<step>.sbatch.j2`, render with config values
- Templates are parameterized versions of mmmdata's hardcoded sbatch scripts
- Context includes: paths, SLURM resources, subject/session, module loads

### `slurm/submit.py` — Job Submission
- `submit_job(sbatch_content, job_name) → job_id`: Write temp sbatch file, run `sbatch`, return job ID
- `submit_with_dependency(sbatch_content, job_name, after_job_id) → job_id`: Chain via `--dependency=afterok:ID`
- `export_script(sbatch_content, output_path)`: Save script to file for manual submission

### `slurm/monitor.py` — Job Status
- `list_jobs(user=None) → list[JobInfo]`: Parse `squeue` output
- `job_status(job_id) → JobInfo`: Query `sacct` for completed/failed jobs
- `job_log(job_id, log_dir) → str`: Read stdout/stderr log files

---

## Streamlit GUI Pages

### Page 1: Project Setup
- First-run wizard: set project name, BIDS dir, LCNI group/project, container paths
- Writes `config/local.toml`
- Validates paths exist, containers are present
- Shows "download container" commands if missing

### Page 2: Data Ingestion
- Lists available sessions from LCNI DICOM source
- Table with columns: folder name, parsed subject, parsed session, date, # series
- User maps scanner session names → BIDS sub/ses (editable text inputs)
- "Ingest" button creates symlinks/copies into sourcedata
- Shows ingestion status (which sessions are already in sourcedata)

### Page 3: BIDS Conversion
- Select subject + session from ingested sourcedata
- Auto-inspect DICOMs → show series table with auto-classification
- Auto-generate dcm2bids config JSON → show in editable code editor
- Fieldmap detection summary
- "Convert" button: submit dcm2bids SLURM job or run locally
- "Export Script" button: save sbatch for manual submission

### Page 4: Preprocessing
- Tabs: fMRIPrep | NORDIC | MRIQC
- Each tab: select subjects/sessions, configure options, submit or export
- fMRIPrep: output spaces, nprocs, mem, session filter, anat-only mode
- NORDIC: shows BOLD count, submits array job, then BIDS input build
- MRIQC: subject/session selection
- All tabs show estimated SLURM resources

### Page 5: QC Dashboard
- Embeds the HTML QC dashboard (adapted from mmmdata's `generate_dashboard`)
- Or: native Streamlit tables + Plotly charts for IQMs
- Decision buttons: keep / exclude / investigate per run
- Decision reason text input
- Outlier highlighting, motion summary

### Page 6: Job Monitor
- Live `squeue` table for current user
- Job history from `sacct`
- Log viewer (select job → show stdout/stderr)
- Auto-refresh toggle

---

## SBATCH Templates (Jinja2)

Example `templates/sbatch/fmriprep.sbatch.j2`:
```
#!/bin/bash
#SBATCH --job-name=fmriprep_{{ subject }}_{{ session }}
#SBATCH --partition={{ slurm.partition_long }}
#SBATCH --time={{ slurm.overrides.fmriprep.time }}
#SBATCH --cpus-per-task={{ slurm.overrides.fmriprep.cpus }}
#SBATCH --mem={{ slurm.overrides.fmriprep.memory }}
#SBATCH --output={{ paths.work_dir }}/logs/fmriprep_%j.out
{% if slurm.email %}#SBATCH --mail-user={{ slurm.email }}
#SBATCH --mail-type={{ slurm.mail_type }}{% endif %}
{% if slurm.account %}#SBATCH --account={{ slurm.account }}{% endif %}

export SINGULARITYENV_TEMPLATEFLOW_HOME={{ paths.work_dir }}/templateflow

singularity run --cleanenv \
  -B {{ paths.bids_dir }}:{{ paths.bids_dir }}:ro \
  -B {{ output_dir }}:{{ output_dir }} \
  -B {{ work_dir }}:{{ work_dir }} \
  -B {{ fs_license_dir }}:{{ fs_license_dir }}:ro \
  {{ container_path }} \
  {{ paths.bids_dir }} {{ output_dir }} participant \
  --participant-label {{ subject_id }} \
  {% if session %}--bids-filter-file {{ filter_file }}{% endif %} \
  --output-spaces {{ output_spaces | join(' ') }} \
  --fs-license-file {{ paths.fs_license }} \
  --nprocs {{ fmriprep.nprocs }} \
  --mem-mb {{ fmriprep.mem_gb * 1024 }} \
  --skip-bids-validation --notrack
```

Each template follows this pattern — all hardcoded paths from mmmdata scripts become Jinja2 variables filled from config.

---

## Implementation Phases

### Phase 1: Foundation + Ingestion + Conversion (MVP)
**Goal**: User can go from LCNI DICOMs to a BIDS dataset via GUI.

Files to create:
1. `pyproject.toml` — package setup with dependencies (streamlit, jinja2, tomli/tomllib, pandas, nibabel, plotly)
2. `config/base.toml` — default config
3. `.gitignore`
4. `src/duckbrain/__init__.py`
5. `src/duckbrain/config.py` — TOML loader
6. `src/duckbrain/core/__init__.py`
7. `src/duckbrain/core/ingestion.py` — LCNI session discovery + BIDS mapping
8. `src/duckbrain/core/dicom_inspect.py` — series enumeration + classification
9. `src/duckbrain/core/dcm2bids_config.py` — auto-config generation
10. `src/duckbrain/core/conversion.py` — dcm2bids runner
11. `src/duckbrain/slurm/__init__.py`
12. `src/duckbrain/slurm/templates.py` — Jinja2 renderer
13. `src/duckbrain/slurm/submit.py` — job submission
14. `src/duckbrain/slurm/monitor.py` — squeue/sacct queries
15. `templates/sbatch/dcm2bids.sbatch.j2`
16. `src/duckbrain/gui/app.py` — Streamlit main
17. `src/duckbrain/gui/pages/1_Project_Setup.py`
18. `src/duckbrain/gui/pages/2_Data_Ingestion.py`
19. `src/duckbrain/gui/pages/3_BIDS_Conversion.py`
20. `src/duckbrain/gui/components.py`
21. `scripts/launch.sh`

### Phase 2: Preprocessing (fMRIPrep + NORDIC + MRIQC)
- `src/duckbrain/core/fmriprep.py`
- `src/duckbrain/core/nordic.py`
- `src/duckbrain/core/mriqc.py`
- `scripts/nordic_denoise.m`
- `templates/sbatch/fmriprep.sbatch.j2`
- `templates/sbatch/nordic_denoise.sbatch.j2`
- `templates/sbatch/nordic_bids_input.sbatch.j2`
- `templates/sbatch/fmriprep_nordic.sbatch.j2`
- `templates/sbatch/mriqc.sbatch.j2`
- `src/duckbrain/gui/pages/4_Preprocessing.py`

### Phase 3: QC Dashboard + Job Monitor
- `src/duckbrain/core/qc.py`
- `src/duckbrain/gui/pages/5_QC_Dashboard.py`
- `src/duckbrain/gui/pages/6_Job_Monitor.py`

---

## Key Reuse from mmmdata

| mmmdata file | duckbrain adaptation |
|---|---|
| `src/python/core/config.py` | `src/duckbrain/config.py` — rename env var, same logic |
| `src/python/dcm2bids_config/dicom_inspect.py` | `src/duckbrain/core/dicom_inspect.py` — generalize fieldmap detection, add series classification |
| `scripts/run_fmriprep.py` | `src/duckbrain/core/fmriprep.py` — extract `build_fmriprep_command()`, parameterize paths |
| `scripts/nordic_denoise.m` | `scripts/nordic_denoise.m` — remove mmmdata references |
| `scripts/nordic_build_bids_input.sh` | `src/duckbrain/core/nordic.py` — rewrite in Python |
| `src/python/neuroimaging/qc_dashboard.py` | `src/duckbrain/core/qc.py` + Streamlit native rendering |
| All `.sbatch` scripts | `templates/sbatch/*.sbatch.j2` — parameterize as Jinja2 |

---

## Verification

1. **Config**: Create `local.toml` pointing to a test BIDS dir, run `python -c "from duckbrain.config import load_config; print(load_config())"`
2. **Ingestion**: Point at real LCNI DICOM source, verify session discovery and series listing
3. **GUI**: `streamlit run src/duckbrain/gui/app.py` — verify all pages render, setup wizard works
4. **Conversion**: Test dcm2bids config auto-generation against a known DICOM session, verify JSON output matches expected BIDS mapping
5. **SLURM**: Verify rendered sbatch scripts look correct (compare to mmmdata originals), test `--export` mode before live submission
