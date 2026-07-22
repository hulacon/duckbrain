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

## Where things are recorded

This file is **orientation** — how to work in this repo, and the rules that bind
before you touch anything. It deliberately does **not** carry the backlog or a
build history; those drifted out of date every time they were duplicated here.

| Question | Read |
|---|---|
| What's left to do? | `TODO.md` (open work; closed items are a one-line ledger) |
| How did we get here / why does this code look like this? | `git log` — the commit message is the record |
| What changed for users? | `CHANGELOG.md` |
| How does subsystem X work? | `docs/` (`pipeline-cockpit.md`, `pipeline-extras.md`, `conversion-legibility.md`, `sanity-checks.md`, `handoff-cluster-session.md`) |
| Why don't we just use Nipoppy / CuBIDS / mrQA? | `docs/sanity-checks.md` — surveyed and each refused or borrowed for a stated reason |
| What did the 2026-07-22 external audit say? | `docs/code-review-260722.md` — answered and closed; see the `#18` ledger row |
| How do I cut a release? | `docs/releasing.md` (incl. why the minor bump is not just bookkeeping) |
| What did we learn validating on real data? | `memory/` via `MEMORY.md` |
| Why is this rule here? | the comment on the code that enforces it |

**Don't trust a number or a commit hash written in any doc** — test counts and
hashes go stale within a session, and this file has been wrong about both before.
Run `git log --oneline -1`, `git status`, `python -m pytest tests/ -q`.

## Status in one paragraph

Feature-complete across all three planned phases, plus a project surveyor and an
actionable pipeline cockpit. **Every core stage is validated live on real data**
on Talapas: DICOM→BIDS (output matches canonical heudiconv), fMRIPrep, MRIQC, and
NORDIC (producer *and* `use_nordic`→fMRIPrep chaining). Semver, git tags,
`CHANGELOG.md`; latest release `v0.2.0` (2026-07-21), first was `v0.1.0`. The GUI
is in active dogfooding. See `TODO.md` for what's open, `docs/releasing.md` to cut
the next one.

## Rules that bind (read before changing related code)

- **Provenance stamps `git describe` of the checkout, not `__version__`.**
  duckbrain is served from a working copy, so users sit *between* releases;
  `__version__` marks the release only. Never treat it as what ran. The version
  literal lives in exactly one place — `src/duckbrain/__init__.py`; `pyproject.toml`
  is `dynamic` and reads it from there. Never add a second copy.
- **Never compare a config-pinned container *tag* to a tool's *self-reported*
  version.** Different namespaces — that bug shipped once. (The MRIQC `24.0.2`
  container self-reports `24.1.0.dev0+…`; a phantom `24.1.0` default came from
  exactly this confusion.)
- **BIDS fieldmap intent: the *fieldmap* carries `B0FieldIdentifier`, the *bold
  and sbref* carry `B0FieldSource`.** The field is estimated from scans sharing an
  identifier and applied to scans sharing a source. duckbrain shipped these
  inverted, and nothing complained — the dataset validates, dcm2bids is happy, and
  fMRIPrep just reports "Susceptibility distortion correction: None" and
  preprocesses uncorrected. Found 2026-07-21 by asking what happens to SBRefs.
  Pinned by tests in `tests/test_conversion_plan.py`; never swap them.
- **Every expectation duckbrain computes is derived from the data it judges** —
  the roster from what exists on disk, the run list from the converted tree, the
  NIfTI counts from the config duckbrain emitted. So a shortfall shrinks the
  expectation to match and the board reads COMPLETE. The **only** independent
  statement of intent is a project's `[expected]` section (`core/expectations.py`,
  `docs/sanity-checks.md`); don't add a "check" that re-derives its own
  expectation from the artifact it is checking, because that is the bug, not the
  fix. `[expected]` is **opt-out by default** — absent means the checks don't run,
  and that is a behaviour with a test, not an oversight.
- **Provenance source rule:** for derivatives duckbrain *produces*, provenance
  lives in the data (sidecars → dataset stamp); for tool-produced derivatives
  (fMRIPrep/MRIQC) the submission log is the only channel. Enforced and explained
  in `core/consistency.py`'s module docstring.
- **Licensed GPL-3.0-or-later**, knowingly: duckbrain code **cannot be upstreamed**
  into Apache-2.0 nipreps or MIT nipoppy. It orchestrates external tools at arm's
  length so no licence crosses in either direction — users obtain each tool
  themselves (NORDIC especially: non-redistributable).
