# Running duckbrain off the cluster

duckbrain is built for Talapas, and using it anywhere else is not supported.
You can still **run the GUI on a laptop to review it**: read its screens,
follow its wording, try its controls, and report what confuses you. You don't
need a Talapas account or a scanner dataset for that. This page sets that up
with a public OpenNeuro dataset that already has MRIQC and fMRIPrep outputs.

Nothing here processes data. Every pipeline step goes through SLURM and
Apptainer containers, and neither exists on a laptop.

## What you can and can't review

| Page | Off the cluster |
|---|---|
| **Setup** | Works. It warns that the LCNI DICOM folder and the containers folder don't exist. On a laptop that's expected. |
| **Status** | Works. The completion grid reads the demo dataset: *converted* and *MRIQC* complete, *fMRIPrep* partial, because the demo leaves out fMRIPrep's preprocessed images. The SLURM job panel is always empty. |
| **Preprocessing** | The forms all work. **Export Scripts** writes the SLURM scripts duckbrain would submit, so you can read them. **Submit** fails for each subject with `No such file or directory: 'sbatch'`. That is expected. |
| **QC Overview**, **QC Inspect** | Work fully. The demo carries MRIQC measures for all 26 subjects, plus MRIQC and fMRIPrep reports and figures for subjects 01–03. Keep/exclude decisions save to `derivatives/duckbrain/` in the demo folder. |
| **Project** | Works, except BIDS validation, which runs inside duckbrain's dcm2bids container and so reports that it can't run. |
| **Ingestion**, **BIDS Conversion** | They open and then stop at their first step. Both start from LCNI's DICOM export, and there's no public stand-in for that. |
| **Guide** | Works. |

## 1. Install

You need Python 3.11 or newer and git. The commands below are for macOS and
Linux. On Windows, use WSL; this route hasn't been tested on Windows.

```bash
git clone https://github.com/hulacon/duckbrain.git
cd duckbrain
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]" awscli
```

Run `python3 --version` first. Many Macs ship an older Python; if yours is
older than 3.11, install a newer one from python.org or Homebrew and use that
interpreter for the `venv` step.

The test suite runs offline, and it's a quick check that the install worked:

```bash
.venv/bin/python -m pytest -q --no-cov
```

## 2. Get the demo dataset

The demo is OpenNeuro's [ds000102](https://openneuro.org/datasets/ds000102)
(a flanker task, 26 subjects, two runs each). It also uses that dataset's
published MRIQC and fMRIPrep outputs. The three commands below download about
400 MB to `~/duckbrain-demo/ds000102`. They need no AWS account, and you can
re-run them safely.

```bash
mkdir -p ~/duckbrain-demo && cd ~/duckbrain-demo
```

The raw BIDS data for subjects 01–03:

```bash
<duckbrain>/.venv/bin/aws s3 sync --no-sign-request s3://openneuro.org/ds000102 ds000102 --exclude "*/*" --exclude ".*" --include "sub-0[1-3]/*"
```

MRIQC: the measures for every subject, and the visual reports for 01–03:

```bash
<duckbrain>/.venv/bin/aws s3 sync --no-sign-request s3://openneuro-derivatives/mriqc/ds000102-mriqc ds000102/derivatives/mriqc --exclude "*" --include "*.json" --include "*.tsv" --include "sub-0[1-3]_*.html"
```

fMRIPrep: the confounds for every subject, and the reports and figures for 01–03:

```bash
<duckbrain>/.venv/bin/aws s3 sync --no-sign-request s3://openneuro-derivatives/fmriprep/ds000102-fmriprep ds000102/derivatives/fmriprep --exclude "*" --include "dataset_description.json" --include "*desc-confounds_timeseries.*" --include "sub-0[1-3].html" --include "sub-0[1-3]/figures/*"
```

`<duckbrain>` is the folder you cloned in step 1. For more subjects, widen
`sub-0[1-3]`. The full raw dataset is about 2 GB, and the fMRIPrep outputs are
about 50 GB, mostly preprocessed images that the GUI doesn't need.

## 3. Launch

From the duckbrain folder:

```bash
DUCKBRAIN_PROJECT_DIR=~/duckbrain-demo/ds000102 bash scripts/launch.sh
```

The script prints instructions for opening an SSH tunnel to Talapas. **Skip
those.** Open the `http://localhost:8501/?token=…` link it prints in your own
browser. Stop the server with Ctrl-C.

Without `DUCKBRAIN_PROJECT_DIR`, pick the project folder in **Setup**.
duckbrain remembers recent projects and your shared settings in
`~/.config/duckbrain/config.toml`.

## 4. Report what you find

**Report a problem**, at the top of every page, gathers a bug report into one
text file: the version, the last error, recent logs and your settings. It shows
you the text before you download it, and it sends nothing. Paste what's useful
into a [GitHub issue](https://github.com/hulacon/duckbrain/issues). In the
issue, say that you were running off the cluster, so nobody chases a missing
`sbatch`.

The most useful reports name a screen, what you expected, and what happened:
a label you misread, a step whose next step you couldn't find, a number with no
explanation of whether high or low is good. Accessibility problems count too,
such as keyboard traps, contrast, or zoom.
