# Joining a project someone else set up

This page is for you if a labmate has already set a study up in duckbrain and
you now want to open the same project and work on it. Two people working on one
project is a different situation from starting your own (the
[Quickstart](../QUICKSTART.md)): most of the setup is already done, and a few
new things can go wrong.

> `UNVALIDATED` — written before a second person had opened a shared
> project end to end. If a step here does not match what you see, use
> **Report a problem** and say which step.

## What you need

| Need | How to check |
|---|---|
| A Talapas account | You can log in to `talapas-login.uoregon.edu` |
| Membership in the PIRG that owns the project | `id -Gn` lists `is.racs.pirg.<pirg>` |
| A Slurm association with the project's account | `sacctmgr -nP show assoc user=$USER format=Account` lists it |
| Write access to the project root | `test -w <project_dir> && echo ok` |
| A duckbrain checkout and environment | See below |

If a check fails, ask the project's owner, or RACS for the PIRG and account
rows. duckbrain cannot fix any of these for you.

**The checkout.** If your PIRG keeps a shared duckbrain checkout with a
recorded environment (a `.conda-prefix` file in it), you can launch from that
and skip installing anything. Otherwise clone your own copy and build the
environment as in [Quickstart §1](../QUICKSTART.md#1-install-duckbrain).

## What you probably do not need

Containers, a FreeSurfer licence and a NORDIC copy are usually **already
provided by the project**. Read the project's own config,
`<project_dir>/code/duckbrain.toml`, and look at its `[paths]` section:

- If it names `containers_dir`, `fs_license` and `work_dir`, those are the
  ones every job in this project uses. **The project config is merged last,
  so it wins over your own user config.** You do not need your own copies.
- If it does not, you need your own, set up as in
  [Quickstart §2–3](../QUICKSTART.md#2-acquire-the-containers-and-nordic).

Your user config (`~/.config/duckbrain/config.toml`) then holds only things
that are about you: your Slurm email, if you want one, and the list of
recently opened projects.

## Opening the project

1. Launch the GUI as in [Quickstart §4](../QUICKSTART.md#4-launch-the-gui). To
   skip the picker, set `DUCKBRAIN_PROJECT_DIR=<project_dir>` before
   `scripts/launch.sh`.
2. On **Setup**, open the project directory. Opening writes only two things:
   any missing standard folders (`derivatives/`, `code/logs/`, and
   `sourcedata/` unless the config puts it elsewhere), plus an entry in your
   own recent-projects list. It does not change the project's config.
3. Go to **Status**. It grades every subject and session from the files on
   disk, so you will see the project's real state right away.

**Read the project config before you press Save on Setup.** Saving writes
your form values into `<project_dir>/code/duckbrain.toml`. That file is the
project's, not yours: it changes settings for everyone, starting with their
next job. If a value looks wrong, ask the owner before you change it. The
comments in the file often say why a value is what it is, and a save from the
GUI currently drops every one of them. Copy the file aside before saving if it
has any.

## Working alongside someone else

**The Status board does not see their jobs.** Live job state comes from
`squeue` for *your* user only. While your labmate's fMRIPrep job for a
session is running, that session looks idle to you, and nothing stops you
from launching the same step a second time. Two jobs writing one derivative
folder are not safe. Before you launch anything, check the whole account:

```bash
squeue -A <account> -o "%.10i %.20j %.8u %.10T %.10M"
```

Job names follow `<step>_<subject>[_<session>]`, so a matching name means
someone already has it. Agree with your labmate on who runs which subjects or
steps.

**Files you create must stay writable by the group.** duckbrain's launchers
and job scripts set `umask 0002`, so everything they write is group-writable.
Files you create *outside* duckbrain (copying data in, editing by hand, other
scripts) follow your login umask. If `umask` prints `0022`, add `umask 0002`
to your `~/.bashrc`. Otherwise your labmates can read those files but cannot
change or remove them, and only you can fix that.

**What is per-person and what is shared:**

| Per person | Shared by everyone on the project |
|---|---|
| Your Slurm jobs and their live state on Status | The project config, `code/duckbrain.toml` |
| Your node-local scratch (the path contains your username) | Job logs and submitted scripts in `code/logs/` |
| Your recent-projects list | Everything under `derivatives/` |
| | QC decisions. Each one records who made it. |

## When something goes wrong

Press **Report a problem** at the top of any page. The report includes the
project's settings and recent logs, so read it before you send it to the
project's owner.