- **A silently-degrading option is worse than one that fails.** If a flag or
  toggle can't do what it says, raise — don't submit a job that quietly does
  something else. (Cost us a real fMRIPrep run: "reuse anat derivatives" with
  nothing to reuse rebuilt the anat and said nothing.)
- **Open work goes in `TODO.md` and nowhere else.** No `# TODO:` markers in
  source — that's a second backlog nothing sorts, prioritizes, or reads. This
  repo has zero and should keep it that way.
- **Cite a `TODO` id only for *open* work, and only from a doc that expands it**
  (`conversion_plan.py` → `docs/conversion-legibility.md` for `#13` is the shape:
  both ends live, the pointer leads somewhere richer than itself). In code,
  **state the reason and let `git blame` carry the provenance.** A backward
  pointer to a closed item resolves to a ledger row that says *less* than the
  comment you were already reading, it pins the id registry in place forever, and
  it rots into a claim about current state — `config.py` spent a week asserting
  `#17.1` was open after it had been closed twice. For a closed item, cite the
  *test* that pins it: a test can't go quietly stale, it fails. `DB-0xx` ids are
  the safe exception — that review document is frozen, so they can never be
  renumbered by anyone. **Don't retro-sweep existing citations**; drop one when
  you're editing that line anyway.

## Validation projects (real data, on Talapas)

- **Source DICOMs:** `/projects/lcni/dcm/hulacon/Hutchinson/divatten` — 37
  subjects, single-session, **read-only**.
- **More real exports, all read-only and all useful as fixtures:**
  `/projects/lcni/dcm/hulacon/Hutchinson/` also holds `PSY607`, `AttTime`,
  `New Program`, `RTPILOT`, `realtime` — the small ones are mostly genuine
  phantom/test folders, which is what makes them worth keeping. And
  `/projects/lcni/dcm/hulacon/mmmdata/` is the **nested** layout: one level of
  protocol folders (`anat_session/`, `func_session_*/`), 104 sessions, several
  with two or three fieldmap pairs.
- **BIDS project — there is exactly one, `/projects/hulacon/bhutch/divatten_beta`**
  (sub-015…019; MRIQC and NORDIC derivatives, no fMRIPrep yet). Converted
  2026-07-22, i.e. *after* the fieldmap-intent fix, and verified correct — it is
  the only dataset on this filesystem known clean.
- **The three projects this file used to name are gone** (`divatten`,
  `divatten_gui_beta`, `mmm_fmap_check`), deleted 2026-07-22 as `#14`'s cleanup.
  Two capabilities lost their live fixture with them: two-fieldmap-pair
  conversion (the `#4` validation) and anything wanting a real fMRIPrep
  derivative. Both are re-creatable from the read-only DICOM sources above —
  `mmmdata/` is where the multi-pair sessions are.
- **Source DICOMs are read-only and were never at risk**, which is why this was
  cheap to recover from. Keep it that way: derived BIDS is reproducible, the
  exports are not.

## Environment / setup

- Python **3.10+**. A virtualenv lives at `.venv/` (gitignored).
- Set up / repair it with:
  ```bash
  python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
  ```
- Dependencies: streamlit, jinja2, pandas, nibabel, plotly, pydicom (+ pytest for dev).

## Running it

- **Tests:** `python -m pytest tests/ -v`
- **The gates CI runs** (`.github/workflows/ci.yml`, on every push and PR against
  Python 3.10 and 3.12) — run them locally before committing, since every setting
  lives in `pyproject.toml` and a local run enforces exactly what CI does:
  ```bash
  ruff check . && ruff format . && python -m pytest tests/ -q --cov=duckbrain
  ```
  The coverage floor (`[tool.coverage.report] fail_under`) is a **ratchet**:
  raise it when coverage rises, never lower it to green a build. It reads low
  (60%) because the seven Streamlit pages are scripts no test imports; core,
  config and slurm run 84–100%.
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

## Start here next session

**Read `TODO.md`** — it opens with a priority-ordered index of the open items,
and the first one is the next thing to do. Trust the index over this sentence; a
named item here goes stale the moment priorities move. Item ids (`#2`, `#5b`, …) are stable names referenced from this
file, `docs/`, and source comments, so they never get renumbered; a closed id
keeps its line in the ledger, and a sub-id like `#17.4` resolves to its parent's
row, so old references still land.

`docs/handoff-cluster-session.md` is **fully discharged** as of 2026-07-21 — keep
it as the record of what was asked and how each hypothesis resolved, but don't
start from it. Its caution earned itself twice over: both the mmmdata nesting it
described and a code comment about "duplicate" fieldmaps turned out to be wrong
when checked against real data. Treat any claim in `docs/` as a hypothesis.
