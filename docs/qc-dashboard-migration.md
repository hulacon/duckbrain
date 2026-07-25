# QC guidance layer — migrating the mmmdata dashboard (TODO #7.4)

Execution plan for `TODO.md` `#7.4`. Written 2026-07-24, before any code moved.

mmmdata built and vetted a QC review layer that answers `#7.4`'s three open
questions directly — which norms to codify, automated flagging vs.
human-in-the-loop, and group-level comparison. This doc records what is coming
across, what it collides with here, which design questions are **settled** (so
they are not re-litigated mid-build), and what cannot be verified without real
data.

The intent is that duckbrain becomes the only implementation. mmmdata will
depend on duckbrain rather than keep a copy — see *End state* below, which has a
prerequisite that is not a coding task.

## Why this moves at all

The guidance layer's own central claim is that **IQMs have almost no defensible
absolute thresholds** — they carry site, scanner and protocol batch effects, so
the honest procedure is to compare within a dataset rather than against fixed
cutoffs. That claim is untestable in a single-project repo. mmmdata has one
dataset; duckbrain is multi-project by construction, and `#7.4`'s third open
question ("group-level IQM comparison") only becomes answerable here.

So the move is not tidying. It is putting the work somewhere its main assertion
can be falsified.

## What is coming across

From `mmmdata/src/python/neuroimaging/`, as of mmmdata `10d272a`:

| Piece | Size | Portability |
|---|---|---|
| `qc_guidance.py` — the registry + renderers | 1720 lines | **Clean.** Imports only `dataclasses` and `typing`. No coupling to mmmdata, to pandas, or to the HTML renderer. |
| `qc_dashboard.py` — HTML renderer + decision I/O | 1214 lines | Partial. Rendering ports; decision I/O collides (below). |
| `[qc]` config section + `qc_settings()` | small | Ports, but must use duckbrain's layered `load_config`. |
| `tests/test_qc_guidance.py`, `tests/test_qc_signoff.py` | 581 lines, 53 tests | Port with the code. |

The registry holds **30 measures** (bold / T1w / T2w / dwi), **7 process notes**,
and **29 distinct sources** — 20 papers, 3 tool docs, 4 NeuroStars threads, 2
software manuals. Each measure answers four questions: why it is on the
dashboard, what a human should check by eye, what is flagged without them, and
where the guidance comes from.

**20 of the 30 carry a `literature_threshold` field, and most of those say a
threshold does *not* exist.** That is the point, not a gap. The content was
verified against MRIQC/fMRIPrep/AFNI source and primary literature rather than
common practice, and several widely-held beliefs did not survive:

- tSNR has no defensible absolute cutoff; "below 20 is poor" has no published
  derivation.
- Power's 0.5 / 0.2 mm FD values are **frame-censoring** thresholds. Applying
  them to a run's *mean* FD is a category error. Parkes et al. (2018) supplies
  the citable run-level rule.
- DVARS ≈ 5 belongs to the non-standardized column, not the standardized one,
  where 1.5 is already a spike.
- `snr_total` is the mean of per-tissue SNRs, not a whole-brain figure.
- `fwhm_avg` is in **voxels**, not mm.
- MRIQC writes `-1` for FBER and QI1 when the image has no usable background —
  a sentinel for a skull-stripped or defaced input, not a catastrophic score. It
  will sort to the extreme of any ranking and can trip the outlier fence.

That last one matters more here than it did in mmmdata: a general-purpose tool
will meet defaced datasets.

## What is here now, and the four collisions

`core/qc.py` is 265 lines with **zero tests** — the only untested module in
`core/`, and reachable only from `5_QC_Dashboard.py`. Four things conflict:

1. **Decision schema differs and neither reader understands the other.**
   duckbrain writes `{"latest": {...}, "history": [...]}` flat in one directory;
   mmmdata writes `{"run_key": ..., "decisions": [...]}` nested under `sub-XX/`.
2. **No reviewer is ever recorded.** `save_decision` accepts `reviewer` and
   defaults it to `""`; page 5 never passes it. **Every QC decision duckbrain
   has ever written is anonymous.** mmmdata hit exactly this and fixed it — a
   decision now only counts when an identifiable person made it.
3. **`fmriprep_dir` is hardcoded** to `derivatives/fmriprep` in page 5, despite
   `use_nordic` existing. On a NORDIC project the QC page reads the wrong tree
   and says nothing — the silently-degrading shape `CLAUDE.md` forbids.
4. **No `[qc]` config section.** The IQR multiplier is a UI slider; the FD
   threshold is a Python default. mmmdata moved both into config for a reason:
   the same literal appeared in four files and drifted.

## Decisions that are settled

Recorded so they are not re-opened. Each was argued out 2026-07-24.

