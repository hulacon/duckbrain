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

**The canonical checkout is
`/gpfs/projects/hulacon/shared/mmmdata/code/duckbrain`
(= `/projects/hulacon/shared/mmmdata/code/duckbrain`)** — since 2026-08-16;
it was `~/code/duckbrain` before that. Canonical means dev happens here *and*
the OnDemand app serves from here: the two were split across checkouts, and
every session ended with a pull into the serving copy that was easy to forget,
so the GUI kept announcing work it didn't have (Ben asked for the repoint after
`#16.2` shipped with exactly that caveat). `~/code/duckbrain` is a **symlink to this
directory** (verified 2026-08-20), not a second checkout — so there is nothing
to pull and no way to dev in the wrong one. This file used to warn that it was a
separate copy that could fall behind; that stopped being true when the symlink
was made on 2026-08-10, and the warning outlived the hazard. Expect tracebacks
to print the `~/code/duckbrain` path when a test is reached through it: same
files, same git. Distribution to other users is unchanged: `git clone` from
`git@github.com:hulacon/duckbrain.git`.

## Working convention: stay on `main`

**Work directly on `main` whenever possible** (Ben's preference, 2026-07-15).
This is a single-maintainer personal working copy, and the OnDemand GUI serves
whatever is checked out here — so feature branches add ceremony and a stale-code
risk (the GUI keeps running old code until you merge back). Commit small,
verified changes straight to `main`. Only branch when a change is genuinely
risky/experimental and you want an easy bail-out; merge back and delete the
branch promptly. After committing, **push to `origin`** so the GitHub distribution
copy doesn't fall behind.

**Sign commits `Co-Authored-By: Claude <noreply@anthropic.com>` — no model name,
no version.** This overrides whatever model-specific trailer the harness supplies.
A session launched as one model can be *served* by another, and the assistant
cannot tell which from the inside: neuroimaging work trips Fable 5's safeguards
often, and the reroute to Opus 5 is announced **in the client UI only** — it never
enters the context. The stale field is the one that looks authoritative. The
identity line ("you are powered by …") is fixed when the prompt is built and is
never re-derived after a mid-session switch, so it keeps naming the *launch*
model; the commit trailer is templated later and tracks the model actually
serving. Anything in-session claiming to know which model is running is inference,
not observation — the assistant is not a reliable witness to its own routing.
History already carries four names across 234 commits (2026-08-06); the plain
trailer is the one form true under any routing. Existing commits stay as they are
— rewriting them would rehash every commit the `v0.1.0`–`v0.3.0` releases are
published against. See `memory/safeguard-reroute-stale-identity`.

## Where things are recorded

This file is **orientation** — how to work in this repo, and the rules that bind
before you touch anything. It deliberately does **not** carry the backlog or a
build history; those drifted out of date every time they were duplicated here.

| Question | Read |
|---|---|
| What's left to do? | `TODO.md` — opens with a priority-ordered index; the body follows that order, closed items are a ledger at the bottom |
| How did we get here / why does this code look like this? | `git log` — the commit message is the record |
| What changed for users? | `CHANGELOG.md` |
| How does subsystem X work? | `docs/` — `ls` it rather than trusting a list here; `pipeline-cockpit.md`, `pipeline-extras.md`, `conversion-legibility.md`, `sanity-checks.md`, `qc-dashboard-migration.md`, `qc-review-domains.md`, `handoff-cluster-session.md` |
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
NORDIC (producer *and* `use_nordic`→fMRIPrep chaining). Semver, annotated git
tags, a `CHANGELOG.md`, and every tag published as a GitHub Release — that last
step is the whole announcement channel and is easy to leave undone, so check
`git tag` against the Releases page rather than trusting a count here (this
sentence has been wrong about both the current release and the number of them).
The GUI is in active dogfooding. See `TODO.md` for what's open — it opens with a
priority-ordered index, and the release-bundling rule that used to be narrated
there now lives in `docs/releasing.md`, which is also how you cut the next one.

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
- **An exit code is not a success signal for a nipype tool.** fMRIPrep and MRIQC
  run some nodes on the master thread, where a crash never reaches the workflow's
  not-run report: the workflow prints "finished successfully", the process
  returns 0, and everything downstream of that node is silently pruned. No
  `set -e` or `$?` handling in an sbatch can see it, and neither can sacct — one
  run wrote native BOLD and nothing else in 46 minutes and reported success. What
  the tool *does* leave is `<derivative>/logs/crash-*.txt`. Read that, not the
  exit code, before believing a run. `consistency._check_tool_crashes` does, and
  `tests/test_consistency.py::test_a_crash_from_a_superseded_run_is_silent` pins
  the part that is easy to get wrong — a crash file outlives the attempt that
  wrote it, so a check that ignores staleness gets switched off within a week.
- **A check only a browser can settle goes in `TODO.md` `#30`, not in the commit
  message.** Streamlit primitives whose output AppTest doesn't model (tabs,
  `st.iframe`, `st.data_editor`, popovers, column widths) and anything the
  OnDemand proxy rewrites are the recurring cases. Left in a commit message the
  check is never done — three such notes sat undischarged in three different
  documents until `#30` collected them. The queue is batched deliberately: the
  tunnel costs more than the looking does.
