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
[`#13`](#13) conversion legibility (`#13.1` only, and it waits on `#16`) ·
[`#15`](#15) BIDS validation ·
[Licensing](#licensing-follow-ups) ·
[`#19`](#19) conversion coverage ·
[`#22`](#22) wire up the dcm2niix probe ·
[`#23`](#23) `st.components.v1.html` past removal date ·
[`#27`](#27) `4_Preprocessing.py` has no test ·
[`#28`](#28) an fMRIPrep run that produced almost nothing and exited 0 ·
[`#18`](#18) type checking · [`#20`](#20) conda environment ·
[`#2`](#2) onboarding · [`#9`](#9) launch surface ·
[`#5`](#5) config edges · [`#10`](#10) template groups · [`#11`](#11) automation ·
[`#12`](#12) mmmdata-agents · [`#5b`](#5b) NORDIC Case 2 · [`#7`](#7) extra
stages · [`#8`](#8) branding + dark theme ·
[Provenance residuals](#provenance--consistency-residuals) ·
[Loose ideas](#loose-ideas-not-scheduled)

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

*First pass, on `mmmsourcedata/sub-03/ses-01`:* 14 of 53 series arrive ticked and
12 are junk, over 95 sessions. But none of the 12 wants a skip — 8 are
`_ND`/non-`_ND` twin pairs `nd_twin_bases` cannot see (`#19.8`; fixing it hands
them to `[conversion] nd_duplicates`, which already has a save-as-project-default
button) and 4 are diffusion SBRefs classified `fmap` (`#19.9`, where they are
wrong bindings rather than clutter). **`#19.9` closed 2026-07-30** and its 4 are
gone — the session now ticks 10, of which 8 are the ND twins and 2 are wanted —
so `#19.8` is the whole remainder of this measurement.

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
  emits beyond `#19.8` (and `#19.9`, closed).
- **Scouts, which prompted the question, already cost nothing.** `scout` is not in
  `EMITTED_CLASSIFICATIONS`, so a scout is never ticked; nor are the MPR
  reformats, vNav setters, ADC/FA/TENSOR maps, PhysioLogs or PhoenixZIPReport,
  which all classify `derived`/`physio`. On the ABCD session above that is 39 of
  53 series already free.

So build it, after `#19.8`, and motivate it by the anat-only curation
rather than by junk removal. Notes for whoever does:

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

---

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

**Unblocked 2026-07-30 by `#19.9`, which this used to have to follow.** On
`mmmsourcedata` the `rl`/`lr` diffusion SBRefs were classified `fmap` and escaped
pairing *only* because those directions went unrecognised, so widening `dir-`
first would have built a second spurious fieldmap pair out of them. They now
classify `dwi` on their sibling's authority and never reach `detect_fieldmaps`,
so the order no longer constrains this. Keep the tree as the fixture — it is the
only LR/RL data on the filesystem — but note the caveat that has not changed:
what it holds is LR/RL *diffusion*, not an LR/RL fieldmap, so the emission still
has nothing to validate against and `#19.1` is the item that would give it one.

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
default (`corrected`) will disagree on every twinned session — 47 of them — and
that would be a *default* to reconsider, not a bug to fix.

### `#19.8` — ND twin detection never fires on a scanner that omits the tag

🔴 **Found 2026-07-28 on a beta tester's data**, `/projects/hulacon/shared/mmmsourcedata`
(read-only; 5 subjects, 95 sessions, ABCD-style protocol). Her sessions save both
reconstructions — `ABCD_T1w_MPR_vNav` beside `ABCD_T1w_MPR_vNav_ND`, same for
`T2_coronal_1.8` and `ABCD_T2w_SPC_vNav` — and duckbrain converts **both**,
writing `T1w run-1..run-4` where two of the four are the same acquisition
reconstructed twice. `nd_twin_bases` returns `[]`, so the page never even offers
the reconstruction choice.

**Re-measured 2026-07-30 while answering a question about `#13.1`:** on
`sub-03/ses-01` this accounts for **8 of the 12 junk rows** that arrive ticked
for conversion (`#19.9` accounted for the other 4; since it closed on 2026-07-30
the session ticks 10, of which these 8 are junk and 2 are wanted — so this item
is now the entire remainder). So this is not only a wrong anatomical count —
it is most of the per-session clicking a user of this protocol does, 95 sessions
over. Fixing it makes `[conversion] nd_duplicates`, which already has a
save-as-project-default button, handle the whole class.

The cause is the one-sided guard in `_nd_twin_groups`: it skips any ND-*named*
series whose header carries an `image_type` that does not contain `ND`. On this
scanner every series reads `('ORIGINAL','PRIMARY','M','NONE')` — the token is
absent from **both** copies, so the guard reads "the name says ND, the header
disagrees, therefore `ND` means something else at this site" and bails. That
inference is right for a site that genuinely reuses the token and wrong for a
site that simply doesn't write it, and nothing in the header distinguishes the
two.

**Do not just delete the guard** — it exists so a sequence with `ND` in its name
for unrelated reasons isn't demoted, and that is a real failure mode. The
promising shape is to require the header to *contradict* rather than merely fail
to confirm: only skip when the image type is present **and** carries a
distortion-correction token of its own (`DIS2D`/`DIS3D`), which is what a site
reusing the name for something else would look like. An `image_type` that names
no reconstruction at all says nothing either way, and should fall through to the
name. Validate against both this tree and the LCNI corpus's 47 twinned sessions
before changing it — the corpus is the only place the guard's original case
exists.

Until it is fixed the `convert` control is the workaround, and it is per-session:
5 subjects × 95 sessions × 3 twins is not a workaround anybody will keep up with,
which is the argument for the project-level skip in `#13.1`.

**Her tree is also a live fixture for two things that had none.** It carries
`cmrr_diff_3shell` in **four** phase-encoding directions — `ap`, `pa`, `rl`, `lr`
— so `#19.2` (LR/RL) finally has real data, and `#19.1` (DWI) has a multi-shell
fixture with an SBRef per direction.

---

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

---

<a id="23"></a>
## #23 — `st.components.v1.html` is past its announced removal date

**One call site left** — `gui/components.py::embed_tool_report`, which shows
MRIQC's and fMRIPrep's own Bootstrap reports and is the one place that genuinely
needs an iframe. `#24` slices C and D (2026-07-28) removed the rest: the QC pages
render natively now, and fMRIPrep's figures are served as individual SVGs through
`st.image` rather than through an embedded document. The exported duckbrain
report is a *file*, not an embed, so it is unaffected either way.

Streamlit 1.56 still emits, on every render:

> Please replace `st.components.v1.html` with `st.iframe`. `st.components.v1.html`
> will be removed after 2026-06-01.

That date has passed. It still works in 1.56, but `pyproject.toml` pins only
`streamlit>=1.48`, so the next upgrade a user happens to install can take it
away — and losing it silently blanks every embedded tool report.

Do not swap it blind:

- `st.iframe` is newer than the floor. Check which version introduced it and
  raise the `streamlit>=` floor to match in the same commit, or the fix breaks
  1.48 users instead. That is a decision about who can install duckbrain, not a
  rename.
- The sandbox is weaker than it looks, so don't budget for losing protection
  that isn't there. Streamlit 1.56 sets `allow-same-origin` *and* `allow-scripts`
  together (`static/js/IFrameUtil.*.js`), which cancels the isolation: a `srcdoc`
  document inherits the parent origin, shared under OnDemand with the OnDemand
  dashboard. `embed_tool_report`'s docstring asserted the opposite until
  2026-07-28. Swapping therefore cannot make this *worse*, but check whether it
  makes it better — and if it offers real sandboxing, take it.
- `tests/test_qc_page.py` and `tests/test_gui_components.py` exercise the call
  site, so a swap that breaks rendering should fail rather than go quiet.
- **`core/qc_report.py`'s module docstring is stale on this** — it still says the
  report is shown "via `st.components.v1.html()`", which slice C made false. Fix
  it in the same commit.

Found 2026-07-28 while adding the fMRIPrep report panel; the deprecation warning
is visible in any `AppTest` run of a QC page.

---

<a id="27"></a>
## #27 — `4_Preprocessing.py` has no test driving it

Surfaced by `#26`'s fix, which is the only reason it is legible: the coverage
source was a package name and could never match a Streamlit page, so all seven
read 0% and nothing distinguished a page that was well covered from one that was
not covered at all. With a path source the other six land between 43% and 100%
and this one is **0% — 157 of 157 statements**.

It is not a small page and it is not a read-only one. It builds and submits
fMRIPrep, MRIQC and NORDIC jobs, and it writes project config. It is also where
the anat-reuse silent no-op lived (`memory/silent-nooption-failures`) — the exact
bug class that renders a page which looks right, and the one CLAUDE.md's
"a silently-degrading option is worse than one that fails" rule exists for.

The pattern to copy is the QC pages': `5a_QC_Signal.py` is a four-statement
declaration over `gui/qc_panels.py`, and splitting one 108-statement page into
five *raised* the total, because the logic moved somewhere a test can import it.
`3_BIDS_Conversion.py` is the counter-example — 80% covered by 36 AppTest tests
without any extraction, so AppTest alone is enough if the page is driven. Either
route is fine; the cheap first move is a handful of AppTest runs asserting the
rendered submission command, since that is what the suite already asserts against
everywhere else.

Do not lower the floor to accommodate it.

---

<a id="28"></a>
## #28 — An fMRIPrep run produced almost nothing and exited 0

🔴 **Observed 2026-07-27 on `divatten_beta_v2` and never explained.** Carried out
of `#21` when that item closed, because it was found in the same run and was
explicitly *not* the fsaverage race: `sub-010` is the one subject of five that
the race did **not** take out.

It exited 0. It also never ran `recon-all` — it has no entry under
`sourcedata/freesurfer/` at all — and produced only minimal-level output: no
confounds, and no `space-MNI152NLin2009cAsym` or `fsaverage6` resampling, despite
`--output-spaces MNI152NLin2009cAsym:res-2 fsaverage6 func` and no `--level` flag.

**The consequence is what makes this worth an item rather than a note.** Across
the whole project the run wrote **zero** `*_desc-confounds_timeseries.tsv` files,
so the QC dashboard had no fMRIPrep input whatsoever (`#7.4`). A stage that exits
0 and silently produces a fraction of what was asked for is the exact shape of
`CLAUDE.md`'s silently-degrading rule, one level up: the surveyor grades on
expected-output globs, so this is also a live test of whether `#16`'s `[expected]`
declaration would have caught it.

Nothing here is diagnosed. First moves: read `sub-010`'s fMRIPrep log in
`log_dir` (it is on shared FS, so it survived), check whether the submitted
sbatch actually carried the flags the cockpit rendered, and check whether
`--level` or an `anat_only` parameter reached the command by some path the GUI
doesn't show. `#16.1`'s request record is what would make this answerable rather
than archaeological.

---

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

**DB-002's fuller recommendation — a persisted expected-output manifest — is the
same feature as `#16.1`'s request record**, and is folded in there along with the
trigger for building it. Don't build it twice.

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
below; the other six are unstarted.

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
| 2026-07-30 | `#19.9` | **A diffusion SBRef converted as a pepolar fieldmap half, and functional runs bound to it** — silently wrong preprocessing, not clutter, since fMRIPrep would have estimated the field from two diffusion references and applied it to a BOLD run with nothing complaining. The header tier was not being sloppy and is unchanged: diffusion *is* spin-echo EPI, so a diffusion reference genuinely satisfies `2D and is_epi and is_spin_echo`, and against the real `se_epi_ap_encoding` beside it `is_epi`, `is_spin_echo`, `mr_acquisition_type` and the volume count are identical. `ImageType[2]` is not the discriminator either — `M` on the reference, but 48 of 60 sampled corpus pepolar fieldmaps also read `M`. The fix is the sibling: `_recover_dwi_sbref_from_sibling` strips `_SBRef`, and a base sibling carrying `DIFFUSION` makes this a diffusion reference (`dwi`/`sbref`, `classified_by = "sibling"`). **It is the one place a sibling's header overrules a series' own**, which `_recover_func_from_sbref` refuses to do — the asymmetry is the evidence, not the direction: `DIFFUSION` is a positive statement and what it overturns is a fall-through, so the rule is now stated at both ends. A project declaration still wins over both. Measured before and after across 263 sessions: on the LCNI corpus (166) **nothing changed at all**, as predicted — it holds zero diffusion SBRefs across all 2139 series directories, which is why the tests are synthesised from the real `mmmsourcedata` headers rather than from a corpus run. On `mmmsourcedata` exactly 28 series moved, one transition only (`fmap/epi` → `dwi/sbref`), the spurious `cmrr_diff_3shell_sbref` group was the only group removed and none was added, and 12 direction warnings went to 0. All 10 bindings the item named are corrected: `sub-06`/`sub-07` `ses-01` now bind the resting run and its reference to the real `encoding` pair, `sub-03`/`04`/`05` to nothing, which is right because those sessions contain no fieldmap. Two neighbours moved with it — `#19.2` is unblocked (the `rl`/`lr` references escaped pairing only through going unrecognised, so widening `dir-` first would have built a second spurious pair), and `#13.1`'s ABCD session drops from 14 ticked rows to 10, leaving `#19.8` as the whole remainder of that measurement |
| 2026-07-30 | `#13.1` | **The `Type` column is editable, and a correction generalizes to the study** — a `SelectboxColumn` plus a new `[series_types]` project section read by `classify_series` as a tier above header and name (`core/series_types.py`, `save_project_series_types`). The item's own warning about the write-back was right and its fix was not: the edit is read **above** `classify_series`, so `detect_fieldmaps`, the task/run seeding, the fieldmap bindings and `generate_config`'s dispatch all see one datatype instead of the column and the emission following different ones — there is no second copy to keep in sync. `generate_session_config` takes `type_rules` for the same reason it takes `fmap_rules`, or bulk convert would write a different datatype than the one reviewed. Three refusals carry the honesty. **An anat declaration names its suffix** (`anat/T1w`): `_anat_description` reads the suffix off the *name* vocabulary and returns `None` when nothing fires, so a bare `anat` on a study-specific label writes nothing and says nothing — and the declaration outranks that vocabulary, where `suffix_hint` deliberately cannot, or a misread `t1w_mprage` would be uncorrectable. **`fmap` and `dwi` are not declarable**, since a label alone can't make either emit (pairing reads the direction from the description; `#19.1`). **A non-declarable pick is refused by name** rather than accepted and ignored — the dropdown must still *offer* the inferred classifications because a select cell cannot render a value outside its options. The `convert` checkbox stayed the way to drop a series. One neighbouring silence closed on the way: the one-shot JSON import now reports a datatype it will not carry over, which it had always dropped under a banner saying the JSON had loaded |
| 2026-07-30 | `#26` | **The coverage gate could not see a single Streamlit page, and the item's own diagnosis of why was wrong.** `source = ["duckbrain"]` is a package *name*, and coverage resolves those by **module name**: streamlit execs a page as a module called `5_QC_Overview`, which is not a `duckbrain` submodule and is not a legal Python identifier, so it could never match — `COVERAGE_DEBUG=trace` says exactly that. Not AppTest, not a process boundary, not the `magic` AST rewrite; a path source traces the pages fine. Same tests, same 6466 statements, **73% → 87%**, floor 70 → 85. The load-bearing part is what the false explanation cost: the item claimed the ratchet "exerts no pressure at all on the code where this bug class lives" and that was never true — `3_BIDS_Conversion.py` was **80% covered** by tests already passing, and the report was throwing it away. Also required, not cosmetic: CI's `--cov=duckbrain` *overrides* the config source, so fixing `pyproject.toml` alone would have left CI measuring the old way. The floor was measured after the fact rather than reused from the exploration, since two pages had changed since. One real gap fell out and is open as `#27` (`4_Preprocessing.py`, 0%). Two notes cleared with it: `#26.1`, a comment asserting `series_list` is cached across reruns — it is not (no `lru_cache`, no `st.cache_data`, no fragment; `list_series` runs at page top every rerun), so the `elif` it guarded was dead and is gone. `#26.2`, the `st.stop()` at the config call: **reachable, but not by the binding its comment named** — the two repair passes above it rewrite every unsatisfiable rule to `none`, so what still lands there is `generate_config`'s *other* raise, two fieldmap groups colliding on one B0 identifier (`2.5mm`/`25mm`). No table cell repairs that and the call already raised, so there is no config to render from: it stays a stop where its neighbours warn, now with a test that says so. **The refactor is deferred, not refused** — extracting `(seed, edits, imported, override) -> effective plan` into `core/` is still the right shape, but its cheapest justification was the coverage gap and that is now free, one of the four inputs already got one home in `c0f4650`, and the diagnostics are interleaved with the derivation so ~18 of the 36 render-coupled tests would be rewritten for a presentation-token round trip |
| 2026-07-29 | `#25` | **All three tags published as GitHub Releases, and `v0.3.0` cut to make that worth doing.** A pushed tag notifies nobody and is invisible to the API, so `docs/releasing.md` step 7's announcement channel did not exist and `core/updates.py` — shipped the day before — queried `releases/latest` and got a 404, meaning the GUI's "newer version" line was dark for every user from the moment it landed. Backfilling 0.1/0.2 alone would have turned the channel on and had nothing worth announcing: the **fieldmap-intent inversion fix sat in `[Unreleased]` for eight days**, so users on `main` had it and anyone pinned to a tag did not. Hence `v0.3.0` — 50 commits, +27.8k/−1.7k. **Minor, not patch, deliberately**: `_release_line()` reduces to `major.minor` and `check_duckbrain_drift()` therefore flags every derivative built under the 0.2 line, which is *correct* here rather than collateral, because this release changes recipes duckbrain authors (which series convert, their datatype, the `B0Field*` intent in every sidecar, which reconstruction ships, which pair corrects which run) and not merely the flags passed to a container. The changelog's thirteen repeated Added/Changed/Fixed headers — one set per work session — were merged into one of each, since that section becomes the published notes; every bullet moved verbatim and the 688 content lines were diffed before and after rather than eyeballed. Two environment limits worth knowing if this is ever automated: the agent sandbox refuses tag refs (`HTTP 403`) while accepting branch refs, and the GitHub MCP server exposes releases read-only — so tag and publish stayed manual |
| 2026-07-28 | — | **A series can be left out of the conversion** — a `convert` checkbox on the plan table, prompted by a beta tester asking how to skip a run. The config's native spelling of "not converted" is *no description*, so `generate_config(skip=…)` simply omits one and everything downstream follows with no new state: `becomes` already rendered `— not converted` for an unclaimed series, and the skip survives save/reload through the saved JSON alone. Three things the naive version gets wrong. **A skipped fieldmap half takes its whole pair** (`_without_skipped_groups`) — half a pair is not half a fieldmap, and emitting the survivor writes a `fmap/` file nothing can be estimated from; a run still bound to a pair whose half was unticked is refused, naming the two edits that conflict rather than letting `generate_config` say the session lacks a group the user removed three rows up. **The drop carries a reason**, because the warning it otherwise raises means "nothing claimed this" — the anat-suffix bug that warning exists to catch — so the reason travels on `SeriesInfo.drop_reason` and the finding is an info note; that also fixes the pre-existing double-report where an ND-demoted anat got both the warning and the note, and the kind is `deliberate-drop` now, not `nd-duplicate`, since the ND policy was the first thing to set a reason and is no longer the only one. **A stranded SBRef is reported** (`orphan-sbref`): bold and sbref are two rows, so skipping one and not the other is a click away, and an SBRef alone is the reference volume for a run that isn't being written. Rows duckbrain has no emission path for start unticked so the box agrees with `becomes`; `EMITTED_CLASSIFICATIONS` is deliberately not "everything that isn't an expected drop", because `dwi` classifies cleanly and still converts to nothing. Per-session by construction — see `#13.1` for why a project-level skip needs the description key |
| 2026-07-28 | — | **All duckbrain-authored output moved under `derivatives/duckbrain/`** (`qc/decisions/`, `qc/reports/`), so a project shows at a glance which derivatives a tool produced and which duckbrain did. The tool trees stay put — they are the tools' own derivative datasets and BIDS expects them at `derivatives/<pipeline>/`, and that includes `fmriprep/sourcedata/freesurfer`, which duckbrain only seeds `fsaverage` into. No file is moved: `decision_search_dirs` still reads `preprocessing_qc/`, legacy root first so the current location's entries are the newest, because mmmdata still writes there and a project reviewed before the move must not lose its history — the same treatment `_history_of` gives the two on-disk schemas, applied to the two locations. Verified live on both real projects: 1 and 609 records, all still read, none moved. The report's MRIQC links are now computed from `REPORT_SUBDIR` rather than a hardcoded `../mriqc`, since deepening the subdir would otherwise have pointed every link at a directory that does not exist — silently, a broken relative link being ordinary text |
| 2026-07-28 | `#24` | **QC review is grouped by the question being asked** — an Overview plus one page per domain (signal, temporal, alignment, artifact) under a collapsible `QC` nav group, each measure's guidance beside the number instead of in a glossary, and each measure shown with where the run sits among the runs around it. `core/qc_domains.py` partitions all 30 registry measures at import (a measure in two domains emits duplicate `#guidance-{key}` anchors), and carries the fMRIPrep figures that can never be registry entries — which is what gives alignment, the domain with no MRIQC number on bold, anything to show. `core/qc_evidence.py` serves those figures per run: 1.1 MB against 80 MB for the subject report, with the SDC flicker intact because the animation is CSS inside each SVG, verified reaching the browser as a self-contained data URI. Matching is by BIDS entity, not by prefix join, which is what makes `sub-03_acq-MPR_dseg.svg` findable on a session dataset. An absent figure is stated, not skipped — no SDC figure means the run was preprocessed with no distortion correction. Domain reviews share the per-run decision file via an optional `domain` field, with a vocabulary disjoint from the verdicts' and `latest` meaning the newest entry carrying *no* domain, so a note about alignment can never become the run's verdict; 609 real records read unchanged. Coverage rose 70.83% → 73.51% because the five pages are four-statement declarations over one tested module, so the ratchet went 65 → 70. Slice B (regrouping the HTML export) dropped by decision, not deferred |
| 2026-07-27 | `#21` | **The shared `fsaverage` race is closed by seeding, not staggering** — `core/fsaverage.py`, wired into `advance_one` so no launcher can forget it. fMRIPrep's `BIDSFreeSurferDir` deletes an fsaverage tree that lacks the FreeSurfer-7 sentinel, and a tree being copied into lacks it for the first 0.39 s of a 1.83 s copy, so job B `rmtree`s job A's copy in progress and nothing raises — surfacing ~3 hours later at `recon-all`'s BA_exvivo stage, and stickily, since the merged tree *does* carry the sentinel so the self-repair can never fire again. Took out 4 of 5 subjects on `divatten_beta_v2`. Completeness is judged against the container's own manifest (312 files / 109), never the sentinel — a checker asking fMRIPrep's question would have called the 259-file tree fine. The full reasoning is the `core/fsaverage.py` module docstring and commit `a6eb399`; pinned by `tests/test_fsaverage.py`. One thing from that run is **not** explained by the race and is open as `#28` |
| 2026-07-24 | `#7.4` | **The QC norms layer migrated from mmmdata in three slices.** Slice 1, the 30-measure registry plus a `[qc]` config section, worked the plan's "cannot be verified without data" table first against 717 real MRIQC JSONs — the registry was right about every content question it raised, and real output is now committed as `tests/fixtures/mriqc/` so a wrong key name fails a test instead of rendering a blank column. Slice 2, `core/qc_report.py` plus the embed, settled the link question by having duckbrain serve the reports itself through Streamlit's media endpoint (`core/report_embed.py`) — relative paths fix the exported copy and can never fix a `srcdoc` iframe, whose base URL is the page's; two alternatives that look right from outside are recorded in `components.py`. It also found `load_mriqc_metrics` returning **zero** runs on any sessionless study, so the QC page had never worked on `divatten_beta`. Slice 3 migrated nothing because nothing needed it: mmmdata's append-only schema reads as-is (609/609, 0 files modified), and live data forced a third count bucket, `automated` vs `unattributed`, because only the second is closable by re-reviewing. Plan and the two corrections it forced: `docs/qc-dashboard-migration.md`. Group-level IQM comparison stays open under `#7` |
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
