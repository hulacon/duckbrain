# New to Talapas?

If words like *compute node*, *SLURM*, or *PIRG* are new to you, start here.
Nothing on this page is specific to your study — it is the background the
[Quickstart](../QUICKSTART.md) and the rest of duckbrain quietly assume.

This guide lives in the repository rather than in the GUI on purpose: the
people who need it most are exactly the people who can't launch the GUI yet.
Read it here first, then take the [Quickstart](../QUICKSTART.md) from the top.
(The GUI's **New to Talapas?** page points back to this document, so it stays
findable after setup too.)

## The five-minute picture

- **Talapas is a cluster** — hundreds of computers (*nodes*) sharing one
  filesystem. You connect to a **login node** (a shared front door for
  light work only), and real computation runs on **compute nodes**.
- **SLURM is the scheduler** that hands out compute nodes. You describe a
  *job* (what to run, how much memory and time); SLURM queues it and runs
  it when a node is free. **duckbrain writes and submits these jobs for
  you** — you'll watch them on the Status page, not write them.
- **A PIRG** (Principal Investigator Research Group) is the account your
  jobs charge against and the group that owns shared storage under
  `/projects/<pirg>/`. Your PI owns it; you need to be a member.
- **Your files live in two kinds of place**: a small private home
  directory (`/home/<you>`), and your PIRG's much larger project space
  (`/projects/<pirg>/`). Studies and their data belong in project space.
- **What duckbrain does with all of that**: takes scanner DICOMs to a
  standard layout (BIDS), runs the standard preprocessing and QC tools on
  compute nodes via SLURM, and shows you completion, running jobs, and
  logs — without you writing pipeline scripts.

## Learn the basics

Each of these is the canonical starting point, not a random tutorial.
You don't need all of them on day one — the first two carry you a long way.

- **The command line** — [The Unix Shell (Software
  Carpentry)](https://swcarpentry.github.io/shell-novice/), the standard
  half-day introduction. Files, directories, running programs.
- **Talapas itself** — [RACS](https://hpcf.uoregon.edu/) (Research
  Advanced Computing Services) runs Talapas: their site links the current
  Talapas knowledge base (accounts, connecting, storage, SLURM on this
  specific cluster) and is where help tickets go.
- **Git and GitHub** — you need just enough to `git clone` duckbrain and
  `git pull` updates: [Git started guide
  (GitHub)](https://docs.github.com/en/get-started/start-your-journey), or
  the fuller [Version Control with Git (Software
  Carpentry)](https://swcarpentry.github.io/git-novice/). No account or
  SSH key is needed to clone — the HTTPS URL in the Quickstart works
  anonymously.
- **Conda** (environments) — duckbrain's `scripts/setup_env.sh` builds the
  environment for you; day to day you only `conda activate` it. If you
  want the concepts: [Getting started with
  conda](https://docs.conda.io/projects/conda/en/latest/user-guide/getting-started.html).
- **SLURM** (optional) — duckbrain submits and monitors jobs for you, so
  this is background, not prerequisite: [SLURM quick-start
  guide](https://slurm.schedmd.com/quickstart.html).

## The neuroimaging side

- **BIDS** — the standard layout for neuroimaging data, and the reason the
  whole pipeline can be automatic: [bids.neuroimaging.io](https://bids.neuroimaging.io/)
  for the standard, the [BIDS Starter
  Kit](https://bids-standard.github.io/bids-starter-kit/) for the gentle
  on-ramp. duckbrain's conversion step produces BIDS from your DICOMs.
- **fMRIPrep** — the standard fMRI preprocessing pipeline duckbrain runs
  for you: [fmriprep.org](https://fmriprep.org/). Worth skimming what it
  does even if you never run it by hand.
- **MRIQC** — automated image quality metrics, feeding duckbrain's QC
  pages: [mriqc.readthedocs.io](https://mriqc.readthedocs.io/).

## Check with your PI first

Several setup steps encode a *lab decision*, not a personal preference —
and the right answer is whatever your lab has standardized on, not
whatever a tutorial (or the GUI) defaults to. Before setting these,
ask your PI or lab manager:

- **Your PIRG and SLURM account.** Every job charges to it, and the Setup
  page and OnDemand launch form both ask for it. If you don't know yours,
  that's the first question.
- **The shared conda environment.** `scripts/setup_env.sh` builds one
  environment per lab at a shared prefix
  (`/projects/<pirg>/shared/envs/duckbrain`), so the whole lab shares one
  build instead of each person growing a private copy. Ask whether your
  lab already has one — and if not, where it should live — before
  building your own.
- **The containers.** The fMRIPrep/MRIQC/dcm2bids container images are
  ~8.6 GB and take real time to build, and nothing about them is
  per-user. Ask whether your lab already has a containers directory
  before building your own set.
- **Which tool versions and options.** Preprocessing choices — fMRIPrep
  version, output spaces, whether the lab denoises with NORDIC — should be
  consistent across everyone working on a study. Ask what the lab uses
  before preprocessing anything; changing versions mid-study is a
  methods-section problem.
- **Where your project lives.** BIDS projects belong in PIRG project
  space, and labs usually have a convention (and a quota). Ask where
  yours should go before creating it in Setup.
- **Access to the DICOMs.** LCNI writes scanner exports under
  `/projects/lcni/dcm/<group>/<PI>/<study>`; being able to read your
  study's export is arranged through your PI, not through duckbrain.

Two things are yours alone and can't be shared: the **FreeSurfer license**
(free per-user registration at
[surfer.nmr.mgh.harvard.edu](https://surfer.nmr.mgh.harvard.edu/registration.html))
and, if your lab uses NORDIC, **your own copy of the toolbox** (its
licence forbids redistribution — see
[the Quickstart](../QUICKSTART.md#2-acquire-the-containers-and-nordic)).

## What you do *not* need to learn

You never have to write an sbatch script, remember `squeue` flags, or
hand-edit JSON pipeline configs — duckbrain generates, submits, and
monitors all of that, and the **Status** page shows every job with its
logs. The command line you actually need is the handful of lines in the
[Quickstart](../QUICKSTART.md): clone, set up the environment, launch.