- **Open work goes in `TODO.md` and nowhere else.** No `# TODO:` markers in
  source — that's a second backlog nothing sorts, prioritizes, or reads. This
  repo has zero and should keep it that way.
- **Cite a `TODO` id only for *open* work, and only from a doc that expands it**
  — both ends live, the pointer leads somewhere richer than itself.
  (`conversion_plan.py` → `docs/conversion-legibility.md` for `#13` was the
  canonical example until `#13` closed 2026-08-17; the module now cites the doc
  alone, which is the closed-item form of the same shape.) In code,
  **state the reason and let `git blame` carry the provenance.** A backward
  pointer to a closed item resolves to a ledger row that says *less* than the
  comment you were already reading, it pins the id registry in place forever, and
  it rots into a claim about current state — `config.py` spent a week asserting
  `#17.1` was open after it had been closed twice. For a closed item, cite the
  *test* that pins it: a test can't go quietly stale, it fails. `DB-0xx` ids are
  the safe exception — that review document is frozen, so they can never be
  renumbered by anyone. **Don't retro-sweep existing citations**; drop one when
  you're editing that line anyway.
  **The test is "does the pointer lead somewhere richer", not "is the item
  open"** — so `TODO.md`'s unscheduled tails are citable too. `#5` is the live
  case: it holds no task and never will, but it is where the standing rule on
  messy source labeling is argued, five source sites point at it for that, and
  each one lands on a fuller account than the comment making the reference.
  Reclassifying it out of the priority queue (2026-08-06) did not invalidate
  them. What the rule actually forbids is a pointer into the *ledger*, which
  compresses to one line by design.

## Validation projects (real data, on Talapas)