### Streamlit stays as the control plane; the QC report becomes a document

duckbrain is a control panel, not a report generator. Across the five working
pages there are 35 buttons and nearly all of them run Python that mutates the
filesystem or the SLURM queue — `advance_one`, `save_*_config`,
`scaffold_project`, `sort_dicoms`. Static HTML cannot submit an sbatch, and
OnDemand Batch Connect requires a server on the compute node regardless.
Replacing Streamlit is not a conversion but a rewrite onto a different web stack,
for the same capabilities.

**QC is the exception because it is the one surface that is mostly read.** Its
output is a *document*: dense tables and charts, read-mostly, worth keeping and
worth sending to someone. MRIQC and fMRIPrep both already do exactly this —
headless tools emitting self-contained HTML into `derivatives/`. A duckbrain QC
report belongs beside them, opened the same way.

**This does not generalize to the other pages.** Do not read this decision as a
direction of travel.

### One renderer, two delivery paths — not two versions

`st.components.v1.html()` renders arbitrary HTML in a sandboxed iframe.
Self-contained Plotly works inside it, as do in-page anchor links from column
headers to the glossary.

The iframe is **one-way**: HTML inside cannot call back into Streamlit without
`declare_component` and a bundled JS build. That constraint falls along a seam
that already exists, so it is a clarifier rather than a limitation:

- **Read-only** — run table, IQM charts, guidance glossary, process notes,
  outlier detail — is one function in `core/`, embedded in page 5 *and* written
  to `derivatives/` as the shareable export.
- **Decision recording** stays Streamlit widgets outside the iframe, because
  persisting a decision needs a server-side callback that static HTML cannot do.

So the split is **read vs. write**, not HTML vs. Streamlit, and the write half
was always Streamlit-only. There is one renderer to maintain.

### Reviewer identity comes from the session, not a text box

mmmdata asks the reviewer to type a name and rejects blank or automation-like
values. duckbrain can do better: under OnDemand the session owner is known, so
capture `$USER` and record it without asking. That is a stronger provenance
record than an honour-system field, and it removes the failure mode where a
reviewer leaves the box empty.

### End state: mmmdata depends on duckbrain

Not a copy back. One implementation, no drift — which is what `#7`'s standing
instruction ("fold them together rather than building two things") requires.

**Two consequences, and the second is a prerequisite, not a task:**

- **Dependency weight.** `pip install duckbrain` currently pulls streamlit,
  jinja2, pydicom and nibabel. A library consumer needs none of them. `core/` is
  already provably Streamlit-free, so the clean fix is to move the GUI
  dependencies into an optional extra — `duckbrain[gui]` for the app, bare
  `duckbrain` for consumers. Small packaging change, follows the existing
  architecture. Best done **as part of** this work rather than after.
- ⚠️ **Licensing gates the end state.** duckbrain is GPL-3.0-or-later; mmmdata is
  "License TBD". A dependency does not dodge that — mmmdata importing duckbrain
  puts mmmdata under GPL. So the **Licensing follow-ups** item stops being
  background and becomes a precondition for mmmdata taking the dependency. It
  does not block moving code *into* duckbrain, and the slices below are all
  safe to build before it is answered.

## The slices

Three, each independently mergeable and independently valuable. Ordered so that
the piece needing no schema decisions lands first.

### Slice 1 — the guidance registry — **DONE 2026-07-24**

Port `qc_guidance.py` near-verbatim into `core/` with its 26 tests. Add the
`[qc]` config section (`fd_threshold`, `investigate_threshold`,
`iqr_multiplier`) to `config/base.toml` and resolve it through duckbrain's
layered `load_config`, so a project can override a threshold in its own
`code/duckbrain.toml`.

Additive only — touches no existing behaviour. Surfaces nothing in the GUI yet.

**Note on config resolution.** mmmdata's port of this hit a trap worth not
repeating: its `core/__init__.py` imports pybids-dependent helpers, so
`from core.config import load_config` raised ImportError wherever pybids was
absent and silently stranded every threshold on its fallback. duckbrain's
`config.py` has no such package-level import today — **verify that still holds**
rather than assuming, and make an unreadable config warn rather than default in
silence.

*Landed:* the trap was checked, not assumed — `core/__init__.py` is a bare
docstring, so it does not apply here. `qc_settings()` still imports inside the
function and warns on both an unreadable config and a non-numeric threshold,
because the failure being defended against is silence, not the import. The
registry ported with **two** edits, both cosmetic (a docstring import path and a
generated-from line); it is otherwise byte-identical, which is what makes the
eventual "mmmdata depends on duckbrain" end state a deletion rather than a merge.
One config note the port did not carry over: `fd_threshold` is duckbrain's own
threshold for summarising fMRIPrep confounds and is **not** MRIQC's `fd_perc`
threshold, which is fixed at 0.2 mm inside the container and cannot be set from
here. The shipped comment now says so.

