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

## Completely new to Talapas, the command line, or GitHub?

That is expected, not a problem — but this guide will read better after an hour
with the basics. **[New to Talapas?](docs/new-to-talapas.md)** is written for
exactly this: the concepts (compute nodes, SLURM, PIRGs) in plain words, the
canonical tutorials to start from (the Unix shell, Talapas/RACS, Git/GitHub,
conda, SLURM, BIDS, fMRIPrep, MRIQC), and the list of setup decisions to check
with your PI before building anything. Read it first, then come back here. (The
GUI's **Guide** page points at the same document.)

> **⚠️ Several steps below encode a *lab* decision, not a personal one** —
> which PIRG to charge, where the shared conda environment and containers
> live, which tool versions and options your study uses, whether you denoise
> with NORDIC, where projects go. Your PI (or lab manager) owns those answers;
> the steps below flag them with **"ask your PI"** where they bite. When in
> doubt, ask before building — most of this is shareable, and the wrong move
> is each lab member building a private copy of everything.

## What you need before you start

1. **A Talapas account and a PIRG.** You submit and charge jobs against a PIRG
   (Principal Investigator Research Group) account. If you don't have one, that
   is an [RACS](https://hpcf.uoregon.edu/) / your-PI question, not a duckbrain
   one.
2. **Access to your DICOMs.** LCNI writes scanner exports under
   `/projects/lcni/dcm/<group>/<PI>/<study>`. You need read access to yours.
3. **Somewhere to put a BIDS project** — a directory you can write to, typically
   under your PIRG's project space (e.g. `/projects/<pirg>/$USER/<study>`).
   **Ask your PI** where projects go — labs usually have a convention, and a
   quota.
4. **The external tools**, which duckbrain runs but does **not** ship — see
   [Acquire the containers and NORDIC](#2-acquire-the-containers-and-nordic).
   Budget **~8.6 GB** of space and a chunk of time for the container builds; this
   is the slowest part of setting up, so start it early.
5. **A way to launch the GUI** — see [Launch the GUI](#4-launch-the-gui). The
   interactive-session route (Option A) needs nothing beyond your Talapas
   account and is what current beta testers use. If you intend to use the Open
   OnDemand app instead, **ask RACS about sandbox app development before you
   plan around it**: on current OnDemand an administrator has to enable it for
   your account.

duckbrain itself needs **Python 3.10+**. Getting the *code* needs nothing —
the repository is public.

---

## 1. Install duckbrain

```bash
git clone https://github.com/hulacon/duckbrain.git   # no GitHub account needed
cd duckbrain
./scripts/setup_env.sh                     # build the conda environment
module load miniconda3/20260319
conda activate "$(cat .conda-prefix)"
python -m pytest tests/ -q                 # sanity check the install
```

(The HTTPS URL clones anonymously. `git clone git@github.com:hulacon/duckbrain.git`
works too, if you already have an SSH key on GitHub.)

`scripts/setup_env.sh` is the supported path on Talapas, and it is a script
rather than a `conda env create` one-liner for a reason: if you ever ran FSL's
`fslinstaller`, your `~/.condarc` pins FSL's channel with markers conda cannot
override, and `conda env create` silently resolves against it. The script
works around that, verifies nothing resolved off conda-forge, and pins the
interpreter (Python 3.11) as well as the packages — with a `venv`, your Python
is whatever `python3` happened to be.

By default the environment is built at a **shared prefix**,
`/projects/hulacon/shared/envs/duckbrain` — one build serves the whole PIRG
instead of each user growing a ~1.2 G private copy under `~/.conda`, a model
other PIRGs can copy with
`./scripts/setup_env.sh --prefix /projects/<your-pirg>/shared/envs/duckbrain`.
Use `--personal` for `~/.conda/envs/duckbrain`.

> **Ask your PI before building:** that default prefix is one lab's. If you are
> not in `hulacon`, you cannot write (or likely even see) it — and the right
> question is not "what prefix do I use" but "does our lab already have this
> environment". One build serves the whole lab; if yours exists, skip the build
> and just record it: `echo /projects/<your-pirg>/shared/envs/duckbrain > .conda-prefix`.

The script records the environment's location in `.conda-prefix` (gitignored),
which is how the OnDemand app and `scripts/launch.sh` find it at launch. A
legacy `.venv` (`python -m venv .venv && pip install -e ".[dev]"`) still works
— both launchers fall back to it when no conda env is recorded.

The test suite runs entirely offline (no cluster, no containers) and should
pass on any machine with Python 3.10+.

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
singularity build $CONTAINERS_DIR/fmriprep-25.2.5.sif docker://nipreps/fmriprep:25.2.5
singularity build $CONTAINERS_DIR/mriqc-24.0.2.sif    docker://nipreps/mriqc:24.0.2
```

> **Note on the MRIQC version.** `24.0.2` is both the version the maintainer
> validated end-to-end (all test subjects clean) and MRIQC's latest stable
> release. There is **no `24.1.0` release** — `docker://nipreps/mriqc:24.1.0`
> does not exist as a pullable tag; `24.1.0.dev0` is only what the `24.0.2`
> container self-reports internally (an upstream packaging artifact).
>
> On Talapas you may need `module load apptainer` (or `singularity`). The three
> images total **~8.6 GB**, so build somewhere with room. `UNVALIDATED` for a new
> account: the exact module name and any build-node requirements aren't
> confirmed here.

> **Ask your PI whether the lab already has these before building.** Containers
> are the one expensive, *shareable* prerequisite — nothing about them is
> per-user, so a lab should build once, not once per person. And **put them
> where your lab can actually reach them**. A home directory is the wrong place:
> if `~` is mode `0700` (the default on Talapas) nobody can traverse into it, so
> `~/containers` is unreachable **even if that directory is itself
> world-readable**. Prefer group-readable PIRG space, e.g.
> `/projects/<pirg>/shared/containers`, and check that a colleague can actually
> `ls` it before assuming they can.

duckbrain finds a container by **filename**, assembling `<tool>-<pin>.sif` (or
`.simg`) from the `[containers]` version pins in config. So the filenames above
must match your pins. It does not look inside the image to choose it.

You also need a **FreeSurfer license file** (`fs_license`) for fMRIPrep and
MRIQC — free from <https://surfer.nmr.mgh.harvard.edu/registration.html>. Save
the file somewhere readable and point config at it.

### NORDIC (only if you denoise)

Whether a study denoises with NORDIC is a **pipeline decision — ask your PI**
before assuming either way; it changes what fMRIPrep preprocesses and belongs
in the methods section. The same goes for the container versions above and for
fMRIPrep options like output spaces: use what your lab has standardized on, and
don't change versions mid-study.

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

duckbrain's GUI is served two ways, and **both are in real use** (as of
2026-08-07): current beta testers use **Option A** (an interactive session +
`scripts/launch.sh`), and the maintainer uses **Option B** (a personal
OnDemand sandbox app). Option A needs nothing enabled for your account, so it
is the one to start with; Option B is a nicer daily driver once its
prerequisite is sorted. Neither is yet the one-click, RACS-published app that
is the long-term goal — see
[The distribution question](#the-distribution-question).

### Option A — `scripts/launch.sh` in an interactive session

**The route the current beta testers use.** Works from any checkout with a
recorded conda env (`.conda-prefix`) or a `.venv`. Start Streamlit on a
compute node:

```bash
srun --account=<pirg> --partition=interactive --time=04:00:00 \
     --mem=4G --cpus-per-task=2 --pty bash scripts/launch.sh
```

Then reach it one of two ways:

- **SSH tunnel from your laptop.** The script prints the exact `ssh -L …`
  command for the node it landed on. Run that in a second terminal on your
  own machine, then open <http://localhost:8501>.
- **Inside an OnDemand Interactive Desktop.** If you are already working in a
  Talapas desktop session (OnDemand's Interactive Desktop app), run
  `bash scripts/launch.sh` in a terminal there and open
  <http://localhost:8501> in the desktop's own browser — no tunnel needed.

> `UNVALIDATED`: the `srun` flags above (partition name, whether `--account` is
> required for `interactive`) are the shape the repo already documents but have
> not been re-checked against a current Talapas policy on a fresh account.

### Option B — Open OnDemand app

**The route the maintainer uses daily.** The `ondemand/` directory is a
complete OnDemand Batch Connect app. **Today it is registered as one user's
personal sandbox** (a symlink from `~/ondemand/dev/duckbrain` into that user's
checkout), so it is not yet something a new user can simply click. To use it
now you would register your own sandbox app pointing at your own checkout:

```bash
mkdir -p ~/ondemand/dev
ln -s ~/code/duckbrain/ondemand ~/ondemand/dev/duckbrain
```

Then reload the OnDemand dashboard; the app appears under **Develop → My Sandbox
Apps** (Interactive Apps → Neuroimaging).

> ⚠️ **This is not self-service, and that is the part to check first.** On
> OnDemand 1.6 and later, creating `~/ondemand/dev` is *not* enough — an
> administrator must also create a symlink under `/var/www/ood/apps/dev/<user>/`
> before the **Develop** menu appears for you at all. (Sites can opt back into
> "everyone a developer" via `nginx_stage.yml`, and can separately restrict the
> menu to a group in the dashboard initializer.) Whether Talapas has done either
> is **not verifiable from a login node** — `/var/www/ood` lives on the OnDemand
> web hosts. **Ask RACS.** If the answer is "we enable it per user on request",
> then Option B costs a ticket per person, which is a strong argument for the
> shared published app in
> [The distribution question](#the-distribution-question) instead.
>
> See [Enabling App Development](https://osc.github.io/ood-documentation/latest/how-tos/app-development/enabling-development-mode.html)
> in the OnDemand docs.

> `UNVALIDATED`: the steps above are the shape the maintainer's working setup
> takes, but have not been walked through on a *fresh* account. The form
> defaults the install directory to the maintainer's shared checkout
> (`/gpfs/projects/hulacon/shared/mmmdata/code/duckbrain`) — point the field at
> your own clone on first launch; OnDemand remembers your value after that.

---

## 5. Your first project

Once the GUI is open, the intended flow is:

1. **Setup** — choose your project directory; set SLURM account and the
   shared container/license/NORDIC locations. This writes your user + project
   config. (A session with no project open lands here.)
2. **BIDSification → Ingestion** — browse your LCNI DICOM export, let duckbrain
   assign BIDS subject/session labels, and symlink (or copy) sessions into
   `sourcedata/`.
3. **BIDSification → Conversion** — review the auto-detected series
   classification and fieldmap pairing, then submit a dcm2bids job (or
   bulk-convert everything).
4. **BIDSification → Project** — generate `participants.tsv` /
   `dataset_description.json`, validate the BIDS tree, and (once a session has
   converted correctly) freeze the study's declared expectations.
5. **Preprocessing** — run fMRIPrep, NORDIC, and/or MRIQC.
6. **QC** — review MRIQC metrics and record keep/exclude decisions.
…but **Status** is where you land once a project is open, and where you will
spend most of your time. It is the cockpit: a per-`(subject, session) × stage` matrix that grades
completion from real outputs and fuses in live SLURM state. The cells *are* the
controls — launch the next step, or open a running/failed cell to see the exact
SLURM job (id, live state, log tail) and cancel or re-run it. Live
`squeue`/`sacct` for everything else is the "All SLURM jobs" panel on the same
page. The pages above are for the work Status can't do for you: choosing a
project, mapping DICOMs, and recording QC decisions.

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
