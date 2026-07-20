# duckbrain — TODO

**Open work only.** Closed items are a one-line ledger at the bottom — the detail
lives in `git log`, `CHANGELOG.md`, `docs/`, and `memory/`, and every design rule
that still constrains new code is a comment on the code that enforces it. See
`PLAN.md` for the original design and `CLAUDE.md` for current status.

**Item ids (`#4`, `#5b`, …) are stable names, not positions.** They're referenced
from CLAUDE.md, `docs/`, and source comments, so they never get renumbered — the
list is ordered by priority and the ids stay put. Closed items keep their id in
the ledger so an old reference still resolves.

---

## #4 — Live-validate discovery + fieldmap handling (needs real data)

The only items left in `docs/handoff-cluster-session.md` (§2, §3) — built and
unit-tested offline, never run against a real LCNI export. That doc's *previous*
version asserted findings that turned out to be wrong on inspection, so treat its
claims as hypotheses to verify.

- **Session/subject discovery against a real export.** `G##_S##` session parsing
  and phantom/test-folder filtering. The thing to confirm is the dangerous
  direction: **no real subject is silently dropped** by the exclusion rules.
- **Multiple fieldmap pairs, end to end.** Two AP/PA pairs must convert to
  `dir-AP_run-1` / `dir-AP_run-2`, not one overwritten `dir-AP`.
- **Eyeball the dcm2bids `GeneratedBy`** on an ingested root while you're there.
- *Known limitation, deliberate:* with ≥2 fieldmap pairs, bold→fmap linking sends
  every task to the first group (`_assign_fmap_group` has no temporal-proximity
  logic). Fine for conversion; a candidate refinement, not a bug.
- **DEFERRED — mmmdata-style nested multi-session** (`func_session_*/anat_session/`
  under the source) breaks `discover_sessions`, which expects session folders
  directly under the source dir. The real nesting isn't documented in this repo;
  implementing against a guess is unverifiable and risks the working LCNI path.
  Needs a real example tree. (This is the "#4 item 4" the handoff doc refers to.)

## #2 — Onboarding for external users

**The writing is done; the dogfooding and the distribution story are open. Do not
tick this off.** `QUICKSTART.md` and `README.md` are written and current.

