# duckbrain — Quickstart

Getting from zero to your first BIDS conversion on Talapas. This is the lean
path; the [README](README.md) has the fuller reference.

> **Status of this guide.** duckbrain has been dogfooded end-to-end by its
> maintainer on real data, but this *new-user* walkthrough has **not** been
> validated by someone setting the tool up from scratch. Steps that a fresh
> user would hit but that haven't been verified on a clean account are marked
> **`UNVALIDATED`** inline. Treat them as "this *should* work — confirm it
> does," not as guarantees. If a command or path differs from what you see,
> that difference is the bug — please report it.

---

## What you need before you start

1. **A Talapas account and a PIRG.** You submit and charge jobs against a PIRG
   (Principal Investigator Research Group) account. If you don't have one, that
   is an [RACS](https://hpcf.uoregon.edu/) / your-PI question, not a duckbrain
   one.
2. **Access to your DICOMs.** LCNI writes scanner exports under
   `/projects/lcni/dcm/<group>/<PI>/<study>`. You need read access to yours.
3. **Somewhere to put a BIDS project** — a directory you can write to, typically
   under your PIRG's project space (e.g. `/projects/<pirg>/$USER/<study>`).
4. **The external tools**, which duckbrain runs but does **not** ship — see
   [Acquire the containers and NORDIC](#2-acquire-the-containers-and-nordic).

duckbrain itself needs **Python 3.10+**.

---

## 1. Install duckbrain

```bash
git clone git@github.com:hulacon/duckbrain.git
cd duckbrain
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -q      # sanity check the install
```

The test suite runs entirely offline (no cluster, no containers) and should
pass on any machine with Python 3.10+.

Keeping the `.venv` present matters for launching on the cluster: the OnDemand
app and `scripts/launch.sh` both activate it if it exists, and fall back to a
fragile module-load path if it doesn't.

---

## 2. Acquire the containers and NORDIC

duckbrain **orchestrates external tools at arm's length and bundles none of
them.** You obtain each yourself, under its own licence.

### Singularity/Apptainer containers

Build these into one directory (your `containers_dir`). These pull refs are the
real, validated build sources:

```bash
CONTAINERS_DIR=/path/to/your/containers   # e.g. /projects/<pirg>/$USER/containers

singularity build $CONTAINERS_DIR/dcm2bids-3.2.0.sif  docker://unfmontreal/dcm2bids:3.2.0
singularity build $CONTAINERS_DIR/fmriprep-24.1.1.sif docker://nipreps/fmriprep:24.1.1
singularity build $CONTAINERS_DIR/mriqc-24.1.0.sif    docker://nipreps/mriqc:24.1.0
```

> **`UNVALIDATED` — the MRIQC version.** The shipped default in
> `config/base.toml` is `mriqc_version = "24.1.0"`, so the command above follows
> it. But the setup the maintainer actually validated (all test subjects clean)
> used **`24.0.2`** — pinned in their *user* config, which overrides the shipped
> default. The shipped `24.1.0` default is therefore **untested**. If you hit
> trouble with MRIQC, try `24.0.2` (build `mriqc-24.0.2.sif` from
> `docker://nipreps/mriqc:24.0.2` and set `mriqc_version = "24.0.2"`). Whether
> the shipped default *should* become `24.0.2` is an open question for the next
> on-cluster session (see `TODO.md` §2).
>
> On Talapas you may need `module load apptainer` (or `singularity`) and to
> build somewhere with room — images are multi-GB. `UNVALIDATED` for a new
> account: the exact module name and any build-node requirements aren't
> confirmed here.

duckbrain finds a container by **filename**, assembling `<tool>-<pin>.sif` (or
`.simg`) from the `[containers]` version pins in config. So the filenames above
must match your pins. It does not look inside the image to choose it.

You also need a **FreeSurfer license file** (`fs_license`) for fMRIPrep and
MRIQC — free from <https://surfer.nmr.mgh.harvard.edu/registration.html>. Save
the file somewhere readable and point config at it.

### NORDIC (only if you denoise)

**NORDIC is not redistributable and duckbrain ships none of it.** It is
© Regents of the University of Minnesota, covered by US patent 10,768,260, and
licensed for non-profit research and educational use only — it "may not be sold
or redistributed." **Every user must obtain their own copy from upstream:**

```bash
git clone https://github.com/SteenMoeller/NORDIC_Raw /path/to/your/NORDIC_Raw
```

Then set `nordic_toolbox_dir` to that path (see config below). NORDIC runs as a
MATLAB job, so you also need a MATLAB module available on the cluster (the
config default is `matlab/R2024a`). If you are not using NORDIC, skip this
entirely.

---

## 3. Configure

Config is **layered and project-directory-first** — later layers deep-merge over
earlier ones:

1. **`config/base.toml`** — shipped defaults (in the repo; don't edit).
2. **User config** — `~/.config/duckbrain/config.toml` (or
   `$DUCKBRAIN_USER_CONFIG`). Shared, machine-level resources you reuse across
   every project: `containers_dir`, `fs_license`, `nordic_toolbox_dir`,
   container version pins, SLURM email.
3. **Project config** — `<project_dir>/code/duckbrain.toml`. Everything specific
   to one study: its name, its DICOM source, `use_sessions`, SLURM
   account/partition.

The **project directory is the anchor**: `bids_dir`, `sourcedata_dir`,
`derivatives_dir`, `code_dir`, and `log_dir` are all derived from it. You pick
it via the GUI's Project Setup page, the OnDemand form's "Project directory"
field, or the `DUCKBRAIN_PROJECT_DIR` environment variable.

> `config/local.toml` still merges if present, but it is **legacy** and no
> longer the intended place for your settings — use the user + project split
> above.

**You do not have to hand-write these files.** The GUI's **Project Setup** page
writes both the user config and the project config for you, and validates that
the containers and license it points at actually exist. Editing the TOML by hand
is the fallback, not the happy path.

If you prefer to write them by hand, the shapes are:

```toml
# ~/.config/duckbrain/config.toml  — shared across your projects
[paths]
containers_dir = "/projects/<pirg>/$USER/containers"
fs_license = "/home/<you>/licenses/fs_license.txt"
nordic_toolbox_dir = "/path/to/your/NORDIC_Raw"   # only if using NORDIC

[slurm]
email = "you@uoregon.edu"
```

```toml
# <project_dir>/code/duckbrain.toml  — one study
[project]
name = "my_study"

[dcm_source]
group = "<pirg>"
project = "<study>"

[slurm]
account = "<pirg>"
```

> `UNVALIDATED` — these hand-written shapes are illustrative. The Setup page is
> the tested writer of these files; confirm the exact key set it emits before
> relying on a hand-edited config. See `src/duckbrain/config.py`.

---

## 4. Launch the GUI

> **`UNVALIDATED` — the whole launch story for a new user.** duckbrain's GUI is
> served two ways today, and **neither is yet a documented, RACS-blessed happy
> path** for someone other than the maintainer. This section lays out the
> options; it does not (yet) pick one. See
> [The distribution question](#the-distribution-question).

### Option A — `scripts/launch.sh` + SSH tunnel

Works from any checkout with a `.venv`. Start Streamlit on a compute node:

```bash
srun --account=<pirg> --partition=interactive --time=04:00:00 \
     --mem=4G --cpus-per-task=2 --pty bash scripts/launch.sh
```

The script prints the exact `ssh -L …` tunnel command for the node it landed
on. Run that from your laptop, then open <http://localhost:8501>.

> `UNVALIDATED`: the `srun` flags above (partition name, whether `--account` is
> required for `interactive`) are the shape the repo already documents but have
> not been re-checked against a current Talapas policy on a fresh account.

### Option B — Open OnDemand app

The `ondemand/` directory is a complete OnDemand Batch Connect app. **Today it
is registered as one user's personal sandbox** (a symlink from
`~/ondemand/dev/duckbrain` into that user's checkout), so it is not yet
something a new user can simply click. To use it now you would register your own
sandbox app pointing at your own checkout.

> `UNVALIDATED`: the personal-sandbox registration steps for a *new* user
> aren't written up here and haven't been walked through. The form defaults the
> install directory to `/gpfs/home/$USER/code/duckbrain` — i.e. it assumes you
> cloned there.

---

## 5. Your first project

Once the GUI is open, the intended flow is:

1. **Project Setup** — choose your project directory; set SLURM account and the
   shared container/license/NORDIC locations. This writes your user + project
   config.
2. **Data Ingestion** — browse your LCNI DICOM export, let duckbrain assign BIDS
   subject/session labels, and symlink (or copy) sessions into `sourcedata/`.
3. **BIDS Conversion** — review the auto-detected series classification and
   fieldmap pairing, then submit a dcm2bids job (or bulk-convert everything).
4. **Preprocessing** — run fMRIPrep, NORDIC, and/or MRIQC.
5. **QC Dashboard** — review MRIQC metrics and record keep/exclude decisions.
6. **Project Status** — the cockpit: a per-`(subject, session) × stage` matrix
   that grades completion from real outputs and fuses in live SLURM state, with
   a dependency-gated "launch the next step" control per unit.
7. **Job Monitor** — live `squeue`/`sacct` and a log viewer.

> `UNVALIDATED` — the new-user *feel* of this flow (where the friction points
> are, whether the ingestion mapping and conversion steps are self-explanatory)
> has not been assessed in a real browser session by a first-time user. That
> walkthrough is explicitly still open work (`TODO.md` §2).

---

## The distribution question

How a new user should launch duckbrain is **unresolved**, not a settled path.
There are three candidate answers, and picking one needs input from RACS and
real testing (it is not decided here):

- **Personal OnDemand sandbox** — each user registers the `ondemand/` app in
  their own OnDemand dashboard, pointing at their own checkout. Works today but
  is per-user setup.
- **`scripts/launch.sh` + SSH tunnel** — no OnDemand at all; works from any
  checkout, at the cost of managing an `srun` session and a tunnel by hand.
- **A shared, RACS-published OnDemand app** — the long-term answer: one blessed
  app all LCNI users launch without cloning or registering anything. This needs
  RACS involvement and does not exist yet.

Until this is resolved, expect to use Option A or your own Option B sandbox.
