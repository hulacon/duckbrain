# Sanity checks: codifying intent (TODO #16)

Design record for `core/expectations.py` and `core/checks.py`. Written
2026-07-22, when Slice A shipped. The prior-art verdicts below are here so they
are not re-litigated; the code comments carry the rules that bind.

## The gap, and why validators don't close it

`#15` shipped BIDS validation on by default and immediately proved its own
limit: run against a dataset whose `B0FieldIdentifier`/`B0FieldSource` were
inverted, the validator reported **zero fieldmap issues**. The keys were valid
strings in valid places. dcm2bids converted successfully, fMRIPrep exited 0, and
the only trace was one line in an HTML report nobody reads.

Validators check that data is well-**formed**. Nothing checked that processing
did what was **intended**.

Ben's sharpening of that (2026-07-22) is what this design turns on:

> Codifying a project's intent is different from cataloguing what has been done.

duckbrain was entirely the latter. Every "expectation" in the codebase is
re-derived from the data it is judging:

| Where | What it calls "expected" | Derived from |
|---|---|---|
| `surveyor.discover_units` | the subject roster | the union of what exists on disk |
| `surveyor._expected_bold_keys` | the BOLD run list | the converted tree |
| `surveyor._expected_conversion_counts` | NIfTI counts per datatype | the dcm2bids config duckbrain emitted |
| `consistency.check_consistency` | agreement | provenance sources compared to *each other* |

That is a comparison of the data with itself, and its failure mode is specific:
**a shortfall shrinks the expectation to match, and everything reads COMPLETE.**
A subject scanned but never ingested is a row that never appears. A run the
scanner aborted is three-of-three. `#14` was the same shape one level down —
every artifact agreed with every other artifact and all of them were wrong
together.

Proven live on 2026-07-22 against `divatten_beta`: with one task's BOLD removed
and one fieldmap direction removed, `survey_project` still reported `complete`
for every subject, while the new checks flagged both. That contrast is pinned by
`test_surveyor_still_reads_complete_when_a_run_is_missing`.

## Three levels of intent

They have different owners and different prior art, and conflating them was the
first draft's mistake.

| | Declares | Stated by | Status |
|---|---|---|---|
| **L1 — roster + protocol** | "37 subjects; each session has 1×T1w, 1 fieldmap pair, 4 runs of `task-div`" | the experimenter | **Slice A — shipped** |
| **L2 — request** | "fMRIPrep for sub-015 with these `output_spaces`, `use_nordic`, no anat reuse" | duckbrain, at launch | **Slice B — shipped 2026-08-11** |
| **L3 — outcome** | "fMRIPrep actually applied SDC / actually wrote `space-fsaverage6`" | only the tool knows | **Slice C — shipped 2026-08-16** |

L3 checks are only expressible against L2, and acquisition-level omissions only
against L1. Record intent first, check second — which is why Slice A is the
foundation rather than the SDC report parse that motivated the item.

**One L3 check needs no L2 record, and it is the cheapest one there is**
(2026-08-04). The rule above holds wherever duckbrain has to compare what was
*asked* with what appeared. It does not hold where the tool **testifies against
itself**: a nipype crash dump is the tool's own statement that a node it intended
to run did not, and it needs nothing from duckbrain to be legible. So
`consistency._check_tool_crashes` is a directory glob on the render path rather
than part of Slice C — it needs neither the request record nor Slice C's cache.
It also sharpens the "nobody does L3" bullet below: it is not that the answer is
unavailable, it is that fMRIPrep writes it to a file and the state of the art is
that nobody reads it. A second L3 case turned out to be free for a different
reason: **confounds**. One `_desc-confounds_timeseries.tsv` per BOLD run is
fMRIPrep's default behaviour, so the raw BOLD list already says how many there
should be, and `surveyor._fmriprep_func_keys` requires them without recording
anything. What remains genuinely blocked on L2 is the **output spaces**, because
`surveyor._entity_key` strips `space-`/`res-`/`den-` by design and nothing else
states the ask.

**duckbrain's unique position is L2→L3.** It is the only component in the stack
that knows the request.

## Prior art: what was borrowed, what was refused