- **`UNVALIDATED` — the new-user path on a clean account.** Flagged inline in the
  docs too. Nobody has walked: fresh `git clone` → venv → `pip install -e ".[dev]"`
  → tests pass; the three `singularity build` commands actually building on Talapas
  (and whether it's `apptainer` or `singularity` under current module policy); the
  exact config key set the Setup page emits matching the hand-written shapes in the
  docs; `scripts/launch.sh` srun flags under current partition/account policy; and
  personal-OOD-sandbox registration for a *new* user (never written up).
- **In-GUI guidance at friction points** (Setup, ingestion mapping, conversion) —
  needs a real walkthrough to know where the friction actually is.
- **Distribution story — needs RACS.** The OOD app is a personal sandbox today.
  Three candidates laid out but not picked in
  `QUICKSTART.md#the-distribution-question`: personal sandbox / `launch.sh`+tunnel
  / a shared RACS-published app.
- **NORDIC constraint that shapes this:** the licence forbids redistribution and
  the PIRG root is `0770` (no world access), so every user must fetch their own
  toolbox copy and each will sit at a different SHA. Already the config shape. See
  `memory/nordic-versioning-and-licence`.

## #9 — Launch surface: one place to run, everywhere else prepares

**PUNTED 2026-07-20** pending more discussion + hands-on time in the GUI. Ben's
question was whether the non-dashboard pages should be config-only, with all
running done from the cockpit. The rest of the interface pass is settled: recent
projects and top nav shipped, the browser eyeball closed, and the icon question
was dropped (it is Streamlit's own chrome, not worth the time).

Assessment so far, to pick up from — the answer is *mostly yes, but not
uniformly*, because the redundancy is not evenly spread:

- **Preprocessing is almost pure duplication** of the cockpit and the best
  candidate. But deleting its Submit buttons leaves the page purposeless; the
  better move is to turn it into where you set **per-stage defaults persisted to
  the project config**, so the cockpit's one-click launch inherits them. That
  converts a redundant launcher into the thing that makes one-click *correct*.
  Note this overlaps with `#10` — per-session template groups would want the same
  persistence mechanism, so design them together rather than twice.
- **BIDS Conversion is a mix.** The per-session mapping surface (series
  inspection, fieldmap detection, task/run mapping) is a work surface, not
  settings, and must stay. Its *bulk* submit duplicates the cockpit and can go;
  the *single-session* submit is worth keeping — you have just fixed that
  subject's mapping, which is the moment of highest intent.
- **Data Ingestion must keep its actions.** Ingestion is deliberately read-only
  in the cockpit (Ben agreed), and the page also does local work that is not a
  SLURM stage at all (`participants.tsv`, `dataset_description.json`, DICOM
  sorting).
- **QC Dashboard is not duplication** — keep/exclude decisions are their own job.
- **Two capabilities exist only on the pages — do not lose them.** "Export
  Scripts" (write the sbatch without submitting) has no cockpit equivalent and is
  genuinely useful on HPC; and bulk-with-shared-non-default-params, since the
  cockpit's column-header bulk runs a stage with *defaults* and its per-cell
  params are per-cell. Either move both into the cockpit first, or keep them a home.

## #5 — Config / mapping niceties

Deliberate deferrals, each fine as-is — listed so they aren't rediscovered as bugs.

- No per-rule temporal-proximity for fieldmap linking (same limitation as #4).
- Task rules are dataset-wide; there's no per-subject *rule* scoping. Per-subject
  *edits* already cover the exception case.
- `directory_picker` is dirs-only; `fs_license` stays a text field. File-mode
  deferred until something needs it.

## #10 — Template groups: config defaults that vary within a project

**Captured 2026-07-20.** Today the config layers are base → user → project, and
the project layer is flat: one set of defaults for the whole study. That breaks
when sessions genuinely differ — session 1 on a different protocol from session 2
wants different dcm2bids expectations, task mapping, maybe different fMRIPrep
params or SLURM resources.

- **Prefer named groups over keying on the session label.** `ses-01` / `ses-02` is
  the obvious key but the wrong one: the real distinction is usually *protocol*
  ("pilot" vs "main", "7T" vs "3T"), several sessions can share one, and a
  sessionless project can still want two groups. So: define named template groups,
  assign units to a group, fall back to the project defaults when unassigned.
- **There is already a pattern to follow, not invent.** Project-wide task mapping
  does exactly this shape one layer down — project-wide rules, per-session
  overrides, persisted read-modify-write into a `[task_mapping]` section
  (`save_project_task_map`). Template groups generalize it from "task labels" to
  "any default". Reuse the mechanism; don't grow a second one.
- **Open questions to settle first:** does a group override the *whole* section or
  merge key-by-key (merge, presumably — same deep-merge the config layers already
  use)? Where does assignment live, the project config or per-unit? And does the
  surveyor need to know about groups, or is this purely a launch-time concern
  (probably the latter — completion is still completion).
- **Design with `#9` together.** That item wants per-stage defaults persisted to
  the project config; this wants those defaults to vary by group. Same persistence
  mechanism, so designing them separately would build it twice.

## #11 — Automated pipeline: DICOMs in, derivatives out (exploratory)

**Captured 2026-07-20, Ben's idea.** Given source DICOMs, run every step
unattended — either by periodically checking in, or by chaining dependencies.

- **duckbrain already has both ingredients.** `survey_live` + `stage_runnable`
  answer "what could run right now" for every unit, and `advance_one` launches
  exactly one stage for one unit. An unattended driver is close to a loop over
  those two — most of the work is deciding the *policy*, not the mechanism.
- **Two mechanisms, and they are not equivalent:**
  - **SLURM dependency chaining** (`--dependency=afterok:<jobid>`) submits the
    whole chain up front. No polling, and the scheduler enforces order. But a
    failed stage strands its dependents in a held state, and re-planning after a
    partial failure is awkward.
  - **A periodic reconciler** (cron/timer: wake, survey, launch whatever is
    runnable) is **the better fit for this codebase.** duckbrain keeps no state
    store — every page re-derives what exists from the filesystem — which is
    exactly what a reconciler needs, and it self-heals after partial failures
    instead of stranding them.
- **The failure mode to design against is a resubmission loop.** A stage that
  always fails would be relaunched forever. Needs a retry cap and backoff, and a
  durable record of attempts per unit/stage — `submissions.tsv` is already that
  record. The no-double-submit guard exists (`stage_runnable` refuses a
  running/queued unit); the missing piece is "stop retrying a *failing* one".
- **Unresolved, and it gates the whole thing:** where does the driver actually
  run? Cron on a Talapas login node may be discouraged or disallowed — that is a
  RACS question, and the answer may push this toward a long-lived SLURM job or an
  OOD-launched daemon instead.
- Related but distinct from `#12`: a deterministic reconciler and an agent that
  decides what to run next are alternative drivers over the same core API.

## #12 — Merge with mmmdata-agents (exploratory)

**Captured 2026-07-20, Ben's idea.** `/gpfs/projects/hulacon/shared/mmmdata/code/mmmdata-agents`
is a Claude-powered agent repo over the mmmdata dataset: a data agent (natural
language BIDS queries), a QC agent (MRIQC outliers), an orchestrator, and a tool
registry under `src/tools/` — `bids_tools`, `conversion_tools`, `manifest_tools`,
`qc_tools`, `slurm_tools`, `sourcedata_tools`.

- **The overlap is close to one-to-one**, which is the argument for merging rather
  than a second implementation: those tool modules map onto duckbrain's
  `core/surveyor.py` (inventory/status), `core/consistency.py`, `slurm/monitor.py`
  + `core/pipeline.py`, and the `core/` BIDS modules. mmmdata-agents even carries
  its own `pipeline_status_*.tsv` — the thing the surveyor exists to produce.
- **duckbrain is already shaped for this.** The core/GUI split means the useful
  surface is plain Python with no Streamlit in it (`survey_project`, `survey_live`,
  `stage_runnable`, `advance_one`, `check_consistency`). Backing agent tools with
  that core is mostly wiring, not redesign.
- **⚠️ Check the licence before any code moves.** duckbrain is GPL-3.0-or-later and
  **mmmdata-agents has no LICENSE file at all**. If it imports duckbrain, the
  copyleft reaches it. Same trap that blocks the `surveyor.py` → mmmdata port. Settle
  the licensing question (see the Licensing section) *before* writing integration
  code, not after.
- **Cheapest first step, if this proceeds:** point one existing agent tool at
  duckbrain's surveyor instead of its own status code, and see whether the
  abstraction actually fits before committing to a merge.

## Provenance / consistency residuals

The item is closed and shipping; these are the accepted edges.

- **The mixing check has never been driven by two *completed* real fMRIPrep runs.**
  It costs hours of compute and works by deliberately corrupting a derivative.
  Every *input* to the check is live-validated, so what's unproven is grouping
  logic over real values. **Close it for free** the next time a project genuinely
  mixes variants.
- Config-vs-provenance is dataset-level; per-subject would be finer.
- An mriqc `DatasetLinks` check, if MRIQC ever records one.
- `tool_version` is overloaded — a container *tag* for container stages, a
  `git describe` for NORDIC. Defensible (both are "what we pinned"), not worth its
  own migration. Fold in if those columns are ever touched again.
- NORDIC log rows still write `tool_version`/`runtime`/`code_source` that nothing
  reads now that sidecars are the source. The row still earns its place via `job_id`.

## #5b — NORDIC Case 2: same-project raw-vs-NORDIC comparison

Deferred until actually needed. Case 1 (the `use_nordic` toggle) is validated live.

- **Try the zero-code fallback first:** two project dirs over the same BIDS, one
  with `use_nordic` on.
- If it needs building: **do not branch the pipeline.** Use distinct derivative
  names (`derivatives/fmriprep/` vs `derivatives/fmriprep-nordic/`) and
  parameterize the hardcoded derivative dir in `_fmriprep_status` and the builder,
  so a variant appears as an *additive extra column* only when the project opts in.
  Matches BIDS-derivatives norms.
- **Case 3, full named-pipeline DAG: PARKED.** Only if branch counts grow (multiple
  denoisers / fMRIPrep configs routinely). This is the complexity to avoid.
- **Candidate affordance** (ties to #2): the Setup page validates containers exist;
  give NORDIC the same treatment — "toolbox not found → fetch pinned version",
  cloning upstream at a duckbrain-pinned SHA into the user's own space. Not
  redistribution (the user pulls from UMN) and it gives version uniformity.

## #7 — Pipeline extras: candidate stages (backlog, none started)

Each is its own focused effort. Full annotated backlog — candidate tools, ties to
existing duckbrain/mmmdata work, open questions per item — in
**`docs/pipeline-extras.md`**.

1. **De-identification for sharing — highest value.** Defacing **+** metadata/header
   PII scrubbing (DICOM headers *and* BIDS sidecars), "derive-then-torch" policy
   (age ok, name/DOB auto-removed). Candidate: `bidsonym`. *(The precomputed-mask
   fast-track is a different feature, deliberately deferred — see the doc.)*
2. **DTI/DWI preprocessing** — orthogonal modality branch (candidate: QSIPrep).
3. **Scanning-notes integration** — input-shaping producer (exclude bad runs via
   bids-filter/`scans.tsv`); reuse mmmdata `build_manifest`/`sessions.tsv`.
4. **QC norms & best-practice dashboard** — consumer of fMRIPrep+MRIQC; layer norms
   on the existing surveyor/QC pages.
5. **Physiological data as BOLD regressors** — downstream consumer (PhysIO/TAPAS →
   confounds); fMRIPrep ingests physio but doesn't compute RETROICOR.
6. **ReproIn evaluation** — upstream naming convention (ties to #4); adopt
   internally vs. recommend to LCNI users.
7. **Eye-movement reconstruction from BOLD** (DeepMReye-style) — a branch fMRIPrep
   actively *fights* (brain extraction removes the eyes); opt-in "preserve eyes"
   path off raw/minimal data. Low demand, unique requirements.

## Licensing follow-ups

- **Open question: confirm with UO/RACS that Ben can license duckbrain** under
  GPL-3.0-or-later (employee-IP policy).
- The `surveyor.py` → mmmdata port (the old #6 follow-on) is **blocked on the
  copyleft choice** — it would need dual-licensing to land in Apache-2.0 nipreps /
  MIT nipoppy territory. See `memory/licensing-and-versioning`.
- **`#12` (mmmdata-agents) hits the same wall and is the more likely one to be
  tried first.** That repo has no LICENSE file, so today there is nothing to
  reconcile duckbrain's GPL *against*. Give it a licence before, not after, any
  code moves between them — retrofitting one over code that already imports GPL
  work is a much worse conversation.

## #8 — Visual identity & branding (someday)

Gated behind functionality + onboarding (#2); captured so it isn't forgotten.
Logo/wordmark that works small (favicon) and as a banner; a considered Streamlit
theme instead of defaults; favicon for the GUI tab and the OOD tile; README banner.
Tasteful, not over-designed, and after the product behavior is locked.

## Loose ideas (not scheduled)

- Cockpit: re-run of an already-*complete* stage behind an advanced toggle
  (deliberately excluded from `stage_runnable` today).
- The NORDIC column is always-on; for non-NORDIC projects it's a column of ⚪.
  Fine for LCNI/mmmdata, revisit if it reads as noise elsewhere.
- **Re-add the Nipoppy bagel export** if Nipoppy takes off — but feed it from
  *provenance, not config*, which is the bug that made removal right. Verified spec
  preserved in `memory/nipoppy-status-tracking`; recover the code with
  `git show 9c3ab39:src/duckbrain/core/surveyor.py`.

---

# Closed

One line each. Detail is in `git log` (the commit message is the record),
`CHANGELOG.md` for anything user-facing, `docs/` for design, and `memory/` for
validation findings. Design rules that still bind live as comments on the code that
enforces them — the provenance source rule in `consistency.py`'s module docstring,
the BEP028 sidecar warning in `core/nordic.py`, the task-vs-run rule in
`core/dcm2bids_config.py`.

| Done | Id | Item |
|---|---|---|
| 2026-07-20 | #9 | **Top nav + recent-projects MRU** — declarative `st.navigation(position="top")`, sidebar freed, project bar with a Switch popover; fixed a relative import that had silently broken the project indicator under `streamlit run` |
| 2026-07-20 | #0 #1 | **Browser eyeball pass** — dashboard table width reads well at project scale; folder picker fine as-is. Generated `#9` above |
| 2026-07-20 | — | **fMRIPrep anat-reuse gated + self-overlapping bind dropped** — reuse was a silent no-op when there was nothing to reuse; `has_anat_derivatives()` now gates it in `_build_fmriprep` (API *and* GUI) |
| 2026-07-17 | #0 | **Cockpit usability pass** — three stacked blocks became one actionable board; cells *are* the controls, per-cell job reference + cancel/re-run |
| 2026-07-17 | #0 | **Job Monitor page retired**, folded into the cockpit as the "All SLURM jobs" panel; new `cancel_job()` / `find_job_logs()` |
| 2026-07-17 | #2 | **MRIQC default pinned `24.0.2`** — the old `24.1.0` default was never a real Docker tag, only the container's self-report |
| 2026-07-17 | #5 | **BIDS task-label sanitizing** — `resting_test` → `restingTest` at the entity boundary, GUI warns on rewrite |
| 2026-07-16 | ★ | **Provenance recording + consistency checker** — per-run provenance, `GeneratedBy` on every duckbrain-produced dataset, seven checks in the cockpit |
| 2026-07-16 | #5c | **NORDIC versioning** — toolbox git provenance, MATLAB runtime axis (`container`/`container_source` → `runtime`/`code_source`), `toolbox-drift` / `matlab-drift` / `duckbrain-drift` checks, per-file NORDIC sidecars |
| 2026-07-16 | #5c | **NORDIC fork/rewrite: decided against** — upstream dormant, licence likely forbids it, a rewrite inherits a permanent validation burden |
| 2026-07-16 | #4 | **Naming/discovery** — `G##_S##` sessions, phantom/test-folder filtering, multiple-fieldmap-pair splitting (3 of 4; item 4 still open above) |
| 2026-07-16 | #5 | **Project-wide task mapping** — define once, inherit, override per-session; rules fix the *task* only, never the run |
| 2026-07-16 | #2 | **QUICKSTART + README written**; licensed GPL-3.0-or-later, tagged `v0.1.0` |
| 2026-07-16 | #6 | **Nipoppy bagel export REMOVED** — a write path with no reader whose version column came from config, not provenance |
| 2026-07-15 | #5b | **NORDIC producer + `use_nordic` → fMRIPrep chaining (Case 1)** validated live; fixed three latent bugs (m-file double path, Jinja `{#` collision, sessionless path) |
| 2026-07-15 | — | **MRIQC validated live** — fixed an OOM (`--mem-gb` decoupled from the cgroup alloc) and a surveyor false-green (func IQMs now required) |
| 2026-07-10 | #3 | **fMRIPrep validated live**; command matches mmmdata's `run_fmriprep.py` |
| 2026-07-10 | #6 | **Per-subject status matrix** (`core/surveyor.py`) — completion by expected-output globs, not folder presence |
| 2026-07-10 | #0 | **Pipeline cockpit built** — controller extraction, live-state fusion, cockpit UI, durable submission log |
| 2026-07-09 | #1 | **Folder picker reworked** — fragment-based, lazy, breadcrumb navigation |
| — | — | **DICOM→BIDS validated end-to-end** against canonical heudiconv output |