### Slice 2 — the report renderer and the embed — **DONE 2026-07-24**

Move the HTML rendering out of `qc_dashboard.py` into `core/` as a function
taking already-loaded data and returning a string. Page 5 embeds it via
`st.components.v1.html()` and offers the same string as a download; a copy is
written to `derivatives/`.

This is where `5_QC_Dashboard.py` gets thin. The logic currently in the page —
outlier detection wiring, column selection, run-key construction — moves to
`core/` where it is testable.

~~Fix `fmriprep_dir` here: derive it from `use_nordic` rather than hardcoding.~~

*Landed as `core/qc_report.py`, with one plan correction and one bug found:*

**The `fmriprep_dir` fix was wrong as specified, and doing it would have created
the bug it was meant to fix.** Collision 3 above assumed duckbrain mirrors
mmmdata's two-tree layout (`fmriprep` and `fmriprep_nordic`). It does not:
`core/fmriprep.py` writes to `<derivatives>/fmriprep` unconditionally, and no
`fmriprep_nordic` string exists anywhere in the codebase. Deriving a path from
`use_nordic` would have pointed a NORDIC project at a directory that is never
created — turning a non-bug into a silent empty read. The path is now resolved in
one place (`resolve_fmriprep_dir`) and stays `<derivatives>/fmriprep`.

The real gap that collision was groping toward is a *labelling* one, and it is
fixed: with one directory serving both inputs, nothing in the path tells a
reviewer whether mean FD was computed on NORDIC-denoised or raw data, and those
are different numbers describing different images. `fmriprep_input_variant()`
reads it from the derivative's own `DatasetLinks.raw` — the artifact, not the
config's intent — and the report states it above the motion columns.

**`load_mriqc_metrics` found zero runs on a sessionless project.** All three of
its globs required a `ses-` level, so `sub-015/func/*_bold.json` matched nothing
and the page reported "No MRIQC metrics found" while advising the user to run
MRIQC, which had already run. That is `#17`'s display-vs-reality shape, and it
means the QC page has never worked on `divatten_beta` — the one dataset this repo
calls clean. Now a recursive glob; the `_bold.json` suffix does the filtering, so
MRIQC's companion `_timeseries.json` still cannot be read as a run. All three
layouts have tests.

**Links are relative** (`../mriqc/…`), never `file://` — verified end-to-end
against real data, 78 links across two modalities, zero broken. Payload measured
at 4.96 MB for 65 runs, matching item 3's prediction that the Plotly bundle is
effectively the whole cost. An `@st.cache_data` keyed on a (count, newest-mtime)
fingerprint of the MRIQC output keeps the reload cheap.

**Item 2 is only half-closed.** Relative links fix the *exported* copy, which is
the one a reviewer opens from `derivatives/`. Inside `st.components.v1.html()`
the iframe is a `srcdoc` sandbox with no origin, so a relative link has nothing
to resolve against and the embed cannot route to MRIQC reports at all. The export
is the way to reach them; whether the app should serve the reports itself is
still open and still needs an OnDemand session to settle.

### Slice 3 — the decision model

Unify the schema and add the sign-off distinction: `pending` joins the
vocabulary, automated writers may record nothing else, and a human sign-off
requires an identifiable reviewer. Counts report signed-off separately from
auto-populated.

**Migration matters more here than in mmmdata**, which could classify legacy
records by reviewer name because it had one convention. duckbrain has existing
decisions in the older shape with **no reviewer at all**, so they cannot be
attributed retroactively. The reader must accept both schemas, and every legacy
record should surface as *unattributed* — visible, not silently promoted to a
sign-off it never was.

## Constraints that bind

- **Coverage is a hard CI gate.** `fail_under = 65`, and the Streamlit pages
  score 0% because they are scripts no test imports. Fattening page 5 turns CI
  red for a structural reason. Logic goes in `core/`; the page stays thin. This
  is the architecture anyway — `core/qc.py` is untested precisely because
  `5_QC_Dashboard.py` is 191 lines of logic living in a page.
- **Run the gates locally**: `ruff check . && ruff format . && python -m pytest
  tests/ -q --cov=duckbrain`. Line length 100; the incoming code wraps at ~79,
  which is compatible.
- **Branch, don't work on `main`, for this one.** `CLAUDE.md` prefers `main`
  because the OnDemand GUI serves this checkout and a branch risks the GUI
  running stale code. That rationale does not apply while the GUI is not being
  dogfooded and other work holds `main`; the branch keeps `main` servable and
  uncontended. Rebase onto `main` at the start of each session and merge
  promptly.
