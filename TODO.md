# duckbrain — TODO

**Open work only**, plus three unscheduled tails after it (`#5`, provenance
residuals, loose ideas). Closed items are a one-line ledger below those. The detail
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
[`#16`](#16) **next** — sanity checks (Slices A–C done; `#16.3` open) ·
[Licensing](#licensing-follow-ups) ·
[`#2`](#2) onboarding — the writing shipped in `v0.5.0`; the remainder (clean-account
walk, in-GUI guidance, distribution) is blocked on people who aren't Ben — take
sub-items as the blockers clear ·
[`#19`](#19) conversion coverage — **not scheduled**, mostly data-blocked; take
sub-items as fixtures appear ·
[`#40`](#40) per-subject staleness ·
[`#39`](#39) QC Overview IQR strips ·
[`#9`](#9) launch surface ·
[`#10`](#10) template groups · [`#11`](#11) automation ·
[`#12`](#12) mmmdata-agents · [`#5b`](#5b) NORDIC Case 2 · [`#7`](#7) extra
stages · [`#8`](#8) branding + dark theme ·
[`#30`](#30) GUI eyeball queue (batch these; don't check one at a time)

**Below the queue, unscheduled, and not closed either:**
[`#5`](#5) standing config / mapping decisions ·
[Provenance residuals](#provenance--consistency-residuals) ·
[Loose ideas](#loose-ideas-not-scheduled)

**How the open items bundle into releases: [Roadmap](#roadmap)** — decided
2026-08-06, and it is what reordered the queue above: `#20`/`#2` moved ahead of
`#16`, which had been marked **next** since 2026-07-22. On 2026-08-11 `#2`
moved back out of **next**: `v0.5.0` shipped its writing, and everything left
in it is externally blocked (see the entry), so `#16` leads again. On
2026-08-16 `#16.2` shipped, which hands the lead to `#13.1` — the last item in
`v0.6.0`'s plan. Later the same day `#13.1` shipped too (the `[series_skip]`
section; see the ledger), and `v0.6.0` was cut the same day — a fact this file
kept misstating as "ready to cut" for a day afterwards; `git tag` and the
Releases page agree it is out and published. On 2026-08-17 `#13.2` shipped —
the plan-time schema check, taking `#19.11`'s answer with it — which closed
`#13` outright, so `#16` leads the queue and `#13.2` rides in whatever release
comes next.

---

<a id="roadmap"></a>
## Roadmap — which open items ship together, and why

**Decided with Ben 2026-08-06, immediately after cutting `v0.4.0`.** The question
that produced it was whether `#16`, `#13`, `#19`, `#20` and `#2` could go out as a
single increment. They can't, and the interesting part is *why not* — the answer
generalizes past this one bundle, so it lives here rather than in the commit.

**The cut is by kind, not by size.** Two questions sort the queue, and neither is
"how much work is it":

1. **Does it change a recipe duckbrain authors?** That is `docs/releasing.md`'s
   own minor-vs-patch test, and it has a mechanical consequence:
   `consistency._release_line()` reduces to `major.minor`, so any minor bump makes
   `check_duckbrain_drift()` flag every existing `converted` and `nordic`
   derivative. A release that changes what gets *written* should flag them. A
   release that changes only how duckbrain is *installed* should not have to.
2. **Is it schedulable at all?** Several open items are blocked on data or on
   another item's design settling, not on effort. Those cannot be committed to a
   release without making the release hostage to something nobody controls.

Bundling everything collapses both distinctions at once: finished, zero-risk
packaging work would sit unreleased behind an open architectural question, and the
whole thing would wait on fixtures that may never arrive.

### `v0.4.0` — cut 2026-08-06 ✅

88 commits and a 474-line changelog section had accumulated in the eight days
since `v0.3.0`. The trigger was not the size but who was missing it: `#34` (host
site-packages leaking into every container) and `#36` (MRIQC OOM at the shipped
defaults) were both reported *by* a beta tester and both fixed only on `main`, and
`core/updates.py` compares against published Releases, so their GUI said nothing.
Minor rather than patch because the recipe genuinely moved — diffusion converts,
the diffusion SBRef stopped being emitted as half a fieldmap, `dir-` widened to
LR/RL, and the BIDS root files are written at the conversion choke point.

### `v0.5.0` — accessibility: `#20` + `#2`'s writing — cut 2026-08-11 ✅

Shipped `#20`'s conda environment and `#2`'s writing (`QUICKSTART.md`,
`README.md`, `docs/new-to-talapas.md` + its GUI signpost page, both launch
routes documented as real). The order was not arbitrary: `#20` made conda the
documented path, and `#2`'s `UNVALIDATED` new-user walk is only worth doing
once, on whichever path new users are actually told to take — which is now the
conda one. Invisible to `duckbrain-drift` by design: not a byte duckbrain emits
changed, so no existing derivative gets flagged.

**Decided with Ben 2026-08-11: the release did *not* wait for the rest of
`#2`.** The plan above had been "`#20` then `#2`", but everything left in `#2`
fails this roadmap's own second sorting question — schedulability. The
clean-account walk needs a non-maintainer account, the in-GUI guidance is gated
on that walk, and distribution is gated on a RACS answer; none is under Ben's
control on any timeline, and holding finished, zero-risk accessibility work
behind them is exactly the hostage-taking the roadmap exists to prevent.
`core/updates.py` compares against published Releases, so unreleased docs were
invisible to the beta testers who wanted them. `#2` stays open, below `#16` in
the queue, and its remainder rides in whatever release is current when the
blockers clear.

The cut also surfaced that **`v0.4.0`'s tag was pushed but its GitHub Release
was never published** — the exact failure `docs/releasing.md` warns about, and
why the GUI told nobody about `v0.4.0` for five days.

### `v0.6.0` — the expectation layer: `#16.1` ✅, `#16.2` ✅, `#13.1` ✅ — cut 2026-08-16 ✅

This is the one with genuine design risk in it, which is exactly why it must not
be bundled with the release above. That risk is now retired: `#16.2` needed
duckbrain's *first cache*, and it shipped — `surveyor.py`'s docstring now names
`checks.json` as the one deliberate exception to "no state store" rather than
advertising the absence as a virtue.

**`#16.1` shipped 2026-08-11** (see the ledger; decisions in
`docs/sanity-checks.md`, Slice B). It also discharged the question it owned:
"which series this study converts" does **not** fold into `[expected]` — the
reasoning is recorded at `#13.1`, which therefore gets built as its own
description-keyed section.

**`#16.2` shipped 2026-08-16** (see the ledger; decisions — including the one
deviation from the plan recorded here, no job id in the cache key — in
`docs/sanity-checks.md`, Slice C).

**`#13.1` shipped 2026-08-16** (see the ledger; the design record is
`core/series_skip.py`'s module docstring, the page mechanics are
`docs/conversion-legibility.md` phase 9), and the release was cut the same day
— tagged, pushed, and published on the Releases page. `#13.2` (2026-08-17)
missed it and rides in the next release: a new refusal, not a new recipe — the
sweep measured zero filename changes, so nothing duckbrain *writes* moved, and
on the roadmap's own minor-vs-patch test it does not by itself force a minor.

### `#19` — deliberately not in the version plan

Take its sub-items opportunistically as fixtures appear; do not schedule the item.
Most of what is open there is **blocked on data, not on effort**:

- `#19.2` waits on an LR/RL *fieldmap*. Neither `mmmsourcedata` nor the LCNI
  corpus holds one.
- `#19.6` has a local oracle now (the `PHASE` token, and the phase sidecar's
  `EchoTime1` matching the magnitude's `EchoTime`) but still no session exhibiting
  either fragility — "no evidence available" became "no failing case available",
  which is closer but is still not a thing to schedule.
- `#19.7` waits on LCNI re-converting their anatomicals.
- `#19.10` waits on `#7.2`/QSIPrep existing as a *consumer*; writing
  `B0FieldSource` before then is metadata nothing reads.
- `#19.12` has no fixture at all — 0 unequal ND pairings across all 166 corpus
  sessions — so it is a policy decision whenever someone wants to make it.

The one sub-item that needed no fixture, `#19.11`, rode along with `#13.2` and
closed 2026-08-17 (see the ledger).

### The cost this plan accepts, stated once

Three minor bumps instead of one means a beta tester sees the `duckbrain-drift`
note three times rather than once. Accepted deliberately: it is `note` severity,
and two of the three releases genuinely change what duckbrain writes, so the note
is telling the truth each time it fires. The alternative — suppressing real
provenance drift to keep a notification quiet — is the trade this project has
consistently refused elsewhere.

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

**Slice B (`#16.1`, the request record) shipped 2026-08-11** — every launch
writes `requests/<job_id>.json`, `submissions.tsv` gained `request_path`, and
`checks._check_requested_spaces` is the first consumer (see the ledger; the
design decisions, including the per-check gate restructure and the DB-002
"persisted manifest" framing this also closes, are recorded in
`docs/sanity-checks.md` under Slice B). The `#13.1` question it owned is
answered at `#13.1`; NORDIC's sidecar-vs-NIfTI "free half" was deliberately
left for `#16.2`'s outcome family.

**Slice C (`#16.2`, the outcome checks and the first cache) shipped
2026-08-16** — `outcome-sdc` and `outcome-nordic`, `EXPENSIVE` in the registry,
persisted to `<log_dir>/checks.json` with a fingerprint and rendered in the
cockpit's outcome panel with a staleness confession (see the ledger; the
decisions, including the one deviation from the in-principle plan and the two
family members that needed no code, are in `docs/sanity-checks.md` under
Slice C). The anat-reuse family member moved to the unhomed candidates below.

What remains:

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

- **"Reuse anat derivatives" actually reusing** — the `#16.2` family member
  that shipped without code, for want of an honest outcome signal: fMRIPrep's
  report does not state reuse legibly, and the dangerous direction (nothing to
  reuse) already raises at build time (closed 2026-07-20). Needs a signal
  before it needs a check.
- **Cross-artifact agreement**, the family `fmap-pe-direction` (2026-07-21)
  started: TR / volume counts consistent across runs of one task.
- **Quality norms** — overlaps `#7.4` (MRIQC norms dashboard); fold them together
  rather than building two things.
- **Display-vs-reality**, inherited from `#17`. Every one of that item's ten
  findings was a display or a control, so none could be caught by tests asserting
  on returned values. The cheap general *defense* is already articulated by
  `#13`'s anti-drift rule (now closed; the standing statement is
  `core/conversion_plan.py`'s module docstring) — **derive the display from the
  artifact that will actually be used, never re-derive it from the inputs**.
  Whether detection can be mechanized here at all is unproven; that rule may be
  the whole answer.

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

<a id="2"></a>
## #2 — Onboarding for external users

**The writing shipped in `v0.5.0` (2026-08-11); the dogfooding and the
distribution story are open — and, decided with Ben the same day, they no
longer gate a release.** Every remaining sub-item below is blocked on someone
other than the maintainer: the `UNVALIDATED` walk needs a non-maintainer
account (a beta tester's time), the in-GUI guidance needs the walk to have
happened, and distribution needs RACS. Take them as the blockers clear, and
batch `#30`'s browser-eyeball queue into the walkthrough — it puts you in front
of the GUI anyway. `QUICKSTART.md` and `README.md` are written and current.

**2026-08-07 — Ben's three directions for this item, all landed the same day:**

1. **Both launch routes are documented as real, current paths** — the
   interactive-session + `scripts/launch.sh` route is what the beta testers
   actually use (over an SSH tunnel, or tunnel-free from a browser inside an
   OnDemand Interactive Desktop), and the personal OnDemand sandbox is the
   maintainer's route. The docs previously framed launch as "unresolved,
   neither blessed", which understated reality. The *distribution* question
   (RACS-published shared app) stays open below — routes being real is not the
   same as routes being one-click.
2. **A hand-holding guide for users new to cluster computing entirely** —
   `docs/new-to-talapas.md` (it landed as an in-app page,
   `7_New_to_Talapas.py`, and moved to the repo the same day so it is
   readable on GitHub *during* setup — the people who need it most are
   exactly the people who can't launch the GUI yet). Plain-words concepts
   (nodes, SLURM, PIRGs), canonical tutorial links (shell, RACS, Git/GitHub,
   conda, SLURM, BIDS, fMRIPrep, MRIQC), and the PI-check list below. The
   GUI page and `QUICKSTART.md`'s opening section are now signposts to the
   one canonical copy; `tests/test_guide_pages.py` pins the doc's link set
   and both signposts. Audience context that shaped it: the current
   beta testers are tech-savvy, but users new to clusters, the command line,
   and GitHub are coming — and the docs now clone over HTTPS for exactly that
   reason (no GitHub account or SSH key needed).
3. **Lab decisions are flagged as "ask your PI", in the docs and on the page** —
   because these newcomers' PI will *not* be duckbrain's maintainer. The
   flagged set: PIRG/SLURM account, whether the lab already has the shared
   conda env (and at what prefix — `setup_env.sh`'s default is hulacon's) and
   the containers, tool versions and options (output spaces, NORDIC yes/no —
   consistency across a study is a methods-section matter), and where projects
   live.

- **`UNVALIDATED` — the new-user path on a clean account.** Flagged inline in the
  docs too. The path to walk is the **conda** one, since 2026-08-07 that is what
  new users are told to do (that reordering is the whole reason this item waited
  for the environment work). Nobody has walked: fresh `git clone` →
  `./scripts/setup_env.sh` → activate → tests pass — and on an account that is
  not the maintainer's, which matters twice here: the shared prefix already
  exists (their run takes the *update* path, never exercised clean) and the FSL
  condarc landmine fires per-account. Then the three `singularity build`
  commands actually building on Talapas
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

<a id="40"></a>
## #40 — Staleness check: compare per subject, not project-wide

Found live 2026-08-18, the first real firing of `_check_staleness`
(`core/consistency.py`): a NORDIC run for `sub-020` — a subject fMRIPrep has
never touched — flagged fMRIPrep stale across the whole project, and the
message's advice ("re-run it on the updated NORDIC data") prescribed re-running
five subjects whose inputs never changed. The heuristic compares project-wide
newest mtimes by design, which is exactly wrong for the grow-the-project case:
every new subject's NORDIC run smears "stale" over every finished one, and a
warning that overreaches gets ignored, which is how a *true* staleness later
walks past it. Compare newest NORDIC bold against newest preproc bold **per
subject**, flag only subjects where both derivatives exist and NORDIC is newer,
and name them in the message. A subject with NORDIC and no fMRIPrep is not
stale — it is not run yet, which the cockpit already shows and
`_check_presence` deliberately doesn't cover (it guards the inverse).

---

<a id="39"></a>
## #39 — QC Overview: IQR strip plots under the run table, click-to-inspect

Asked by Ben 2026-08-18: the exported dashboard's IQR plots are "pretty
useful" — render them live below the Overview run table too. Plotly is
already a dependency, and the click-through is less ambitious than it sounds:
`st.plotly_chart` emits `on_select` events the same way the run table's
row-click does, so a clicked point hands its run to the Inspect page through
the exact mechanism the two-page rework proved — including the
consumed-selection guard against re-firing on the way back, which the
2026-08-18 eyeball pass confirmed working live. While touching the page: a
caption hint on the run table ("select a row to open it in Inspect") — the
same pass read the bare checkbox affordance as odd, and a hint is the whole
remedy available (`st.dataframe` has no button column; hand-rolled rows would
trade away sorting and column config).

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
   **Dud detection is this item's first half** (ruled 2026-08-17, mmmdata
   Contract A close-out): MMMData's catalog declares physio/eyetracking per
   bold unit, and per the acquisition notes ~50% of physio attempts produced
   empty files — the catalog sees presence, not emptiness. The pass this item
   owns: read each recording (766 across sub-03/04/05), judge real-vs-dud, and
   hand per-run dispositions back across the ingest boundary so the catalog's
   315 `pending` physio/eye units resolve (engine/contributor split:
   mmmdata-agents `docs/constellation-contracts.md` §3.2 — duckbrain
   contributes facts, the catalog ingests). Any PhysIO/TAPAS implementation
   parses every recording anyway, so dud detection falls out of step one.
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

Two polish notes from `#13`'s eyeball pass landed here when that item closed
(2026-08-17) — both were parked on "decide with the theme, or the work is done
twice", which is this item:

- The Conversion table's `anat/T1w` reads slightly filenamey; `anat (T1w)` was
  floated and called non-essential. Not free either: the token *is* the
  persisted `[series_types]` value, so changing the display means either a
  render-only mapping or a config-format change.
- Whether the grouped fieldmap view (`docs/conversion-legibility.md` phase 4)
  is redundant with the unified table (phase 6). The table carries the same
  relation on every row; what the section still adds is aggregation — every
  bold for one pair in one place — which Ben found "good for sanity checking".
  The cheap middle is an expander rather than deletion. A density judgment,
  and density depends on the theme.

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
   and click through to an MRIQC report. The 2026-08-18 pass left this pending
   but noted "the html report downloaded via browser nicely" — if that download
   *was* the click on a View-report link, the verdict is "the link resolves but
   this serving context downloads instead of rendering", a different (and
   probably livable) outcome from the dead click; pin down which it was.
2. **[OOD] Should the app serve tool reports itself?** A design question, not a
   check — restated 2026-08-18 after a pass found it too vague to act on. The
   embedded report is a `srcdoc` frame with **no origin**, so links *inside* it
   have nothing to resolve against and are dead by construction, and the
   exported dashboard is today's only route to a full MRIQC/fMRIPrep report
   outside the app. The concrete question, answerable only mid-review: **while
   doing a real QC pass, how often do you reach for the full report, and does
   the export-then-open detour hurt enough to justify the app serving
   derivative files over HTTP itself?** If the detour is fine in practice,
   close this as an accepted limitation in `docs/qc-dashboard-migration.md`
   (which calls its item 2 "only half-closed" for exactly this); if it hurts,
   the follow-up is real design work — a static file route — and gets its own
   TODO item rather than a line here.
3. **The full tool report embedded on the Inspect page** — the "Open the
   tool's own report" expander (`gui/qc_panels.py`, `full_report_panel`), which
   ships the MRIQC/fMRIPrep HTML itself as an `st.iframe` `srcdoc`. Distinct
   from the evidence figures above it, which the 2026-08-18 pass cleared; the
   2026-08-18 pass asked "what report?", which is this note's reason to exist.
   Closed 2026-08-03 (`#23`) on an assertion about the frame's `srcdoc` — the
   right test for *what was passed*, and silent about what renders. Look for
   what a srcdoc assertion cannot reach: does the report scroll inside its
   frame rather than clipping, is the height sane, and do its own internal
   anchors work.
4. **The `#37` bar redraw.** The reorganized top nav (Status · Setup ·
   Preprocessing · Guide · BIDSification ▾ · QC ▾) is exactly the width/strip
   behaviour AppTest cannot judge — it asserts the declared page lists, not
   what the frontend draws. Three looks in one: does the **BIDSification
   dropdown** open, name its three pages, and navigate; does the bar hold at
   the widths the 2026-08-18 pass tried now that the two longest labels are
   gone and two groups sit in it; and does the computed landing behave in a
   real session (a fresh launch with a project open goes to Status, one
   without goes to Setup — AppTest pins the `default=`, not what the browser's
   session actually restores).
5. **[OOD] Repoint the cached OnDemand form value, then confirm the stamp.**
   Narrowed 2026-08-18 from the conda-branch launch entry: the launch itself is
   now proven — the whole eyeball pass ran through the proxy on the conda env
   (the personal checkout records the shared prefix and has no `.venv`, so no
   other branch could have served it) — but the session's `duckbrain_dir` was
   the *cached* legacy default (`/gpfs/home/%{ENV:USER}/code/duckbrain`, which
   `script.sh.erb` rewrites to `$HOME/code/duckbrain`), so it served the
   personal checkout, not the shared one. Harmless that day — both checkouts
   sat at the same commit with clean trees, which is what keeps the pass's
   verdicts valid — but exactly the drift the 2026-08-16 repoint exists to end.
   Edit the field once to `/gpfs/projects/hulacon/shared/mmmdata/code/duckbrain`
   (OnDemand remembers it from then on), relaunch, and confirm the sidebar
   version stamp shows the shared checkout's `git describe` — the commit that
   struck the old entries landed only here, so until `~/code` pulls, the stamp
   discriminates.
6. **The ingestion "Imported" badge column** (`#38`, 2026-08-18). Rendered
   inside `st.data_editor`, whose output AppTest does not model — the tests
   pin the backing dataframe's values, not what the frontend draws. Look at a
   project with ingested sessions: do the ✅/❓ glyphs render legibly in the
   disabled column, does the column width leave the `sub-XX/ses-YY` labels
   readable rather than truncated, and does the header tooltip open.

**Dark theme is deliberately not an entry** — it is `#8`'s, with the two specific
traps already named there. But `#8` and this item want the same session, and that
is the obvious economy: the theming pass has to look at every surface anyway.

**Already discharged; do not re-add.** The 2026-08-18 pass (Ben, OnDemand +
resize) discharged ten entries in one sitting — the Preprocessing tabs and
their `.sbatch` export, the BIDS validation panel, save confirmations, cockpit
narrowness, the before/after flicker viewer, the four-button save row, the
Overview→Inspect→Overview round trip, the Inspect page's weight with every
figure open, the fifteen-column export, and the seven-entry top nav — verdicts
in the commit that struck them. It also surfaced the staleness heuristic firing
correctly on a same-day NORDIC run for a subject fMRIPrep hasn't touched
(`_check_staleness` compares project-wide newest mtimes by design; its
"re-run fMRIPrep" advice overreaches in that case). The cockpit's browser
eyeball closed
2026-07-17 (`de1a155` — dashboard width good, folder picker fine); three rows of
`docs/pipeline-cockpit.md` claimed otherwise until this item was written, and now
say so. `#13`'s Conversion Plan pass closed 2026-07-30 on `fmap_eyeball`
(`f1bde41`) — the colour join holds on three pairs. The QC evidence viewer's
figures were confirmed reaching a browser as self-contained data URIs, which is
why they are **not** entry 1: a data URI has no URL for the proxy to get wrong,
and that is by construction rather than by luck. (That eyeball judged *presence*,
not motion — the same figures sat frozen on their "before" frame until the
2026-08-10 hover fix, whose flicker eyeball the 2026-08-18 pass cleared. The
hover-gated ones travel as srcdoc iframes; still URL-free, so still not entry
1's problem.)

---

<a id="5"></a>
## #5 — Standing config / mapping decisions

**Not open work, and it never was** — every bullet below is a decision already
made, a trigger waiting on the outside world, or a pointer to where the live work
went. It sat in the priority list until 2026-08-06 promising a task that doesn't
exist; moved here rather than to the ledger because the standing rule it opens
with still **binds new code** — `ingestion.py`, `conversion_plan.py`,
`dcm2bids_config.py` and `dicom_inspect.py` each cite `#5` for it, as do
`docs/conversion-legibility.md`, `docs/pipeline-extras.md` and
`docs/handoff-cluster-session.md`. The id and this anchor stay put so those
citations keep resolving; a ledger row would have said less than the comments
making the reference.

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

Listed so they aren't rediscovered as bugs. Each is fine as-is.

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
| 2026-08-18 | `#38` | **Ingestion badges source sessions that are already imported.** An "Imported" column on the Available DICOM Sessions table joins each discovered folder to what sourcedata holds, via the provenance `ingest_session` already leaves (symlink target / copy marker) — read the way `_same_source` reads it but precomputed per side, O(N+M) resolves. The three specified states shipped as specified: ✅ imported (naming the sub/ses), ❓ unverifiable (pre-marker copies, whose None must not read as "different"), blank = new; badged rather than filtered so a source folder that changed after ingest stays visible. `core.ingestion.match_imported_sources`; the badge refreshing on a plain rerun (an ingest changes sourcedata without changing the folder set that keys the table rebuild) is pinned by `tests/test_ingestion_page.py`. The rendered column is a `#30` entry. |
| 2026-08-18 | `#37` | **GUI reorganized around a BIDSification nav group** (Ingestion · Conversion · **Project**). The new Project page collects the dataset-management cluster — `participants.tsv` / `dataset_description.json` generation (from Ingestion), the BIDS validation panel and the expectations editor (from Status) — so Status is purely cockpit + SLURM and Setup purely configuration; the warnings a declaration drives still render on Status, next to the board they judge. "New to Talapas?" merged into Guide (`#37.2`), and the landing page is computed (`#37.3`): Status with a project open, Setup without. Two deviations from the sketch, both Ben's calls the same day: **Preprocessing keeps its bar slot** (the decided bar had no home for it, and hiding a feature page behind a footer link was declined), and **Guide sits inline after Setup** — Streamlit renders ungrouped pages before the collapsible groups regardless of dict order, so last-in-bar would have cost Guide a one-item dropdown. The freeze control gained its first test in the move (`tests/test_project_page.py`); the redraw itself is a `#30` entry. |
| 2026-08-17 | `#13` | **Plan-time filename validation against the BIDS schema (`#13.2`) — closes the item.** `core/bids_schema.py` compiles `bidsschematools`' schema into filename regexes; a planned path matching none is an `invalid-filename` **error** in `plan_warnings`, shown in the page's preflight and refused by bulk convert. `_bids_filename` now mirrors the pinned dcm2bids' entity reordering, quirks included — without it the check would cry wolf on a mis-order the tool repairs itself, and *with* it the collision check finally sees two entity strings that differ only in order landing on one file. Measured across 268 LCNI-corpus + `mmmsourcedata` sessions (3162 planned files): zero nonconforming names from generated configs and zero paths moved by the mirror, so what the check guards in practice is the hand-edited JSON override. Design: `docs/conversion-legibility.md` phase 10; pinned by `tests/test_bids_schema.py` and the schema-check block of `tests/test_conversion_plan.py`. `bidsschematools` is a new runtime dep, pip-side deliberately (the reasoning is on the dep in `pyproject.toml`). The eyeball pass's residual polish notes (the `anat (T1w)` display, phase 4's redundancy with the table) moved to `#8`, whose theme decision they were always waiting on. |
| 2026-08-17 | `#19.11` | **Yes — dcm2bids reorders every filename it writes** (`setDstFile` in the pinned container's `acquisition.py`, on by default), so `_fmap_description`'s manual entity ordering is redundant for the *file*. It stays anyway, for the saved JSON a user reads and hand-edits, with a comment saying exactly that; and the confirmed table now does real work as `conversion_plan._DCM2BIDS_ENTITY_ORDER`, where the preview mirrors the tool's reorder (see the `#13` row above). |
| 2026-08-16 | `#13.1` | **The project-level skip — `[series_skip]`, a list of SeriesDescriptions the study never converts, honoured by the page, bulk convert and the cockpit alike.** Closes the item; the standing design record is `core/series_skip.py`'s module docstring, the page mechanics are `docs/conversion-legibility.md` phase 9. Motivated by curation scope, not junk (the item's own second measurement): five of the LCNI corpus's fifteen studies curate **anat only** — on WMS that is 6 descriptions × 56 sessions, ~336 unticks — and REV's curator dropped `fieldmap1` in 6 of 6 sessions. Every decision the item queued got its answer. **Own section**, not a `[series_types]` `ignore` value (the 2026-07-30 rejection holds: an ignore *classification* bypasses the actual skip mechanism — `generate_config(skip=…)` + `_without_skipped_groups`, keyed on series numbers — cannot express the per-session aborted-run case, and erases the classification the preflight reads) and **not `[expected]`** (the 2026-08-11 decision: a count cannot say *which*, and reports-never-repairs must stay true). The **coarser include-by-datatype control was declined**: "anat only" in one line inverts the failure mode — a study that adds a sequence loses it silently, where under a skip the new series converts visibly. Applied **inside `generate_session_config`, next to `type_rules`**, exactly as the item's note demanded: a description resolves to series numbers only once the session is listed, and the resolved set merges into the existing per-session `skip`, so the whole-pair rule and the saved-JSON round trip carry over with no new state. Only emitted classifications resolve — a scout matching a skipped description earns no "deliberate drop" note for a conversion that was never going to happen — and a **malformed section raises** (the fallback is converting the series the study excluded, the silently-degrading shape). On the page: the seed unticks, a re-tick wins for that session, the drop note names the section rather than "you unticked `convert`", and a fourth save button promotes **only descriptions with no ticked row** — a mixed description (the `fmap_eyeball` aborted-run case, identical names) stays per-session and the save says so — while re-ticking every row of a saved description and saving removes it, the same last-wins layering as `[series_types]`. A project binding to a pair the project's own skip removes **fails loudly** through the existing missing-group path. One neighbouring guard corrected on the way: the one-shot JSON import and the hand-edited override used to re-derive `convert` only for rows currently ticked, so an explicit review could never re-tick a row a seed had unticked; both now key on the row being *emittable*, and the import wins in both directions. Pinned by `tests/test_series_skip.py` (section, resolution, the non-GUI path) and the `[series_skip]` block of `tests/test_conversion_page.py`; the four-column save row is a `#30` eyeball entry. |
| 2026-08-16 | `#16.2` | **Outcome checks and duckbrain's first cache (L3, `#16` Slice C):** `outcome-sdc` reads fMRIPrep's own SDC verdict from the per-run summary reportlets (filename entities map each verdict to its BOLD; gated on sidecar `B0FieldSource`, COMPLETE units only) and `outcome-nordic` flags NORDIC output numerically identical to its raw input (volume 0, scaled values). Both `EXPENSIVE`: run only via `run_expensive_checks`, persisted to `<log_dir>/checks.json` with a per-check `count:mtime` fingerprint, rendered in a cockpit panel that confesses staleness. One deviation from the in-principle plan (no job id in the key) and two family members closed without code — design record: `docs/sanity-checks.md` Slice C. Anat-reuse re-homed to the unhomed candidates. Slice A's tripwire test flipped into the admission condition. Validated live on `divatten_beta_v2`: 65/65 runs judged through the NORDIC staged tree, clean, 8.4 s to measure and 0.07 s to fingerprint. |
| 2026-08-11 | `#16.1` | **The request record (L2, `#16` Slice B):** every SLURM launch writes `<log_dir>/requests/<job_id>.json` — the builder's resolved context minus config-wide keys, sorted for diffing — with a `request_path` column in `submissions.tsv`; first consumer `checks._check_requested_spaces` compares recorded `output_spaces` to written `space-` entities (newest attempt only, COMPLETE units only), and the `run_checks` gate became per-check so L2 needs no `[expected]`. Design record: `docs/sanity-checks.md` Slice B. The `[expected]`-vs-skip question it owed is answered at `#13.1`. |
| 2026-08-07 | `#20` | **conda is the documented environment: `environment.yml` + `scripts/setup_env.sh`, built and verified at the shared prefix `/projects/hulacon/shared/envs/duckbrain`.** braintwill's recipe taken working rather than re-derived, exactly as the item instructed: the script reads the package list out of `environment.yml` and passes it to a plain `conda create --override-channels -c conda-forge` (`conda env create` cannot be made safe against FSL's `#!final` condarc — re-verified nothing here), then **fails** unless every conda package resolved from conda-forge. The ownership split is the design decision: conda pins the interpreter (3.11) and the runtime deps, unpinned; the dev extra stays on pip via `-e .[dev]` **even though the blocker died** — conda-forge now carries ruff 0.16.x, rechecked as the item asked — because `pyproject.toml` must stay the single source of the gate pins, and a pin duplicated into `environment.yml` re-opens the drift the pins exist to close. One clean solve is committed as `conda/lock-linux-64.txt` (172 packages; regenerate only from a deleted prefix — an incremental solve is not a fresh one). Launch discovery is a gitignored `.conda-prefix` the script writes into the checkout: both launchers now prefer it over `.venv`, prepend the env's `bin/` (no conda shell hook needed), and set `PYTHONPATH=<checkout>/src` so the launched checkout is always the code that serves — the shared env has one checkout editable-installed, and without that line a user launching their own clone would silently run someone else's code. **The import check earned itself twice on day one, both times against the script itself.** First: `~/.local` site-packages shadow a conda env's own — the host-side twin of the `#34` container leak, a venv being immune is why nobody had met it — observed live as the env solving streamlit 1.61.1/nibabel 5.4.2 and importing this account's stale `pip install --user` 1.56.0/5.3.3 behind two green channel checks. Fixed with `PYTHONNOUSERSITE=1` in the script, in both launchers' conda branches, and as an `activate.d` hook in the env so the documented `conda activate` path is protected without knowing about it. Second: `conda run` does not forward stdin, so a heredoc check under it runs **empty and exits 0** — a vacuous pass caught only because the expected output went missing; the check now invokes the env's python directly, asserts `sys.executable` is the prefix's, and fails when any runtime module resolves from outside it. Verified end to end: full local gate green **in the env** — ruff, `format --check`, mypy, 1495 tests, coverage 89.81% over the 89 floor — which is also the first confirmation the suite passes against streamlit 1.61.x resolved fresh; and `scripts/launch.sh` served the app HTTP 200 through the conda branch (the OnDemand leg is `#30`'s new entry). CI deliberately stays on pip: GitHub runners have no FSL condarc, conda would cost solve time on every push, and the runners' pip path is the one GitHub users take — the accepted cost is that CI no longer tests the path Talapas users take, and the local gate run inside the env is the compensating check. The shared prefix is the model for other PIRGs to copy (`/projects/<pirg>/shared/envs/<name>`, setgid, one build per PIRG instead of ~1.2 G per user under an unreadable `~/.conda`); `--personal` and `--prefix` cover everyone else. |
| 2026-08-06 | `#33` | **`disallow_any_generics` is on, which closes `#33.2` and with it the whole item — the type-checked surface is now the whole package under every knob this project has measured.** The knob was **226 errors**, not the 90 the mypy comment carried; that figure predated `#33.4`, and the item had already said the cost is a function of the gated surface. So the ninth and last of this item's estimates was wrong in the same direction as the other eight, and the item's own prediction that it would be — "the last such number" — is the one that held. But the count was never the shape of the work: **199 of the 226 were a bare `dict`, and 95 of those were one parameter, `config`, repeated across 20 modules**. One decision, then a sweep. `dict[str, Any]` is the end of that decision and not a placeholder — four TOML layers deep-merged, every key optional — spelled as a named alias `Config` because 90-odd signatures take one and `dict[str, Any]` is equally what a sidecar, a job-parameter dict and a Jinja context are. **Naming it immediately caught three functions taking the wrong one**: `plan_conversion`, `read_config_into_table` and `config_to_json` take a *dcm2bids* config, which the mechanical sweep had annotated `Config` and which is now `Dcm2BidsConfig`. That is the entire argument for a transparent alias, since mypy sees straight through both. **The `typing_extensions` blocker this item recorded was never real, and the item had already established why**: a required base plus a `total=False` subclass is the pre-3.11 spelling of `NotRequired`. `dcm2bids_config.Description` is written that way. Two rules came out of doing it, and they are in `pyproject.toml` because they decide the next one: a payload **read off disk** stays `dict[str, Any]` (sidecars, dataset descriptions, decision entries and hand-edited configs arrive in more than one schema with every key absent from some real file, which is why each reader is a chain of `.get()` and `isinstance` — a TypedDict over all-optional keys says nothing and reads as a guarantee); a payload **this code builds** gets one, because then the keys really are set in one place. Three qualified: `pipeline.JobIndex` (three keys, two different types, so no `dict[K, V]` describes it — which is how it came to be bare), `qc.DecisionRecord`/`DomainRecord` (and `DecisionRecord` *subclasses* `DomainRecord`, because `_domains_of`'s docstring already claimed a domain record is the run-level one minus the breakdown, and inheritance is that sentence in a form that stays true), and `Description`. **Four defects, all found by writing a type down rather than by looking for them.** `generate_config` bound `desc` to three different descriptions 60 lines apart — the `#18` shape a sixth and seventh time, fixed by renaming. `containers._inspect_labels_cached` returns a tuple of `(key, value)` **pairs** as its own docstring says, and the wrong `tuple[str, ...]` I first wrote was rejected at both the `tuple(labels)` that builds it and the `dict(...)` that consumes it. `qc.parse_entities` really does return `dict[str, str]`, which exposed `summarize_motion` stuffing four floats into the shared helper's result. And `survey_live`'s second return value was the bare dict `JobIndex` replaced. **The one that matters most is a hole in the checker, not in the code.** Naming `StageBuilder` broke the package on import and mypy stayed green: `from __future__ import annotations` defers *annotations*, but a type alias is an ordinary assignment evaluated at module load, so `Callable[[Config, …]]` at module scope needs a `TYPE_CHECKING`-only name at runtime. Six test files stopped collecting. To mypy the guard branch is always taken, so this is permanent blindness rather than a bug to file — hence `tests/test_runtime_type_aliases.py`, which imports every module in the package, and which was verified by putting the bad alias back (mypy clean, three tests red). It also guards itself: an empty `walk_packages` would pass vacuously. Gate verified to *block* rather than pass over — deleting one type argument from `discover_units` turns it red. Coverage measured before and after at 89.80% and 89.81%, so the floor is untouched: this added and removed no reachable code. What is left of widening is `strict`, which is not measured. |
| 2026-08-06 | `#33.4` | **mypy checks the whole package now — `core/`'s 36 errors, then the 11 nobody had scoped, and the file list is one directory.** `core/` first, as the item asked. Its headline — a third-party *decision* for `plotly` — was right about the shape and wrong about the size: 4 of 36. `plotly-stubs` 0.1.3 exists and makes `qc_report.py` clean with **no code change at all**, which is the measurement that settles it rather than a guess either way; declined anyway, because ten calls into a chart library in one module do not justify a single-maintainer 0.1.x package as a hard dependency of a *blocking* gate, and a stale stub is a false error or a false pass with nothing naming the cause. Two of the 36 were defects. `SessionExpectation` served the declared prescription and the observed count at once, so `fmap_pairs=None` — meaningful on one, impossible on the other — made `checks.py:174` an `int | None < int` that held only by what the caller passed; split into `SessionCounts` with `as_declaration()` the single crossing, and a test on the zero it carries across, since a measured zero read as silence is exactly the fallback this module exists to prevent. `SortResult.errors` was `list[str] | None` repaired in `__post_init__`, so every `.append` was against a declared `None`. Also four JSON/config boundaries returning `Any` under a concrete annotation, two of which now shape-check: a template listing from a script run inside somebody else's container is not a mapping just because it parsed, and an empty manifest reads downstream as "nothing to repair". **Then the remainder, which no note had ever estimated: `config.py` + `slurm/` at 11 errors** — six signatures, `find_job_logs` declaring `log_dir: str` and rebinding it to a `Path` on the next line, and a `try: import tomllib` that could only run below 3.11, where tomllib does not exist. That branch is also why `tomli` needs an override: the analysis target is pinned at 3.10 while the interpreter is whatever the developer has, so without it the gate is green in CI and red on a 3.11 box. Gate verified to *cover* the new files rather than pass over them — deleting two annotations turns it red at 20. `[tool.mypy]`'s comment rewritten, not appended to: it opened by explaining which files were chosen and why the rest was a different job, and none of that is true any more |
| 2026-08-06 | `#36` | **The headroom was never the lever — synthstrip is admitted against a memory estimate nobody set, so `--mem-gb` could not have restrained it at any value.** The item asked for a measurement before a fix and the measurement changed the fix. MRIQC's scheduler (its own `engine/plugin.py`, admission logic identical to nipype's `MultiProc`) starts a node when a process slot *and* its **declared** `mem_gb` both fit; `workflows/shared.py` builds the synthstrip node with `num_threads` and **no `mem_gb`**, so it carries nipype's `0.2` default and 24 GB of budget admits 120 of them. Scaling `MEM_HEADROOM_GB` with `cpus` — the item's leading candidate — would have grown a number that is never consulted for this node. What *is* honoured is the thread count, and `--omp-nthreads` was sitting unpassed: `#35` had left it alone six days earlier on the correct reasoning that fMRIPrep derives it from `--nprocs` itself, and recorded that MRIQC instead reads the image's `OMP_NUM_THREADS=1` — which is the whole bug, one observation short. Single-threaded nodes each claim one slot, so `--nprocs` of them ran side by side. Now `--omp-nthreads` equals `--nprocs`, one multi-threaded node fills the allocation, and the flat 8 GB constant is correct again for the reason it always claimed: it covers **one** overshooting node, and something now keeps it to one. **Measured rather than reasoned** — one real T1w on n0135: synthstrip peaks at **12.25 GB at 1 thread and 12.24 GB at 4**, so threading is free memory-wise and 2.4× faster (77 s → 32 s), and serialising costs no wall clock. Four concurrent wanted 49 GB of a 32 GB allocation; `sacct MaxRSS` is the cgroup total, not a per-process maximum, which is why the beta user's failures read 28–31 GB with exactly two synthstrips resident. **The shipped 32 GB default was therefore right all along and needed no raise** — the concurrency was wrong, not the allocation. Confirmed live by re-running the two sessions that OOM-killed, at the unchanged 32G/4-CPU default: `sub-06/ses-01` went `OUT_OF_MEMORY` at 7 min / 18.6 GB → **COMPLETED, 48 min, 11.7 GB**, and `sub-07/ses-02` `OUT_OF_MEMORY` at 54 min / 28.3 GB → **COMPLETED, 69 min, 9.1 GB**. Both wrote their full report set with no `crash-*`, and 48 min sits inside the 44–58 min the batch's *surviving* jobs already took, so serialising cost no measurable wall clock there either. One thing the change nearly shipped broken: the explaining comment was written *inside* the command's `\` continuations, where Jinja renders it as a blank line that silently ends the command — MRIQC would have run with no `--mem-gb`, no `-w` and no `--no-sub`. `test_no_comment_breaks_a_line_continuation` caught it, which is `#31`'s sweep earning itself; the comment now sits above `singularity run` and says why |
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