- **The conversion fixture — `/projects/lcni/dcm/repository`, and it is the good
  one.** 15 studies with **paired `dicoms/` and `bids/` trees**: 2139 series
  directories against the 404 canonical BIDS files the LCNI curator produced from
  them, 189 distinct series descriptions, 112 sessions that pair exactly (join
  the sidecars' `SeriesDescription`/`SeriesNumber` to the DICOM folder). Nothing
  else on this filesystem gives you a *canonical answer* to diff against, and it
  is the only place the hard cases exist together — both MR dialects, both
  fieldmap flavours, the vNav setter, `_ND` duplicates, empty series directories.
  **Read-only; never write to it** — scratch output goes to
  `/projects/hulacon/bhutch`. Use it for anything touching conversion; see
  `memory/lcni-repository-corpus` for what it proved and `TODO.md` `#19` for what
  it still shows missing.
- **Source DICOMs:** `/projects/lcni/dcm/hulacon/Hutchinson/divatten` — 37
  subjects, single-session, **read-only**.
- **More real exports, all read-only and all useful as fixtures:**
  `/projects/lcni/dcm/hulacon/Hutchinson/` also holds `PSY607`, `AttTime`,
  `New Program`, `RTPILOT`, `realtime` — the small ones are mostly genuine
  phantom/test folders, which is what makes them worth keeping. And
  `/projects/lcni/dcm/hulacon/mmmdata/` is the **nested** layout: one level of
  protocol folders (`anat_session/`, `func_session_*/`), 104 sessions, several
  with two or three fieldmap pairs.
- **The sourcedata fixture — `/projects/hulacon/shared/mmmsourcedata`.** A beta
  tester's ABCD-protocol tree, 5 subjects and 95 sessions, **already in
  duckbrain's `sourcedata` layout** (`sub-XX/ses-YY/dicom/Series_NN_<desc>/`), so
  it needs no ingestion. Treat as read-only — `sub-06`/`sub-07` are `drwxr-sr-x`,
  and duckbrain writes each session's `dcm2bids_config.json` back into the tree,
  so symlink at the `dicom` level into your own project instead of pointing
  `sourcedata_dir` at it. It holds three shapes the LCNI corpus does not:
  **diffusion SBRefs** (the corpus has zero across all 2139 series directories —
  they are what `_recover_dwi_sbref_from_sibling` and its tests in
  `tests/test_dicom_header.py` exist for), **LR/RL phase-encoding** (still
  unexploited — `TODO.md` `#19.2`), and **a scanner that writes no `ND` token in
  `ImageType`**, the only fixture for the twin guard's contradiction rule
  (`tests/test_series_classification.py`). See `memory/mmmsourcedata-fixture`.
- **BIDS projects — `ls /projects/hulacon/bhutch` rather than trusting a list
  here; this entry has been wrong about both the count and the derivatives.**
  `divatten_beta` (sub-015…019) is the one *known clean*: converted 2026-07-22,
  i.e. after the fieldmap-intent fix, and verified. `divatten_beta_v2` is the
  larger working project and is what the QC work was dogfooded on — 70 MRIQC
  reports, and an fMRIPrep tree that **is** now clean: the `#21`-damaged run was
  deleted and re-run on 2026-07-27, and all five subjects were re-measured
  2026-08-04 (13 preprocessed BOLD, 13 confounds, `recon-all.done`, MNI and
  fsaverage6 output each). This entry claimed the opposite for a week after the
  re-run — check before quoting either way.
  `memory/mmmduck-multisession-fixture` names a third (`/projects/hulacon/shared/mmmduck`,
  read-only), which is the only *longitudinal* fMRIPrep tree on Talapas.
- **The fieldmap fixture — `/projects/hulacon/bhutch/fmap_eyeball`.** Two
  sessions symlinked at the `dicom` level into the read-only `mmmdata` export:
  `sub-01` has two complete fieldmap pairs, `sub-02` has **three**. Staged
  2026-07-30 for `#13`'s browser eyeball pass, because the two-pair case lost its
  only fixture when `#14` deleted `mmm_fmap_check`. Nothing is converted and
  nothing needs to be — the Conversion Plan renders from DICOMs. Both also carry
  a real filename collision (a run reacquired under the same console name), so
  the preflight has something true to say.
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

- **The documented environment is conda** (since 2026-08-07): build or
  repair it with `./scripts/setup_env.sh`, which creates/updates the shared
  prefix `/projects/hulacon/shared/envs/duckbrain` and records it in the
  gitignored `.conda-prefix` (how both launchers find it). The script exists
  because `conda env create` cannot be made safe on this cluster — FSL's
  `~/.condarc` pins its channel with `#!final` markers nothing overrides
  except `--override-channels` on a plain `conda create`. Read the script's
  header before "simplifying" it. Intent lives in `environment.yml` (Python
  pinned at 3.11, runtime deps unpinned, conda-forge only); one clean solve is
  recorded in `conda/lock-linux-64.txt`; **the version bounds stay in
  `pyproject.toml`**, which the pip step (`-e .[dev]`) reads — never duplicate
  a pin into `environment.yml`.
- A legacy `.venv` still works and is still probed (after conda) by both
  launchers: `python -m venv .venv && source .venv/bin/activate &&
  pip install -e ".[dev]"`. Python **3.10+** either way.
- Dependencies: streamlit, jinja2, pandas, nibabel, plotly, pydicom (+ pytest for dev).

## Running it

- **Tests:** `python -m pytest tests/ -v`
- **The gates CI runs** (`.github/workflows/ci.yml`, on every push and PR against
  Python 3.10 and 3.12) — run them locally before committing, since every setting
  lives in `pyproject.toml` and a local run enforces exactly what CI does:
  ```bash
  ruff check . && ruff format --check . && mypy && python -m pytest tests/ -q --cov --cov-report=term-missing
  ```
  `--check`, the bare `--cov` and the bare `mypy` are all load-bearing: `ruff
  format .` *rewrites* instead of failing, a `--cov=<value>` overrides the source
  in `pyproject.toml` — which is exactly how the Streamlit pages went unmeasured
  — and passing paths to `mypy` overrides `[tool.mypy] files` the same way, so
  you'd check something other than what CI checks.
  The coverage floor (`[tool.coverage.report] fail_under`) is a **ratchet**: raise
  it when coverage rises, never lower it to green a build. Read the current value
  from `pyproject.toml`, not from here. Everything under `src/duckbrain` is
  measured, pages included, and **branches are counted as well as statements** —
  so an `if` whose fall-through no test takes is a gap the report names, even
  though the line itself ran. That is deliberate: this project's bugs are
  one-directional conditions in code that executes fine, not unexecuted lines.
  A consequence worth knowing before you compare numbers: the total is not on the
  same scale as any figure in git history from before 2026-08-03.

  `mypy` runs as its **own CI job** pinned to Python 3.10, not a step in the
  3.10/3.12 matrix, so that it answers one way rather than depending on which
  third-party builds pip resolved on a given leg. It checks **the whole package**
  (`src/duckbrain/`, since 2026-08-06) and is a **ratchet** like the coverage
  floor: every file was annotated and every knob measured at zero before being
  turned on, so it holds a property rather than opening a project. That is also
  what makes it safe to *block* rather than advise. Tightening it further means
  re-measuring first, and the knobs come from `pyproject.toml`, not from here —
  which is also where every ruff ruleset's decline is recorded, next to the
  `select` it constrains.

  **A `TYPE_CHECKING` import is safe in an annotation and unsafe in a type
  alias**, and mypy cannot tell you which you wrote. `from __future__ import
  annotations` defers annotations; an alias is an ordinary assignment evaluated
  at import, so `Foo = Callable[[Config], ...]` at module scope raises
  `NameError` while the gate stays green (to mypy the guard branch is always
  taken). Put the alias inside the guard. `tests/test_runtime_type_aliases.py`
  imports every module so the next one fails a test rather than a launch.
- **GUI locally (SSH-tunnel workflow):** `bash scripts/launch.sh` — starts
  Streamlit on port 8501; the script prints the exact `ssh -L` tunnel command.
  Uses the `.conda-prefix` env if recorded (falling back to `.venv`) and sets
  `DUCKBRAIN_CONFIG_DIR`.
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
~/ondemand/dev/duckbrain  ->  /gpfs/projects/hulacon/shared/mmmdata/code/duckbrain/ondemand
```
So it appears in the Talapas OnDemand dashboard under **Develop → My Sandbox
Apps** (Interactive Apps → Neuroimaging). Launch it there; once the SLURM
session starts, OnDemand exposes a "Connect to duckbrain" gateway link to the
Streamlit GUI.

Key behaviors to know when editing the app:
- The launch form's `duckbrain_dir` field **defaults to
  `/gpfs/projects/hulacon/shared/mmmdata/code/duckbrain`** — i.e. this
  checkout. If the canonical location ever moves, update BOTH the symlink
  target and this form default in `ondemand/form.yml`. The default is now a
  path only hulacon members can read — an accepted cost of serving from the
  shared checkout; anyone else edits the field once at their own clone, and
  OnDemand remembers per-user values from then on. That memory cuts both ways:
  **Ben's cached value may still say `~/code/duckbrain`**, so the first launch
  after the repoint needs the field checked, not trusted.
- `ondemand/template/script.sh.erb` uses, in order: the conda env recorded in
  `${DUCKBRAIN_DIR}/.conda-prefix`, then `${DUCKBRAIN_DIR}/.venv`, then a bare
  `module load python3` + `pip install -e` on the compute node (fragile —
  depends on module Python + network). **Keeping a recorded env (or `.venv`)
  present is what makes launches reliable.** The conda branch also sets
  `PYTHONPATH=${DUCKBRAIN_DIR}/src`, so the launched checkout is always the
  code that serves even though the shared env has one checkout
  editable-installed — don't remove that line as redundant.
- Because the OnDemand app serves THIS checkout, work landing here is live on
  the next launch — the pull step that used to sit between dev and the GUI is
  gone, which was the point of the repoint. The flip side: this working copy
  *is* the served copy, so an uncommitted half-edit can reach a running GUI.
  Commit small and keep the tree clean (the stay-on-`main` convention above is
  what makes that workable), and remember an already-running session keeps the
  code it launched with.

## Start here next session

**Read `TODO.md`** — it opens with a priority-ordered index of the open items,
and the first one is the next thing to do. Trust the index over this sentence; a
named item here goes stale the moment priorities move. Item ids (`#2`, `#5b`, …) are stable names referenced from this
file, `docs/`, and source comments, so they never get renumbered; a closed id
keeps its line in the ledger, and a sub-id like `#17.4` resolves to its parent's
row, so old references still land.

**Never read `TODO.md` whole — read the index, then slice the one item you want.**
The file is ~52k tokens; the index is under 800 and a median item is ~800, so the
whole-file read costs roughly ten times the slice and buys nothing. **About half
the file is the closed-item ledger** — under 100 lines, but every row is a dense
paragraph, and it is almost never what you want at launch. Every item begins
`<a id="N"></a>` on the line above its `##` heading, so this slices one:

```bash
awk -v want='"43"' '/^<a id=/{f=index($0,want)>0} /^# Closed/{f=0} f' TODO.md
```

The quoting is load-bearing and the naive form is *silently* wrong, which is why
it is written out here: `/^<a id="43">/,/^<a id=/` closes the range on the line
it opened and returns one line, and an unquoted `43` matches `#43` inside other
anchors the way an unquoted `5` would match `#5b`. Verified against `#43`, `#19`,
`#5` and the last item, which has to stop at `# Closed` instead of an anchor.

A slice is complete as *text* but not as *context*: bodies cross-refer by id (105
references across the 16 open items, all of them live), so read the `#NN`
references your slice makes and pull those spans too. Sub-ids mostly aren't
addressable — only `#16.3` and seven under `#19` have their own heading; the rest,
`#7.1` and `#43.3` among them, live in prose inside the parent section.

`docs/handoff-cluster-session.md` is **fully discharged** as of 2026-07-21 — keep
it as the record of what was asked and how each hypothesis resolved, but don't
start from it. Its caution earned itself twice over: both the mmmdata nesting it
described and a code comment about "duplicate" fieldmaps turned out to be wrong
when checked against real data. Treat any claim in `docs/` as a hypothesis.