- **This doc and `TODO.md` are the only places open work is recorded.** No
  `# TODO:` markers in source.

## Checked against real data — 2026-07-24

The table below was the open list. It was worked before any code moved, against
`/projects/hulacon/bhutch/divatten_beta` (70 MRIQC JSONs, 65 BOLD runs) and
`/gpfs/projects/hulacon/shared/mmmdata` (647 MRIQC JSONs, T2w and dwi, both
fMRIPrep variants). Both read-only.

**The headline: the registry was right about every content question, and the
MRIQC *docs* are the stale side.** Nothing in it needed correcting on the way in.

| # | Verdict |
|---|---|
| 1 | **RESOLVED — registry correct.** Real output writes `tpm_overlap_csf/gm/wm`; `overlap_*_*` appears nowhere. Every registry key for bold/T1w/T2w exists in real output, with two intended exceptions (`mean_fd`, `pct_high_motion`) that duckbrain derives from fMRIPrep confounds and MRIQC never writes. Pinned by `TestAgainstRealMriqcOutput`. |
| 2 | **CONFIRMED AS A REAL RISK, unfixed.** mmmdata's shipped dashboard carries **837** absolute `href="file:///gpfs/…"` links and no relative ones. A browser blocks `file://` navigation from an HTTP page, so under the OnDemand proxy every "View report" link silently does nothing. Slice 2 must emit *relative* paths for the exported copy (which also makes the report movable) and route the embed through the app. Still needs an OnDemand session to confirm the fix. |
| 3 | **RESOLVED — benign.** Payload is ~4.86 MB of inlined Plotly regardless of content; 837 runs of table add only ~0.63 MB (~770 bytes/run). Scaling is not the problem, the fixed bundle is. |
| 4 | **Open, and now concrete.** mmmdata carries `derivatives/fmriprep` *and* `derivatives/fmriprep_nordic` side by side, so this is a real two-tree case, not hypothetical. Slice 2 decides. |
| 5 | **CONFIRMED — one real instance.** `sub-05_ses-01_acq-SPC_T2w` has `fber = -1` with `summary_bg_mean = 1.4`, i.e. a genuinely empty background. 1 of 627. `qi_1` never hit it (0 of 18). That file is now the `T2w` test fixture, so the sentinel has a live regression test rather than a hypothesis. |
| 6 | **RESOLVED — the Parkes citation holds.** `fd_perc` is present. Counting frames above each candidate threshold against MRIQC's own `_timeseries.tsv` matched `fd_num` in **65/65** runs at 0.2 mm and at no other value (0.25/0.3/0.5 each matched 3/65, 0.1/0.15 matched 0/65). The denominator is `size_t`, not the count of FD estimates. |

**Fixtures were committed, with the identifiers stripped.** `tests/fixtures/mriqc/{bold,T1w,T2w}.json` are real output with `bids_meta` and `provenance` removed — every remaining value is a number, so nothing subject- or scanner-identifying survives for a public repo, while the *key names* (the whole point) do. Synthetic fixtures cannot catch a wrong key name, because they would be written from the same assumption as the code.

**One finding the table did not anticipate.** All **609** decision records in mmmdata are `reviewer: "auto-stub"`, `decision: "keep"`, and not one has a second entry — the corpus is 100% machine-written and contains zero human sign-offs. That is the strongest possible argument for Slice 3's rule that an automated writer may record only `pending`: under the current model every one of those reads as a considered "keep". They live in mmmdata and are read-only here; nothing is migrated.

**And one the plan got wrong:** no duckbrain-schema decision file (`*_decision.json` with a `latest` key) exists in any real project directory on this filesystem. The legacy-migration problem Slice 3 describes is real in shape but currently has no instances, so the reader must still accept both schemas — there is just nothing to convert yet.

## Open questions

Not settled; decide when reached.

- **Group-level norms across projects.** `#7.4` asks for "group-level IQM
  comparison". Should duckbrain accumulate IQM distributions across the projects
  one user runs, as a local norm base? That is a genuinely new capability and
  the strongest reason this work belongs here rather than in mmmdata — but it
  raises where such a store lives, and whether cross-protocol pooling is
  defensible at all given the batch effects the guidance layer documents.
- **Does the report replace or complement the fMRIPrep/MRIQC HTML reports?**
  The guidance repeatedly says "open the visual report and look" — so the
  duckbrain report is a *router* to those, and item 2 above decides whether it
  can be.
- **Does `#7.4` want the surveyor's completeness view folded in?** The mmmdata
  dashboard carries a processing-status section that duplicates what
  `core/surveyor.py` already computes better. Probably drop it on the way in and
  link to the cockpit instead.
