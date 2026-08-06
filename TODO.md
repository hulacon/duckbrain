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
[`#16`](#16) **next** — sanity checks (Slice A done; `#16.1`–`#16.3` open) ·
[`#13`](#13) conversion legibility (`#13.1`, and `#13.2` plan-time filename checks) ·
[Licensing](#licensing-follow-ups) ·
[`#19`](#19) conversion coverage (`#19.6` newly actionable — the probe is the
oracle it lacked) ·
[`#20`](#20) conda environment ·
[`#33`](#33) widen the type-checked surface (`gui/` done; `#33.2` needs a
`typing_extensions` decision, `#33.4` is `core/`) ·
[`#36`](#36) the memory headroom is flat but the overshoot scales with `--nprocs`
(measured on a beta user's OOMs; needs a measurement before a fix) ·
[`#2`](#2) onboarding · [`#9`](#9) launch surface ·
[`#5`](#5) config edges · [`#10`](#10) template groups · [`#11`](#11) automation ·
[`#12`](#12) mmmdata-agents · [`#5b`](#5b) NORDIC Case 2 · [`#7`](#7) extra
stages · [`#8`](#8) branding + dark theme ·
[`#30`](#30) GUI eyeball queue (batch these; don't check one at a time) ·
[Provenance residuals](#provenance--consistency-residuals) ·
[Loose ideas](#loose-ideas-not-scheduled)

---

<a id="16"></a>
## #16 — Sanity checks: what we asked for vs. what we got

**Slice A shipped 2026-07-22** — a declared `[expected]` prescription plus the
cheap checks that read it (see the ledger). **Full design, prior-art verdicts and
the decisions that are settled: `docs/sanity-checks.md`.** Do not re-open the
boundary question or the Nipoppy/CuBIDS/mrQA verdicts without reading it.

🔴 **The caveat this item exists for, inherited from `#15` when that closed
2026-08-03.** Run against `mmm_fmap_check` while its sidecars still carried the
inverted `B0FieldIdentifier`/`B0FieldSource`, the BIDS validator reported **zero
fieldmap issues** — the keys were valid strings in valid places. Validation is
now genuinely usable (`#15` fixed the symlink flood that made it unreadable) and
that changes nothing here: it checks structure and naming, not semantic intent.
**Validation raises the floor; it does not catch the class of bug that has
actually bitten us.** The cockpit's validation panel says so in its own caption,
because whoever reads a clean result is exactly who needs to know.

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
  nothing else records the ask. **That is now the item's *only* surviving
  motivating case** (2026-08-04): the run this record was expected to explain
  turned out to need none of it, because the archived sbatch was byte-identical
  to the successful re-run's and `script_path` reached it in one `diff`. Two
  further things that case settled about the boundary here — the *confounds* half
  of "did we get what we asked for" needed no record at all (fMRIPrep writes one
  per BOLD run at its default level, so the raw BOLD list already says how many
  there should be, and `surveyor._fmriprep_func_keys` now requires them); and the
  *outcome* half can sometimes be read straight off the tool, which is what
  `consistency._check_tool_crashes` does. So this layer is narrower than it
  looked, and what is left in it is genuinely the ask nobody else records — the
  spaces, and drift between runs.
- Not a JSON blob column (keeps the TSV greppable), and not a stamp in the
  derivative tree (fMRIPrep/MRIQC overwrite their own `dataset_description.json`,
  which is why `consistency.py`'s source rule routes tool-produced derivatives to
  the log).
- **This is also DB-002's "persisted expected-output manifest"** (external review,
  2026-07-22), arrived at from the other direction — one feature, so build it
  once. What that framing adds is a trigger and a free half. The trigger:
  counting expected-vs-found already covers the failure DB-002 reported and needs
  no state store, so the manifest earns its keep only for the two things counting
  can't see — a missing output *space* (the bullet above) and config drift between
  runs — which means **revisit when per-launch `output_spaces` overrides become
  common**. The free half: `nordic.write_nordic_sidecars` writes one sidecar per
  intended run at launch already, so NORDIC could be graded by "every sidecar has
  a matching NIfTI" without inventing anything.
- **`#13.1` is waiting on this layer to settle** (Ben, 2026-07-30). A study that
  converts only part of what it acquired — five of the LCNI corpus's fifteen
  curate `anat/T1w` alone — currently has to say so as a per-session skip. That
  may be a *statement of intent* rather than a config toggle, and `[expected]` is
  the only statement of intent duckbrain has. Whoever shapes this should decide
  whether "which series this study converts" belongs in it; if it does, `#13.1`'s
  separate section never gets built.

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

---

<a id="13"></a>
## #13 — Conversion legibility: what the eyeball pass left

**Phases 1–8 shipped, granularity is settled, and the browser validation is
done** (see the ledger). What is left is `#13.1` below plus three notes the
eyeball pass produced. Full design in **`docs/conversion-legibility.md`**.

- **The eyeball pass is done, 2026-07-30, on
  `/projects/hulacon/bhutch/fmap_eyeball`** (`sub-01` two fieldmap pairs,
  `sub-02` three; symlinked at the `dicom` level into the read-only `mmmdata`
  export, nothing converted because the Conversion Plan renders from DICOMs).
  Ben's verdict: the board works. **The central bet holds** — the third pair's
  colour was "orange and easy to see", which is the thing the whole
  one-stable-colour-per-group design was for and the thing tests could only
  assert as a string. Density fine, the `Type` dropdown fine. Keep the fixture:
  92 of the export's 109 sessions have ≥2 complete pairs, max 4 groups against a
  5-colour palette, so the wrap-around is unreachable in this study.
- **Three residual notes, none blocking, all deliberately not acted on** — they
  are polish, and polish before the theme is settled is work done twice:
  - `anat/T1w` reads slightly filenamey; `anat (T1w)` was floated and explicitly
    called non-essential. Not free either: the token *is* the persisted
    `[series_types]` value, so changing the display changes the config format.
  - The grouped fieldmap view (phase 4) may be **redundant with the table**
    (phase 6). Fair: phase 4 was designed before the unified table existed, and
    the table now carries the same relation on every row in both directions.
    What the section still adds is *aggregation* — every bold for one pair in one
    place, versus scanning 40 rows for a colour — and Ben found it "good for
    sanity checking". So the question is whether that earns a surface, and the
    cheap middle is an expander rather than deletion. Decide with `#8`, since it
    is a density judgment and density depends on the theme.
  - Judged on a desktop monitor only. Narrow widths are untested, and OnDemand
    users are often on laptops.
- **Dark theme was not tested and is now `#8`'s**, by Ben's call — a theming pass
  is coming and testing against defaults would be work done twice. One specific
  thing for whoever does it, or it will be missed: the Fieldmap Detection badges
  use Streamlit's theme-aware `:blue-badge[…]` markdown while the tokens *inside*
  the table are plain emoji, which are font-rendered and do not shift with the
  theme. If those two diverge, the colour join breaks exactly where it carries
  information. `docs/conversion-legibility.md` phase 3 also names
  `5_QC_Dashboard.py`'s hardcoded `#ffcccc` as the existing example of getting
  this wrong.
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

### `#13.1` — A project-level skip, keyed on description

**The editable `Type` shipped 2026-07-30** — see the ledger and
`docs/conversion-legibility.md` phase 8 for the design and the refusals it rests
on. What that work left open is one bullet of the original item.

**Measured twice on 2026-07-30, and the second measurement is the one to
trust — the item is justified, but not by either example it used to cite.**

*First pass, on `mmmsourcedata/sub-03/ses-01`:* 14 of 53 series arrived ticked
and 12 looked like junk. **Both causes closed 2026-07-30** (see the ledger), and
the pass no longer supports the item at all — it also **overcounted**. Four of
the 12 were diffusion SBRefs classified `fmap`, and four were `_ND` copies of a
twin pair `nd_twin_bases` could not see; the other four rows it called junk are
the *corrected* copies, which are genuine anatomicals. The session now ticks **6
rows and none of them is junk** — two acquisitions of `ABCD_T1w_MPR_vNav` (a real
repeat, so `run-1`/`run-2` is right), the two T2 anatomicals, and the resting run
with its reference. So this measurement is spent; the second pass below is the
whole case.

*Second pass, on the LCNI repository, prompted by Ben pointing out that
`mmmsourcedata` was pruned on its way out of `lcni/dcm` and that most studies
discard some series anyway.* Study-level, since a project-level skip is itself a
study-level statement: for each of the 15 studies, every SeriesDescription
duckbrain converts that the curator's canonical BIDS never contains. It found the
class, and it is neither of the ones above:

- **Five studies of fifteen curate anat only.** WMS, pMAP, Round_Robin, NAGL and
  DEV have canonical trees containing *nothing but* `anat/T1w` — verified by
  listing them, not inferred. duckbrain correctly converts their BOLD, SBRef and
  fieldmap series, and the curator wanted none of it. On WMS that is 6
  descriptions across **56 sessions**, so ~336 unticks for one study. This is
  LCNI's own workflow, which makes it the strongest case the corpus can offer.
- **REV keeps one of two fieldmaps, every time.** Its canonical tree is otherwise
  complete (18 fmap, 42 bold, 6 anat), so this is not a curation-scope artifact:
  the protocol shoots `fieldmap1` and `fieldmap2`, the curator kept `fieldmap2`
  in 6 of 6 sessions, and duckbrain converts both. A recurring, description-keyed
  "we acquire this and never use it".
- **The control holds.** Where the curator converted everything — GAME,
  Dissonance, Crave_control, HOYA, JABBA — duckbrain shows *no* systematic
  disagreement at all. So there is no hidden class of junk duckbrain wrongly
  emits beyond the twin and SBRef defects above, both closed 2026-07-30.
- **Scouts, which prompted the question, already cost nothing.** `scout` is not in
  `EMITTED_CLASSIFICATIONS`, so a scout is never ticked; nor are the MPR
  reformats, vNav setters, ADC/FA/TENSOR maps, PhysioLogs or PhoenixZIPReport,
  which all classify `derived`/`physio`. On the ABCD session above that is 39 of
  53 series already free.

So build it, and motivate it by the anat-only curation rather than by junk
removal — which is now the *only* thing motivating it, the first pass having
gone to zero. Notes for whoever does:

- **Key it on *description*,** the same key `[task_mapping]` and `[series_types]`
  use, in its own section rather than as a `[series_types]` value — a datatype is
  a claim about what a series *is*, a skip is a decision about what to do with
  it, and collapsing them would make relabelling a series the only way to drop
  it. The read-modify-write shape is `save_project_series_types`; copy it.
- **Reaching the non-GUI path is the part with a decision in it.**
  `generate_session_config` takes `skip` as series numbers and its docstring
  says, correctly for today, that "nothing here reads it from the project
  config". A description-keyed skip resolves to series numbers only once the
  session is listed, so it has to be applied *inside* that function, next to
  where `type_rules` is applied — not passed in as `skip`.
- **Consider whether the anat-only case wants a coarser control.** Naming six
  descriptions to exclude is how a skip expresses "T1w only", and an
  include-by-datatype would express it in one line — but it is a different
  feature with its own failure mode (a study that adds a sequence gets it
  silently), so decide rather than drift into it.

**Folding the skip into the `Type` column as an `IGNORE` value was explored
2026-07-30 and rejected** — recorded here because it is the obvious
simplification and will otherwise be re-proposed. It would replace this whole
item with one `[series_types]` rule, and it does not work as a *classification*:

- **It would not reliably drop a fieldmap.** `detect_fieldmaps` selects on
  `classification == "fmap"` **or** `_is_fieldmap(description)`, and
  `generate_config` emits fieldmaps by walking `fieldmaps.groups` without
  consulting `classification` at all. What actually implements a skip is
  `generate_config(skip=…)` plus `_without_skipped_groups`, both keyed on series
  numbers — so `IGNORE` would bypass the mechanism it is meant to drive.
- **It cannot express the per-session case, which is real.** `fmap_eyeball`'s
  `sub-01` holds `cued_recall_encoding_run2` twice — aborted at 14 volumes and
  complete at 210, **identical descriptions**. Dropping the aborted one is a
  fact about that session; a description-keyed `IGNORE` drops both. The key that
  makes a rule generalize is exactly what makes this inexpressible, and an
  aborted run is common enough that the collision check exists for it.
- **It erases what the row is**, and the preflight needs both facts: that a
  dropped series was a *functional run* rather than a scout, that an SBRef was
  stranded by dropping only its BOLD, that unticking one fieldmap half took the
  whole pair. All read `classification` alongside the skip.

**The version that does work** keeps `convert` per-session and makes `ignore` a
project-level *skip flag* rather than a classification — leaving the inferred
datatype intact, so detection, the checks and the series-number `skip` set all
keep working. Which reduces the question to spelling: `[series_types]` with
`type = "ignore"`, or its own `[series_skip]` section. Own section is the
current lean, because every value in `[series_types]` is today a
datatype-and-suffix that something emits, and the one member that isn't reads
later as a bug.

**Deferred until `#16`'s expectations/manifest layer takes shape** (Ben,
2026-07-30), and the reason is worth keeping: "which series this study converts"
may not be a config toggle at all but a *statement of intent*, which is what
`[expected]` already is and the only such statement duckbrain has
(`core/expectations.py`, `docs/sanity-checks.md`). If the skip belongs there, the
spelling question above answers itself and the separate section never gets built.
Decide that before writing either one.

### `#13.2` — Check a planned filename against the schema, before submitting

Inherited from `#15` when that closed 2026-08-03. `bidsschematools` (pip)
validates a *filename* against the BIDS schema with no dataset present, which
would let every row of the Conversion Plan be checked before a job is submitted
rather than after one has run. It can say whether
`sub-001_task-x_run-1_bold.nii.gz` is legal BIDS; it cannot say that
`div_perFace_r1` means task `divPerFace` run 1 — that inference is study-specific
and is what duckbrain's heuristics are *for*. Complementary to the dataset
validator, not an alternative to it.

It lives here rather than under `#15` because it is plan-time, and **`#15`'s own
advice about where it fits — "`core/consistency.py` is where a wrapper fits" — is
stale.** The plan-time check surface that actually exists is `plan_warnings` (via
`conversion_plan.py`, expanded in `docs/conversion-legibility.md`), which is this
item's subject, and a finding belongs in the plan table beside the row it is
about, not in a panel two pages away.

---

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

---

<a id="19"></a>
## #19 — Conversion coverage: what the LCNI repository still shows missing

Validated against `/projects/lcni/dcm/repository` — 15 studies, 189 distinct
series descriptions, 112 sessions paired with the BIDS the LCNI curator produced.
**Treat that corpus as the fixture for anything in this section** — it is
read-only, and it is the only place these cases exist together. Write scratch
output to `/projects/hulacon/bhutch`.

**Agreement against the canonical tree is a dated measurement, never a standing
claim, and canonical is not an oracle** — it holds illegal subject labels
(`#19.5`), it silently kept one of two fieldmap pairs on six sessions (`#19.6`),
and LCNI says many of its anatomicals are missing. Three independent ways it is
wrong, so "matches the curator" has never been a correctness argument on its own.
**What gates instead is duckbrain's own frozen inventory**, diffed before and
after a change with every difference triaged rather than counted — independent of
a tree someone else is editing. `#19.7` carries the numbers and the re-measure
protocol.

**`#19.8`, `#19.9` and `#19.1` all closed 2026-07-30**, and what they leave behind
is an instrument: a before/after sweep that classifies every session in *both*
trees and diffs each dimension a change could move — classification, planned
files, plan warnings, fieldmap groups, fieldmap warnings, `nd_twin_bases`, drop
notices. Assume it for anything in this section. It is what caught the pMAP101
third anatomical the unit tests could not, and it is what let all three changes
prove the corpus untouched rather than assert it. It is **not** in the repo and
has been rebuilt from scratch three times; if a fourth item in this section needs
it, that is the point to stop rebuilding and commit it.

**The sweep's "plan warnings" dimension is wider since 2026-08-03 (`#22`), and a
rebuild has to opt into it.** `plan_warnings` takes `probes=` and grows
`pe-collinear` and `pe-direction` from it, but *only* when a caller passes one —
absence skips both silently, by design. So a harness that calls `plan_warnings`
the old way is not measuring the same thing the GUI and the bulk path now
measure, and a diff against the frozen baseline will look clean for the two
dimensions most likely to move. Pass the container:
`by_series_number(probe_session([s.path for s in series], sif))` at ~0.5 s per
session, which is noise against the header reads the sweep already pays for. The
baseline itself predates the probe, so the first sweep that turns it on should
expect new warnings and triage them rather than read them as a regression.

**The beta tester's tree at `/projects/hulacon/shared/mmmsourcedata` is the live
fixture two items here had none of.** It carries `cmrr_diff_3shell` in **four**
phase-encoding directions — `ap`, `pa`, `rl`, `lr` — which is what let `#19.1`
convert diffusion against real multi-shell data with an SBRef per direction, and
what supplied `#19.2` its two measured `PE_FOR_DIR` rows. Read-only; symlink at
the `dicom` level rather than pointing `sourcedata_dir` at it. `#19.1` staged it
alongside an LCNI `Round_Robin` session at
`/projects/hulacon/bhutch/dwi_eyeball` — two scanners and two naming
conventions, because one fixture lets a CMRR-specific assumption pass.

The rest, in the order the corpus argues for:

### `#19.10` — What diffusion still doesn't take part in

`#19.1` gave `dwi` an emission path (ledger). Three things it deliberately left,
each because doing it now would have been a guess:

- **No `B0FieldSource` on a diffusion series.** duckbrain runs no diffusion
  preprocessing, so nothing consumes it; `_assign_fmap_group` is keyed on
  `(task, run)` and diffusion has no task; and the nearest-in-time binding is
  validated for BOLD only. The decisive reason is reviewability, though:
  `resolve_fmap_assignments` filters `role != "bold"`, and that is what the
  Conversion page's `fieldmap` column renders from — so a binding chosen in the
  emitter would be applied silently and could not be overridden. Doing it before
  a consumer exists is writing metadata nothing reads, in a column nothing shows.
  **This now belongs to `#7.2`**, which was scoped 2026-08-01 and is the
  consumer: QSIPrep reads `B0FieldSource`, so it is the item that can say what
  the right binding *is*. Cross-referenced from `docs/pipeline-extras.md` §9.
- **`[expected]` cannot say how much diffusion a session should hold.**
  `expectations.py` counts anat suffixes, fieldmap pairs and task runs; a `dwi/`
  tree is invisible to it, and `checks.py`'s shortfall arithmetic is anat/func
  only. That is `#16`'s layer and belongs with whoever next opens it — note
  `[expected]` is opt-out by default, so nothing regresses meanwhile. The
  *surveyor* needs nothing: `_converted_status` counts per datatype directory
  against the saved config's description counts, so it picked `dwi/` up for free.
- **NORDIC does not stage `dwi/`.** NORDIC is a BOLD denoiser; this is a note that
  the omission is deliberate, not an oversight to find later.

**One thing `#22` leaves sitting here for `#7.2`.** `SeriesProbe` already carries
`total_readout_time` and `effective_echo_spacing`, read for free from the same
sidecar and consumed by nothing today. Both are what QSIPrep wants from a
diffusion acquisition. That does not move the `B0FieldSource` bullet above — that
one is blocked on a *consumer*, not on information — but it means the field is
readable at plan time when the consumer arrives, without a second pass over the
DICOMs.

**This is the prerequisite for `#7` item 2 (QSIPrep).** That stage has nothing to
read until DWI converts, and the missing canonical output above is inherited
whole: QSIPrep validation would be internal consistency plus "the tool accepts
it", not the curator comparison every other conversion capability got. Scoped in
`docs/pipeline-extras.md` §1.

### `#19.2` — Phase-encoding directions other than AP/PA

**Narrowed by `#19.1` (2026-07-30), which had to widen the vocabulary to emit
diffusion.** Two of the three hardcodings are gone: `_DIRECTION_TOKEN` now reads
`ap|pa|rl|lr`, and `PE_FOR_DIR` carries all four. What is left is **fieldmap
*pairing***, and it is one named constant plus one function:

- `dicom_inspect._PAIRABLE_DIRECTIONS` — `detect_fieldmaps` recognises an LR/RL
  direction and then declines to pair it, saying so in its own warning rather
  than the old "cannot determine". Deleting that constant is the change.
- `_extract_fmap_group` still strips only `ap|pa` from a group name, so widening
  the gate without widening it too would split one pair across two groups.

**Still deliberately not done speculatively**: neither fixture holds an LR/RL
*fieldmap*, so there is nothing to validate the emission against. What `#19.1`
did give this item is the two `PE_FOR_DIR` rows — `RL`→`i`, `LR`→`i-` — measured
on diffusion at two independent sites, which is the part that used to be
unguessable. They are the table's weakest rows and are checked both at plan time
and after conversion, so a site where they invert says so.

**What changed 2026-07-24 (`#22`): the direction is no longer a guess we can't
check.** dcm2niix reports a *signed* `PhaseEncodingDirection`; the raw tag
`InPlanePhaseEncodingDirection` gives `ROW`/`COL` with no polarity and is absent
on XA30 entirely, so the `_ap`/`_pa` name token was genuinely all duckbrain had.
It is right for all 32 name-tokened fieldmaps in the corpus — but that is now
*measured* rather than assumed.

**Correction, 2026-07-30 — "read the probe instead of widening `PE_FOR_DIR`, then
delete the table" was wrong, and `#19.1` did the opposite.** That sentence
confused emission with checking. No emitter reads `PE_FOR_DIR`; its only two
consumers (`plan_warnings`' `pe-direction` and `consistency._check_pe_direction`)
exist *to compare a name-derived label against the probe*. You cannot replace
"compare the name to the probe" with "read the probe" — that deletes the check,
not the table. The table is a statement of the **naming convention**, and it
survives this item.

**The two fixtures, and the gap that has not closed.** `mmmsourcedata` and the
corpus's `Round_Robin` between them hold LR/RL *diffusion*, which is what made
the `RL`→`i` / `LR`→`i-` rows measurable. Neither holds an LR/RL *fieldmap*, so
the pairing this item is about still has nothing to validate against. `#19.9`
removed the ordering constraint (the `rl`/`lr` diffusion references escaped
pairing only through going unrecognised; they now classify `dwi` on their
sibling's authority and never reach `detect_fieldmaps`), so this is unblocked —
it is waiting on data, not on other work.

**Two things `#22`'s wiring (2026-08-03) changes about that wait.**

*There is now a partial oracle, so "nothing to validate against" is too strong.*
`pe-collinear` is deliberately **orientation-free** — it asks only that the two
halves' signs differ on a shared axis and never consults `PE_FOR_DIR` — so it can
confirm that an LR/RL pair genuinely opposes without a canonical tree to diff
against and without the AP/PA convention holding. That is not a full validation
of the *emission* (it says nothing about whether the `dir-` label is the right way
round), but it is exactly the property pairing exists to guarantee, and it costs
nothing extra to have.

*And the weakest rows now announce themselves.* `pe-direction` compares the
name-derived label to the scanner and, since `#19.1`, covers `dwi` — which is the
only thing that exercises the `RL`/`LR` rows. Until 2026-08-03 that check had no
caller, so a site where those rows invert would have said nothing. It now fires at
preflight *and* post-conversion, so the first real LR/RL dataset reports the
disagreement rather than converting quietly. Whoever picks this up should
therefore look for `pe-direction` warnings first: on a site where R→L reads `i-`
(the first-principles reading these two measured rows contradict), that is the
signal, and the fix is the table, not the pairing.

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

### `#19.6` — Gradient-echo (GRE) fieldmaps: what is still open

**The two defects LCNI's report surfaced are fixed (2026-07-24, see the ledger),
and the mispairing concern that prompted the look was unfounded** — pairing is
header `ImageType` plus an identical `SeriesDescription` plus ordering, never
`SeriesNumber + 1`. What stands:

- **`phasediff` is the only GRE flavour implemented, and the only one present.**
  No BIDS Case-2 (`phase1`/`phase2`) or Case-3 (`_fieldmap`) data exists in the
  corpus. `EchoTime1`/`EchoTime2` are deliberately left to dcm2niix rather than
  injected.
- **Two fragilities left standing, neither observed in the corpus**, both of which
  drop a fieldmap *with warnings* rather than silently: a phase series that
  *precedes* its magnitude (the pairing requires the phase to sort after), and
  halves whose `SeriesDescription` differs (e.g. `gre_field_mapping` vs
  `gre_field_mapping_phase`). A magnitude split into two single-echo series also
  fails, since a magnitude is recognised by `len(echo_numbers) > 1`. Worth a
  decision, not a speculative fix — there is nothing local to validate against,
  which is `#19.2`'s reasoning.

  **The probe changes what is available here, and it is the reason to reopen this
  (measured 2026-08-03, after `#22` wired it in).** Both fragilities are name- and
  order-dependencies, and the probe answers both from the single file it already
  reads. On `Crave_control/CC052` and `Dissonance/EUG027`, through the pinned
  container:

  | | magnitude (#5) | phase (#6) |
  |---|---|---|
  | `ImageType` | `ORIGINAL PRIMARY M ND NORM` | `ORIGINAL PRIMARY P ND PHASE` ← |
  | `EchoTime` | `0.00437` | `0.00683` |
  | `EchoTime1`/`EchoTime2` | absent | `0.00437` / `0.00683` |

  Two usable joins fall out. The explicit `PHASE` token names which half is which
  **regardless of series order**, which is the first fragility outright. And the
  phase sidecar's `EchoTime1` *equals the magnitude's `EchoTime`* — dcm2niix
  reconstructs both echo times from the phase series alone — which is a
  **content-based link between the halves that never reads their names**, and so
  is the second fragility.

  **Why that specifically matters: it is additive, not a loosening.** The bullet
  below is this item's real constraint — relaxing the identical-`SeriesDescription`
  match to fix the `gre_field_mapping` case would merge the `_ND` and non-`_ND`
  reconstructions and pair a corrected magnitude with an uncorrected phase. Echo-time
  agreement is *extra evidence* admitted alongside the name match rather than in
  place of it, so the ND behaviour that depends on the strict match survives
  untouched. That is the shape any fix here should take.

  **What still blocks it, and it is a weaker blocker than before.** The corpus
  holds no session actually exhibiting either fragility, so there is a local
  oracle now but still no failing case — "no evidence available" has become "no
  failing case available". Both readings above rest on two LCNI sessions running
  what looks like one `fieldmap_2mm` protocol, so confirm on a second site
  (`mmmsourcedata`) before building on them. Note also that `EchoTime1`/`EchoTime2`
  are the same values the bullet above deliberately declines to *inject* — reading
  them to decide pairing is not the same act as writing them into a sidecar, and
  that distinction should stay explicit in whatever lands.
- **Pairing on an identical `SeriesDescription` is load-bearing for a second
  reason, so any loosening has to preserve it.** It is what makes
  `nd_duplicates = "both"` work with no fieldmap-specific code at all: the two
  reconstructions are named `fieldmap_2mm` and `fieldmap_2mm_ND`, so they fall
  into separate groups, take separate `acq-` entities from the existing
  multi-pair machinery, and end up as two independent `B0FieldIdentifier`s.
  Loosening the match to fix the `gre_field_mapping` case above would otherwise
  merge the two reconstructions into one group and pair a corrected magnitude
  with an uncorrected phase — precisely the mispairing LCNI reported from another
  converter.

### `#19.5` — Subject labels the corpus contains but BIDS forbids

`sub-DIPPER_007`, `sub-hoya_01`, `sub-AEPET2_55`, `sub-NAGL_28` all carry an
underscore, which is not a legal BIDS label — the filename then re-parses as an
extra entity. duckbrain's `_sanitize_label` already strips these on ingestion, so
this is not a duckbrain bug; it is a note that the *canonical* trees in that
repository are not all valid, so "matches the curator" is not by itself a
correctness argument.

### `#19.11` — Is `_fmap_description`'s manual entity ordering already redundant?

Inherited from `#15` when that closed 2026-08-03, and it is a check-then-probably-
delete, not a feature. dcm2bids reorders `custom_entities` per the spec unless
`--do_not_reorder_entities` is passed, which duckbrain does not pass — so
`_fmap_description`'s hand-written acq/dir/run ordering may be doing work dcm2bids
would do anyway. Harmless either way; worth resolving *before* anyone adds more of
it. Confirm against the pinned container's source, then either delete the ordering
or leave a comment saying why it stays.

### `#19.12` — Should an unequal ND/corrected pairing be refused, not truncated?

**Surfaced 2026-08-04 by `#18`'s `B905` pass, and deliberately not answered
there** — it is behaviour, and a lint commit is the wrong place to change
behaviour. `_nd_twin_groups` in `core/dicom_inspect.py` zips the ND side against
the corrected side after sorting both by series number, so when the two come in
unequal numbers the surplus is silently dropped from the group. Its own docstring
authorizes that ("a surplus on either side when the two do not come in equal
numbers"), which is why the zip now reads `strict=False` with a pointer to that
paragraph rather than raising.

The question is whether the docstring is right. A surplus **ND** series left out
of the group is never demoted, so under the default `corrected` policy it
converts anyway — as an extra anatomical alongside the pair the policy chose.
That is the exact symptom of the third pairing defect
(`memory/nd-duplicate-reconstructions`): pMAP101's 1008 went unclaimed and
"converted as a spurious third anatomical under every policy including the
default". That defect was closed by pairing in acquisition order, which fixes the
*equal*-length many-to-one case; the unequal case still reaches the same outcome
by the other route.

**Nothing exercises it.** Walking all **166** sessions of
`/projects/lcni/dcm/repository/dicoms` and bucketing by `_ND_STRIP`'s base
exactly as `_nd_twin_groups` does gives **52** twin base-groups that have a
counterpart at all, and **0** of them unequal (measured 2026-08-04). So there is
no fixture, and any change here needs a unit test as its only oracle — the same
position `memory/nd-duplicate-reconstructions` records for ND fieldmaps
generally, where the corpus also cannot validate. Decide it as a policy question
(refuse and report, versus demote the surplus, versus keep truncating and say so
in the plan's drop notices), not by whichever is easiest to code.

Note the 52 is base-*groups*, not sessions, so it is not the 46 twinned sessions
`#19.7` counts nor the ledger's "52 corpus sessions" — three different
denominators that happen to collide on a number.

### `#19.7` — Re-measure agreement once LCNI re-converts the anatomicals

**The number, and why it is frozen.** As of 2026-07-24 duckbrain reproduced 391
of the 392 canonical files — the miss is `anat/T1wa`, a curator typo and not a
valid BIDS suffix. LCNI reported that same day that many anatomicals in the
repository are missing and will be redone, in exactly the datatype `#19.6` and
the ND work touch. So the canonical anat denominator is about to move: **391/392
must be re-measured rather than carried forward**, it must not be quoted as
current, and a lower figure afterwards is not by itself a regression.

When the re-conversion lands: re-run the corpus harness, diff duckbrain's own
inventory against the frozen baseline first (that is the regression gate), and
only then compare against canonical — treating each *new* disagreement as
something to triage rather than a score to restore. Expect the ND work to show up
here: `both` doubles the anatomicals, and `corrected`/`uncorrected` change which
source series a given `T1w` came from without changing its name, so a filename
diff is the wrong instrument for that part.

The one thing worth asking the curator directly is which reconstruction their
re-conversion keeps. If they keep the `_ND` copy where both exist, duckbrain's
default (`corrected`) will disagree on every twinned session — **46 of the 166**,
re-counted 2026-07-30 with `nd_twin_bases`, one twin base each — and that would be
a *default* to reconsider, not a bug to fix. (This line said 47; the ledger's
"52 corpus sessions" is a different quantity — sessions that gained a drop
*notice*, which is not only the twinned ones.) Re-confirmed unchanged the same
day by the twin-guard sweep, which is what makes 46 a measurement rather than a
carried-forward number: narrowing the guard moved nothing on the corpus.

---

<a id="33"></a>
## #33 — Widen the type-checked surface

`#18` closed with mypy gating three modules and the ruff ruleset at `B`/`E`/`F`/
`FIX`/`I`/`TD`/`UP`/`W`. Both were deliberately stopped at what could be gated
*today*, and everything left over was filed here.

**`#33.1` and `#33.3` are closed (2026-08-06); what is open is `#33.2` and one
new question.** All of `gui/` is gated — 23 source files against the original
three — two mypy knobs this item had declined are on, `RUF100` is on, and every
remaining ruleset has a recorded verdict.

**Read the file list and the ruleset from `pyproject.toml`, not from here**, and
**re-measure before changing either.** The reason `#18` landed green is that the
config was set after measuring — and this item is now **six for six** on its own
estimates being wrong, every one of them in the direction of deferring work that
was already tractable: `pipeline.py` (filed as blocked, cost 9 signatures),
`disallow_untyped_calls` (filed as repo-wide-or-nothing, 0 errors),
`warn_return_any` (filed as pandas-noisy, 3 errors and one live bug), the pages
(filed as a third-party-stub project, and the 115 errors contained no stub
complaint at all), and then twice more inside `#33.1` itself — see its ledger
row. A deferral written without a number behind it is worth re-measuring before
it is inherited.

### `#33.4` — The rest of `core/`, measured but not scoped

**36 errors across 13 modules** (2026-08-06, against the configured knobs). Not
started, and unlike `gui/` this one really does have a third-party component:
`plotly.offline` ships no stubs and no `py.typed`, so `qc_report.py` needs that
answered rather than annotated. Measure before scoping — the whole record of
this item says the number will not be what a reading of the code suggests.

One shape is already known and is *not* a bug: `checks.py:174` reads as
`int > None` because `Expected` is one dataclass serving two roles, the
*declared* prescription (where `fmap_pairs=None` means "not declared") and the
*observed* count (where `_fmap_pair_count` always returns an `int`). Splitting
the two, or narrowing at the boundary, is the fix; silencing the comparison is
not.

### `#33.2` — `disallow_any_generics`, and the dcm2bids description dicts

**The two knobs filed alongside this one are done — both were declined on a
guess and both measured free** (2026-08-06, and see the config for each). That
is the reusable lesson here: a decline recorded without a number is worth
re-measuring before it is inherited.

- `disallow_untyped_calls` was "effectively repo-wide-or-nothing". It is **0
  errors** — `follow_imports = silent` reads types rather than discarding them.
  Enabled.
- `warn_return_any` was "noisy against untyped pandas". It was **3 errors, none
  of them pandas**, and one was a live bug in the function the note used as its
  example: `consistency._read_json` promised `-> dict` and returned whatever
  `json.load` gave it, so `null` / `[]` / a bare string — valid JSON, not
  sidecars — defeated the `except ValueError` written to absorb exactly that
  case and raised `AttributeError` at the caller. Fixed, tested, enabled.

**`disallow_any_generics` itself is still real work: 90 errors.** The shape is
unchanged, and so is the reason it is a design project rather than a config
line. The dcm2bids **description dicts** are the real content — heterogeneous
literals built and then conditionally extended (`dcm2bids_config.py` ~`:836`),
then chain-subscripted downstream (`d["criteria"]["SeriesNumber"]`,
`desc["sidecar_changes"]["B0FieldSource"]`). Typing them properly means real
`TypedDict`s with optional keys, i.e. `NotRequired`, which the 3.10 floor cannot
have without adding `typing_extensions`. Weigh that before starting.

**But not every bare `dict` in the 90 is one of those, and the cheap ones are
worth taking first.** `FieldmapDetection`'s four fields were bare `dict`/`set`
and are now `dict[str, dict[str, int]]`, `dict[str, str]`, `dict[str, float]`,
`set[str]` — homogeneous maps, no `TypedDict` needed, and typing them is what
cleared two of the three `warn_return_any` errors above. Sweep for that shape
before opening the `typing_extensions` question; the count that makes this look
like one big decision is mostly not one.

### `#33.3` — Rulesets measured and judged

Everything is measured now (2026-08-06, counts against the configured `select`,
so they are what enabling each would actually cost). `RUF100` was enabled and is
the only one that paid. **Recorded so nobody re-measures, and so nobody re-opens
a decline without new evidence.**

| | findings | verdict |
|---|---|---|
| `ARG` | 309 (14 in `src`) | **declined** — it fires on the `#29` fix |
| `N` | 57 (15 in `src`) | **declined** |
| `D` | 1274 | **declined** |
| `PTH` | 30 | **declined** |
| `RUF` (ruleset) | 37 | **declined**, except `RUF100` (9) — **enabled** |
| `C4` | 36 | **declined** |
| `PERF` | 23 | **declined** |
| `SIM` | 16 | **declined** |
| `RET` | 3 | **declined** |

`D` (pydocstyle) is declined for the reason it always was: a four-figure
docstring-*format* diff across a codebase whose docstrings are its best feature
is a net loss, and the rules are about punctuation and mood, not content. (The
`235` this item used to record was a subset; the ruleset is 1274.)

`PTH` was the one this item predicted would be worth it, and measuring says no —
but the *shape* of the finding is the useful part. `PTH` exists to catch string
path handling: `os.path.join`, `os.path.exists`, manual separator arithmetic.
This repo has **zero** of those. All 30 findings are `open(p)` → `p.open()` (23)
plus a tail of `os.chmod`/`os.replace`/`os.symlink`/`os.listdir`. The codebase
already passes the rule's substantive test and what remains is its cosmetic
half, so enabling it buys a 30-line diff and no defect.

The rest, each checked at the site rather than by count — this is the part that
would otherwise get re-litigated:

- **`SIM115`** (open-without-context-manager, 1) reads
  `tempfile.NamedTemporaryFile(delete=False)` in `slurm/submit.py`. The handle
  *is* closed and `delete=False` is load-bearing (sbatch reads the file after).
  A false positive, and it was the single most promising finding in the batch.
- **`RUF001`–`RUF003`** (12) are not the em-dash false positives you would
  expect — ruff does not flag `—`. They are EN DASH, MINUS SIGN, and the GUI's
  deliberate `➕` / `ℹ` / `×` button glyphs. Nothing is compared against them.
- **`RUF015`/`RUF059`/`RUF012`** (13) are entirely in `tests/`. `RUF015` would
  make assertions *worse*: `[x for x in … if …][0]` failing with `IndexError`
  says more at a test failure than `next(…)` raising `StopIteration`.
- **`C4`** is 32× `dict()` → `{}`; **`PERF`** is 14 manual list comprehensions
  and 9 `try`/`except`-in-loop, which is the correct shape where it appears;
  **`RET`** is 3 named returns that are named on purpose.

**`ARG` is the one to re-read before anyone re-opens it, because the raw count
argues the opposite way.** Split `src` from `tests` first (the `#18` precedent:
39 of 44 `B905` hits were one shape in one test file) and it drops from 309 to
14 — a number small enough to check by hand, which is what settles it. All 14
are deliberately unused, and **five are unused *on purpose, for correctness*:**
`_inspect_labels_cached(path, mtime, size)` and `ensure(…, mtime, size)` take
their cache key as arguments an `lru_cache` hashes and the body never reads, and
the three `fingerprint: tuple` parameters in `qc_panels` / `conversion_panels`
are **the fix that closed `#29`** — the one whose whole content was that
`_fingerprint` with a leading underscore is silently dropped from Streamlit's
cache key, so a re-run of MRIQC served a stale DataFrame until the server
restarted.

So `ARG001` would point at those five and say "delete this", while
`tests/test_streamlit_caches.py` exists to forbid the only other spelling. A
gate that argues against a fix the repo shipped, and against a test written to
hold it, is worse than no gate. The remaining nine are `pipeline.py`'s four
uniform `StageSpec.build` signatures and `domains_for_modality(modality)`, whose
docstring states in full why it ignores the argument.

Two real-but-minor things `ARG` did surface, left alone deliberately rather than
folded into a linting commit: `core/ingestion.py`'s `plan_ingest` takes a
`sourcedata_dir` it never reads (an API question, not a bug), and
`0_Project_Status.py`'s `_stage_params` docstring says "subject/session gate
options" when only `subject` does.

`N` is declined on shape rather than judgment: **10 of its 15 `src` findings are
`N999` on the Streamlit page filenames**, and those names are Streamlit's
multipage API — the leading digit *is* the sidebar ordering. Silencing ten
findings by `per-file-ignores` to keep three exception-naming opinions
(`InvalidLabel` → `InvalidLabelError`) is not a trade worth making.

---

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
- ✅ **Where the env lives — answered, with a precedent to copy.**
  `~/.conda/envs` is per-user and invisible to others (`/home/bhutch` is
  `drwx------` — the same wall `#2` hit with the containers), so a shared
  `--prefix` it is: **`/projects/hulacon/shared/envs/<name>`**. That parent is
  `drwxrwsr-x` and setgid, so one build serves the PIRG. It was empty until
  2026-08-04, when **braintwill** built the first one there and wrote the recipe
  up in `docs/talapas-conda.md` (repo: `…/shared/mmmdata/code/braintwill`).
  Its `scripts/setup_env.sh` transfers, and so does the channel handling — but
  take the **working** version, because the first attempt there was wrong and
  this item currently plans the same mistake.

  🔴 **`conda env create -f environment.yml` cannot be made safe on Talapas.**
  Checked 2026-08-04. It accepts no channel flags at all and merges the file's
  `channels:` with the condarc ones, so it resolves against FSL's channel *and*
  `defaults`. Two plausible workarounds also fail: pointing `$CONDARC` at a clean
  file **adds** to conda's search path rather than replacing `~/.condarc`, so
  FSL's `#!final` channels still apply; and `CONDA_CHANNELS` is outranked by
  `#!final` too. What works is `--override-channels -c conda-forge` on a plain
  `conda create`/`conda install`, so braintwill's script reads the package list
  out of `environment.yml` itself and never calls `conda env`. Verify with
  `conda config --show channels`. Note the giveaway, which is the reusable
  lesson: the check that "confirmed" the `$CONDARC` trick had
  `--override-channels` on its command line, so the flag did the work while the
  mechanism under test did nothing.

  That script ends by asserting nothing resolved off conda-forge and *failing* if
  anything did — worth copying, since that assertion is the only thing between
  this landmine and a silently contaminated env. One caveat if duckbrain keeps a
  `pip:` section: the script refuses to run against an `environment.yml`
  containing one rather than installing a subset and reporting success, so a pip
  step has to be added deliberately.

  Two more findings from actually building it, both of which apply to any
  pip→conda migration and neither of which the channel work would have caught:

  - 🔴 **A resolved dependency is not a verified one — conda-forge has name
    collisions that solve cleanly.** braintwill asked conda-forge for `himalaya`
    and got version 1.2.0, which installs a single binary and no Python package
    at all, from unrelated software. `import himalaya` failed at runtime behind a
    clean solve, a green channel-purity check, and a plausible `conda list` row;
    the real library is PyPI-only at 0.4.11. The tell was the version *lineage*
    (1.2.0 vs 0.4.x is not one project's history). Since `#20` moves eight
    packages off pip, **check each resolved version against what pip currently
    gives**, and end the setup script by importing every one of them — that
    import is what caught this, nothing earlier did.
  - 🟡 **An incremental solve is not a fresh one.** Re-running the setup against
    an existing prefix moved nilearn 0.14.0 → 0.13.1 while scikit-learn went the
    other way; deleting the prefix and rebuilding restored both. Fine in a
    working env, not fine in a committed lockfile, which is supposed to describe
    what a new user gets. If `#20` ships a lockfile, generate it from a clean
    build.

  Still a distribution decision in the `#2` sense — who else gets told about
  it — but the location question is closed.

  Two corrections to the findings above, from that build. **`pkgs_dirs` is not
  pinned solely to the read-only FSL path** — `~/.conda/pkgs` is listed first, so
  the cache problem is milder than stated, though naming `CONDA_PKGS_DIRS`
  explicitly is still right. And **conda-forge now has ruff 0.16.1**, so the
  `ruff>=0.16,<0.17` pin may be satisfiable there after all; recheck before
  assuming the dev extra must stay on pip.

  Note braintwill deliberately runs **Python 3.12 / pandas 3.0.5 / numpy 2.5.1**,
  not duckbrain's 3.11. That is not a divergence to reconcile: the two repos
  share no imports, and one env across the ecosystem was considered and rejected
  — mmmdata sits on pandas 2.3.3 and merging would force a side. See the
  "cross-repo conventions" section of that doc.
- CI (`.github/workflows/ci.yml`) is a separate call: GitHub runners have no FSL
  condarc and pip works fine there, so switching CI to conda buys little and
  costs solve time on every push. Leaving CI on pip while users get conda means
  the gate no longer tests the path users take — say which trade-off was taken,
  in the commit.
- Update `README.md`, `QUICKSTART.md` and `CLAUDE.md` together; five places
  currently instruct `python -m venv .venv`.

---

<a id="36"></a>
## #36 — The memory headroom is a constant; the overshoot it covers scales with `--nprocs`

`config.tool_mem_gb` holds back a flat `MEM_HEADROOM_GB = 8` so a node that
overshoots its target dies inside the allocation rather than being OOM-killed.
That constant was measured against **one** overshooting node. It is not one: the
overshoot is per *concurrently running* node, and `--nprocs` is what sets how
many there are.

**The evidence, from a beta user's real runs on `/projects/hulacon/shared/mmmduck`
(2026-08-04 and again 2026-08-06, unchanged in between).** Fourteen MRIQC jobs at
the shipped defaults — `#SBATCH --mem=32G`, `--mem-gb 24`, `--nprocs 4` — of which
nine were `OUT_OF_MEMORY` and two more finished within a gigabyte of the wall.
Every failure is synthstrip, MRIQC's torch brain extraction, and `slurmstepd`
reports **two `oom_kill` events in a single step** on `mriqc_06_01`: nodes
`synthstrip.a0` and `synthstrip.a1` were resident together and the cgroup took
both. `sacct` `MaxRSS` across the fourteen runs is 17.7–31.5 GB against a 32 GB
allocation, and `MaxRSS` is polled, so the true peaks are higher than that.

Both the anatomical and the functional workflow do it — `anatMRIQC.synthstrip_wf`
on `mriqc_06_01`, `funcMRIQC.synthstrip_wf` on `mriqc_07_02` — so the docstring's
"MRIQC's functional synthstrip" is narrower than the behaviour.

**What is not yet known, and has to be measured before anything is changed.**
Whether nipype's scheduler is even the right lever: `MultiProc` admits a node when
both a process slot and its *declared* `mem_gb` estimate fit, and if synthstrip's
declaration is the 0.2 GB default then the memory budget never binds and
`--nprocs` is the only real cap. If that is so, raising the allocation cannot
increase concurrency (the process cap is unmoved) and is a safe remedy, while
raising `cpus` is a memory decision wearing a throughput label — which is worth
saying on the widget, and is currently said on neither.

**Do not just raise the constant.** 8 GB is right for one overshooting node, and
a bigger constant is wrong for a different `nprocs` in the same way. The shapes
worth weighing: derive the headroom from `cpus`; declare a real `mem_gb` on the
synthstrip node so the scheduler serialises them itself; or leave the number
alone and have the GUI refuse — or warn about — a `cpus`/`memory` pair that
cannot hold that many synthstrips, which is the option consistent with *a
silently-degrading option is worse than one that fails*.

The immediate remedy shipped 2026-08-06 and is not this item: both numbers are
now editable from the MRIQC tab, so the user can raise the allocation without
hand-editing TOML. This is about the default being wrong for a four-process job
in the first place.

---

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

---

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

---

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
- **bold→fmap linking binds by acquisition time** (since 2026-07-24) — the rule,
  its precedence over a declared `[fmap_mapping]`, and the one residue (a tie,
  when a session shoots two pairs back-to-back) are all in `#19.3`. Nothing about
  it is an accepted edge any more; it is live work with a live home, and this
  bullet asserted the *opposite* rule for three days after the change landed,
  which is why it now points instead of restating.
- **`se_epi_2.5mm_ap` reads as a named group `2.5mm`** — the resolution token
  becomes the group name. Harmless (divatten/PSY607 shoot one pair) and left
  alone on purpose: renaming it would change the `B0FieldIdentifier` of
  already-converted data for no functional gain.
- Task rules are dataset-wide; there's no per-subject *rule* scoping. Per-subject
  *edits* already cover the exception case.
- `directory_picker` is dirs-only; `fs_license` stays a text field. File-mode
  deferred until something needs it.

---

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

---

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

---

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

---

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

---

<a id="7"></a>
## #7 — Pipeline extras: candidate stages

Each is its own focused effort. Full annotated backlog — candidate tools, ties to
existing duckbrain/mmmdata work, open questions per item — in
**`docs/pipeline-extras.md`**. Items 4 and 6 are **partly built** and say so
below, item 2 is **scoped but unstarted** (`docs/pipeline-extras.md` §1); the
other five are unstarted.

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
2. **DTI/DWI preprocessing** — orthogonal modality branch, **QSIPrep**.
   **Scoped 2026-08-01, not started; the full write-up is `docs/pipeline-extras.md`
   §1** — read it before starting, it is where the traps are. Headline: two
   independently shippable slices, **A** a launchable + tracked stage (~2–3 days)
   and **B** QC-dashboard ingestion (~2.5–3 days), and A is a real stopping point.
   The stage plumbing itself is a short checklist and the cockpit board needs
   nothing, so the cost is not where you'd expect it. It is in three places:
   QSIPrep **merges** DWI runs that share a warped space, which makes
   `surveyor._grade`'s superset rule false forever and needs a new
   coarser-key grader; per-session jobs **silently clobber each other's anat**
   unless `--subject-anatomical-reference sessionwise` is forced; and
   `--output-resolution` is required with no defensible default, so it must raise
   rather than guess. **Its prerequisite `#19.1` is met** (closed 2026-07-30 —
   DWI converts, with `.bval`/`.bvec`, validated on two scanners), and it hands
   this item one open decision: a diffusion series carries no `B0FieldSource`,
   because nothing consumed it and the binding is keyed on `(task, run)`, which
   diffusion has neither of. QSIPrep is the consumer that makes it answerable.
   Two smaller findings worth having
   either way: QSIPrep is **not** a forcing function for `#5b` Case 3 (it has no
   anat-reuse flag, and its ACPC/LPS+ anat is not fMRIPrep's anyway), and the QC
   layer already claims `dwi` for three measures MRIQC does not emit for it — see
   §1's "pre-existing inaccuracy".
3. **Scanning-notes integration** — input-shaping producer (exclude bad runs via
   bids-filter/`scans.tsv`); reuse mmmdata `build_manifest`/`sessions.tsv`.
   **This is also where `events.tsv` would come from** (inherited from `#15`,
   closed 2026-08-03). The BIDS validator warns `EVENTS_TSV_MISSING` on every
   task scan and always will: onsets are not in the DICOMs, so duckbrain has
   nothing to derive them *from* and must not invent them. It is a real gap and
   it is this item's, not validation's.
4. **QC norms & best-practice dashboard** — consumer of fMRIPrep+MRIQC; layer norms
   on the existing surveyor/QC pages. **Largely built: all three slices landed
   2026-07-24 (ledger), and `#24` regrouped the result by the question being
   asked.** The plan, the two corrections real data forced, and the decisions
   settled so they are not re-argued are in `docs/qc-dashboard-migration.md` —
   Streamlit stays the control plane and only the QC *report* becomes a document
   (one renderer, embedded **and** exported, not two versions), and mmmdata will
   depend on duckbrain rather than keep a copy, which makes
   [Licensing](#licensing-follow-ups) a precondition for that end state rather
   than background.
   **What is left is this item's original ask:** group-level IQM comparison, which
   is the part that only becomes answerable in a multi-project tool and is why the
   layer moved here from mmmdata in the first place.
   Two accepted residues. `core/qc.py` accepted a `reviewer` argument that the
   page never passed, so **every QC decision duckbrain wrote before 2026-07-24 is
   anonymous** and legacy records cannot be attributed retroactively;
   `save_decision` raises on a blank reviewer now and the page takes it from the
   session, but the existing records are what they are. And `core/qc.py` is the
   only untested module in `core/`.
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

---

<a id="8"></a>
## #8 — Visual identity & branding (someday)

Gated behind functionality + onboarding (`#2`); captured so it isn't forgotten.
Logo/wordmark that works small (favicon) and as a banner; a considered Streamlit
theme instead of defaults; favicon for the GUI tab and the OOD tile; README banner.
Tasteful, not over-designed, and after the product behavior is locked.

**Dark theme is this item's, not `#13`'s** (Ben's call, 2026-07-30 — a facelift is
coming, so testing against the defaults would be work done twice). Two things
already known to check when it happens, both of which a screenshot at the time
will not remind you of:

- The Conversion page's fieldmap colour join spans **two rendering mechanisms** —
  `:blue-badge[…]` markdown above the table (theme-aware) and plain emoji inside
  it (font-rendered, theme-blind). They must still read as the same colour or the
  join breaks where it carries information. See `#13`.
- `5_QC_Dashboard.py` hardcodes `#ffcccc`, which reads poorly on a dark
  background. Flagged in `docs/conversion-legibility.md` phase 3 as the thing not
  to repeat, and never fixed.

---

<a id="30"></a>
## #30 — The GUI eyeball queue

**A running list of things only a human in a real browser can settle, batched on
purpose.** Each one costs a tunnel or an OnDemand session and about a minute of
looking; done piecemeal that setup is paid over and over, and in practice it gets
skipped instead, which is how the entries below accumulated unnoticed in three
different documents. Do them in one sitting.

**When you land a change AppTest cannot judge, add a line here rather than
leaving the check in a commit message.** That is the only rule this item has.
Two things qualify almost every time: anything rendered by a Streamlit primitive
whose *output* the test framework does not model (tabs, `st.iframe`,
`st.data_editor`, popovers, column widths), and anything whose URL is rewritten
by the OnDemand proxy. Delete a line when it is checked — the verdict belongs in
`git log` or the relevant `docs/` page, not here. The entries are numbered for
reading, not for citing: they renumber as they are struck off, so point at `#30`
and never at an entry number.

**Two sessions, not one, and they are different setups.** Entries marked
**[OOD]** must run through Open OnDemand, because the thing under test is the
`/node/<host>/<port>/` prefix; the rest are fine over `bash scripts/launch.sh`
plus the `ssh -L` line it prints.

### Open

1. **[OOD] Do the *exported* dashboard's report links navigate?** The oldest
   entry and the highest value. mmmdata's shipped dashboard carried 837 absolute
   `href="file:///gpfs/…"` links; a browser blocks `file://` navigation from an
   HTTP page, so under the proxy every "View report" did nothing at all — no
   error, no console message, just a dead click. Slice 2 emitted relative paths
   to fix the exported copy, and that fix has never been confirmed under the
   proxy. Open the exported dashboard from `divatten_beta_v2`'s `derivatives/`
   and click through to an MRIQC report.
2. **[OOD] Should the app serve tool reports itself?** A design question, not a
   check, and the one that needs a live session to settle rather than an
   argument. The embed is a `srcdoc` frame with **no origin**, so a relative link
   inside it has nothing to resolve against and cannot route to an MRIQC report
   by construction — the export above is the only way to reach them today.
   `docs/qc-dashboard-migration.md` calls item 2 "only half-closed" for exactly
   this. Its analysis predates `#23`'s `st.iframe` swap but survives it: that
   ledger row measured the two elements' sandboxes as identical.
3. **The embedded report after the `st.iframe` swap (`#23`).** Closed 2026-08-03
   on an assertion about the frame's `srcdoc` — the right test for *what was
   passed*, and silent about what renders. Look for what a srcdoc assertion
   cannot reach: does the report scroll inside its frame rather than clipping,
   is the height sane, and do its own internal anchors work.
4. **The Preprocessing page's three tabs.** Added 2026-08-04 with the page's
   first tests. All three tab bodies execute on every run, so AppTest sees their
   contents whether or not Streamlit would draw them — the tab strip itself is
   unexercised. Confirm the three tabs render and switch, and that **Export
   Scripts** puts an `.sbatch` in `code/logs`.
5. **The BIDS validation panel (`#15`).** The validator was proved end to end
   through a real conversion job — the *log* was read, not the panel. It is an
   on-demand button whose results table nothing has ever looked at. A clean
   project (`divatten_beta`) and a dirty one is the useful pair.
6. **Do save/launch confirmations actually appear?** Added 2026-08-04 with the
   streamlit 1.61 fix. Every "Saved"/"Submitted"/"Cancelled" toast in the GUI is
   now queued into session state and raised on the *next* run rather than beside
   the action, because 1.61 discards a toast queued before the `st.rerun()` that
   follows one. AppTest confirms the message is produced; **what it cannot say is
   whether a real browser was ever dropping them, or for how long.** If the
   browser on 1.59 was already silently swallowing these, then this fixed a
   user-facing bug nobody had reported rather than only a test. Press Save on
   Project Setup and launch a cell on the cockpit, and see whether a toast
   appears — and note that the queued one now arrives on the *redrawn* page,
   which is a slightly different moment than before.
7. **Narrow widths — a laptop, not a desktop monitor.** `#13`'s pass explicitly
   judged density on a large display and recorded that narrow widths were
   untested, which matters because OnDemand users are usually on laptops. The
   Conversion Plan table and the cockpit grid are the two that will break first.
   Worth doing at 1280px wide before anything else on this list.

**Dark theme is deliberately not an entry** — it is `#8`'s, with the two specific
traps already named there. But `#8` and this item want the same session, and that
is the obvious economy: the theming pass has to look at every surface anyway.

**Already discharged; do not re-add.** The cockpit's browser eyeball closed
2026-07-17 (`de1a155` — dashboard width good, folder picker fine); three rows of
`docs/pipeline-cockpit.md` claimed otherwise until this item was written, and now
say so. `#13`'s Conversion Plan pass closed 2026-07-30 on `fmap_eyeball`
(`f1bde41`) — the colour join holds on three pairs. The QC evidence viewer's
figures were confirmed reaching a browser as self-contained data URIs, which is
why they are **not** entry 1: a data URI has no URL for the proxy to get wrong,
and that is by construction rather than by luck.

---

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

---

<a id="loose-ideas-not-scheduled"></a>
## Loose ideas (not scheduled)

- Cockpit: re-run of an already-*complete* stage behind an advanced toggle
  (deliberately excluded from `stage_runnable` today).
- The NORDIC column is always-on; for non-NORDIC projects it's a column of ⚪.
  Fine for LCNI/mmmdata, revisit if it reads as noise elsewhere.
- ~~The QC metrics table doesn't carry a `current_decision` column.~~ **Resolved
  by `#24`, 2026-07-28** — the ordering problem it described was an artefact of
  the single page, and the Overview's run table now carries Decision and Reviewer
  because decisions are loaded before anything renders.
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

**A row is a pointer, not the account.** Detail is in `git log` (the commit
message is the record), `CHANGELOG.md` for anything user-facing, `docs/` for
design, and `memory/` for validation findings. Rows through 2026-07-24 keep to
one line; several later ones ran to paragraphs, which is drift and not a change
of contract — don't take them as the pattern, and don't move a closed item's
reasoning here when the commit that made the change already carries it. Design
rules that still bind live as comments on the code that enforces them — the provenance source rule in `consistency.py`'s module
docstring, the BEP028 sidecar warning in `core/nordic.py`, the task-vs-run rule in
`core/dcm2bids_config.py`.

| Done | Id | Item |
|---|---|---|
| 2026-08-06 | — | **MRIQC's allocation is editable from the GUI**, reported by a beta user whose MRIQC job was OOM-killed and who noticed the fMRIPrep tab had boxes the MRIQC tab did not. Nothing had to be plumbed: `#35` wired `_build_mriqc` to honour `nprocs`/`mem_gb` the same day on the grounds that *"a stage that quietly ignores a parameter its twin acts on is how the next knob gets wired up to nothing"*, and the two widgets are the whole change. Worth recording because the failure mode was the inverse of the one that rule guards — the parameter was live and the page was what had nothing to send it, so the knob existed in every layer except the one a user can reach, and the SLURM Resources panel displayed the number it could not change. The `--mem-gb`-from-allocation derivation makes the box the right remedy for the OOM specifically: one number moves the cgroup limit and the target MRIQC aims at inside it. Pinned in the real rendered script rather than only at the `advance_one` boundary, because a context assertion can only check the side it already knows to look at |
| 2026-08-06 | `#33.1` | **All of `gui/` is type-checked — 115 errors to zero, and the file list goes from 6 entries to 23.** The four pieces landed in the order the item set, and the two estimates it carried were both low, which is this item's own recurring shape a fifth and sixth time. Piece 1, `Scope` as a dataclass: 37 errors against 34, and writing the fields down is what found `metrics_df` — assembled, passed in, read by **nobody** — and a `getattr(self, "selected_key", "")` whose default was unreachable. Declaring `runs: list[dict]` also resolved an `st.dataframe` call with no matching overload. Piece 2, the renames: **21 errors against 13, because the item had counted only one of the two collisions.** `s` was a session `dict` at line 41 and a `SeriesInfo` at line 648; `w` was a warning `str` at line 389 and a `PlanWarning` at line 1007 — the third and fourth instances of the shape `#18` found, and the first pair a *reader* trips on rather than only a checker. Piece 3 split in two once `--check-untyped-defs` showed the bodies were **not** free the way `pipeline.py`'s were (33 more errors, 27 of them calls into the same untyped functions): **five helpers in `components.py` had zero callers anywhere**, so 90 lines went rather than gaining signatures they had no caller to satisfy, and the coverage floor rose 88 → 89 on the 44 dead statements leaving the denominator. The 26 real signatures then needed `from __future__ import annotations` on the two pages lacking it, so `SeriesInfo`/`JobInfo`/`DeltaGenerator` sit under `TYPE_CHECKING` and a page that defers its first-party imports past the config guard still does. Piece 4's flagged `ReviewDomain | None` cluster was a symptom one layer down: `get_domain` was declared `-> ReviewDomain | None` and **none of its 27 call sites checked** — the same shrug as `SeriesInfo.header: object | None` — so it raises `KeyError` naming the registered keys instead. `domain_of` keeps its `| None` on purpose; an undocumented measure is a real answer. Also `probe_session` takes `Sequence[str | Path]`, since `list` is invariant and it only ever iterates. Verified against a fresh 3.10 venv on the interpreter CI's `types` job pins, with `singularity` hidden from `PATH` and `DUCKBRAIN_USER_CONFIG` at a nonexistent file, before each of the five commits. **The item's headline prediction — "expect a project, not a widening", because the pages drag streamlit/plotly/nibabel in — was wrong in kind, not just in size: zero of the 115 named a third-party package.** What is left is `core/`, measured at 36 and opened as `#33.4` |
| 2026-08-06 | `#35` | **`--nprocs` is the allocation's CPUs outright — no headroom, and no `--omp-nthreads`.** The decision the item asked for, settled by reading both images rather than by matching `#32`'s shape: fMRIPrep documents `--nprocs` as "maximum number of threads across all processes", which is the same quantity `--cpus-per-task` grants, so there is nothing to hold back the way memory needs. `--omp-nthreads` stays unpassed because fMRIPrep 24.1.1 sets it to `min(nprocs - 1, 8)` in `config.nipype.init` — already a function of the one input we have, so pinning it would freeze a number the tool derives correctly. The template now reads `--nprocs` from the same `slurm.cpus` the `#SBATCH` directive does, which is what MRIQC always did. **What reading the images added that the item did not anticipate:** MRIQC does *not* derive its per-process cap from nprocs — `_default_omp_threads` is `int(os.getenv('OMP_NUM_THREADS', os.cpu_count()))`, and the 24.0.2 image sets `OMP_NUM_THREADS=1`, so `cpus` buys N single-threaded processes and is the whole of MRIQC's parallelism. That is recorded on the `cpus` key with an instruction to re-measure, because if a future image dropped that variable MRIQC would default to the *node's* 48 CPUs against a 4-CPU allocation. `[fmriprep] nprocs` is deleted and refused at submission on the same terms as `mem_gb`, the two refusals sharing one loop. `_build_mriqc` now honours `nprocs`/`mem_gb` although nothing passes the first: a stage that quietly ignores a parameter its twin acts on is how the next knob gets wired up to nothing. Verified by rendering all four combinations — fMRIPrep defaults `--cpus-per-task=8`/`--nprocs 8`/`--mem=48G`/`--mem-mb 40960`, and both knobs raised to 16/64 G moving all four |
| 2026-08-06 | `#32` | **The allocation is authoritative; the tool's ceiling is derived from it.** `config.tool_mem_gb` is the one place the rule lives, and both nipype stages go through it, so fMRIPrep works the way MRIQC already did and MRIQC's numbers are unchanged (32G → `--mem-gb 24`). fMRIPrep at the shipped default now reads `#SBATCH --mem=48G` with `--mem-mb 40960` instead of 32768, which is the 16 GB the 2026-07-24 run was allocated, warned about not having, and never used. `[fmriprep] mem_gb` is deleted from `base.toml` and a config that still carries it is **refused at submission**, before anything touches the filesystem — ignoring it would leave the key reading as the ceiling in force, which is the same silent-degradation rule that governs the anat-reuse toggle. The GUI knob was retargeted rather than removed: it names the allocation, so raising it moves the `#SBATCH` directive and the derived ceiling together, and the SLURM Resources expander shows the job about to be sent rather than the config file. Two things the fix needed that the item didn't mention — `parse_mem_gb`, because `"49152M"` is the same allocation as `"48G"` and the old `.replace("G", "")` would have read it as 49152 GB, and a **raise** when the allocation is at or below the 8 GB buffer, since flooring at a token 1 GB is a ceiling nobody wrote. Pinned by rendering the real scripts and reading both numbers back out of the text (`test_a_script_states_its_memory_once`), over both stages — a context assertion can only check the side it already knows to look at, and the defect was two template lines disagreeing. The same shape on CPUs was opened as `#35` and closed the same day, separately because it needed its own decision rather than a copy of this one |
| 2026-08-04 | `#34` | **Every container ran against the host's Python, and a beta tester's MRIQC crash is what surfaced it.** `--cleanenv` was on all nine invocation sites and is not isolation: it clears environment *variables*, while apptainer still binds `$HOME` and CPython still puts `~/.local/lib/pythonX.Y/site-packages` on `sys.path` **ahead of** the image's own. Measured inside the real image — `python 3.11.8`, `numpy 1.26.4`, `user site enabled: True`, and `/home/$USER/.local/lib/python3.11/site-packages` on the path. The reporter had NumPy 2.x there; MRIQC imported it instead of the image's 1.26.4 and died building its workflow, because transforms3d calls something NumPy 2.0 removed. **Not MRIQC-specific**: the MRIQC 24.0.2 and fMRIPrep 24.1.1 images are both Python 3.11, so one host directory shadows both, and dcm2bids (3.12) is exposed to a 3.12 one. Fixed with `PYTHONNOUSERSITE=1` via `--env`, spelled **once** in `core.containers.ISOLATION_FLAGS` and reaching the four sbatch lines through `build_context`'s `container_flags` — the `#31` rule, because a flag needed at nine sites is a flag that goes missing at the tenth. `--no-home` also works and was rejected: it removes `$HOME` wholesale, where nipype's config, matplotlib's cache and the FreeSurfer licence live. `tests/test_container_isolation.py` pins both halves — seven behavioural tests that fail against the old flags, and four sweeps (AST over `src/`, text over the templates) that fail when a *new* site spells its own. Verified against the real image with a shadowing home: `user site enabled: False`. **The crash was the lucky outcome** — a host package close enough to import but not to behave would have changed results in silence |
| 2026-08-04 | `#18` | **Static analysis — both follow-ons closed.** Ruff widened a ruleset per commit as the item asked: `B`, then `I`, then `UP`, plus `TD`+`FIX` at zero findings to make CLAUDE.md's "no `# TODO:` in source" rule a gate instead of a promise (verified first that it does *not* match the sanctioned mid-sentence `(TODO #17.4)` citation style — all 13 in `src` still pass). The item's own numbers were stale and are corrected here: 100 findings, not 59, and **44** `B905` sites, not eight. But only **5** were in `src`; the other 39 were one repeated shape in `test_conversion_page.py`, collapsed to a single `_by_series` helper in a prior commit so the bugbear diff was 8 lines of judgment rather than 45 of mechanism. The judgments did not come out uniform, which is the value: three `core/` sites document an unequal zip as intended and take `strict=False`, two GUI sites zip against `st.columns(len(X))` and take `strict=True`. The one `B023` is a false positive with a stated `noqa`. **mypy gates the three modules the item named**, in its own CI job (not a matrix step — the matrix installs different third-party builds per leg, so it could go red on one for reasons nobody caused) and blocking rather than advisory, which is only safe because the config was dialled to a measured zero *first*. `disallow_untyped_defs` cost nothing — all 87 functions in those files were already annotated — so it is a ratchet like the coverage floor, not a cleanup project; `follow_imports = "silent"` contains the closure's 23 modules, and pandas is the one stub gap, named rather than blanketed. **It found five errors, all one shape**: a name bound to two unrelated things in one long function (`expected` meaning both a phase-encoding direction and a list of dropped series 130 lines apart in `plan_warnings`; `run` meaning both a BOLD's counted index and an SBRef's possibly-absent one). Fixed by renaming, since the type complaint was pointing at something a reader trips on too. `disallow_any_generics` and a wider file list are real work rather than config and moved to `#33`; the ND-pairing behaviour question `B905` surfaced moved to `#19.12` |
| 2026-08-04 | `#31` | **Node-local scratch is qualified by project now, and a job clears its own.** `config.unit_work_dir` builds `<work_dir>/duckbrain-<user>-<project>-<hash8>/<step>_sub-XX[_ses-YY]`: the digest is what separates two studies, the basename is only so the tree is recognisable on the node, and the login name is there because `/tmp` is shared between users too and the first creator owns the tree — without it the second user gets an unexplained `EACCES` rather than a wrong answer. Derived in `build_context` rather than by each caller, because the bug was two templates independently spelling `paths.work_dir ~ "/sub-"`; `test_no_template_builds_a_scratch_path_out_of_paths_work_dir` sweeps the whole directory so a third cannot. Read from `config[paths][bids_dir]` and never from the context, or a `use_nordic` fMRIPrep run — handed a *derivative* as its BIDS input — would give one unit two caches depending on a toggle. **Stable per (project, step, unit) and not per attempt**, which is the question the item asked to settle first: a re-run after a walltime kill resumes from the cache the killed attempt left, and that is the only reason the tree is worth keeping rather than always wiping. **Cleanup is not keyed on the exit code** — that would trust exactly the signal `#28` proved lies. A job removes its work dir when it exits 0 *and* wrote no `crash-*` under its derivative newer than a stamp it touched at start; `-newer` and not merely "exists", or the first crash a project ever recorded would switch cleanup off for good. A kill keeps the tree by construction: the shell never reaches the line. All four states execute for real in `tests/test_sbatch_templates.py` against a stubbed `singularity`, over both nipype stages, and each was checked to fail against the behaviour it replaced. `core/fmriprep.py`/`core/mriqc.py`'s `build_*_command` are untouched: they take `work_dir` from a caller, have no caller in `src/`, and are not on the submission path |
| 2026-08-04 | `#28` | **Diagnosed, and the item's own premise was wrong: it *was* the `#21` fsaverage race, the other branch of it.** Job 45644650, submitted 2026-07-24T18:33:05 — not a 07-27 job; those are the successful re-run that wiped and recreated the tree, which is why no crash file survives. The submitted sbatch is **byte-identical** to that re-run's, so command construction is exonerated and `#16.1`'s request record was never needed to answer this. `code/logs/fmriprep_45644650.out:405-462` has `fsdir_run_…` raising `OSError: [Errno 39] Directory not empty: 'label'` in `niworkflows/interfaces/bids.py:1463 shutil.rmtree(dest)`: `sub-010` is the job whose own `rmtree` *lost* the footrace, where the other four inherited a half-copied tree and died in `recon-all` hours later. Everything downstream of `fsdir` was pruned, and the log still ends "fMRIPrep finished successfully!" with exit 0 — the mechanism is in `consistency._check_tool_crashes`'s docstring. The cause is already closed by `core/fsaverage.py`; what was open is that duckbrain **read nothing**, and now reads the crash record the tool writes (`84cb31f`) and requires the confounds TSV before grading fMRIPrep complete (`0eb9be4`). Output-space grading stays impossible by construction and stays with `#16.1`. Opened `#31` and `#32` from what the diagnosis walked past |
| 2026-08-04 | `#27` | **The page that submits every job now has tests, and driving it found a subject it was dropping in silence.** 0% → 100%, floor 85 → 88. Route taken was AppTest at the boundary, **not** this item's suggested "assert the rendered submission command": that command is already asserted in `test_pipeline.py` and `test_sbatch_templates.py`, so re-deriving it through the GUI would have tested the pipeline three more times and the page not at all. 19 tests stub `advance_one` on `duckbrain.core.pipeline` — a single patch, because the page imports it *inside* the submit branch at call time — and assert which stage, which units, which parameters crossed. One test does run the real chain with only `submit_job` stubbed, via **MRIQC**, the one stage with neither an fsaverage preflight nor a licence lookup, so a fake `.sif` and a pinned `shutil.which` are the whole setup; without it nothing would prove the page reaches SLURM at all. **Then the extraction, second and deliberately**: the three tabs each held a near-verbatim copy of the same submit loop, ~90 of 321 lines, and `gui/preproc_panels.run_batch` is that loop once — safe only because the tests already pinned the behaviour, and the proof is that all 19 passed **unchanged** across it. Page 321 → 224 lines and 100% covered, module 100%, total up on fewer statements. Taking `bids_path` as an argument instead of closing over the page's global is what made `targets` reachable from `tests/test_preproc_panels.py` with a tmp_path and no Streamlit. **What driving it found**: a subject whose sessions miss the selection returned an empty target list and vanished from the batch — select two subjects and one session in a study where they don't share sessions, get one job and a results table that looks complete. Now named. The all-dropped case turned out to be **unreachable from the page** and the reason is worth keeping: the session multiselect offers only the union of the selected subjects' sessions, and Streamlit *clears* the selection when that union changes, so the earlier guard always catches it first — pinned by `test_changing_subjects_clears_a_session_that_no_longer_applies`, with the empty-batch branch itself tested against the module. Two page changes were prerequisites, not cleanups: `get_slurm_resources` moved out of the fMRIPrep tab (all three read it; it worked only because Streamlit executes every tab body), and the six fMRIPrep option widgets gained `key=`, without which AppTest reaches them only by position and a layout edit silently re-points the very assertion that reads every option back out of the call. Floor measured under the CI shim, not a dev-box run, per `memory/local-tests-are-not-ci-tests`. |
| 2026-08-04 | `#29` | **A cache key Streamlit was throwing away** — `cache_data` drops underscore-prefixed arguments, so `_load_metrics`'s `_fingerprint` keyed on `(mriqc_dir, modality)` alone and every QC page served the first MRIQC run's numbers until the server restarted. The rename, the test that fails before it (`test_a_rerun_of_mriqc_is_not_served_the_previous_numbers`), and an AST sweep over every `st.cache_*` in the package (`tests/test_streamlit_caches.py`, `EXEMPT` empty) so the next cache cannot repeat it. The two docstrings that named `_load_metrics` as the bad example now point at that test instead: a comment asserting a defect in another function is a claim about current state with nothing to notice when it stops being true. |
| 2026-08-03 | `#23` | **`st.components.v1.html` swapped for `st.iframe`, and the floor raised to pay for it.** `streamlit>=1.48` → `>=1.56`, in the same commit and deliberately: `st.iframe` landed in 1.56 (2026-03-31), and a `hasattr` fallback would have left a second code path nobody runs. What the item asked to check, checked: the sandbox is **identical** — one flag list in `static/js/IFrameUtil.*.js`, `allow-same-origin` *and* `allow-scripts` together, serves both elements — so the swap neither costs nor buys isolation, and `core.report_embed.resolve_asset` remains the control doing the work. Two things `st.iframe` adds that its argument-sniffing makes easy to lose: pass the markup as a **string**, since a `Path` re-reads the file and would discard the asset-link rewriting `embed_tool_report` exists for, and keep `height` an `int`, since `"content"` injects a sizing script and a `MutationObserver` into the report document. Pinned by a test on the frame's `srcdoc` — the old tests asserted only the return value, which a path-shaped argument would still have made `True`. Stale docstrings fixed with it: `core/qc_report.py` claimed the report is embedded via `st.components.v1.html()`, which `#24` slice C made false, and three more places still described a `report_base=None` "embedded copy" that no caller passes. |
| 2026-08-03 | `#22` | **The dcm2niix probe is wired in, and it exposed a check that was wrong in the other direction.** Both probe-fed checks had shipped 2026-07-24 with zero callers, so the *signed* phase-encoding direction — unreachable from raw tags, absent on XA30, and the one thing in a fieldmap plan taken entirely on the operator's word — went unchecked before every conversion. Wiring it required fixing `pe-collinear` first: `_fmap_halves` bucketed every planned `fmap` file with no pepolar test, so a gradient-echo magnitude and its phasediff (one group, two series, one direction **by construction**) read as a pepolar pair that estimates nothing. That is an *error*, which on the bulk path refuses the conversion — and it would have fired on **32** of the corpus's fieldmap sessions against the **22** pepolar ones the check is for. `suffix == "epi"` is the discriminator. Then: `probe_runtime` (prefer the pinned image over a host dcm2niix, and *say* when you fell back), `gui/conversion_panels.py` (cache keyed on the series names and file counts `list_series` already has plus the image's mtime/size — deliberately not an rglob, which would stat ~2000 files on GPFS to protect a 0.15 s call), and the same probe on the bulk/SLURM path via a `container=` parameter, since a probe wired only into the page would leave bulk checking strictly less than the reviewed path. **The panel is the part that mattered**: green is now *replaced* by an `st.info` when nothing was probed, not annotated, and the "not checked" caption renders unconditionally — a session with a collision *and* an unrunnable probe must still say the phase encoding went unchecked. **Measured, and it closed the one open question**: 52/52 fmap/dwi series across 25 sessions and both Siemens dialects report a signed direction, zero blank — so a `pe-unchecked` finding would be pure noise and was dropped. Validated live: `fmap_eyeball`'s two- and three-pair sessions read `j-`/`j` throughout at 0.46 s for 38 series, a Crave_control GRE session reads `i`/`i` and raises nothing, and `divatten_beta` renders the green message naming 33 probed series. Left open as `#29`: the qc_panels cache the probe cache was about to copy |
| 2026-08-03 | `#15` | **BIDS validation actually validates, and the item's own open question is answered NO.** Validation had been on by default since 2026-07-21 and had never been usable: on `divatten_beta` — the project `CLAUDE.md` calls known-clean — it indexed **24 647 files / 37 GB** and `NOT_INCLUDED` was the *only* error, so any real finding was buried under thousands of lines. **The cause is in the validator, read off the bundled bids-validator 1.14.6 inside `dcm2bids-3.2.0.sif`** (`dist/commonjs/index.js`, `getFilesFromFs`): it recurses into a symlinked directory using the *target* path against an unchanged `rootPath`, so every file's `relativePath` escapes the dataset (`./../../gpfs/projects/…/*.dcm`) — and the ignore test runs against **that**, which is why the validator's own `defaultIgnore()`, which already contains `/sourcedata`, `/derivatives` and `/code`, never fires. So the item's standing question — *check the v2 validator before adding a `.bidsignore` entry* — resolves to **no entry could ever have worked**: the default is already strictly stronger than anything duckbrain could write, and it still does not match. `_BIDSIGNORE_ENTRIES` deliberately gained no `sourcedata/` line, because a dead entry invites the next reader to believe it works. The only knob is `--ignoreSymlinks`, and **dcm2bids cannot pass it** — `dcm2bids_gen.py:133-145` calls `run_shell_command(['bids-validator', bids_dir])` over a `Popen` wrapper (`utils/utils.py:143-155`) that returns stdout and never inspects the return code, so the flag could not have failed a job even had it produced a usable answer. duckbrain therefore invokes the validator itself, in `new core/validation.py`, whose argv the sbatch template renders verbatim — pinned as a *contiguous-sublist* assertion rather than a flag-presence one, because the duplication here is exact. `exec`, never `run`: the sif's runscript **is** dcm2bids, so `run <sif> bids-validator …` would feed those tokens to dcm2bids as arguments. The call sits **after** `EXIT_CODE=$?` and on one unbroken line — after, so dcm2bids' status stays the job's (validation reports, never blocks, which is also what `--bids_validate` did in practice); unbroken, because a line with no continuation is structurally immune to the hazard `test_no_comment_breaks_a_line_continuation` exists for. **Measured, not asserted:** `dwi_eyeball` 2605 files / 2540 `NOT_INCLUDED` → **66 files / zero, in 0.98 s**; `divatten_beta_v2` (147 GB of derivatives) 293 files in 3.5 s, which is what makes an on-demand GUI panel affordable at all. **What a clean run then exposed was that three of the four surviving findings were duckbrain's own doing.** `dataset_description.json` is *compulsory* and was reachable only from a button on the Ingestion page, so a project nobody clicked through converted fine and then failed a compulsory-file check — the single error on `dwi_eyeball`. A root `README` was never written at all, and `Authors` never at all (`NO_AUTHORS`, code 113). All three are now ensured at the `_build_dcm2bids` choke point, mirroring the `.bidsignore` top-up exactly and for the same reason; both `ensure_` verbs **decline an existing file**, which is what makes them safe on a path that runs at every submission. Deliberately *not* in `scaffold_project`, unlike `.bidsignore`: that file's content is config-free and these are not, so at scaffold time the description would land thin and then be declined forever. **Underneath them was a data-loss bug worth more than the warnings it blocked**: `write_dataset_description` was a whole-file `json.dump`, so every press of "Generate" destroyed any hand-added `License`/`Funding`/`EthicsApprovals`/`DatasetDOI`. It now merges over the keys duckbrain owns — the `_save_sections` `owned=` contract one layer down — and that had to be true *before* `Authors` could become a Setup field, or the button would blank what the user typed. `[project] authors` is a TOML **list** (BIDS `Authors` is an array; a delimited string pushes the split into every reader), entered one per line because comma-splitting guesses wrong on `Doe, Jane`, and saved as `_authors or ""` because `_clean_dict` drops on `v != ""` and an empty *list* would otherwise survive to be written as `authors = []` — a declaration, not an absence. The **cockpit panel is not a `core/checks.py` REGISTRY entry** and the reason is not cost: `run_checks` returns `[]` when a project declares no `[expected]`, so registering there would make BIDS validation silently conditional on an opt-in that has nothing to do with it — the spec is not a project's statement of intent. (Also `ConsistencyIssue` carries no file list, and a validator finding is *about* files.) It runs **nothing** until the button is pressed, because the board is a 30 s fragment; `test_the_validation_panel_runs_nothing_until_the_button_is_pressed` is the guard, and a run that could not happen reports *why* rather than an empty result that reads as clean. Not memoised, deliberately: `fsaverage` caches against an immutable image, a BIDS tree changes underneath you, and a stale "clean" is the exact failure this item removed. **One new invariant the fix creates**: `--ignoreSymlinks` means nothing duckbrain writes into a validated tree may be a symlinked directory, or it silently drops out of validation — NORDIC already hardlinks or copies, and `test_staged_bids_input_files_are_never_symlinks` keeps it that way. **Proved end to end on real data**, a fresh conversion of `mmmsourcedata/sub-06/ses-01` into `/projects/hulacon/bhutch/validate_eyeball`: job COMPLETED exit 0, both root files and the configured `Authors` written at submission and untouched by dcm2bids, the validation block **20 lines with zero errors**, and `bids-validator exit: 0` printed separately from `Exit code: 0`. The old invocation on that same tree indexes 998 files and reports two errors. Four residuals were **re-homed rather than closed with the row**: the validator-didn't-catch-`#14` caveat → `#16` (its own text said so), `events.tsv` → `#7` item 3, `bidsschematools` plan-time filename checking → new `#13.2` (correcting this item's stale "`core/consistency.py` is where a wrapper fits" — the plan-time surface is `plan_warnings`), entity-ordering → `#19.11`. |
| 2026-07-30 | `#19.1` | **Diffusion is converted, and the cost the item named was a misdiagnosis** — "no `bval`/`bvec` handling" implied duckbrain had to move those files. It does not: dcm2bids 3.2.0's `Dcm2BidsGen.move` globs `<srcRoot>.*` and whitelists `.nii`/`.gz`/`.json`/`.bval`/`.bvec`, so claiming the series is the whole of the work and the item collapsed from a subsystem to an emitter. Read off the pinned container's source, then **proved by converting real multi-shell data** — reading it was not evidence. `_dwi_description` writes `dwi/…_dwi` and, for a `_SBRef` whose sibling is diffusion, `dwi/…_sbref`; it **returns a description unconditionally** where `_anat_description` returns `dict | None`, because an anat's suffix comes from a name vocabulary that can fail to fire and diffusion's cannot — `dir-` is decoration, not a precondition, and a `return None` would drop the commonest single-direction acquisition there is. Three things it deliberately does not do, now `#19.10`: **no `B0FieldSource`** (the decisive reason is reviewability, not "diffusion has no task" — `resolve_fmap_assignments` filters `role != "bold"`, which is what the GUI's fieldmap column renders from, so a binding chosen in the emitter would be applied silently and could not be overridden), no `[expected]` coverage, no NORDIC staging. **The `_SBRef` runs are inherited, never computed independently**: numbering each suffix on its own is right only when repeats are *balanced*, and with references 1/2/3 and volumes 1/3 surviving an aborted middle run, independent numbering makes `dir-AP_run-2_sbref` claim to be the reference for the *third* acquisition — wrong pairing, no warning. `_disambiguate_dwi` numbers the volume series and hands each reference its own sibling's run; the leftover keeps unnumbered entities so `orphan-sbref` names it. The test is written as the *unbalanced* case, because the balanced one proves nothing. **One new failure mode the change created and closed**: `detect_fieldmaps`' name fallback was classification-blind, harmless only while `dwi` emitted nothing — a series named `dwi_topup_ap` (DIFFUSION token classifies it `dwi`, the name matches `topup`) would have been written *twice*, into `dwi/` and `fmap/`, where the collision check cannot see it because the paths differ. The fallback now skips anything already in `EMITTED_CLASSIFICATIONS`, which moved to `dicom_inspect` since `dcm2bids_config` imports that module. Direction widened to `ap\|pa\|rl\|lr` for the emitter only — **fieldmap pairing is untouched**, gated on a named `_PAIRABLE_DIRECTIONS` that is now all `#19.2` has to delete — and the old single warning was split, because "cannot determine direction" became false the moment duckbrain could read `rl` and merely decline to pair it. `PE_FOR_DIR` gained `RL`→`i`, `LR`→`i-`, **measured at two sites rather than derived** (R→L is −x, which would imply `i-`); they are the table's weakest rows, so both the plan check and `consistency._check_pe_direction` — renamed and widened to `dwi/`, since the two must cover the same files — now verify them. `dwi` also became declarable; there is no `dwi/sbref` token and the reason is mechanical and tested: the sibling pass runs after the project tier and reads its bases from `classification == "dwi"`, declarations included, so declaring the volume series reclaims the reference in the same pass. Swept before and after across all 263 sessions on eight dimensions: **zero classification transitions, zero fieldmap-group / fieldmap-warning / `nd_twin_bases` changes, and zero planned files removed or changed** — 2903 → 2995 is +92 additions and nothing else, exactly the 36 (18 LCNI `Round_Robin` sessions) + 56 (8 `mmmsourcedata` sessions) predicted from the source directories, with 92 `dropped` warnings retired and no new warning of any kind. **Converted for real** into `/projects/hulacon/bhutch/dwi_eyeball` — two scanners, because one fixture lets a CMRR-specific assumption pass: `mmmsourcedata/sub-06/ses-01` (4 directions + 4 references, `.bval` 54 volumes across shells 1000/2000/3000) and LCNI `Round_Robin/G16_S01` (RL/LR, no reference, 65 volumes, single shell). `.bval`/`.bvec` landed beside every `_dwi` with no duckbrain code, `.bvec` is 3×N on all six, every derived map logged `No Pairing`, nothing diffusion reached `fmap/`, and **`PhaseEncodingDirection` matched the `dir-` label on all 12 files — `RL`→`i` and `LR`→`i-` independently on both scanners**, which is the confirmation those two `PE_FOR_DIR` rows rest on. A `--force` reconversion rewrote a deleted `.bval` rather than skipping it. **One thing only the conversion could find**: dcm2niix writes `.bval`/`.bvec` for a single-volume diffusion *reference* too, and dcm2bids' move step whitelists extensions without looking at the datatype — so a legal `dwi/…_sbref.nii.gz` drags two files BIDS does not define, and the validator reports NOT_INCLUDED on all 8. Ignored rather than deleted (the validator's own text names `.bidsignore` for this; the content is inert; a delete step would need to exist in both the sbatch template and `run_dcm2bids`), and `_build_dcm2bids` now tops `.bidsignore` up on **every** conversion, since an entry added today would otherwise never reach a project scaffolded yesterday. The validator's remaining complaint is `#15`'s symlinked-DICOM finding, which this re-measured and promoted |
| 2026-07-30 | `#19.8` | **A scanner that writes no `ND` token hid every duplicate reconstruction it had** — `_nd_twin_groups`' guard skipped any ND-*named* series whose `image_type` was readable and lacked `ND`, reading that silence as "the token means something else at this site". On a beta tester's ABCD tree, where every series reads `('ORIGINAL','PRIMARY','M','NONE')`, it fired on **26 of 26**: both copies of every anatomical converted — `T1w run-1..run-4` where two of the four are one acquisition reconstructed twice — and since `nd_twin_bases` returned `[]`, the Conversion page never offered the reconstruction radio it gates on that call. **Deleting the guard was refused** (a sequence carrying `ND` in its name for unrelated reasons is a real failure mode); it now needs a *contradiction* rather than a failure to confirm. `ND` is Siemens for No Distortion correction, so its complement is what the corrected copy carries, and only `DIS2D`/`DIS3D` overrules an `_ND` name. Only the ND-named side is tested — the corrected twin carries `DIS*` by definition, so checking it would delete the pair on exactly the scanners this fixes. **One of the item's own claims was wrong, and it was the one that would have shaped the validation.** It said the corpus is the only fixture for the guard's original case; it is not — the guard never fires there at all (all 53 LCNI ND-named series carry `ND`, 4 more have no header), so that case has **no measured instance on this filesystem** and what keeps the narrowed guard is the Siemens semantics, not evidence. The code says so rather than implying otherwise. Swept before and after across 263 sessions on all eight dimensions the change could move — classification, planned files, plan warnings, fieldmap groups, fieldmap warnings, `nd_twin_bases`, ticked rows, drop notices. **LCNI corpus (166/166): zero on every one**, 1192 planned files unchanged, and `#19.7`'s 46-of-166 twinned sessions re-confirmed as the harness's own self-test before any diff was read. On `mmmsourcedata` (97) exactly 26 series moved in 11 sessions, two transitions only — `anat/` → `derived/` ×21 and `anat/T2w` → `derived/T2w` ×5, which is the default `corrected` policy finally getting to act — 26 planned anat files gone, 26 drop notices arrived, none of them the empty-twin fallback, and no fieldmap moved. It **corrects** `#13.1`'s ticked-row measurement rather than finishing it: that session goes 10 → **6**, not to 2, because four of the eight rows `#13.1` counted as junk are the genuine anatomicals — `ABCD_T1w_MPR_vNav` really was acquired twice. Zero junk rows remain there, so `#13.1` now rests entirely on its anat-only-curation pass. Tests are synthesised from the real headers of *both* scanners, neither fixture being able to pin the other's shape |
| 2026-07-30 | `#19.9` | **A diffusion SBRef converted as a pepolar fieldmap half, and functional runs bound to it** — silently wrong preprocessing, not clutter, since fMRIPrep would have estimated the field from two diffusion references and applied it to a BOLD run with nothing complaining. The header tier was not being sloppy and is unchanged: diffusion *is* spin-echo EPI, so a diffusion reference genuinely satisfies `2D and is_epi and is_spin_echo`, and against the real `se_epi_ap_encoding` beside it `is_epi`, `is_spin_echo`, `mr_acquisition_type` and the volume count are identical. `ImageType[2]` is not the discriminator either — `M` on the reference, but 48 of 60 sampled corpus pepolar fieldmaps also read `M`. The fix is the sibling: `_recover_dwi_sbref_from_sibling` strips `_SBRef`, and a base sibling carrying `DIFFUSION` makes this a diffusion reference (`dwi`/`sbref`, `classified_by = "sibling"`). **It is the one place a sibling's header overrules a series' own**, which `_recover_func_from_sbref` refuses to do — the asymmetry is the evidence, not the direction: `DIFFUSION` is a positive statement and what it overturns is a fall-through, so the rule is now stated at both ends. A project declaration still wins over both. Measured before and after across 263 sessions: on the LCNI corpus (166) **nothing changed at all**, as predicted — it holds zero diffusion SBRefs across all 2139 series directories, which is why the tests are synthesised from the real `mmmsourcedata` headers rather than from a corpus run. On `mmmsourcedata` exactly 28 series moved, one transition only (`fmap/epi` → `dwi/sbref`), the spurious `cmrr_diff_3shell_sbref` group was the only group removed and none was added, and 12 direction warnings went to 0. All 10 bindings the item named are corrected: `sub-06`/`sub-07` `ses-01` now bind the resting run and its reference to the real `encoding` pair, `sub-03`/`04`/`05` to nothing, which is right because those sessions contain no fieldmap. Two neighbours moved with it — `#19.2` is unblocked (the `rl`/`lr` references escaped pairing only through going unrecognised, so widening `dir-` first would have built a second spurious pair), and `#13.1`'s ABCD session drops from 14 ticked rows to 10, leaving `#19.8` — closed the same day, and it found that measurement overcounted — as the remainder |
| 2026-07-30 | `#13.1` | **The `Type` column is editable, and a correction generalizes to the study** — a `SelectboxColumn` plus a new `[series_types]` project section read by `classify_series` as a tier above header and name (`core/series_types.py`, `save_project_series_types`). The item's own warning about the write-back was right and its fix was not: the edit is read **above** `classify_series`, so `detect_fieldmaps`, the task/run seeding, the fieldmap bindings and `generate_config`'s dispatch all see one datatype instead of the column and the emission following different ones — there is no second copy to keep in sync. `generate_session_config` takes `type_rules` for the same reason it takes `fmap_rules`, or bulk convert would write a different datatype than the one reviewed. Three refusals carry the honesty. **An anat declaration names its suffix** (`anat/T1w`): `_anat_description` reads the suffix off the *name* vocabulary and returns `None` when nothing fires, so a bare `anat` on a study-specific label writes nothing and says nothing — and the declaration outranks that vocabulary, where `suffix_hint` deliberately cannot, or a misread `t1w_mprage` would be uncorrectable. **`fmap` and `dwi` are not declarable**, since a label alone can't make either emit (pairing reads the direction from the description; `#19.1`). **A non-declarable pick is refused by name** rather than accepted and ignored — the dropdown must still *offer* the inferred classifications because a select cell cannot render a value outside its options. The `convert` checkbox stayed the way to drop a series. One neighbouring silence closed on the way: the one-shot JSON import now reports a datatype it will not carry over, which it had always dropped under a banner saying the JSON had loaded |
| 2026-07-30 | `#26` | **The coverage gate could not see a single Streamlit page, and the item's own diagnosis of why was wrong.** `source = ["duckbrain"]` is a package *name*, and coverage resolves those by **module name**: streamlit execs a page as a module called `5_QC_Overview`, which is not a `duckbrain` submodule and is not a legal Python identifier, so it could never match — `COVERAGE_DEBUG=trace` says exactly that. Not AppTest, not a process boundary, not the `magic` AST rewrite; a path source traces the pages fine. Same tests, same 6466 statements, **73% → 87%**, floor 70 → 85. The load-bearing part is what the false explanation cost: the item claimed the ratchet "exerts no pressure at all on the code where this bug class lives" and that was never true — `3_BIDS_Conversion.py` was **80% covered** by tests already passing, and the report was throwing it away. Also required, not cosmetic: CI's `--cov=duckbrain` *overrides* the config source, so fixing `pyproject.toml` alone would have left CI measuring the old way. The floor was measured after the fact rather than reused from the exploration, since two pages had changed since. One real gap fell out and is open as `#27` (`4_Preprocessing.py`, 0%). Two notes cleared with it: `#26.1`, a comment asserting `series_list` is cached across reruns — it is not (no `lru_cache`, no `st.cache_data`, no fragment; `list_series` runs at page top every rerun), so the `elif` it guarded was dead and is gone. `#26.2`, the `st.stop()` at the config call: **reachable, but not by the binding its comment named** — the two repair passes above it rewrite every unsatisfiable rule to `none`, so what still lands there is `generate_config`'s *other* raise, two fieldmap groups colliding on one B0 identifier (`2.5mm`/`25mm`). No table cell repairs that and the call already raised, so there is no config to render from: it stays a stop where its neighbours warn, now with a test that says so. **The refactor is deferred, not refused** — extracting `(seed, edits, imported, override) -> effective plan` into `core/` is still the right shape, but its cheapest justification was the coverage gap and that is now free, one of the four inputs already got one home in `c0f4650`, and the diagnostics are interleaved with the derivation so ~18 of the 36 render-coupled tests would be rewritten for a presentation-token round trip |
| 2026-07-29 | `#25` | **All three tags published as GitHub Releases, and `v0.3.0` cut to make that worth doing.** A pushed tag notifies nobody and is invisible to the API, so `docs/releasing.md` step 7's announcement channel did not exist and `core/updates.py` — shipped the day before — queried `releases/latest` and got a 404, meaning the GUI's "newer version" line was dark for every user from the moment it landed. Backfilling 0.1/0.2 alone would have turned the channel on and had nothing worth announcing: the **fieldmap-intent inversion fix sat in `[Unreleased]` for eight days**, so users on `main` had it and anyone pinned to a tag did not. Hence `v0.3.0` — 50 commits, +27.8k/−1.7k. **Minor, not patch, deliberately**: `_release_line()` reduces to `major.minor` and `check_duckbrain_drift()` therefore flags every derivative built under the 0.2 line, which is *correct* here rather than collateral, because this release changes recipes duckbrain authors (which series convert, their datatype, the `B0Field*` intent in every sidecar, which reconstruction ships, which pair corrects which run) and not merely the flags passed to a container. The changelog's thirteen repeated Added/Changed/Fixed headers — one set per work session — were merged into one of each, since that section becomes the published notes; every bullet moved verbatim and the 688 content lines were diffed before and after rather than eyeballed. Two environment limits worth knowing if this is ever automated: the agent sandbox refuses tag refs (`HTTP 403`) while accepting branch refs, and the GitHub MCP server exposes releases read-only — so tag and publish stayed manual |
| 2026-07-28 | — | **A series can be left out of the conversion** — a `convert` checkbox on the plan table, prompted by a beta tester asking how to skip a run. The config's native spelling of "not converted" is *no description*, so `generate_config(skip=…)` simply omits one and everything downstream follows with no new state: `becomes` already rendered `— not converted` for an unclaimed series, and the skip survives save/reload through the saved JSON alone. Three things the naive version gets wrong. **A skipped fieldmap half takes its whole pair** (`_without_skipped_groups`) — half a pair is not half a fieldmap, and emitting the survivor writes a `fmap/` file nothing can be estimated from; a run still bound to a pair whose half was unticked is refused, naming the two edits that conflict rather than letting `generate_config` say the session lacks a group the user removed three rows up. **The drop carries a reason**, because the warning it otherwise raises means "nothing claimed this" — the anat-suffix bug that warning exists to catch — so the reason travels on `SeriesInfo.drop_reason` and the finding is an info note; that also fixes the pre-existing double-report where an ND-demoted anat got both the warning and the note, and the kind is `deliberate-drop` now, not `nd-duplicate`, since the ND policy was the first thing to set a reason and is no longer the only one. **A stranded SBRef is reported** (`orphan-sbref`): bold and sbref are two rows, so skipping one and not the other is a click away, and an SBRef alone is the reference volume for a run that isn't being written. Rows duckbrain has no emission path for start unticked so the box agrees with `becomes`; `EMITTED_CLASSIFICATIONS` is deliberately not "everything that isn't an expected drop", because `dwi` classifies cleanly and still converts to nothing. Per-session by construction — see `#13.1` for why a project-level skip needs the description key |
| 2026-07-28 | — | **All duckbrain-authored output moved under `derivatives/duckbrain/`** (`qc/decisions/`, `qc/reports/`), so a project shows at a glance which derivatives a tool produced and which duckbrain did. The tool trees stay put — they are the tools' own derivative datasets and BIDS expects them at `derivatives/<pipeline>/`, and that includes `fmriprep/sourcedata/freesurfer`, which duckbrain only seeds `fsaverage` into. No file is moved: `decision_search_dirs` still reads `preprocessing_qc/`, legacy root first so the current location's entries are the newest, because mmmdata still writes there and a project reviewed before the move must not lose its history — the same treatment `_history_of` gives the two on-disk schemas, applied to the two locations. Verified live on both real projects: 1 and 609 records, all still read, none moved. The report's MRIQC links are now computed from `REPORT_SUBDIR` rather than a hardcoded `../mriqc`, since deepening the subdir would otherwise have pointed every link at a directory that does not exist — silently, a broken relative link being ordinary text |
| 2026-07-28 | `#24` | **QC review is grouped by the question being asked** — an Overview plus one page per domain (signal, temporal, alignment, artifact) under a collapsible `QC` nav group, each measure's guidance beside the number instead of in a glossary, and each measure shown with where the run sits among the runs around it. `core/qc_domains.py` partitions all 30 registry measures at import (a measure in two domains emits duplicate `#guidance-{key}` anchors), and carries the fMRIPrep figures that can never be registry entries — which is what gives alignment, the domain with no MRIQC number on bold, anything to show. `core/qc_evidence.py` serves those figures per run: 1.1 MB against 80 MB for the subject report, with the SDC flicker intact because the animation is CSS inside each SVG, verified reaching the browser as a self-contained data URI. Matching is by BIDS entity, not by prefix join, which is what makes `sub-03_acq-MPR_dseg.svg` findable on a session dataset. An absent figure is stated, not skipped — no SDC figure means the run was preprocessed with no distortion correction. Domain reviews share the per-run decision file via an optional `domain` field, with a vocabulary disjoint from the verdicts' and `latest` meaning the newest entry carrying *no* domain, so a note about alignment can never become the run's verdict; 609 real records read unchanged. Coverage rose 70.83% → 73.51% because the five pages are four-statement declarations over one tested module, so the ratchet went 65 → 70. Slice B (regrouping the HTML export) dropped by decision, not deferred |
| 2026-07-27 | `#21` | **The shared `fsaverage` race is closed by seeding, not staggering** — `core/fsaverage.py`, wired into `advance_one` so no launcher can forget it. fMRIPrep's `BIDSFreeSurferDir` deletes an fsaverage tree that lacks the FreeSurfer-7 sentinel, and a tree being copied into lacks it for the first 0.39 s of a 1.83 s copy, so job B `rmtree`s job A's copy in progress and nothing raises — surfacing ~3 hours later at `recon-all`'s BA_exvivo stage, and stickily, since the merged tree *does* carry the sentinel so the self-repair can never fire again. Took out 4 of 5 subjects on `divatten_beta_v2`. Completeness is judged against the container's own manifest (312 files / 109), never the sentinel — a checker asking fMRIPrep's question would have called the 259-file tree fine. The full reasoning is the `core/fsaverage.py` module docstring and commit `a6eb399`; pinned by `tests/test_fsaverage.py`. This row used to end "one thing from that run is **not** explained by the race and is open as `#28`" — wrong on both halves. It *was* this race, the branch where a job's own `rmtree` raised instead of inheriting a half-copied tree; see the `#28` row |
| 2026-07-24 | `#7.4` | **The QC norms layer migrated from mmmdata in three slices.** Slice 1, the 30-measure registry plus a `[qc]` config section, worked the plan's "cannot be verified without data" table first against 717 real MRIQC JSONs — the registry was right about every content question it raised, and real output is now committed as `tests/fixtures/mriqc/` so a wrong key name fails a test instead of rendering a blank column. Slice 2, `core/qc_report.py` plus the embed, settled the link question by having duckbrain serve the reports itself through Streamlit's media endpoint (`core/report_embed.py`) — relative paths fix the exported copy and can never fix a `srcdoc` iframe, whose base URL is the page's; two alternatives that look right from outside are recorded in `components.py`. It also found `load_mriqc_metrics` returning **zero** runs on any sessionless study, so the QC page had never worked on `divatten_beta`. Slice 3 migrated nothing because nothing needed it: mmmdata's append-only schema reads as-is (609/609, 0 files modified), and live data forced a third count bucket, `automated` vs `unattributed`, because only the second is closable by re-reviewing. Plan and the two corrections it forced: `docs/qc-dashboard-migration.md`. Group-level IQM comparison stays open under `#7` |
| 2026-07-24 | — | **A project chooses which reconstruction converts, prompted by LCNI** asking that the user be able to select the distortion-corrected copy, the `_ND` copy, or both. `[conversion] nd_duplicates`, defaulting to today's behaviour. Project-level and not a table column: bulk and cockpit converts go through `generate_session_config` and have no table, so a table-only control would mean the reviewed session and the bulk-converted session held different images with nothing saying so. `both` needed new code only for anatomicals — `acq-nd`/`acq-dis`, with `_disambiguate_anat` now bucketing by `(suffix, custom_entities)` so `run-` still means *acquired* twice rather than *reconstructed* twice. The fieldmap half falls out of description-matched pairing for free (two groups, two `B0FieldIdentifier`s), except that both pairs share an acquisition time, so nearest-in-time cannot separate them and fell through to insertion order — hence `FieldmapDetection.deprioritized`, which narrows the *automatic* candidates only. Validated live through dcm2bids on Crave_control/CC052: both reconstructions land, they differ across 61% of voxels, and the B0 intent is correct |
| 2026-07-24 | — | **The ND choice is made per twin pair, not per series** — the defect LCNI's fieldmap layout exposed (27 `fieldmap_2mm_ND` mag, 28 `fieldmap_2mm` mag, 29 `fieldmap_2mm` phase, 30 `fieldmap_2mm_ND` phase). The twin lookup was a dict comprehension keyed on the description, so of the two series sharing `fieldmap_2mm` it kept only the last — the *phase* — and demoted the ND *magnitude* on the strength of it, never checking the role. And deciding per series can keep one half of each reconstruction, which the identical-description pairing then refuses entirely. Together those reproduced CC056 with a fieldmap: both ND series demoted, the group built on an empty directory, a complete populated pair discarded. LCNI's other worry — that the halves get matched in order, so 27 pairs with 29 — cannot happen here; pairing is `ImageType` + identical description, never ordering. The corpus run then found a third case the unit tests could not: pMAP101 shoots its mprage twice and saves both copies of each, and with each ND picking its own nearest twin one corrected series went unclaimed and converted as a spurious third anatomical **under every policy including the default**. Sides are now paired in acquisition order. The drop is also no longer invisible — `DroppedSeries.reason` and an `nd-duplicate` notice, on 52 corpus sessions that previously said nothing |
| 2026-07-24 | — | **Spin echo read from both witnesses, and the pulse sequence name read at all.** `is_spin_echo` asked only whether `SequenceName` started `epse`, which is right for the pepolar fieldmap and wrong for every other spin-echo family: `*tse2d1_18` does not, so a classic turbo spin echo read as gradient echo — leaving the `anat`/`T2w` rule unreachable in that dialect (those series classified only because their *name* said `t2`) and putting a dual-echo TSE on course to convert as half a fieldmap. Neither witness subsumes the other: the pepolar `epse2d1_104` reports `ScanningSequence ('EP',)` with no `SE`, `*tse2d1_18` reports `('SE',)` with the wrong name — so it is a union. Separately, LCNI's note that the field to read is `PulseSequenceName` (post XA30) else `SequenceName`: duckbrain read only the latter, used it for one bit, and never stored it. Now on `SeriesHeader` and used as a last tier for the two classes nothing else reaches — `*fl3d1_ns` scouts (previously name-only, so a localizer called anything else was `unknown`) and `*spcR` SPACE. The plan for that said SPACE was absent from the corpus and would ship on a synthetic test; the corpus run said otherwise — WMS179 Series_21 is a real undefaced 3D SPACE, and enhanced-dialect, so it exercises exactly the tag that was never read |
| 2026-07-24 | #22 | **A dcm2niix probe, and the correction it forced.** `core/dcm2niix_probe.py` stages one symlink per series and makes a single `dcm2niix -b o` call — **0.15 s warm per session** against 90 s for the same flag over the session directory, which is the invocation the "too slow to preview with" objection was actually about. It buys two fields `dicom_header` cannot reach by any amount of pydicom: the **signed** `PhaseEncodingDirection` (the raw tag is `ROW`/`COL`, no polarity, and absent on XA30) and `ShimSetting`. `plan_warnings` grows `pe-collinear` (error — both halves of a pepolar pair encoded the same way estimate nothing, and it is orientation-free so it holds for oblique acquisitions) and `pe-direction` (warning — the `_ap`/`_pa` name token disagrees with what the scanner did). The second is `consistency._check_fmap_pe_direction` moved to where it can still change the outcome; both now import one `PE_FOR_DIR` so a plan cannot pass preflight and fail after. **The correction: shim is reachable and useless.** dcm2niix reports it for 383/385 corpus series including 100% of XA30 — but in all 18 sampled multi-fieldmap sessions every group shares one shim, and in DEV102 the pair's shim matches *no* BOLD run. So the acquisition-time binding is not a compromise awaiting a shim upgrade; it is strictly better, and `#19.3` and `memory/fieldmap-binding-and-heudiconv` said the opposite until now. Also measured: the `_ap`/`_pa` token is correct 32/32 on the corpus, and LR/RL exists there after all (as diffusion). Wiring it into the GUI followed 2026-08-03, in the row above |
| 2026-07-24 | #19.6 | **Two gradient-echo fieldmap defects, prompted by LCNI** flagging that older fieldmaps are gradient double-echo and that converters mispair them when the halves aren't neighbouring. **That concern was unfounded** — pairing is header `ImageType` + identical description + ordering, never `SeriesNumber + 1`; a magnitude at 5 and a phase at 12 pair fine (all 38 GRE pairs the corpus holds happen to be `+1`, so the robustness is by design, not validation). What checking it *did* find: (a) `plan_warnings`'s half-pair check tested `ap`/`pa` membership rather than calling `is_complete_group`, so **every** GRE session was told its complete fieldmap "can't correct anything and isn't offered for binding" — false in both halves, since the runs were bound to it. `is_complete_group` exists to be the one predicate and the GUI had already moved onto it; this call site had not. (b) `group_entities` was populated only on the pepolar path, so two GRE pairs both wrote `sub-X_ses-Y_{magnitude1,magnitude2,phasediff}`. The collision check caught it as an *error* so nothing was overwritten, but the session could not convert at all and the message advised "distinct task or run values", which a fieldmap has none of. GRE groups now take the same `acq-`/`run-` entities. Fixed on all 6 affected corpus sessions (REV055/REV074/REV126, both sessions each) with binding unchanged; corpus-wide re-run confirms no duplicate fmap filename and no false half-pair anywhere. The 6 are also where duckbrain finds a **second** pair the canonical tree lost — the curator hit this same collision and silently kept the last |
| 2026-07-24 | #19.3 #19.4 | **Three heudiconv ideas borrowed after comparing against its canonical DIVATTEN run on this filesystem.** (1) **Bold→fmap binding by acquisition time** — heudiconv's real criterion is shim settings (a fieldmap corrects only what shares its shim group), but Siemens keeps the shim in a CSA blob not populated until dcm2niix runs, and 36% of the corpus is XA30 with no CSA; AcquisitionTime is the portable proxy and is standard in both dialects. The old "first complete group" bound every run to whichever pair sorted first — wrong for every run after the second pair. Validated on REV055 (fieldmap1 binds GNG/BART, fieldmap2 binds SST/React). Explicit rule and name-match still outrank it; the preview path takes the same time lookup so it can't drift. (2) **Empty source directories flagged** — `plan_warnings` now carries each planned file's source file count and raises when zero, instead of predicting a file dcm2bids silently can't make. (3) Persisting the seqinfo table (heudiconv's `dicominfo.tsv`) not done — `classified_by` already surfaces the same on the Conversion page. heudiconv is Apache-2.0, so borrowing is one-way |
| 2026-07-24 | — | **Two latent bugs the borrowing exposed.** (a) sbref-vs-bold was decided by `len(files) == 1`, a volume count only for a Siemens mosaic or enhanced series — a non-mosaic/GE/Philips single-volume reference arrives as one file per slice and read as a multi-volume BOLD; now settled by counting distinct slice positions, and an undetermined count defers to the name. The scan runs only for a 2D gradient-echo EPI. (b) an `_ND` copy was demoted whenever a same-named twin existed, without looking inside it — Crave_control/CC056 has the corrected mprage folder present but *empty* beside a populated `_ND` copy, so the session got no anatomical; the twin must now be non-empty |
| 2026-07-24 | — | **Conversion hardened against the LCNI repository** (`/projects/lcni/dcm/repository` — 15 studies, 189 series descriptions, 112 sessions paired with canonical BIDS). Agreement with the curator went from **109 of 494 series** to **391 of 392 files (99.7%)**. Four things were wrong rather than merely narrow: the anat vocabulary matched as bare substrings so `BART1_`/`SST2_`/`React2_` classified as *anatomicals* and overwrote the real MPRAGE on one filename; `\bscout\b` can never match `aa_scout` because `_` is a word character, so `AAHScout` (300+ series) fell through to unknown; `_extract_fmap_group` stripped `ap`/`pa` anywhere in the string, splitting one pair into two groups; and the bulk/SLURM path never called `plan_warnings`, so it submitted the collisions the GUI refused. Also: the vNav setter and Siemens' `_ND` copy each converted as a second and third colliding T1w, and `MAB1`/`MAB2`/`MAB3` read as three tasks rather than three runs of one. Remaining gaps are `#19` |
| 2026-07-24 | — | **Classification reads DICOM headers** (`core/dicom_header.py`). It ran entirely on the console operator's free text, which across that corpus is frequently silent about datatype — `food`, `Whack`, `Resting1`, `WMS_R1`, `EPI196` are all ordinary BOLD runs, all classified unknown, all converted to nothing. `ImageType` + `MRAcquisitionType` + is-EPI + is-spin-echo + volume count is a 100%-pure key: **359/359 of the curator's converted series get the right datatype**, 1195 of 1384 decided by header. The finding that shaped it: **two MR dialects**, and 36% of that corpus is Siemens XA30 enhanced-MR with *no* `ScanningSequence`/`EchoNumbers`/`EchoTime` at the top level — a rule keyed on those doesn't misfire, it sees nothing. Absence is never evidence: unreadable or non-decisive falls back to the name path, `classified_by` records which decided, and the defaced-anatomical rule may only promote |
| 2026-07-24 | — | **Gradient-echo fieldmaps convert** — 96 of the corpus's 404 canonical files, and *more* common there than the pepolar pair. Two consecutive series with the same description; `EchoNumber` joins `SeriesNumber` in the criteria because one magnitude series becomes two files, and `'P'` in `ImageType` is the only thing separating the halves. `EchoTime1`/`EchoTime2` deliberately not injected — dcm2niix writes them. Validated end to end against dcm2bids 3.2.0 on real data, and the result is *better* than the canonical, whose fieldmaps carry no `B0FieldIdentifier` at all so fMRIPrep skips SDC on them |
| 2026-07-22 | #16 | **Sanity checks, Slice A — a declaration the data can't quietly agree with.** Ben's reframing is what the item turned on: *codifying intent is different from cataloguing what has been done*, and duckbrain was entirely the latter — every expectation in the codebase is re-derived from the data it judges, so a shortfall shrinks the expectation to match and reads COMPLETE. New `[expected]` project-config section (roster + per-session contents + `[expected.exceptions]`), `core/expectations.py`, `core/checks.py` with a cost-aware registry, rendered in the cockpit's existing panel. **Absent means off** — opt-out is the default and has its own test. Elicited from a good session then frozen (BIDScoin's study-bidsmap bootstrap); `elicit` deliberately never proposes the roster, the one thing disk can't know. Validated live on `divatten_beta`: with a task's BOLD and a fieldmap direction removed from a scratch mirror, `survey_project` still read **complete** for all five subjects while the checks caught both — the contrast is pinned by `test_surveyor_still_reads_complete_when_a_run_is_missing`. Live validation also found a real bug: zero has to be a *declaration*, or "this subject has no resting run" is unrecordable. Prior art surveyed and refused deliberately (Nipoppy's manifest borrowed as a shape, CuBIDS never a pip dep, mrQA out of scope) — `docs/sanity-checks.md`. `#16.1`–`#16.3` stay open |
| 2026-07-22 | #14 | **Inverted fieldmap intent — data cleanup done, and the detector that makes it self-reporting.** The cleanup resolved by *deletion*: the three affected projects were removed, and the one live project (`divatten_beta`, converted after the fix) verified correct in both directions including SBRefs. No fMRIPrep derivative anywhere had been built from inverted data, so the expensive re-run half never arose. The durable half is `fmap-intent` in `core/consistency.py`, deliberately **wider than the original bug** — a *dangling* `B0FieldSource` that no fieldmap declares fails identically and silently, so it is caught too, and the check runs over the NORDIC `bids_input` tree as well as raw BIDS. Validated both ways against real data: silent on `divatten_beta`, and it fires on that same subject's sidecars re-inverted to the pre-fix shape |
| 2026-07-22 | #18.1 | **Quality gates** — CI on Python 3.10/3.12 (import check + `compileall`, `ruff check`, `ruff format --check`, `pytest --cov`), ruff/coverage/pytest config in `pyproject.toml`, coverage floor 60% as a ratchet. The narrow first ruleset found two real bugs. Type checking and the wider lint were left open under `#18`, and closed there 2026-08-04 |
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
