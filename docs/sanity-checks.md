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
| **L2 — request** | "fMRIPrep for sub-015 with these `output_spaces`, `use_nordic`, no anat reuse" | duckbrain, at launch | Slice B — open |
| **L3 — outcome** | "fMRIPrep actually applied SDC / actually wrote `space-fsaverage6`" | only the tool knows | Slice C — open |

L3 checks are only expressible against L2, and acquisition-level omissions only
against L1. Record intent first, check second — which is why Slice A is the
foundation rather than the SDC report parse that motivated the item.

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
  reading the HTML report. That instruction is the state of the art.

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

## The cost field, and what it is holding open

`Check.cost` is `CHEAP` or `EXPENSIVE`, and **nothing expensive is registered**.
The cockpit re-derives everything on every render — every 30 s under
auto-refresh — so a check that opens a NIfTI or parses an fMRIPrep HTML report
cannot join that path naively. The field exists so that adding one later does not
mean reshaping the registry; the missing piece is a cached, fingerprinted result,
which is Slice C and gets its own decision because it would be duckbrain's first
state store. `test_no_expensive_check_is_registered_yet` pins that.

## What is deliberately still open

- **Slice B — the request record.** `submissions.tsv` carries tool identity only:
  no `output_spaces`, `nprocs`, `anat_only`, `use_derivatives`, `extra_flags`,
  BIDS filter path, or `use_nordic`. `script_path` makes them *recoverable* by
  re-parsing an sbatch, which is not the same as recorded. A
  `<log_dir>/requests/<job_id>.json` plus a `request_path` column would mirror
  `script_path` exactly, and is what "requested vs written `output_spaces`" needs
  — impossible today because `surveyor._entity_key` strips `space-`.
- **Slice C — the outcome checks and their cache.** Parsing the fMRIPrep report
  for SDC-applied is the one that motivated `#16`. Note it is *complementary* to
  `fmap-intent`, which catches the cause from the sidecars before hours of
  compute; what it cannot see is fMRIPrep declining metadata that is correct.
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