BIDS itself has **no slot for declaring expected acquisitions**. `sessions.tsv`
and `scans.tsv` are descriptive records of what was collected. There is no
standard to conform to here, only shapes to copy.

- **[Nipoppy](https://nipoppy.readthedocs.io/)** — the 2026-07-10 evaluation
  (`memory/nipoppy-status-tracking`) decided *borrow the tracker approach, don't
  adopt the framework*, and that still holds: duckbrain's flat layout is more
  BIDS-faithful than `derivatives/<pipe>/<version>/output/` plus a manufactured
  `ses-unnamed`, and a pre-1.0 dependency with a two-person core means
  externally-triggered fire drills for a solo maintainer. **But that evaluation
  only ever weighed the tracker half.** `manifest.tsv` — a declared roster held
  separate from and above what is on disk — is exactly the L1 roster, and
  borrowing it costs none of what the earlier analysis warned about: it is a
  shape, not a dependency. `[expected] participants` is that idea in duckbrain's
  config.
- **[CuBIDS](https://github.com/PennLINC/CuBIDS)** — descriptive, not
  prescriptive: Key Groups → Parameter Groups → a Dominant Group, with deviants
  re-labelled `acq-VARIANT*`. Genuinely complementary. **Not a pip dependency,
  ever:** `datalad` is a hard requirement (and wants `git-annex`, a non-pip
  system binary), plus `pybids`, `scikit-learn`, `pyarrow` and pinned
  `numpy`/`pandas` upper bounds that would fight streamlit in duckbrain's venv.
  If it is ever used, it runs as a container like everything else duckbrain
  orchestrates.
- **[mrQA](https://github.com/Open-Minds-Lab/mrQA)** — the only tool doing real
  prescriptive *protocol* compliance. Apache-2.0, pip-installable, light deps
  (`bokeh`, `dictdiffer`, `jinja2`, `mrdataset`, `nibabel`, `protocol`,
  `pydicom`, `tqdm`), reads DICOM *or* BIDS, and `--ref-protocol-path` is
  **optional** — without a scanner protocol export it infers the reference by
  majority, so it works on any dataset with zero setup. Its `--config` is a
  declarative JSON splitting a *vertical* audit (within-session, across-sequence)
  from a *horizontal* one (within-sequence, across-dataset). Caveat: latest
  release is 0.3, **April 2024**. Pin it; keep it non-load-bearing.
- **[BIDScoin](https://bidscoin.readthedocs.io/)** — the *study bidsmap*,
  bootstrapped from a template by `bidsmapper` and then frozen and corrected by
  hand. **The bootstrap pattern is what was stolen** — see "elicit, then freeze".
- **Nobody does L3.** fMRIPrep's own documentation instructs the *human* to
  "verify that susceptibility distortion correction was applied as intended" by
  reading the HTML report. That instruction is the state of the art. It goes
  further than it looks: fMRIPrep also writes a machine-readable record of every
  node that failed, into its own output directory, and no tool in this space
  reads that either — duckbrain did not until 2026-08-04, which is how a run that
  produced almost nothing and exited 0 went a week without an explanation.

## Where the boundary sits

duckbrain checks the **contract** — did the things we said would exist, exist.
It does not assess image quality (MRIQC) and does not audit acquisition
parameters against a scanner protocol (mrQA). Both are real; neither belongs
here. Growing them in makes duckbrain a worse copy of a tool that already exists,
which is `#16`'s own question 4 answered.

The consequence for the schema: `SessionExpectation` holds **counts and
presence, never parameters**. No TR, no voxel size, no flip angle.

## Design decisions

**Absent means off.** A project with no `[expected]` section gets no checks, in
silence — the same stance `consistency.py` takes toward absent provenance. A
study that has not declared its expectations is not thereby wrong. `[expected]`
is shipped commented-out in `config/base.toml` precisely so it stays absent by
default, and `save_project_expectations({})` removes the section so there is a
way back to absent that is not hand-editing TOML. Pinned by
`test_no_declaration_means_no_issues` — opt-out is a behaviour, so it gets a test.

**Elicit, then freeze.** Nobody hand-writes a declaration, which is how these
formats die. `elicit()` reads one session the user has confirmed good and
proposes it; the cockpit shows it and the user accepts. The freezing is what
makes it worth anything — from then on every other session is judged against
*that* session rather than against itself.

**`elicit()` never proposes a roster.** The participant count is the one thing
the filesystem genuinely cannot know; deriving it from disk would re-close
exactly the loop this module opens. It stays a number the experimenter states,
and it is what catches a subject scanned but never ingested.

**Zero is a declaration, not an absence.** Found live on `divatten_beta`: "this
subject has no resting run" is the commonest real deviation there is, and with
zero parsed as "unstated" the exception fell through to the study default and
could never turn anything off. Hence `fmap_pairs` is `None` when undeclared
rather than `0`, and `_count_map` keeps zeros while still dropping junk.

**Exceptions are load-bearing, not polish.** A subject who genuinely got 3 of 4
runs must be markable as expected-and-accepted, or the board fills with permanent
noise and people stop reading it — which costs more than the check ever paid for.
`[expected.exceptions]` carries a `reason` so the deviation stays legible a year
later. Exceptions merge **key-by-key**, so one naming a task count does not
silently drop the T1w and fieldmap expectations it never mentioned.

**More than declared is never flagged.** Same asymmetry `surveyor._grade` takes:
a re-scan, an extra localizer or a second T1w is a normal thing for real data to
hold, and a check that fires on every legitimate difference gets switched off.

**An unconverted subject is pending, not deficient.** Checks skip units with no
BIDS directory, or the panel is unreadable on day one of a study.

**Reports, never blocks.** `pipeline.stage_runnable` is untouched. Where a
condition is genuinely dangerous the right answer is to raise at *build* time,
per CLAUDE.md's silently-degrading rule — a check that stops you working is a
check people learn to disable.

**One issue type, one panel.** `checks.py` produces
`consistency.ConsistencyIssue` and renders in the same cockpit panel. A reader
does not care which module noticed. The severity vocabulary is shared and now
three-valued (`error`/`warning`/`note`); `conversion_plan.PlanWarning` remains
separate because it is a plan-time surface on a different page.

**Why a new module rather than generalizing `consistency.py`.** That module's
docstring commits it to provenance agreement and its source-of-truth ordering is
specific to that question. Same issue type, same pattern, different question.

## Slice B — the request record (shipped 2026-08-11)

`pipeline.record_request` writes `<log_dir>/requests/<job_id>.json` at every
SLURM submission, and `submissions.tsv` gained a `request_path` column pointing
at it (`_migrate_log_header` widens existing logs, the solved shape). The
decisions, so they are not re-litigated:

- **The record is the builder's resolved template context minus the config-wide
  keys `build_context` injects** (`pipeline._CONTEXT_CONFIG_KEYS`), not a
  curated per-stage field list. The context *is* the ask — the values after
  params-over-config fallback, exactly what the sbatch rendered from — so a
  knob added to a builder later lands in the record automatically instead of
  drifting out of it, which is how `submissions.tsv` came to carry tool
  identity and nothing else.
- **Keys are sorted** so two records `diff` cleanly: "config drift between
  runs" is one of the two questions the record exists to answer.
- **Recording never blocks a launch** — same contract as the TSV row, and the
  JSON half fails independently of it.
- **Nothing is written for `export_only`**: an exported script is launched
  outside duckbrain, so the script itself is the only honest record.

Its first consumer is `checks._check_requested_spaces` — requested
`--output-spaces` versus the `space-` entities actually in the unit's func
output, the comparison `surveyor._entity_key` deliberately cannot make. Two
silences are deliberate and carry the layer's hardest-won lessons: only the
**newest attempt** per unit is judged, and only when that attempt carries a
record (an older record describes a superseded run — the crash-file staleness
shape; a newer launch without one leaves nothing current to judge); and only a
**COMPLETE unit** is judged (a PARTIAL unit's shortfall already shows on the
board, and a running job would read as missing every space it hadn't written
yet). Native-space aliases (`func`, `run`, `boldref`, `sbref`) write no
`space-` entity and are skipped — the surveyor's own grade already requires the
native preproc BOLD. More spaces than requested is never flagged.

**The gate moved with it.** `run_checks` no longer returns `[]` wholesale when
`[expected]` is absent: the registry now judges against two declarations with
different authors — the experimenter's `[expected]` and duckbrain's own request
record — and each check gates on *its* declaration being present. Absent still
means off, per source. `test_the_check_needs_no_expected_declaration` pins the
restructure; `test_no_declaration_means_no_issues` still holds for a project
with neither declaration.

**The NORDIC "free half" was noted and deliberately not built here**: grading
NORDIC by "every launch-written sidecar has a matching NIfTI" needs no request
record (`nordic.write_nordic_sidecars` already writes one per intended run) and
belongs with Slice C's outcome family when that lands.

## Slice C — the outcome checks and their cache (shipped 2026-08-16)

Two `EXPENSIVE` checks and the store that makes them admissible. The
in-principle decision (`TODO.md` `#16.2`) survived contact with the code in all
but one detail, recorded below.

**`outcome-sdc`** reads fMRIPrep's own verdict back out of its report — the
`Susceptibility distortion correction: None` line that was the fieldmap-intent
bug's only trace. Not the monolithic `sub-XX.html`: the per-run summary
reportlets under `figures/` are a few hundred bytes each and carry the run's
entities in their *filename*, so mapping a verdict to its BOLD is
`surveyor._entity_key` on the name rather than HTML section parsing (they sit
at subject level even in longitudinal trees; the `ses-` entity in the name is
what scopes a verdict to its session). The gating declaration is the
`B0FieldSource` duckbrain writes into each BOLD sidecar — absent means off, per
source. Complementary to `fmap-intent`, which catches malformed intent from the
sidecars before hours of compute; this reads what fMRIPrep actually **did**,
which also catches the run that predates a metadata fix, and fMRIPrep declining
intent that is correct. Only COMPLETE units are judged (the requested-spaces
silence, for the same reasons), and a run with no reportlet is skipped — the
tool left no testimony either way.

**`outcome-nordic`** compares each NORDIC output against its raw input and
flags numerically identical data. The denoise's whole product is a difference,
and the sbatch has no copy path — MATLAB always writes the output — so
identical data is never legitimate. One volume, not the series (denoising
changes essentially every voxel, and volume 0 keeps the gzip decompression to
the head of each stream); *scaled values*, not bytes (a silent no-op through
MATLAB's writer re-encodes the file, so a byte comparison would acquit it).
Content only: presence and counts stay the surveyor's
(`_nordic_status`/`run_progress`), which is also what keeps a running array
from being false-flagged for outputs it hasn't written yet.

**The cache — duckbrain's first and only state store.** `run_expensive_checks`
persists a `CheckSnapshot` to `<log_dir>/checks.json`; the cockpit's outcome
panel renders the snapshot, paying one small JSON read plus a fingerprint of
stats per render. Re-measurement is an explicit button, never a post-job hook —
jobs die, get cancelled, and run outside duckbrain, so a hook would leave
exactly the runs most worth checking unmeasured. What makes rendering a cached
verdict honest is the fingerprint it carries: `<file count>:<newest mtime ns>`
per check over the inputs it read (the count is load-bearing — deleting a file
changes the answer but can never raise a max mtime), taken *before* the checks
run so inputs changing mid-measurement leave the snapshot stale rather than
current. The panel confesses staleness instead of serving an old "clean" as
current — the exact failure the validation panel refused a cache over.

**The one deviation from the in-principle decision: no job id in the key.**
`TODO.md` had settled "keyed on job id + newest input mtime". With the code in
front: neither check reads the request record or the submission log — the tools
testify against themselves — so a job id would be borrowed identity nothing
uses, and it does not exist for the externally-run fMRIPrep the checks still
cover. The input mtimes supersede it: any re-run moves them.

**Family members that needed no code, and one still open:**

- *MRIQC IQMs present for every func the surveyor counts complete* — already
  discharged before this slice: `surveyor._mriqc_expected_found` (2026-08-11)
  grades per rated image, so a missing IQM json is a PARTIAL cell on the board,
  not an outcome check.
- *The NORDIC sidecar "free half"* (Slice B's note) — deliberately **not**
  built as a separate cheap check. `_nordic_status` already compares raw BOLDs
  to outputs wherever NORDIC applies, and the sidecars are written at *launch*,
  so a sidecar-vs-NIfTI presence check would false-flag every running array.
  The content comparison above is what the sidecar idea was actually worth.
- *"Reuse anat derivatives" actually reusing* — still open, for want of an
  honest outcome signal: the report does not state reuse legibly, and the
  dangerous direction (nothing to reuse) already raises at build time. Parked
  under `TODO.md` `#16`'s unhomed candidates.

Validated live on `divatten_beta_v2` (2026-08-16): all 65 BOLD runs declare
intent through the NORDIC staged tree, all five units COMPLETE, all 65 verdicts
matched by entity key and read `PEB/PEPOLAR`; 65 NORDIC pairs compared, none
identical. 8.4 s for the full measurement, 0.07 s for the fingerprint — the
render path's whole cost.

## The cost field

`Check.cost` is `CHEAP` or `EXPENSIVE`. The cockpit re-derives everything on
every render — every 30 s under auto-refresh — so a check that opens a NIfTI or
parses an fMRIPrep report may never join that path: `run_checks` excludes
`EXPENSIVE` entries, which run only through `run_expensive_checks` and render
from the snapshot above. Slice A's tripwire
(`test_no_expensive_check_is_registered_yet`) held exactly this open until the
cache existed; it is flipped now into the admission condition — every expensive
check declares a fingerprint, and none runs on a plain `run_checks`
(`tests/test_outcome_checks.py`).

### The BIDS validator is not one of them, and the reason is not cost

The obvious candidate for the first `EXPENSIVE` entry is the BIDS validator, and
it was deliberately given its own module (`core/validation.py`) and its own
cockpit panel instead. Cost is the least of it — with `--ignoreSymlinks` a full
run is under four seconds even on a project with 147 GB of derivatives. Three
reasons, and the first is decisive:

1. **Every check in this registry gates on a declaration** — the experimenter's
   `[expected]` for the L1 checks, duckbrain's own request record for the L2 one
   (the gate is per-check since Slice B; it was a single `run_checks` gate on
   `[expected]` before). A project that declares nothing is not thereby wrong,
   and it gets silence. Registering the validator here would make BIDS
   validation silently conditional on a declaration that has nothing to do with
   it. The BIDS spec is not a project's statement of intent; it is everyone's.
2. **`ConsistencyIssue` carries no file list**, and it is frozen and shared with
   `consistency.py`. A validator finding is *about* files — flattening forty
   paths into a message string destroys what makes it actionable, and widening a
   dataclass two other modules depend on to serve a third is the wrong direction.
3. **It is user-triggered and speaks a third-party vocabulary** (`code`,
   `helpUrl`, its own severity scale). The "one panel, a reader shouldn't have to
   know which module noticed" principle applies to two modules asking the *same*
   question. This asks a different one, in someone else's words, and only when
   asked.

What holds the two together is the caveat at the top of this document, which the
panel repeats in its own caption: a clean validator run is a floor, not an
all-clear. Whoever reads a green result is exactly the person who needs to know
that the fieldmap-intent bug passed it.

## What is deliberately still open

- **Slice D — an opt-in audit stage** shelling out to mrQA (and later CuBIDS) as
  a SLURM stage, reusing `StageSpec`/`advance_one`/the log viewers. Distinct from
  this layer: heterogeneity *discovery* over the whole dataset, occasional and
  deliberate, versus a per-unit contract check on the board.
- **PHI detection vs. removal.** `cubids print-metadata-fields` is read-only and
  would let this layer *report* sidecars still carrying `PatientName`.
  `cubids remove-metadata-fields` mutates sidecars in place and belongs to
  `#7.1`, where the PII policy actually gets decided — shipping a scrubber first
  would fix the mechanism before the policy.
- **Template groups (`#10`).** `[expected.session]` is per-group by construction.
  When named groups arrive they should carry expectations too, rather than a
  second mechanism being grown alongside.
