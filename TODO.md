# duckbrain — TODO

**Open work only.** Closed items are a one-line ledger at the bottom. The detail
lives in `git log` (the commit message is the record), `CHANGELOG.md` for
anything user-facing, `docs/` for design, and `memory/` for validation findings.
Every design rule that still constrains new code is a comment on the code that
enforces it. See `PLAN.md` for the original design and `CLAUDE.md` for status.

**Item ids (`#4`, `#5b`, …) are stable names, not positions.** They're cited from
`CLAUDE.md`, `docs/`, and source comments, so they never get renumbered — the
list is ordered by priority and the ids stay put. A closed item keeps its id in
the ledger so an old reference still resolves. Sub-ids resolve to their parent's
row: a comment citing `#17.4` is answered by the `#17` ledger line, which covers
`#17.1`–`#17.10`. `★` is the provenance/consistency item, closed 2026-07-16.

**Open items, in priority order:**
[`#16`](#16) sanity checks (Slice A done; `#16.1`–`#16.3` open) ·
[`#13`](#13) browser validation · [`#15`](#15) BIDS validation ·
[Licensing](#licensing-follow-ups) ·
[`#18`](#18) type checking · [`#2`](#2) onboarding · [`#9`](#9) launch surface ·
[`#5`](#5) config edges · [`#10`](#10) template groups · [`#11`](#11) automation ·
[`#12`](#12) mmmdata-agents · [`#5b`](#5b) NORDIC Case 2 · [`#7`](#7) extra
stages · [`#8`](#8) branding · [Loose ideas](#loose-ideas-not-scheduled)

---

<a id="16"></a>
## #16 — Sanity checks: what we asked for vs. what we got

**Slice A shipped 2026-07-22** — a declared `[expected]` prescription plus the
cheap checks that read it (see the ledger). **Full design, prior-art verdicts and
the decisions that are settled: `docs/sanity-checks.md`.** Do not re-open the
boundary question or the Nipoppy/CuBIDS/mrQA verdicts without reading it.

What remains, in the order it should be built. Each is a slice because each has
its own commitment to weigh.

### `#16.1` — The request record (L2)

`submissions.tsv` carries tool *identity* only. Absent: `output_spaces`,
`nprocs`, `mem_gb`, `anat_only`, `use_derivatives`, `extra_flags`, the generated
BIDS filter path, `use_nordic`, SLURM resources. `script_path` makes them
*recoverable* by re-parsing an sbatch, which is not the same as recorded.

- Write `<log_dir>/requests/<job_id>.json` at launch and add a `request_path`
  column — mirroring `script_path` exactly, so this is a solved shape
  (`pipeline._migrate_log_header` already handles the column addition).
- Its first consumer: **requested `output_spaces` vs the spaces actually
  written** — impossible today because `surveyor._entity_key` strips `space-` and
  nothing else records the ask.
- Not a JSON blob column (keeps the TSV greppable), and not a stamp in the
  derivative tree (fMRIPrep/MRIQC overwrite their own `dataset_description.json`,
  which is why `consistency.py`'s source rule routes tool-produced derivatives to
  the log).

### `#16.2` — Outcome checks, and duckbrain's first cache

- Parse the fMRIPrep report for **SDC actually applied**. Complementary to
  `fmap-intent`, not redundant: that catches the *cause* from the sidecars before
  hours of compute; this catches fMRIPrep declining metadata that *is* correct.
- Others in the family: "reuse anat derivatives" actually reusing (the silent
  no-op closed 2026-07-20); NORDIC output actually differing from its input;
  MRIQC IQMs present for every func the surveyor counts complete.
- 🔴 **The commitment to weigh, and why this is its own item.** These need
  `Check.cost = EXPENSIVE`, which needs a cached, fingerprinted result — and
  duckbrain has *zero* caching today, with `surveyor.py`'s docstring advertising
  "no state store" as a virtue. Decided in principle (cache to
  `<log_dir>/checks.json` keyed on job id + newest input mtime, rendered with a
  staleness marker, recomputed by an explicit action; **not** a post-job hook,
  since jobs die, get cancelled, and run outside duckbrain). Decide it again with
  the code in front of you.
- The registry already carries the `cost` field so adding one is not a reshape;
  `test_no_expensive_check_is_registered_yet` is the tripwire.

### `#16.3` — An opt-in audit stage (mrQA, later CuBIDS)

Ben's suggestion, and a better home than this layer for external tooling. A
*different question*: heterogeneity **discovery** over the whole dataset,
occasional and deliberate — versus a per-unit **contract** check on the board.

- Costs almost no new architecture: both tools are batch, slow, whole-dataset and
  emit HTML, so it is a SLURM stage reusing `StageSpec`, `advance_one`,
  `submit_job` and the cockpit log viewers. Project-level action with a report
  link, not a matrix column.
- **mrQA first** — Apache-2.0, pip, light deps, reads DICOM *or* BIDS, and
  `--ref-protocol-path` is optional (it infers a reference by majority), so it
  works on `divatten_beta` with zero setup. Behind an optional extra
  (`duckbrain[audit]`); raise a clear "not installed" rather than skipping
  silently. 🔴 Last release 0.3, **April 2024** — pin it, keep it
  non-load-bearing.
- **CuBIDS later and container-only.** `datalad` is a hard dependency (wants
  `git-annex`, a non-pip system binary) and its pinned `numpy`/`pandas` upper
  bounds would fight streamlit. Never a pip dependency of duckbrain. Adds to the
  ~8.6 GB container problem under `#2`, so it must earn it.
- **PHI detection belongs here; PHI removal belongs to `#7.1`.**
  `cubids print-metadata-fields` is read-only and could report sidecars still
  carrying `PatientName`. `cubids remove-metadata-fields` mutates in place and
  must wait for `#7.1`'s PII policy — see the note there.

### Still-unhomed candidates

- **Cross-artifact agreement**, the family `fmap-pe-direction` (2026-07-21)
  started: TR / volume counts consistent across runs of one task.
- **Quality norms** — overlaps `#7.4` (MRIQC norms dashboard); fold them together
  rather than building two things.
- **Display-vs-reality**, inherited from `#17`. Every one of that item's ten
  findings was a display or a control, so none could be caught by tests asserting
  on returned values. The cheap general *defense* is already articulated by `#13`
  — **derive the display from the artifact that will actually be used, never
  re-derive it from the inputs**. Whether detection can be mechanized here at all
  is unproven; `#13`'s rule may be the whole answer.

**Why it's worth real effort:** the failure mode is the expensive one — not a
crash, but hours of compute producing derivatives that are quietly wrong,
discovered (if at all) long after. `CLAUDE.md`'s "a silently-degrading option is
worse than one that fails" is the same principle at the level of a single flag;
this is it applied to the pipeline as a whole.

**One migration lesson from `#17.2`, which generalizes here:** a setting that
never took effect was never tested by reality, so activating one is a
data-migration problem, not just a fix. duckbrain's shipped default partition was
`medium` — not a Talapas partition at all — and that was invisible for months
*because* the field was inert.

<a id="13"></a>
## #13 — Conversion legibility: browser validation

**Phases 1–7 shipped 2026-07-21 and granularity is settled (see the ledger).
What remains is the eyeball pass.** Full design in
**`docs/conversion-legibility.md`**.

- **UNVALIDATED in the browser.** Covered by unit + AppTest tests, but nobody has
  looked at it in the running GUI. The colour tokens in particular are only
  asserted as *strings*; whether the board reads well on a real session (and in
  the dark theme) is an eyeball question. Do it on `divatten_beta` — note the
  projects this used to name (`divatten_gui_beta`, `mmm_fmap_check`) were deleted
  with `#14`, and with them the two-pair case the view most exists to show. A
  session with two fieldmap pairs is worth re-converting from
  `/projects/lcni/dcm/hulacon/mmmdata/` before the eyeball pass, or the hardest
  case goes unlooked-at.
- **The anti-drift rule this hangs on**, and the reason the phases were built
  this way: the preview is derived **from the generated config dict**, never
  re-derived from the series list. Same stance `resolve_fmap_assignments` takes.
- **Drag-and-drop was considered and rejected** — reasoning recorded in the doc so
  it isn't re-proposed. Short version: bindings must persist across 37 subjects,
  which is what `[fmap_mapping]` already is; a gesture is per-session and would
  have to be re-expressed as that rule anyway.
- **Bidirectional table↔JSON sync was also rejected** — the table is *lossy*
  relative to the config (criteria beyond `SeriesNumber`, arbitrary
  `sidecar_changes`, custom ids, dcm2bids options), so a continuous round trip
  would drop them silently. The import is explicit, one-shot, and reports what it
  couldn't represent.

<a id="15"></a>
## #15 — Validate output against the BIDS standard, as a habit not a one-off

**Validation is on by default since 2026-07-21** (see the ledger). What's left is
the residue of the first run against `mmm_fmap_check`, plus one design option.

- 🔴 **The caveat that matters most: the validator did NOT catch `#14`.** Run
  against `mmm_fmap_check` while its sidecars still had the inverted
  identifier/source, it reported zero fieldmap issues. It checks structure and
  naming, not semantic intent. **Validation raises the floor; it does not catch
  the class of bug that has actually bitten us.** That caveat is the seed of
  `#16`; don't try to solve it inside this item.
- **`sourcedata/` DICOM symlinks get followed** and every `.dcm` reported as
  `NOT_INCLUDED`, with paths escaping the dataset root. May be a legacy-validator
  quirk (`sourcedata/` should be skipped); check against the v2 validator before
  adding a `.bidsignore` entry.
- **No `README`** — scaffolding doesn't write one, and BIDS recommends it.
- **No `Authors`** in `dataset_description.json`.
- **`events.tsv` missing** for task scans. Not duckbrain's to invent, but the
  scanning-notes item (`#7.3`) is where it would come from.
- **If plan-time validation is wanted later**, `bidsschematools` (pip) validates a
  *filename* against the schema without a dataset, which would let the Conversion
  Plan table be checked before a job is submitted. It can say whether
  `sub-001_task-x_run-1_bold.nii.gz` is legal BIDS; it cannot say that
  `div_perFace_r1` means task `divPerFace` run 1 — that inference is
  study-specific and is what duckbrain's heuristics are *for*. Complementary, not
  alternatives. `core/consistency.py` is where a wrapper fits.
- **Entity ordering may already be redundant.** dcm2bids reorders
  `custom_entities` per the spec unless `--do_not_reorder_entities` is passed, so
  `_fmap_description`'s manual acq/dir/run ordering might be doing work dcm2bids
  would do anyway. Harmless, but worth checking before adding more of it.

<a id="licensing-follow-ups"></a>
## Licensing follow-ups

- ⚠️ **Can Ben license duckbrain under GPL-3.0-or-later (employee-IP policy)?
  Asked; answered informally and encouragingly, but not by anyone who owns the
  question.** RACS said: *"We are not licensing or legal experts here, but it
  sounds like sharing the app within the university for academic use should be
  okay."* Record it as what it is — a friendly read from research computing, who
  explicitly disclaimed expertise.

  **Two gaps, and the second is the one that matters.** RACS answered *may this
  be shared*; the question was *who owns it and may Ben apply a licence to it* —
  employee-IP, which research computing does not administer. And the scope they
  blessed, "within the university for academic use", is **narrower than what has
  already happened**: the repo is public on GitHub under GPL-3.0 (verified
  2026-07-20), which is worldwide distribution to anyone for any purpose,
  including commercial. GPL grants rights RACS's sentence does not reach.

  **Practically this is low-risk and should not gate anything.** Open-sourcing
  academic research tooling under GPL is thoroughly ordinary, universities
  generally permit or encourage it, and the publication is already done — making
  the repo private again would not un-publish existing clones or forks. So the
  posture is: stop treating this as a blocker, and get a written answer from the
  office that actually owns IP (technology transfer / research innovation —
  Innovation Partnership Services is the likely one at UO — or General Counsel)
  when convenient. Ask them specifically about *public, non-academic-restricted*
  release, since that is the fact on the ground.
- **What RACS's answer does *not* touch: the copyleft question below.** That is
  licence *compatibility*, not permission — even with UO's blessing, GPL code
  still cannot land in Apache-2.0 or MIT projects without dual-licensing. The two
  items look adjacent and are independent; answering one leaves the other exactly
  where it was.
- The `surveyor.py` → mmmdata port is **blocked on the copyleft choice** — it
  would need dual-licensing to land in Apache-2.0 nipreps / MIT nipoppy
  territory. See `memory/licensing-and-versioning`.
- **`#12` (mmmdata-agents) hits the same wall and is the more likely one to be
  tried first.** That repo has no LICENSE file, so today there is nothing to
  reconcile duckbrain's GPL *against*. Give it a licence before, not after, any
  code moves between them.

<a id="18"></a>
## #18 — Static analysis: type checking, and widening the lint

The external review of 2026-07-22 is otherwise closed (see the ledger), as is the
CI work under `#18.1`. Two follow-ons, both deliberately deferred rather than
forgotten:

- **No `[tool.mypy]`.** Start on new and high-risk core modules —
  `conversion_plan`, `dcm2bids_config`, `consistency` — not repo-wide.
- **Widening ruff.** Bugbear, isort and pyupgrade have 59 findings between them
  (measured 2026-07-22); each wants its own commit, or the gate arrives as one
  unreviewable diff. `B905` (`zip(..., strict=)`) is the one with real
  bug-catching value; start there. The eight sites each need a judgment about
  whether the lengths must match.

**DB-002's fuller recommendation, deferred with a trigger:** a **persisted
expected-output manifest**, written at launch. Counting expected-vs-found covers
the reported failure and needs no state store, which the surveyor's docstring
names as a virtue. A manifest additionally catches only two things: a missing
output *space* (stripped by `_entity_key`, and overridable per launch, so the
filesystem holds no record of what was asked for), and config drift between runs.
**Revisit when per-launch `output_spaces` overrides become common.** Half of it
exists for free already — `nordic.write_nordic_sidecars` writes one sidecar per
intended run at launch, so NORDIC could be graded by "every sidecar has a
matching NIfTI" without inventing anything.

<a id="2"></a>
## #2 — Onboarding for external users

**The writing is done; the dogfooding and the distribution story are open. Do not
tick this off.** `QUICKSTART.md` and `README.md` are written and current.

- **`UNVALIDATED` — the new-user path on a clean account.** Flagged inline in the
  docs too. Nobody has walked: fresh `git clone` → venv → `pip install -e ".[dev]"`
  → tests pass; the three `singularity build` commands actually building on Talapas
  (and whether it's `apptainer` or `singularity` under current module policy); the
  exact config key set the Setup page emits matching the hand-written shapes in the
  docs; `scripts/launch.sh` srun flags under current partition/account policy; and
  personal-OOD-sandbox registration for a *new* user.
- **In-GUI guidance at friction points** (Setup, ingestion mapping, conversion) —
  needs a real walkthrough to know where the friction actually is.
- **Distribution story — needs RACS.** The OOD app is a personal sandbox today.
  Three candidates laid out but not picked in
  `QUICKSTART.md#the-distribution-question`.

### Second-user blockers, actually checked (2026-07-20)

Checked on-cluster rather than inferred, and it is **less blocked than this item
implied** — one assumed gate turned out not to exist, and the real cost is
elsewhere.

- ✅ **Getting the code is not a gate. The GitHub repo is PUBLIC** (verified
  against the API; GPL-3.0 detected). Notes previously said "private" — wrong.
  Which is what makes the licensing question above urgent rather than academic.
- 🔴 **Containers are the real blocker — ~8.6 GB and unshareable as things
  stand.** `/home/bhutch` is `drwx------`, so nobody can traverse to
  `~/containers` even though that directory is itself world-readable. And there
  is **no mutually-writable space** to stage copies into: `/gpfs/projects/hulacon`
  is `0770` (invisible to a non-hulacon user) and `/projects/lcni` is not
  writable by Ben (he is in `hulacon`/`psy607`, not `lcni`). So a second user
  either builds their own (needs a build node and time — the long-lead item) or
  Ben opens home traversal (`chmod o+x ~`, reversible, minimal, but it does make
  home traversable).
- 🔴 **OOD sandbox is NOT self-service — this likely needs RACS per user.** On
  OnDemand ≥1.6 creating `~/ondemand/dev` is not enough: an admin must also
  create a symlink under `/var/www/ood/apps/dev/<user>/` before the **Develop**
  menu appears at all. Sites can opt back into "everyone a developer"
  (`nginx_stage.yml`) or restrict it to a group, and **which Talapas does is not
  checkable from a login node** — `/var/www/ood` lives on the OnDemand web hosts.
  The maintainer's own sandbox working proves nothing either way (he is a PIRG
  admin). **Ask RACS.** If it is per-user-on-request, that settles the
  distribution question: if RACS has to touch every user anyway, publishing one
  shared app is strictly cheaper than N tickets. Written up in `QUICKSTART.md` §4
  Option B (with the `mkdir`/`ln -s` steps) *pending* that answer.
- **FreeSurfer license** — free, but per-user registration; not shareable.
- **SLURM account** — theirs, not Ben's. Feeds the OOD form's `bc_account`.
- **NORDIC constraint that shapes all of this:** the licence forbids
  redistribution and the PIRG root is `0770`, so every user must fetch their own
  toolbox copy and each will sit at a different SHA. Already the config shape. See
  `memory/nordic-versioning-and-licence`.
- **What already works in a second user's favour:** the config layering was built
  for exactly this — machine resources in the user config, study specifics in the
  project config, project dir as the anchor.
- **For a first meeting, don't do any of this.** Driving it yourself costs zero
  setup and answers "is this worth doing / what scope should it cover". Do the
  container prep only if hands-on-their-account is the actual goal, and *before*
  the meeting rather than during.

<a id="9"></a>
## #9 — Launch surface: one place to run, everywhere else prepares

**PUNTED 2026-07-20** pending more discussion + hands-on time in the GUI. Ben's
question was whether the non-dashboard pages should be config-only, with all
running done from the cockpit.

Assessment so far, to pick up from — the answer is *mostly yes, but not
uniformly*, because the redundancy is not evenly spread:

- **Preprocessing is almost pure duplication** of the cockpit and the best
  candidate. But deleting its Submit buttons leaves the page purposeless; the
  better move is to turn it into where you set **per-stage defaults persisted to
  the project config**, so the cockpit's one-click launch inherits them. That
  converts a redundant launcher into the thing that makes one-click *correct*.
  Overlaps `#10` — per-session template groups want the same persistence
  mechanism, so design them together rather than twice.
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

<a id="5"></a>
## #5 — Config / mapping niceties

Deliberate deferrals, each fine as-is — listed so they aren't rediscovered as bugs.

### The standing rule on messy source labeling: surface it, don't parse it

Validating `#4` against real exports showed how sloppy scanner-console labeling
gets — `MMM03_sess04CR`, `MMM_15_sess3.2`, `MMM_sub005_sess08`, `MMM_test002`,
`mmm0_230718`, and a `sess04` that means two different sessions for one subject.
**That is the experimenter's data-hygiene problem, not duckbrain's parsing
problem,** and the line is drawn here on purpose:

- **duckbrain accommodates a naming *form*** when it is a form — a regular
  pattern a study actually uses, e.g. the session-label qualifiers handled by
  `_SESSION_TOKEN_RE`. Cheap, and they prevent the dangerous failure: a real
  subject silently disappearing.
- **duckbrain does not chase one-off typos.** A folder the heuristics can't read
  gets a **Notes** entry in the ingestion table and an editable subject/session
  cell. Making a bad guess *visible and overridable* is the whole job; growing a
  parser branch per malformed folder is how the heuristics become unmaintainable
  and start misreading the well-formed ones.
- **So the fix for a study like mmmdata is upstream**, in how sessions are named
  at the console — or a one-time rename of the export. If a *pattern* emerges (not
  an instance), that's when it earns code.
- Parsed session labels are **not unique per subject**, so auto-numbering by date
  is the reliable path and the parsed labels are a suggestion. See
  `memory/validation-discovery-and-fieldmaps`.

### Accepted edges

- **`G##_S##` parsing is unit-tested only and stays that way.** No export on this
  filesystem uses it and it isn't expected to be common. Just **don't record it as
  live-validated**; close it for free if such an export turns up.
- **bold→fmap linking still has no temporal-proximity logic** — an *unbound* task
  goes to the first *complete* group; `_assign_fmap_group` never reasons about
  acquisition time. It can no longer pick a half group (an aborted lone AP), and
  since 2026-07-21 this is escapable rather than fixed: a project can declare
  `task -> group` outright in `[fmap_mapping]` (`FmapRule`, now with optional
  per-run granularity), which wins over the name-match heuristic and the
  first-group default. Inferring from timestamps stays a candidate refinement, and
  the explicit binding is the thing to measure it against. A rule naming a group a
  session lacks **raises**; see the silently-degrading rule in `CLAUDE.md`.
- **`se_epi_2.5mm_ap` reads as a named group `2.5mm`** — the resolution token
  becomes the group name. Harmless (divatten/PSY607 shoot one pair) and left
  alone on purpose: renaming it would change the `B0FieldIdentifier` of
  already-converted data for no functional gain.
- Task rules are dataset-wide; there's no per-subject *rule* scoping. Per-subject
  *edits* already cover the exception case.
- `directory_picker` is dirs-only; `fs_license` stays a text field. File-mode
  deferred until something needs it.

<a id="10"></a>
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
  assign units to a group, fall back to project defaults when unassigned.
- **There is already a pattern to follow, not invent.** Project-wide task mapping
  does exactly this shape one layer down — project-wide rules, per-session
  overrides, persisted read-modify-write into a `[task_mapping]` section
  (`save_project_task_map`). Template groups generalize it from "task labels" to
  "any default". Reuse the mechanism; don't grow a second one.
- **Open questions to settle first:** does a group override the *whole* section or
  merge key-by-key (merge, presumably — the same deep-merge the config layers
  already use)? Where does assignment live, the project config or per-unit? And
  does the surveyor need to know about groups, or is this purely a launch-time
  concern (probably the latter — completion is still completion)?
- **Design with `#9` together.** Same persistence mechanism, so designing them
  separately would build it twice.

<a id="11"></a>
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
  - **A periodic reconciler** (wake, survey, launch whatever is runnable) is **the
    better fit for this codebase.** duckbrain keeps no state store — every page
    re-derives what exists from the filesystem — which is exactly what a
    reconciler needs, and it self-heals after partial failures instead of
    stranding them.
- **The failure mode to design against is a resubmission loop.** A stage that
  always fails would be relaunched forever. Needs a retry cap and backoff, and a
  durable record of attempts per unit/stage — `submissions.tsv` is already that
  record. The no-double-submit guard exists (`stage_runnable` refuses a
  running/queued unit); the missing piece is "stop retrying a *failing* one".
- **Unresolved, and it gates the whole thing:** where does the driver actually
  run? Cron on a Talapas login node may be discouraged or disallowed — a RACS
  question, and the answer may push this toward a long-lived SLURM job or an
  OOD-launched daemon.
- Related but distinct from `#12`: a deterministic reconciler and an agent that
  decides what to run next are alternative drivers over the same core API.

<a id="12"></a>
## #12 — Merge with mmmdata-agents (exploratory)

**Captured 2026-07-20, Ben's idea.**
`/gpfs/projects/hulacon/shared/mmmdata/code/mmmdata-agents` is a Claude-powered
agent repo over the mmmdata dataset: a data agent (natural language BIDS
queries), a QC agent (MRIQC outliers), an orchestrator, and a tool registry under
`src/tools/` — `bids_tools`, `conversion_tools`, `manifest_tools`, `qc_tools`,
`slurm_tools`, `sourcedata_tools`.

- **The overlap is close to one-to-one**, which is the argument for merging rather
  than a second implementation: those tool modules map onto duckbrain's
  `core/surveyor.py` (inventory/status), `core/consistency.py`, `slurm/monitor.py`
  + `core/pipeline.py`, and the `core/` BIDS modules. mmmdata-agents even carries
  its own `pipeline_status_*.tsv` — the thing the surveyor exists to produce.
- **duckbrain is already shaped for this.** The core/GUI split means the useful
  surface is plain Python with no Streamlit in it (`survey_project`, `survey_live`,
  `stage_runnable`, `advance_one`, `check_consistency`). Backing agent tools with
  that core is mostly wiring, not redesign.
- **⚠️ Check the licence before any code moves** — see Licensing above.
- **Cheapest first step, if this proceeds:** point one existing agent tool at
  duckbrain's surveyor instead of its own status code, and see whether the
  abstraction actually fits before committing to a merge.

<a id="5b"></a>
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
- **Candidate affordance** (ties to `#2`): the Setup page validates containers
  exist; give NORDIC the same treatment — "toolbox not found → fetch pinned
  version", cloning upstream at a duckbrain-pinned SHA into the user's own space.
  Not redistribution (the user pulls from UMN) and it gives version uniformity.

<a id="7"></a>
## #7 — Pipeline extras: candidate stages (backlog, none started)

Each is its own focused effort. Full annotated backlog — candidate tools, ties to
existing duckbrain/mmmdata work, open questions per item — in
**`docs/pipeline-extras.md`**.

1. **De-identification for sharing — highest value.** Defacing **+** metadata/header
   PII scrubbing (DICOM headers *and* BIDS sidecars), "derive-then-torch" policy
   (age ok, name/DOB auto-removed). Candidate: `bidsonym`. *(The precomputed-mask
   fast-track is a different feature, deliberately deferred — see the doc.)*
   **Sequencing note:** an identity sanity check wants to run *immediately before*
   this — see Loose ideas. Once the headers are scrubbed, a wrong subject mapping
   can no longer be detected or proven.
   **The sidecar-scrubbing half has a candidate implementation, and it waits for
   this item on purpose:** `cubids remove-metadata-fields --fields PatientName`
   does exactly the BIDS-sidecar half. It **mutates sidecars in place**, so it
   needs this item's PII policy (age ok, name/DOB auto-removed, derive-then-torch)
   decided *first* — shipping a scrubber under `#16` would have fixed the
   mechanism before the policy, and it breaks the report-never-repair rule.
   Read-only *detection* (`cubids print-metadata-fields`) is `#16.3`'s, not this
   item's. Same reasoning that defers the identity check's mechanism to here.
2. **DTI/DWI preprocessing** — orthogonal modality branch (candidate: QSIPrep).
3. **Scanning-notes integration** — input-shaping producer (exclude bad runs via
   bids-filter/`scans.tsv`); reuse mmmdata `build_manifest`/`sessions.tsv`.
4. **QC norms & best-practice dashboard** — consumer of fMRIPrep+MRIQC; layer norms
   on the existing surveyor/QC pages.
5. **Physiological data as BOLD regressors** — downstream consumer (PhysIO/TAPAS →
   confounds); fMRIPrep ingests physio but doesn't compute RETROICOR.
6. **ReproIn** — **reading it is DONE** (2026-07-21): duckbrain parses the naming
   convention and trusts its entities over the heuristics, still converting with
   dcm2bids. What's left is the *social* half — recommending the convention to
   LCNI so exports arrive already carrying their entities, which is `#5`'s "fix it
   at the console" rule in concrete form. Open: does duckbrain also read the
   `ses-` entity (it currently takes session from the ingestion mapping), and is a
   ReproIn-named study worth acquiring as a test case.
7. **Eye-movement reconstruction from BOLD** (DeepMReye-style) — a branch fMRIPrep
   actively *fights* (brain extraction removes the eyes); opt-in "preserve eyes"
   path off raw/minimal data. Low demand, unique requirements.

<a id="8"></a>
## #8 — Visual identity & branding (someday)

Gated behind functionality + onboarding (`#2`); captured so it isn't forgotten.
Logo/wordmark that works small (favicon) and as a banner; a considered Streamlit
theme instead of defaults; favicon for the GUI tab and the OOD tile; README banner.
Tasteful, not over-designed, and after the product behavior is locked.

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

<a id="loose-ideas-not-scheduled"></a>
## Loose ideas (not scheduled)

- Cockpit: re-run of an already-*complete* stage behind an advanced toggle
  (deliberately excluded from `stage_runnable` today).
- The NORDIC column is always-on; for non-NORDIC projects it's a column of ⚪.
  Fine for LCNI/mmmdata, revisit if it reads as noise elsewhere.
- The QC metrics table doesn't carry a `current_decision` column. It renders
  before decisions are loaded, so showing it means reordering the page; the
  decision is visible in each run's expander header meanwhile. Cosmetic.
- **Re-add the Nipoppy bagel export** if Nipoppy takes off — but feed it from
  *provenance, not config*, which is the bug that made removal right. Verified spec
  preserved in `memory/nipoppy-status-tracking`; recover the code with
  `git show 9c3ab39:src/duckbrain/core/surveyor.py`.
- **Identity sanity check before de-identification.** Do the sessions mapped to
  one subject actually come from one person — same `PatientBirthDate`,
  `PatientID`, `PatientName`, consistent sex? A mismatch means the ingestion
  mapping is wrong, and the value is in *when* it runs: **before** the
  de-identification step of `#7.1`, because that is the last moment the
  identifying fields still exist. "Derive-then-torch" means a mis-assignment
  found afterwards is unprovable and possibly unfixable.
  - **The hook exists:** `bids_metadata.read_dicom_demographics` already opens a
    DICOM per session for `PatientSex`/`PatientAge`. This is the same read
    widened to identity fields and compared *across* the sessions of a subject.
  - **It's the natural successor to the ingestion Notes column** (`#5`), which
    flags a suspect mapping from folder *names*. This checks the same question
    against the DICOM headers, which are much harder to get wrong by hand.
    mmmdata's duplicate `sub-003/ses-sess04` is exactly the shape it would catch.
  - **Design caution, agreed and deliberately not settled here:** report, don't
    block, and never write the identifying values into any durable artifact —
    that would defeat the de-identification it guards. Comparing hashes rather
    than values is the likely shape. **The mechanism gets decided when the formal
    anonymization layer of `#7.1` is built**, so it falls out of that layer's PII
    policy rather than being fixed early by a check that has to live alongside it.

---

# Closed

One line each. Detail is in `git log` (the commit message is the record),
`CHANGELOG.md` for anything user-facing, `docs/` for design, and `memory/` for
validation findings. Design rules that still bind live as comments on the code
that enforces them — the provenance source rule in `consistency.py`'s module
docstring, the BEP028 sidecar warning in `core/nordic.py`, the task-vs-run rule in
`core/dcm2bids_config.py`.

| Done | Id | Item |
|---|---|---|
| 2026-07-22 | #16 | **Sanity checks, Slice A — a declaration the data can't quietly agree with.** Ben's reframing is what the item turned on: *codifying intent is different from cataloguing what has been done*, and duckbrain was entirely the latter — every expectation in the codebase is re-derived from the data it judges, so a shortfall shrinks the expectation to match and reads COMPLETE. New `[expected]` project-config section (roster + per-session contents + `[expected.exceptions]`), `core/expectations.py`, `core/checks.py` with a cost-aware registry, rendered in the cockpit's existing panel. **Absent means off** — opt-out is the default and has its own test. Elicited from a good session then frozen (BIDScoin's study-bidsmap bootstrap); `elicit` deliberately never proposes the roster, the one thing disk can't know. Validated live on `divatten_beta`: with a task's BOLD and a fieldmap direction removed from a scratch mirror, `survey_project` still read **complete** for all five subjects while the checks caught both — the contrast is pinned by `test_surveyor_still_reads_complete_when_a_run_is_missing`. Live validation also found a real bug: zero has to be a *declaration*, or "this subject has no resting run" is unrecordable. Prior art surveyed and refused deliberately (Nipoppy's manifest borrowed as a shape, CuBIDS never a pip dep, mrQA out of scope) — `docs/sanity-checks.md`. `#16.1`–`#16.3` stay open |
| 2026-07-22 | #14 | **Inverted fieldmap intent — data cleanup done, and the detector that makes it self-reporting.** The cleanup resolved by *deletion*: the three affected projects were removed, and the one live project (`divatten_beta`, converted after the fix) verified correct in both directions including SBRefs. No fMRIPrep derivative anywhere had been built from inverted data, so the expensive re-run half never arose. The durable half is `fmap-intent` in `core/consistency.py`, deliberately **wider than the original bug** — a *dangling* `B0FieldSource` that no fieldmap declares fails identically and silently, so it is caught too, and the check runs over the NORDIC `bids_input` tree as well as raw BIDS. Validated both ways against real data: silent on `divatten_beta`, and it fires on that same subject's sidecars re-inverted to the pre-fix shape |
| 2026-07-22 | #18.1 | **Quality gates** — CI on Python 3.10/3.12 (import check + `compileall`, `ruff check`, `ruff format --check`, `pytest --cov`), ruff/coverage/pytest config in `pyproject.toml`, coverage floor 60% as a ratchet. The narrow first ruleset found two real bugs. Type checking and wider lint stay open under `#18` |
| 2026-07-22 | #18 | **External code review answered** (`docs/code-review-260722.md`, DB-001…DB-012) — every finding fixed with a regression test or given a written reason to stand. Two findings were already fixed by `#17.5`–`#17.10` and one half-fixed; **two of its claims were wrong** and were checked rather than actioned; and it missed a regression its own subject introduced (a collision check comparing `target.resolve()` to the source, meaningless for a copied directory). An audit is not uniformly right |
| 2026-07-22 | #17 | **GUI/config drift audit — `#17.1`–`#17.10` all closed.** One bug class: the computation is correct and the interface describes it wrongly, or a control looks live and isn't. Invisible to the whole suite, since nothing asserted on what is *displayed*, and every one exited 0. Each fix is pinned by a test **checked to fail against the old code**. `#17.1` was reopened once by `#18`/DB-001 — a closed item can be half-closed |
| 2026-07-22 | #17.2 | **SLURM partition fields reach jobs** — stages declare a *role* (`long = true`) instead of naming a partition. Exposed a second bug it had been hiding: the shipped default `medium` **is not a Talapas partition**, invisible for months *because* the field was inert. Every project set up before 2026-07-22 carries it; Setup now validates against `sinfo` |
| 2026-07-21 | #13 | **Conversion legibility phases 1–7 shipped** — `core/conversion_plan.py`, the Conversion Plan section, the "which pair corrects which run" view, one unified table, explicit one-shot JSON back-import. Granularity settled: bindings attach at series/run level (`FmapRule.run`), existing `[fmap_mapping]` unchanged. Browser validation still open under `#13` |
| 2026-07-21 | #15 | **BIDS validation on by default** — dcm2bids' own `--bids_validate`, and bids-validator 1.14.6 already ships inside `dcm2bids-3.2.0.sif`. Nothing to install. Also fixed: `.bidsignore` missing `tmp_dcm2bids/` (a phantom subject inferred from dcm2bids' own log), and `PhaseEncodingDirection` no longer overwritten from the `_ap`/`_pa` token — the header wins, disagreements are flagged by the new `fmap-pe-direction` check. Resolved: `_sbref` does **not** require `TaskName` |
| 2026-07-21 | #4 | **Discovery + fieldmaps live-validated** on real LCNI exports — **item fully closed**; five bugs real data found: reacquired *named* fmap pairs silently discarded, qualified session labels adopted as the subject, `PermissionError` on an unreadable folder, bolds linking to a half fmap group, nested sources finding nothing. Two-pair conversion verified end to end. Accepted edges moved to `#5` |
| 2026-07-21 | #4 | **Nested multi-session sources** (mmmdata's `func_session_*/` protocol folders) — one-level descent, fallback-only so the flat path is untouched; duplicate sub/ses labels flagged. Closes the deferred "`#4` item 4" (`docs/handoff-cluster-session.md`) |
| 2026-07-20 | #9 | **Top nav + recent-projects MRU** — declarative `st.navigation(position="top")`, sidebar freed, project bar with a Switch popover; fixed a relative import that had silently broken the project indicator under `streamlit run` |
| 2026-07-20 | #0 #1 | **Browser eyeball pass** — dashboard table width reads well at project scale; folder picker fine as-is. Generated `#9` |
| 2026-07-20 | — | **fMRIPrep anat-reuse gated + self-overlapping bind dropped** — reuse was a silent no-op when there was nothing to reuse; `has_anat_derivatives()` now gates it in `_build_fmriprep` (API *and* GUI) |
| 2026-07-17 | #0 | **Cockpit usability pass** — three stacked blocks became one actionable board; cells *are* the controls, per-cell job reference + cancel/re-run |
| 2026-07-17 | #0 | **Job Monitor page retired**, folded into the cockpit as the "All SLURM jobs" panel; new `cancel_job()` / `find_job_logs()` |
| 2026-07-17 | #2 | **MRIQC default pinned `24.0.2`** — the old `24.1.0` default was never a real Docker tag, only the container's self-report |
| 2026-07-17 | #5 | **BIDS task-label sanitizing** — `resting_test` → `restingTest` at the entity boundary, GUI warns on rewrite |
| 2026-07-16 | ★ | **Provenance recording + consistency checker** — per-run provenance, `GeneratedBy` on every duckbrain-produced dataset, seven checks in the cockpit |
| 2026-07-16 | #5c | **NORDIC versioning** — toolbox git provenance, MATLAB runtime axis (`container`/`container_source` → `runtime`/`code_source`), `toolbox-drift` / `matlab-drift` / `duckbrain-drift` checks, per-file NORDIC sidecars |
| 2026-07-16 | #5c | **NORDIC fork/rewrite: decided against** — upstream dormant, licence likely forbids it, a rewrite inherits a permanent validation burden |
| 2026-07-16 | #4 | **Naming/discovery** — `G##_S##` sessions, phantom/test-folder filtering, multiple-fieldmap-pair splitting (built offline; live-validated and corrected 2026-07-21) |
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
