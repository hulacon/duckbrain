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
[`#13`](#13) conversion legibility (browser validation; `#13.1` open) ·
[`#15`](#15) BIDS validation ·
[Licensing](#licensing-follow-ups) ·
[`#19`](#19) conversion coverage ·
[`#22`](#22) wire up the dcm2niix probe ·
[`#24`](#24) QC review domains (A + C done; B dropped; D–E open) ·
[`#23`](#23) `st.components.v1.html` past removal date ·
[`#21`](#21) fsaverage race ·
[`#18`](#18) type checking · [`#20`](#20) conda environment ·
[`#2`](#2) onboarding · [`#9`](#9) launch surface ·
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
## #13 — Conversion legibility: browser validation, and an editable Type

**Phases 1–7 shipped 2026-07-21 and granularity is settled (see the ledger).
What remains is the eyeball pass, plus `#13.1` below.** Full design in
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

### `#13.1` — An editable `Type`, if it can be made honest

**Captured 2026-07-24, Ben's question thinking about a naive user** — no live
misclassification prompted it. Today `Type` is read-only and the only way to
correct one is the hand-edited JSON override.

- **Unlocking the column is one line and would be a bug.** Drop `"Type"` from
  `_locked` (`3_BIDS_Conversion.py`) and the edit half-applies: the page builds
  `edited_mapping` and `session_fmap_rules` off `row["Type"]`, but `generate_config`
  dispatches on `SeriesInfo.classification`, and nothing writes the column back
  onto `series_list`. Task/run and the bindings would follow the new type while
  the emission followed the old one. Writing it back is mechanical — the honest
  part is below.
- **The datatype alone under-determines the output, so the control is not a
  datatype dropdown.** `func`→`bold` and `sbref`→`sbref` are fixed, and nothing
  else is: `_anat_description` picks the suffix from the *name* vocabulary
  (`t1`/`t2`/`mprage`/`flair`) and falls back to `suffix_hint` — **and returns
  `None` when neither fires, dropping the series**. So relabelling `food_r1` as
  anat writes no file and says nothing, which is the failure the feature exists
  to prevent, reintroduced by the feature. `fmap` is worse: `_fmap_description`
  only emits for series `detect_fieldmaps` already grouped, so a manual label
  creates no pair. And `dwi` has no emission path at all (`#19.1`).
- **So: datatype+suffix (`anat/T1w`, `fmap/epi`) as a `SelectboxColumn`,
  restricted to combinations that actually emit, and anything unhandled raises.**
  The silently-degrading rule in `CLAUDE.md` is the whole difficulty here, not an
  afterthought.
- **Per-session is the wrong grain.** A table edit reaches conversion only
  because the page saves `dcm2bids_config.json` before `advance_one` and
  `_build_dcm2bids` reuses it; bulk convert and the cockpit re-derive through
  `generate_session_config` ("no manual edits"). A scanner label duckbrain
  misreads is misread for every subject, so this wants a project-level section
  read by `classify_series` as a tier above header and name — same read-modify-write
  shape as `save_project_task_map` / `save_project_fmap_map`, and the same
  argument `docs/conversion-legibility.md` makes for keeping bindings declarative.
- **Check first whether the case is a classifier bug.** The `Type from` column
  (added 2026-07-24) now says `header` or `name`; a wrong `header` verdict is a
  bug to fix at the source, and the override is for what no rule can reach.
  `memory/header-based-classification` is the record of that distinction.
- **Adjacent and unbuilt: there is no exclude/skip control either.** A series is
  dropped only implicitly, by classifying as `scout`/`physio`/`derived`. If the
  Type control is built, "don't convert this" is arguably one of its values —
  decide that deliberately rather than discovering it.

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

<a id="22"></a>
## #22 — The dcm2niix probe: wire it into the Conversion page

**The probe itself landed 2026-07-24** (`core/dcm2niix_probe.py`, ledger row), and
`plan_warnings` takes an optional `probes=` and grows two checks from it. What is
open is the last mile: **nothing calls it yet**, so the checks are dead code in
practice. Read the module docstring first — it carries the measurements, and they
are the reason the shape is what it is.

**The one-line case for it.** `dicom_header` normalises the two Siemens dialects
by hand, and the two fields the conversion plan most wants are ones it cannot
reach at all: the *signed* phase-encoding direction (the raw tag is `ROW`/`COL`
with no polarity, and absent on XA30) and `ShimSetting`. dcm2niix has both, is
the tool that will do the conversion anyway, and is Chris Rorden's to maintain.

**Cost is settled, and it is the objection people will raise first.** `dcm2niix
-b o` over a session *directory* is 90 s for REV055 — 2155 files, 2.5 GB, and 1.2 s
of that is CPU. One file per series is enough, so the probe stages a directory of
symlinks and makes a single call: **0.15 s warm, 0.7 s cold, per session**, host
or container. Validated one-file-vs-whole-series on REV055 at 259/272 key/value
pairs identical, every difference confined to multi-echo GRE fieldmaps and
sub-second `AcquisitionTime` jitter.

Open work, in order:

- **Call it from `3_BIDS_Conversion.py`** and pass `probes=` into `plan_warnings`.
  Resolve the container from `containers_dir` + the `dcm2bids_version` pin —
  **prefer the container over a host `dcm2niix`**, because it holds the same build
  that will convert, so the preview cannot disagree with the result for a reason
  duckbrain can't see. (Verified identical on REV055: same v1.0.20240202, zero key
  differences, +0.2 s of apptainer startup.)
- **Say when it didn't run.** `probe_unavailable_reason()` exists for exactly
  this and currently has no caller. A skipped check that renders as a clean panel
  is the silently-degrading behaviour `CLAUDE.md` forbids, and it is the specific
  way this item could ship broken.
- **Cache per session** keyed on the session directory + its newest mtime. 0.7 s
  is fine once and not fine on every Streamlit rerun. Note this is the same
  shape `#16.2` needs and has been deferred twice — if that cache gets built
  first, use it rather than adding a second one.
- **The bulk/SLURM path too.** It skipped `plan_warnings` entirely once already
  and submitted the collisions the GUI refused (2026-07-24 ledger). Same trap.

Not in scope, deliberately: replacing anything in `dicom_header`. The probe reads
one file, so it cannot count volumes or see a second echo — which is precisely
what `dicom_header`'s three-file read exists to do. They are complementary, and a
migration would trade a validated classifier for an unvalidated one.

<a id="21"></a>
## #21 — The shared `fsaverage` race: N concurrent fMRIPrep jobs, one SUBJECTS_DIR

**FIXED 2026-07-27 — `core/fsaverage.py`, wired into `advance_one`.** duckbrain
installs every `fsaverage*` template fMRIPrep will want *before* it submits, so
each job finds the directory present and the FreeSurfer-7 sentinel present and
takes neither the `rmtree` nor the copy branch. Completeness is judged against
the container's manifest (312 files for `fsaverage`, 109 for `fsaverage6` in the
24.1.1 image), never against the sentinel — see below for why that distinction is
the fix rather than a detail. Pinned by `tests/test_fsaverage.py`, including the
exact `divatten_beta_v2` shape. The rest of this item is the record of what was
wrong and stays because the reasoning is not re-derivable from the code.

**Flagged by LCNI (2026-07-24) from their own runs, then traced to the code in the
24.1.1 image on disk. duckbrain has this exposure today** — it is not something
the FreeSurfer-8 plan (`#7` item 7) would introduce, though that plan makes it
sharper.

**Observed locally 2026-07-27 on `divatten_beta_v2`, and it took out 4 of 5
subjects.** All five jobs (`45644650`–`45644654`) started within one second of
each other, which is the precondition at its worst. `sub-010` finished; `sub-011`
through `sub-014` all died at `recon-all` with

```
ERROR: Label BA1_exvivo does not exist in SUBJECTS_DIR fsaverage!
       The fsaverage link probably points to an older freesurfer version
```

**It is not the `FileExistsError` branch below, and it is worse than it.** Zero
jobs logged `exists; if multiple jobs are running in parallel`. The destroyer is
an `rmtree` a few lines *above* that `try`, which the excerpt below originally
omitted:

```python
if space == "fsaverage" and dest.exists() and self.inputs.minimum_fs_version == "7.0.0":
    label = dest / "label" / "rh.FG1.mpm.vpnl.label"  # new in FS7
    if not label.exists():
        shutil.rmtree(dest)  # <-- deletes a copy that is still in progress
```

fMRIPrep always passes `minimum_fs_version='7.0.0'` (`fmriprep/workflows/base.py`),
so this branch is armed on every run. Job A creates `fsaverage/` and begins
streaming 312 files into it. Job B arrives inside that window, sees `dest.exists()`
is true, looks for the FreeSurfer-7 sentinel `rh.FG1.mpm.vpnl.label` — which A has
not written yet — concludes the tree is a stale FreeSurfer-6 copy, and **deletes it
out from under A**. Both then write into the same path and the result is a merged,
permanently incomplete tree. No exception is raised anywhere, so nothing appears in
any log.

Measured on this filesystem 2026-07-27, copying from the 24.1.1 image to
`/projects/hulacon/bhutch`: a clean `fsaverage` copytree is **312 files / 261 MB
in 1.83 s**, and the sentinel lands at **+0.39 s**. So the window splits in two —
arrive before +0.39 s and you *destroy* the tree; arrive between +0.39 s and
+1.83 s and you skip both the `rmtree` and the copy (`if not dest.exists()`) and
start `recon-all` against a tree that is only partly there. Either way the damage
is silent and does not surface until `recon-all`'s BA_exvivo stage, which here was
**~3 hours later**. `divatten_beta_v2` ended up with 259 of 312 `fsaverage` files —
53 missing, including `lh.BA1_exvivo.label`, which is exactly what the error names.
`fsaverage6` came through complete (109/109).

FreeSurfer's error text blames a stale version link. That is wrong and sends you to
the wrong place.

**The broken tree is sticky, and this is the part that bites twice.** It *does*
contain `rh.FG1.mpm.vpnl.label`, so the self-repair branch above will never fire
again: every future fMRIPrep run on this project reuses the incomplete `fsaverage`
and fails identically. Re-submitting without first deleting
`sourcedata/freesurfer/fsaverage` cannot work.

**Staggering submissions is the wrong fix.** The window is ~2 s, but the quantity
you would have to stagger against is the *spread in when jobs reach the copy*,
which is fMRIPrep's workflow-build time — 61 s in this run (18:33:33 submit →
18:34:34 copy) and dependent on BIDS indexing, node load and container cold-start.
Two jobs launched a minute apart can still collide; you cannot bound the variance,
so any fixed delay is a probabilistic dodge of a failure that is silent, sticky and
three hours deferred. **Pre-populate instead:** copy `fsaverage` and any
`fsaverageN` in `--output-spaces` into `<derivatives>/fmriprep/sourcedata/freesurfer/`
once, before submitting anything. Every job then takes the "present, sentinel
present" path — no `rmtree`, no copy, no window. `overwrite_fsaverage` defaults to
False and fMRIPrep never sets it, so this is stable. That is the fix to build:
a pre-flight in the bulk-submit path, not a `--begin` offset.

Two things this run showed that are **not** explained and should not be assumed
to be this race: `sub-010` exited 0 but never ran `recon-all` (it has no entry
under `sourcedata/freesurfer/`) and produced only minimal-level output — no
confounds, no `space-MNI152NLin2009cAsym` or `fsaverage6` resampling — despite
`--output-spaces MNI152NLin2009cAsym:res-2 fsaverage6 func` and no `--level` flag.
Net effect across the project: **zero** `*_desc-confounds_timeseries.tsv` files,
so the QC dashboard had no fMRIPrep input at all (see `#7.4`).

**The second mechanism, read from
`niworkflows/interfaces/bids.py::BIDSFreeSurferDir`** — real, but *not* what was
observed above, and the milder of the two. At the start of *every* fMRIPrep run it
copies `fsaverage`, and any `fsaverageN` in `--output-spaces`, from
`$FREESURFER_HOME/subjects` into SUBJECTS_DIR. The copy is check-then-act:

```python
if not dest.exists():
    try:
        shutil.copytree(source, dest, copy_function=shutil.copy)
    except FileExistsError:
        LOGGER.warning(
            "%s exists; if multiple jobs are running in parallel, this can be safely ignored", dest
        )
```

Two jobs both see `dest` missing and both start copying. The loser raises
`FileExistsError`, **which is caught and downgraded to a warning whose text tells
you to ignore it** — and then proceeds while the winner is still copying. In FS
8.2.0 `fsaverage` is 482 MB and `fsaverage6` 113 MB, so the window is seconds to
minutes on GPFS, not microseconds. The loser's downstream `mri_surf2surf
--trgsubject fsaverage6` then reads a half-populated tree, so the failure surfaces
somewhere else entirely and the one log line that would explain it says to ignore
it. 🔴 **Two paths in the same function are worse**: `overwrite_fsaverage`, and a
staleness check keyed on an FS7-era label, both `shutil.rmtree(dest)` — deleting
fsaverage out from under jobs currently reading it.

**Why duckbrain is exposed right now.** Four things, all true today: every unit's
fMRIPrep writes to the same `<derivatives>/fmriprep`; `fs_subjects_dir` defaults
to `<output_dir>/sourcedata/freesurfer` (`fmriprep/cli/parser.py`), so **one
SUBJECTS_DIR is shared by every concurrent job**; the shipped default
`output_spaces` includes `fsaverage6`; and the cockpit's column-header bulk
submits every runnable unit at once. It has likely just never been run at the
scale that triggers it — the projects that held fMRIPrep derivatives were deleted
under `#14`.

**This is the third instance of one bug shape, and duckbrain already fixed the
first.** The TemplateFlow race in `templates/sbatch/fmriprep.sbatch.j2` is the
same thing down to the exception type, fixed by giving each job its own
`SINGULARITYENV_TEMPLATEFLOW_HOME` under `$WORK_DIR`. **That fix does not transfer
here**: TemplateFlow is a pure cache, so isolating it costs nothing, whereas
SUBJECTS_DIR holds the recon outputs whose whole value is being shared and reused.
Per-job isolation would close the race by throwing away the feature.

**The fix: seed once, before fan-out.** Copy `fsaverage`/`fsaverage5`/`fsaverage6`
into the shared SUBJECTS_DIR serially, then submit. Every job's
`BIDSFreeSurferDir` then sees `dest.exists()` and skips the copy entirely — the
window closes because nobody races. `_build_fmriprep` is the right home: it
already does synchronous filesystem prep at submit time
(`build_nordic_bids_input`, `write_session_filter`), and the cockpit's bulk loop
runs in a single process, so the first unit seeds and the rest no-op. Small and
contained.

- 🔴 **Seed from inside the fMRIPrep container (`$FREESURFER_HOME` in the `.sif`),
  not from the FreeSurfer 8 module.** The two trees differ, and the staleness
  check's failure mode is a destructive `rmtree` under concurrency. Checked: FS
  8.2.0's `fsaverage` *does* carry `label/rh.FG1.mpm.vpnl.label`, so seeding from
  it would not trip that path today — but that is luck, not a guarantee, and
  copying from the image gives exactly what fMRIPrep would have produced itself.
- **Add a check, not just a fix.** This is `#16`'s shape: a cheap consistency check
  that every `fsaverageN` named in `output_spaces` exists in SUBJECTS_DIR and is
  complete before a bulk launch. The failure it guards is one whose only symptom
  today is a log line advertising itself as ignorable.
- **Ties to `#7` item 7:** an external FreeSurfer 8 stage makes a shared
  SUBJECTS_DIR the entire point *and* adds a second writer to it, so seeding stops
  being a nicety and becomes a precondition of that plan.

<a id="20"></a>
## #20 — Ship a conda environment, not a `.venv`

**Asked for by RACS and LCNI** (relayed 2026-07-24). It is the same institutional
argument as `#2`'s distribution question: conda is what neuroimaging users on
Talapas already have and what RACS supports, `module load miniconda3` needs no
build node, and `environment.yml` pins the *interpreter* as well as the packages
— which `pip install -e ".[dev]"` cannot, so today a new user's Python version is
whatever `python3` happened to be.

**Checked on-cluster 2026-07-24, before designing anything.** Four findings, two
of which change the shape of the work:

- 🔴 **`~/.condarc` is FSL's, and it is hostile.** The `fslinstaller` wrote it and
  says in the file that it *rewrites it without warning*. It pins
  `channel_priority: strict` with the FSL channel `#!top` and conda-forge
  `#!bottom`, and pins `pkgs_dirs` to the read-only `/packages/fsl/.../pkgs` — all
  marked `#!final`, so a lower-priority condarc cannot override them. This is not
  a local quirk: **any user who ran `fslinstaller` has it**, which on an fMRI
  cluster is most of them. So the env file must carry
  `--override-channels -c conda-forge` semantics explicitly, and setup docs must
  set `CONDA_PKGS_DIRS`. The first `conda env create` on a stock account will
  otherwise resolve against FSL's channel and fail to write its package cache.
  Also note `conda` on a bare `$PATH` here is *FSL's* conda, not a module's.
- 🔴 **`ruff>=0.16,<0.17` does not exist on conda-forge** — it tops out at
  0.15.22. That pin is a deliberate gate (see the comment on it in
  `pyproject.toml`: unpinned, CI re-resolves the formatter and the same commit
  goes red with nothing changed). So the dev extra **must** stay pip-installed
  inside the conda env; conda cannot own the whole dependency set. Don't
  "simplify" this away by relaxing the pin — that re-opens the bug the pin closed.
- ✅ **Every runtime dependency solves cleanly from conda-forge on Python 3.11**,
  verified by dry-run solve, and at essentially the versions the working `.venv`
  already has: streamlit 1.60.0 (venv 1.59.1), pandas 3.0.3 (same), nibabel 5.4.2
  (same), pydicom 3.0.2 (same), plotly 6.9.0 (venv 6.8.0), jinja2 3.1.6, tomli-w
  1.2.0. So there is **no version-jump risk** — this is a packaging change, not a
  dependency upgrade, and it should be kept that way.
- ✅ Modules available: `miniconda3/20260319` and `miniconda3/20240410` (the
  module's own `conda` is 23.11.0). `mamba`/`micromamba` are **not** on `$PATH`.

**`neuroconda3` is not reusable — build a fresh one.** The existing env
(`~/.conda/envs/neuroconda3`, Python 3.10.15, 359 packages, 2.2 GB) was created
2024-10-08 for the mmmdata era and is missing four of duckbrain's eight runtime
deps (streamlit, plotly, tomli-w — plus ruff). It carries a lot duckbrain never
uses (gtk3, graphviz, nipype, h5py, dcm2niix), the `conda env create` source file
it was built from (`~/tmp/neuroconda-20241006.yml`) **is gone**, so it is not
reproducible except by `conda env export`, which would pin 2024 builds. And it
lives under `~/.conda` — personal, un-shareable, which defeats the point.
Its one useful property: it still imports fine, so it is a working fallback while
this is built, not something to delete in a hurry.

The work, then:

- Add `environment.yml` (name `duckbrain`, conda-forge only, `python=3.11`, the
  runtime deps) with a `pip:` section for `-e ".[dev]"` — which is what pulls the
  pinned ruff and duckbrain itself. One file, and `pyproject.toml` stays the
  single source of the dependency list as far as possible.
- Decide **coexist or replace**. Coexisting is the cheap, honest answer:
  `scripts/launch.sh` and `ondemand/template/script.sh.erb` already probe for
  `.venv` and fall through, so they gain a conda branch ahead of it and nobody's
  working checkout breaks. `#2`'s `UNVALIDATED` new-user walk should then be
  walked on the **conda** path, since that becomes the documented one.
- Decide **where the env lives**. `~/.conda/envs` is per-user and invisible to
  others (`/home/bhutch` is `drwx------` — the same wall `#2` hit with the
  containers). A shared `--prefix` under `/projects/hulacon/shared` would let one
  build serve the PIRG, and there is no shared env there today. That is a
  distribution decision, not a packaging one, and it belongs with `#2`.
- CI (`.github/workflows/ci.yml`) is a separate call: GitHub runners have no FSL
  condarc and pip works fine there, so switching CI to conda buys little and
  costs solve time on every push. Leaving CI on pip while users get conda means
  the gate no longer tests the path users take — say which trade-off was taken,
  in the commit.
- Update `README.md`, `QUICKSTART.md` and `CLAUDE.md` together; five places
  currently instruct `python -m venv .venv`.

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
- **bold→fmap linking binds by acquisition time** (since 2026-07-24, `#19.3`) —
  an unbound task goes to the complete group it was acquired *nearest in time*,
  not the first one. This bullet asserted the opposite for three days after the
  change landed; the ledger row and `memory/fieldmap-binding-and-heudiconv` are
  the record. A project can still declare `task -> group` outright in
  `[fmap_mapping]` (`FmapRule`, with optional per-run granularity), which wins
  over the name match, the timing, and the first-group fallback. A tie falls
  through to first-group, which is what a session shooting two pairs
  back-to-back hits — that residue is `#19.3`, and it belongs with `#16`'s
  `[expected]` rather than a heuristic. A rule naming a group a session lacks
  **raises**; see the silently-degrading rule in `CLAUDE.md`.
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
   on the existing surveyor/QC pages. **Scoped 2026-07-24 and ready to execute —
   full plan in `docs/qc-dashboard-migration.md`.** mmmdata built and vetted the
   layer this item describes: a registry of 30 measures, each stating why it is
   shown, what a human should check by eye, what is flagged automatically, and
   its source — 29 citations verified against MRIQC/fMRIPrep/AFNI source rather
   than common practice, which is how it establishes that most IQMs have **no**
   defensible absolute cutoff. It moves here because that claim is untestable in
   a single-project repo, and because this item's own "group-level IQM
   comparison" only becomes answerable in a multi-project tool.
   Three independently-mergeable slices: the registry plus a `[qc]` config
   section, the report renderer plus its embed, then the decision model.
   **Slice 1 landed 2026-07-24** on `qc-guidance-migration`, and the plan's
   "cannot be verified without data" table was worked first, against 717 real
   MRIQC JSONs across both projects: the registry was right about every content
   question it raised, so nothing needed correcting on the way in — `tpm_overlap_*`
   is what MRIQC really writes (its *docs* are the stale side), and `fd_perc`
   counts frames at 0.2 mm in **65/65** runs and at no other threshold, which is
   what makes the Parkes 20% rule citable. Real output is now committed as
   `tests/fixtures/mriqc/` with identifiers stripped, so a wrong key name fails a
   test instead of rendering a blank column. **Two findings for the later slices:**
   mmmdata's dashboard carries 837 absolute `file:///` links, every one of which a
   browser blocks from an HTTP page — Slice 2 must emit relative paths or the
   "View report" link is a silent no-op under OnDemand; and all **609** decision
   records in mmmdata are machine-written `auto-stub`/`keep` with zero human
   sign-offs, which is Slice 3's whole case.
   **Slice 2 landed 2026-07-24**: the renderer is `core/qc_report.py`, page 5 is
   wiring only, and links are relative rather than `file://`. Two corrections to
   the plan, both in the doc — the `fmriprep_dir`/`use_nordic` "fix" would have
   *created* a bug (duckbrain has one fMRIPrep tree, not mmmdata's two, so
   branching on `use_nordic` points at a directory that never exists; the real gap
   was that nothing told the reviewer which variant the motion numbers came from,
   and that is now read from provenance) — and `load_mriqc_metrics` was finding
   **zero** runs on any sessionless study, so the QC page had never worked on
   `divatten_beta`. **The link question is settled 2026-07-27, dogfooding
   `divatten_beta_v2`: duckbrain serves the reports itself.** Relative links fixed
   the exported copy and could never fix the embedded one — a `srcdoc` iframe's
   base URL is the *page's*, so under OnDemand `../mriqc/…` addressed
   `/node/<host>/mriqc/…`, which nothing serves. The mechanism is Streamlit's own
   media endpoint (`core/report_embed.py` rewrites each relative asset reference;
   `gui/components.embed_tool_report` supplies the URLs): same origin, so the
   OnDemand proxy carries it with no route, launch flag or symlink of duckbrain's.
   Two rejected alternatives are recorded in `components.py` because both look
   right from outside — `server.enableStaticServing` cannot reach a project
   directory (its handler resolves symlinks then demands the result stay under the
   static root, and making the static folder itself the symlink trips a 1 GB size
   check that disables serving *silently*), and an OnDemand Files deep link does
   not exist in the SSH-tunnel workflow. Reports open per run from the decisions
   panel rather than from the table, because the figures run 4–15 MB per run; the
   table now names its report instead of offering a link that does nothing.
   Validated across all **70** MRIQC reports in `divatten_beta_v2`: zero
   unresolved assets. **Left open by this:** `st.components.v1.html` is deprecated
   with a removal date already past (2026-06-01), and `st.iframe` replaces it but
   does not exist at our `streamlit>=1.48` floor — switching means raising the
   floor, which is a decision about who can install duckbrain, not a rename.
   **Slice 3 landed 2026-07-24, and migrated nothing because nothing needed it**:
   the unified on-disk schema is mmmdata's append-only
   `{"run_key", "decisions"}`, so its 609 existing records read as-is (verified:
   609/609 read, 0 files modified) while the zero duckbrain-schema files on disk
   cost nothing to leave behind. Both shapes and both layouts are read; reading
   never rewrites, and that is a test — restamping an old record would give it a
   provenance it does not have. `save_decision` now raises on a blank reviewer,
   and the page takes the reviewer from the session rather than a text box. Live
   data forced a **third** count bucket: `automated` (author known to be a
   machine) and `unattributed` (author unidentifiable) are different provenance
   situations and only the second is closable by re-reviewing — merging them
   misreported all 609 `auto-stub` records as decisions by an unknown person.
   **The
   last has teeth:** `core/qc.py` accepts `reviewer` and page 5 never passes it,
   so *every QC decision duckbrain has written is anonymous*, and legacy records
   cannot be attributed retroactively. Settled in the doc so they are not
   re-argued — Streamlit stays the control plane and only the QC *report* becomes
   a document (one renderer, embedded **and** exported; not two versions), and
   mmmdata will depend on duckbrain rather than keep a copy, which makes
   [Licensing](#licensing-follow-ups) a precondition for that end state rather
   than background. Note `core/qc.py` is the only untested module in `core/`.
5. **Physiological data as BOLD regressors** — downstream consumer (PhysIO/TAPAS →
   confounds); fMRIPrep ingests physio but doesn't compute RETROICOR.
6. **ReproIn** — **reading it is DONE** (2026-07-21): duckbrain parses the naming
   convention and trusts its entities over the heuristics, still converting with
   dcm2bids. What's left is the *social* half — recommending the convention to
   LCNI so exports arrive already carrying their entities, which is `#5`'s "fix it
   at the console" rule in concrete form. Open: does duckbrain also read the
   `ses-` entity (it currently takes session from the ingestion mapping), and is a
   ReproIn-named study worth acquiring as a test case.
7. **External FreeSurfer 8 feeding fMRIPrep 25** instead of fMRIPrep's bundled
   recon — **asked for by LCNI**, who already run it this way. Cheaper than it
   looks: **FS 8.2.0 is already installed on Talapas and on the default `PATH`**,
   so this is the one candidate stage with nothing to build, and NORDIC is the
   precedent for an `--array` stage that shells out. Writing to
   `<derivatives>/fmriprep/sourcedata/freesurfer/` means fMRIPrep finds it with
   **no flag at all** (that is its default `fs_subjects_dir` under
   `--output-layout bids`). Two traps and the real cost — including why
   `--fs-subjects-dir` without `--fs-no-resume` re-creates the anat-reuse silent
   no-op, and why fMRIPrep-25-against-FS-8 is a question for LCNI/nipreps and not
   for us — in `docs/pipeline-extras.md` §9. **If taken, it forces `#5b` Case 3's
   DAG decision**: fMRIPrep would depend on two producers and
   `effective_depends_on` is a single string with one special case already.
8. **Eye-movement reconstruction from BOLD** (DeepMReye-style) — a branch fMRIPrep
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

<a id="19"></a>
## #19 — Conversion coverage: what the LCNI repository still shows missing

Validated against `/projects/lcni/dcm/repository` — 15 studies, 189 distinct
series descriptions, 112 sessions paired with the BIDS the LCNI curator produced.
**Treat that corpus as the fixture for anything in this section** — it is
read-only, and it is the only place these cases exist together. Write scratch
output to `/projects/hulacon/bhutch`.

**The 391-of-392 number is a measurement dated 2026-07-24, not a standing
claim.** As of that date duckbrain reproduced 391 of the 392 canonical files (the
miss is `anat/T1wa`, a curator typo and not a valid BIDS suffix). LCNI has since
said **many anatomicals in that repository are missing and will be
re-converted** — in exactly the datatype `#19.4`/`#19.6` and the ND work touch.
So the number must be **re-measured rather than carried forward**, and a lower
agreement afterwards is not by itself a regression: it may only mean the curator's
denominator moved.

**What actually gates now is duckbrain's own frozen inventory** — the planned-file
set across all sessions, snapshotted before a change and diffed after, with every
difference triaged rather than counted. That is independent of a tree someone else
is editing. Canonical stays useful as a one-way check for *new* disagreements,
each looked at individually — and no more than that, because it is not an oracle:
it holds illegal subject labels (`#19.5`), it silently kept one of two fieldmap
pairs on six sessions (`#19.6`), and now it is known to be missing anatomicals.
That is three independent ways it is wrong, so "matches the curator" has never
been a correctness argument on its own.

What it does *not* cover, in the order the corpus argues for:

### `#19.1` — DWI is recognised and still not convertible

`dwi` is a classification with no emission path: no `bval`/`bvec` handling, no
`dwi/` description in `generate_config`. `plan_warnings` says so out loud now,
which is honest, not fixed. The corpus has `RL_diff_m2p2_64_2mm_rl` /
`LR_diff_m2p2_64_2mm_lr` (Round_Robin) as a live fixture, and the curator dropped
them too, so there is **no canonical output to check against** — that is the real
cost of this one, and why it wants its own validation plan rather than a quick
patch.

### `#19.2` — Phase-encoding directions other than AP/PA

`dir-` is AP/PA only, hardcoded in three places (`dicom_inspect._DIRECTION_TOKEN`,
the `_fmap_description` call sites, and `dcm2niix_probe.PE_FOR_DIR`, whose `j-`/`j`
table also assumes an axial acquisition). LR/RL is ordinary at non-Siemens sites.
**Deliberately not done speculatively**: this corpus has no LR/RL *fieldmap*, so
there is nothing to validate the emission against, and `PE_FOR_DIR` would need the
acquisition plane to stay correct rather than just wider.

**What changed 2026-07-24 (`#22`): the direction is no longer a guess we can't
check.** dcm2niix reports a *signed* `PhaseEncodingDirection`; the raw tag
`InPlanePhaseEncodingDirection` gives `ROW`/`COL` with no polarity and is absent
on XA30 entirely, so the `_ap`/`_pa` name token was genuinely all duckbrain had.
It is right for all 32 name-tokened fieldmaps in the corpus — but that is now
*measured* rather than assumed, and `plan_warnings` says so per session. Two
consequences for this item: LR/RL does exist in the corpus after all
(`RL_diff…_rl` reads `i`, `LR_diff…_lr` reads `i-`), as diffusion, so it is
entangled with `#19.1` rather than absent; and when this is built, the general
case should read the probe's direction instead of widening `PE_FOR_DIR` — the
table can then be deleted rather than taught about oblique acquisitions.

### `#19.3` — Which fieldmap pair, when a session has more than one

**Bold→fmap binding uses acquisition time** (2026-07-24, in the ledger): a run
binds to the pair it was shot nearest in time. That settles the common case —
fieldmap, run block, second fieldmap, second run block — and is validated on
REV055. What it does *not* settle is a session that shoots **two pairs
back-to-back** and expects a policy ("keep the last"): the times are then nearly
equal and a tie falls through to first-group. That residue is genuinely a
declaration, and belongs with `#16`'s `[expected]`, not a heuristic. duckbrain
converts both pairs, which is at least visible — for gradient-echo as well as
spin-echo since `#19.6`.

**Correction, 2026-07-24 — acquisition time is not a fallback for shim, it is
better.** This item and `memory/fieldmap-binding-and-heudiconv` both used to say
that heudiconv's shim criterion is the physically correct one and that duckbrain
approximates it only because shim is unreachable before dcm2niix runs. Both
halves of that are wrong, and it matters because it framed the current binding as
a compromise to be undone later.

*Reachable:* the `#22` probe reads `ShimSetting` for **383 of the corpus's 385**
readable series, XA30 included — dcm2niix reconstructs it from the enhanced
structures even where there is no CSA blob at all.

*And useless for this question:* in **all 18** sampled sessions holding more than
one fieldmap group, every group shares one identical shim. On REV055 — the
session this binding was validated on — `fieldmap1`, `fieldmap2` and all six BOLD
runs carry the same eight values, so a shim match says everything corrects
everything. It is worse than uninformative in DEV102, where the fieldmap pair's
shim is shared by **no** BOLD run, so a strict shim match leaves every run
unbound. LCNI re-shims per prescription, and the fieldmap shot at the end of a
session gets its own group. Pinned by
`test_probe_reads_a_real_dicom_when_dcm2niix_is_available`, which fails if a pair
ever *does* differ. So: don't "upgrade" this to shim later.

### `#19.6` — Gradient-echo (GRE) fieldmaps — the two defects are DONE (2026-07-24, see ledger)

**Prompted by LCNI**, who flagged that older fieldmaps are gradient double-echo
rather than spin-echo and that converters mispair them when the magnitude and
phase series aren't neighbouring. **The adjacency concern was unfounded** —
`_detect_gre_fieldmaps` pairs on header `ImageType` (`P` marks phase) plus an
identical `SeriesDescription` and ordering, never on `SeriesNumber + 1`; fed a
magnitude at 5 and a phase at 12 it pairs them. All 38 GRE pairs the corpus
actually holds are `+1`, so that robustness is by design rather than by
validation. Checking it surfaced two real defects, both since fixed:
`plan_warnings` calling `is_complete_group` rather than testing `ap`/`pa`, and
GRE groups getting the same `acq-`/`run-` entities spin-echo pairs already had.

**What the corpus proved about the rest of it.** duckbrain agrees with the
curator on 26 of 32 GRE sessions and the other 6 are the ones above — where
duckbrain finds a **second** GRE pair the canonical tree lost. REV055 ses-1 holds
`fieldmap1` (series 7/8) and `fieldmap2` (13/14); canonical kept one unentitled
`phasediff`, i.e. the curator hit this same collision and silently kept the last.
So on these six duckbrain is right and canonical is wrong — another instance of
`memory/lcni-repository-corpus`'s point that the canonical tree is not an oracle.
Also confirmed: no BIDS Case-2 (`phase1`/`phase2`) or Case-3 (`_fieldmap`) data
exists in the corpus, so `phasediff` is the only GRE flavour implemented and the
only one present; and `EchoTime1`/`EchoTime2` are correctly left to dcm2niix
(present in the canonical sidecars at 0.00437/0.00683) rather than injected.

**Two fragilities left standing, neither observed in the corpus**, both of which
drop a fieldmap *with warnings* rather than silently: a phase series that
*precedes* its magnitude (the pairing requires the phase to sort after), and
halves whose `SeriesDescription` differs (the pairing requires them equal, e.g.
`gre_field_mapping` vs `gre_field_mapping_phase`). A magnitude split into two
single-echo series also fails, since a magnitude is recognised by
`len(echo_numbers) > 1`. Worth a decision, not a speculative fix — there is
nothing local to validate against, which is `#19.2`'s reasoning.

**Still true, and now load-bearing for a second reason.** Pairing on an identical
`SeriesDescription` is what makes `nd_duplicates = "both"` work with no
fieldmap-specific code at all: the two reconstructions are named
`fieldmap_2mm` and `fieldmap_2mm_ND`, so they fall into separate groups, get
separate `acq-` entities from the existing multi-pair machinery, and end up as
two independent `B0FieldIdentifier`s. Loosening the description match to fix the
`gre_field_mapping` / `gre_field_mapping_phase` case would have to keep that
separation, or it would merge the two reconstructions into one group and pair a
corrected magnitude with an uncorrected phase — precisely the mispairing LCNI
reported from another converter.

### `#19.4` — DONE (2026-07-24, see ledger)

An empty series directory now raises an `empty-source` error in `plan_warnings`
instead of silently predicting a file dcm2bids can't produce. Finding it exposed
and fixed a worse bug: an `_ND` copy dropped because its corrected twin existed
*but was empty*, leaving the session with no anatomical.

### `#19.5` — Subject labels the corpus contains but BIDS forbids

`sub-DIPPER_007`, `sub-hoya_01`, `sub-AEPET2_55`, `sub-NAGL_28` all carry an
underscore, which is not a legal BIDS label — the filename then re-parses as an
extra entity. duckbrain's `_sanitize_label` already strips these on ingestion, so
this is not a duckbrain bug; it is a note that the *canonical* trees in that
repository are not all valid, so "matches the curator" is not by itself a
correctness argument.

### `#19.7` — Re-measure agreement once LCNI re-converts the anatomicals

LCNI reported (2026-07-24) that many anatomicals in the repository are missing
and will be redone. Until then the canonical anat coverage is incomplete, so the
headline agreement number in the preamble above is frozen at its 2026-07-24
measurement and must not be quoted as current.

When the re-conversion lands: re-run the corpus harness, diff duckbrain's own
inventory against the frozen baseline first (that is the regression gate), and
only then compare against canonical — treating each *new* disagreement as
something to triage rather than a score to restore. Expect the ND work to show up
here: `both` doubles the anatomicals, and `corrected`/`uncorrected` change which
source series a given `T1w` came from without changing its name, so a filename
diff is the wrong instrument for that part.

The one thing worth asking the curator directly is which reconstruction their
re-conversion keeps. If they keep the `_ND` copy where both exist, duckbrain's
default (`corrected`) will disagree on every twinned session — 47 of them — and
that would be a *default* to reconsider, not a bug to fix.

<a id="23"></a>
## #23 — `st.components.v1.html` is past its announced removal date

Streamlit 1.56 emits, every time the QC page renders:

> Please replace `st.components.v1.html` with `st.iframe`. `st.components.v1.html`
> will be removed after 2026-06-01.

That date has passed. It still works in 1.56, but `pyproject.toml` pins only
`streamlit>=1.48`, so the next upgrade a user happens to install can take it
away — and it is what renders **both** the QC report itself and every embedded
MRIQC/fMRIPrep report (`gui/components.py` `embed_tool_report`,
`5_QC_Dashboard.py`). Losing it silently blanks the whole QC surface.

Two calls to change, but do not do it blind:

- `st.iframe` is newer than the floor. Check which version introduced it and
  raise the `streamlit>=` floor to match in the same commit, or the fix breaks
  1.48 users instead.
- The sandbox is weaker than it looks, so don't budget for losing protection
  that isn't there. Streamlit 1.56 sets `allow-same-origin` *and* `allow-scripts`
  together (`static/js/IFrameUtil.*.js`), which cancels the isolation: a `srcdoc`
  document inherits the parent origin, shared under OnDemand with the OnDemand
  dashboard. `embed_tool_report`'s docstring asserted the opposite until
  2026-07-28. Swapping to `st.iframe` therefore cannot make this *worse*, but
  check whether it makes it better — and if it offers real sandboxing, take it.
- `tests/test_qc_page.py` and `tests/test_gui_components.py` exercise both call
  sites, so a swap that breaks rendering should fail rather than go quiet.

Found 2026-07-28 while adding the fMRIPrep report panel; the deprecation warning
is visible in any `AppTest` run of the QC page.

**Slice D of `#24` closes this for the whole QC surface** by rendering the domain
pages natively instead of embedding HTML. That leaves only `embed_tool_report`,
which serves the tools' own reports and genuinely needs an iframe.

---

<a id="24"></a>
## #24 — QC dashboard: group review into domains

`5_QC_Dashboard.py` is one mega-page — a per-subject fMRIPrep panel, a modality
selector, a 4.9 MB embedded report, then 65 flat per-run expanders. Everything
about a run arrives at once, and the guidance explaining each number sits in a
glossary far from the number.

Group QC evidence into four **review domains** — signal, temporal, alignment,
artifact — so each aspect of a run is reviewable on its own, with its guidance
attached to it. The run stays the unit of review; domains become per-run
subsections, each on its own page acting as a viewer for the selected run.

Three findings shaped it, all checked against real data rather than assumed:

- **fMRIPrep's alignment evidence is per-run, not per-subject.** `desc-sdc`,
  `desc-coreg`, `desc-fmapCoreg`, `desc-carpetplot` and `desc-rois` all carry run
  entities; only `dseg`, `space-*_T1w`, `desc-reconall` and `fmapid-*_fieldmap`
  are per-subject. The current panel is per-subject only because
  `find_fmriprep_reports` globs the aggregated `sub-*.html`. Serving one figure is
  **1.1 MB against 80 MB**, and each SVG carries its own `@keyframes`, so the SDC
  before/after flicker survives being served standalone.
- **Alignment has no MRIQC number on the BOLD side at all** — `tpm_overlap_*` is
  anat-only. That is the argument for grouping by review *question* rather than by
  data source: it gives the orphaned fMRIPrep evidence a home.
- **The four domains do not partition the question a verdict answers.** None
  covers task timing, stimulus delivery, or a participant asleep with their eyes
  open. So an overall keep/exclude may be *displayed* as derived ("4/4 reviewed,
  no verdict recorded") but never *recorded* that way, and the verdict buttons
  must not be gated behind domain completion.

Slices, each independently mergeable, schema-bound work last:

- **A — the taxonomy. DONE** (see the ledger). `core/qc_domains.py`, additive.
- **~~B — the export regroups.~~ DROPPED 2026-07-28.** The plan was to regroup
  the exported HTML report by domain. Ben's call: punt on the HTML export
  entirely for now, and if the dashboard ever grows persistent artifacts they
  belong in `derivatives/duckbrain`. The export still works and is untouched; it
  is simply not where effort goes. Slice D makes the *pages* the QC surface, so
  regrouping a document nobody was asked to read would have been work spent on
  the wrong end. **Consequence to accept knowingly:** until this is revisited,
  the export shows a flat table with a floating glossary while the pages show
  domains, so the two disagree about how QC is organised.
- **C — the evidence viewer. DONE** (see the ledger). `core/qc_evidence.py` +
  `gui/qc_panels.py`; the fMRIPrep panel is now a per-run figure viewer.
- **D — the page split.** Dict-grouped `st.navigation` (a `QC` group renders as
  one collapsible item at `position="top"`), a shared scope bar, deep links via
  `st.page_link(query_params=…)`, native rendering. This is where
  `detect_outliers(scope="within_subject")` — which exists and has never been
  reachable from the GUI — gets a home; note it changes what is flagged, so the
  export must say which scope produced the flags, as it already does for
  `iqr_multiplier`.
- **E — the domain review store.** An optional `domain` field on entries in the
  existing append-only per-run records. Two rules make it safe: `latest` must mean
  "latest entry with **no** domain", or the last note about a domain silently
  becomes the run's verdict (`#17.10` with the arrow reversed); and the domain
  vocabulary (`reviewed`/`concerns`/`pending`) must be **disjoint** from
  `VALID_DECISIONS`, enforced at the writer rather than by convention.

Known cost of keeping the run as the unit: four domains × 65 runs is 260
possible sign-offs where there are 65 today. Sign-off is optional and gates
nothing, and the overview's run × domain matrix is what keeps a reviewer from
touring everything. A per-run "mark remaining reviewed" bulk action is the
pressure valve **if real use shows one is needed** — design it against observed
friction, not a prediction.

Full design, the assignment of all 30 registry keys, which assignments are
arguable, and the decisions that are settled: **`docs/qc-review-domains.md`**.
Don't re-open the taxonomy or the "run stays the unit of review" question without
reading it.

---

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
| 2026-07-24 | — | **A project chooses which reconstruction converts, prompted by LCNI** asking that the user be able to select the distortion-corrected copy, the `_ND` copy, or both. `[conversion] nd_duplicates`, defaulting to today's behaviour. Project-level and not a table column: bulk and cockpit converts go through `generate_session_config` and have no table, so a table-only control would mean the reviewed session and the bulk-converted session held different images with nothing saying so. `both` needed new code only for anatomicals — `acq-nd`/`acq-dis`, with `_disambiguate_anat` now bucketing by `(suffix, custom_entities)` so `run-` still means *acquired* twice rather than *reconstructed* twice. The fieldmap half falls out of description-matched pairing for free (two groups, two `B0FieldIdentifier`s), except that both pairs share an acquisition time, so nearest-in-time cannot separate them and fell through to insertion order — hence `FieldmapDetection.deprioritized`, which narrows the *automatic* candidates only. Validated live through dcm2bids on Crave_control/CC052: both reconstructions land, they differ across 61% of voxels, and the B0 intent is correct |
| 2026-07-24 | — | **The ND choice is made per twin pair, not per series** — the defect LCNI's fieldmap layout exposed (27 `fieldmap_2mm_ND` mag, 28 `fieldmap_2mm` mag, 29 `fieldmap_2mm` phase, 30 `fieldmap_2mm_ND` phase). The twin lookup was a dict comprehension keyed on the description, so of the two series sharing `fieldmap_2mm` it kept only the last — the *phase* — and demoted the ND *magnitude* on the strength of it, never checking the role. And deciding per series can keep one half of each reconstruction, which the identical-description pairing then refuses entirely. Together those reproduced CC056 with a fieldmap: both ND series demoted, the group built on an empty directory, a complete populated pair discarded. LCNI's other worry — that the halves get matched in order, so 27 pairs with 29 — cannot happen here; pairing is `ImageType` + identical description, never ordering. The corpus run then found a third case the unit tests could not: pMAP101 shoots its mprage twice and saves both copies of each, and with each ND picking its own nearest twin one corrected series went unclaimed and converted as a spurious third anatomical **under every policy including the default**. Sides are now paired in acquisition order. The drop is also no longer invisible — `DroppedSeries.reason` and an `nd-duplicate` notice, on 52 corpus sessions that previously said nothing |
| 2026-07-24 | — | **Spin echo read from both witnesses, and the pulse sequence name read at all.** `is_spin_echo` asked only whether `SequenceName` started `epse`, which is right for the pepolar fieldmap and wrong for every other spin-echo family: `*tse2d1_18` does not, so a classic turbo spin echo read as gradient echo — leaving the `anat`/`T2w` rule unreachable in that dialect (those series classified only because their *name* said `t2`) and putting a dual-echo TSE on course to convert as half a fieldmap. Neither witness subsumes the other: the pepolar `epse2d1_104` reports `ScanningSequence ('EP',)` with no `SE`, `*tse2d1_18` reports `('SE',)` with the wrong name — so it is a union. Separately, LCNI's note that the field to read is `PulseSequenceName` (post XA30) else `SequenceName`: duckbrain read only the latter, used it for one bit, and never stored it. Now on `SeriesHeader` and used as a last tier for the two classes nothing else reaches — `*fl3d1_ns` scouts (previously name-only, so a localizer called anything else was `unknown`) and `*spcR` SPACE. The plan for that said SPACE was absent from the corpus and would ship on a synthetic test; the corpus run said otherwise — WMS179 Series_21 is a real undefaced 3D SPACE, and enhanced-dialect, so it exercises exactly the tag that was never read |
| 2026-07-24 | #22 | **A dcm2niix probe, and the correction it forced.** `core/dcm2niix_probe.py` stages one symlink per series and makes a single `dcm2niix -b o` call — **0.15 s warm per session** against 90 s for the same flag over the session directory, which is the invocation the "too slow to preview with" objection was actually about. It buys two fields `dicom_header` cannot reach by any amount of pydicom: the **signed** `PhaseEncodingDirection` (the raw tag is `ROW`/`COL`, no polarity, and absent on XA30) and `ShimSetting`. `plan_warnings` grows `pe-collinear` (error — both halves of a pepolar pair encoded the same way estimate nothing, and it is orientation-free so it holds for oblique acquisitions) and `pe-direction` (warning — the `_ap`/`_pa` name token disagrees with what the scanner did). The second is `consistency._check_fmap_pe_direction` moved to where it can still change the outcome; both now import one `PE_FOR_DIR` so a plan cannot pass preflight and fail after. **The correction: shim is reachable and useless.** dcm2niix reports it for 383/385 corpus series including 100% of XA30 — but in all 18 sampled multi-fieldmap sessions every group shares one shim, and in DEV102 the pair's shim matches *no* BOLD run. So the acquisition-time binding is not a compromise awaiting a shim upgrade; it is strictly better, and `#19.3` and `memory/fieldmap-binding-and-heudiconv` said the opposite until now. Also measured: the `_ap`/`_pa` token is correct 32/32 on the corpus, and LR/RL exists there after all (as diffusion). Wiring it into the GUI is open as `#22` |
| 2026-07-24 | #19.6 | **Two gradient-echo fieldmap defects, prompted by LCNI** flagging that older fieldmaps are gradient double-echo and that converters mispair them when the halves aren't neighbouring. **That concern was unfounded** — pairing is header `ImageType` + identical description + ordering, never `SeriesNumber + 1`; a magnitude at 5 and a phase at 12 pair fine (all 38 GRE pairs the corpus holds happen to be `+1`, so the robustness is by design, not validation). What checking it *did* find: (a) `plan_warnings`'s half-pair check tested `ap`/`pa` membership rather than calling `is_complete_group`, so **every** GRE session was told its complete fieldmap "can't correct anything and isn't offered for binding" — false in both halves, since the runs were bound to it. `is_complete_group` exists to be the one predicate and the GUI had already moved onto it; this call site had not. (b) `group_entities` was populated only on the pepolar path, so two GRE pairs both wrote `sub-X_ses-Y_{magnitude1,magnitude2,phasediff}`. The collision check caught it as an *error* so nothing was overwritten, but the session could not convert at all and the message advised "distinct task or run values", which a fieldmap has none of. GRE groups now take the same `acq-`/`run-` entities. Fixed on all 6 affected corpus sessions (REV055/REV074/REV126, both sessions each) with binding unchanged; corpus-wide re-run confirms no duplicate fmap filename and no false half-pair anywhere. The 6 are also where duckbrain finds a **second** pair the canonical tree lost — the curator hit this same collision and silently kept the last |
| 2026-07-24 | #19.3 #19.4 | **Three heudiconv ideas borrowed after comparing against its canonical DIVATTEN run on this filesystem.** (1) **Bold→fmap binding by acquisition time** — heudiconv's real criterion is shim settings (a fieldmap corrects only what shares its shim group), but Siemens keeps the shim in a CSA blob not populated until dcm2niix runs, and 36% of the corpus is XA30 with no CSA; AcquisitionTime is the portable proxy and is standard in both dialects. The old "first complete group" bound every run to whichever pair sorted first — wrong for every run after the second pair. Validated on REV055 (fieldmap1 binds GNG/BART, fieldmap2 binds SST/React). Explicit rule and name-match still outrank it; the preview path takes the same time lookup so it can't drift. (2) **Empty source directories flagged** — `plan_warnings` now carries each planned file's source file count and raises when zero, instead of predicting a file dcm2bids silently can't make. (3) Persisting the seqinfo table (heudiconv's `dicominfo.tsv`) not done — `classified_by` already surfaces the same on the Conversion page. heudiconv is Apache-2.0, so borrowing is one-way |
| 2026-07-24 | — | **Two latent bugs the borrowing exposed.** (a) sbref-vs-bold was decided by `len(files) == 1`, a volume count only for a Siemens mosaic or enhanced series — a non-mosaic/GE/Philips single-volume reference arrives as one file per slice and read as a multi-volume BOLD; now settled by counting distinct slice positions, and an undetermined count defers to the name. The scan runs only for a 2D gradient-echo EPI. (b) an `_ND` copy was demoted whenever a same-named twin existed, without looking inside it — Crave_control/CC056 has the corrected mprage folder present but *empty* beside a populated `_ND` copy, so the session got no anatomical; the twin must now be non-empty |
| 2026-07-24 | — | **Conversion hardened against the LCNI repository** (`/projects/lcni/dcm/repository` — 15 studies, 189 series descriptions, 112 sessions paired with canonical BIDS). Agreement with the curator went from **109 of 494 series** to **391 of 392 files (99.7%)**. Four things were wrong rather than merely narrow: the anat vocabulary matched as bare substrings so `BART1_`/`SST2_`/`React2_` classified as *anatomicals* and overwrote the real MPRAGE on one filename; `\bscout\b` can never match `aa_scout` because `_` is a word character, so `AAHScout` (300+ series) fell through to unknown; `_extract_fmap_group` stripped `ap`/`pa` anywhere in the string, splitting one pair into two groups; and the bulk/SLURM path never called `plan_warnings`, so it submitted the collisions the GUI refused. Also: the vNav setter and Siemens' `_ND` copy each converted as a second and third colliding T1w, and `MAB1`/`MAB2`/`MAB3` read as three tasks rather than three runs of one. Remaining gaps are `#19` |
| 2026-07-24 | — | **Classification reads DICOM headers** (`core/dicom_header.py`). It ran entirely on the console operator's free text, which across that corpus is frequently silent about datatype — `food`, `Whack`, `Resting1`, `WMS_R1`, `EPI196` are all ordinary BOLD runs, all classified unknown, all converted to nothing. `ImageType` + `MRAcquisitionType` + is-EPI + is-spin-echo + volume count is a 100%-pure key: **359/359 of the curator's converted series get the right datatype**, 1195 of 1384 decided by header. The finding that shaped it: **two MR dialects**, and 36% of that corpus is Siemens XA30 enhanced-MR with *no* `ScanningSequence`/`EchoNumbers`/`EchoTime` at the top level — a rule keyed on those doesn't misfire, it sees nothing. Absence is never evidence: unreadable or non-decisive falls back to the name path, `classified_by` records which decided, and the defaced-anatomical rule may only promote |
| 2026-07-24 | — | **Gradient-echo fieldmaps convert** — 96 of the corpus's 404 canonical files, and *more* common there than the pepolar pair. Two consecutive series with the same description; `EchoNumber` joins `SeriesNumber` in the criteria because one magnitude series becomes two files, and `'P'` in `ImageType` is the only thing separating the halves. `EchoTime1`/`EchoTime2` deliberately not injected — dcm2niix writes them. Validated end to end against dcm2bids 3.2.0 on real data, and the result is *better* than the canonical, whose fieldmaps carry no `B0FieldIdentifier` at all so fMRIPrep skips SDC on them |
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
