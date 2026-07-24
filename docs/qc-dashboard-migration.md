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

### Slice 1 — the guidance registry

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

### Slice 2 — the report renderer and the embed

Move the HTML rendering out of `qc_dashboard.py` into `core/` as a function
taking already-loaded data and returning a string. Page 5 embeds it via
`st.components.v1.html()` and offers the same string as a download; a copy is
written to `derivatives/`.

This is where `5_QC_Dashboard.py` gets thin. The logic currently in the page —
outlier detection wiring, column selection, run-key construction — moves to
`core/` where it is testable.

Fix `fmriprep_dir` here: derive it from `use_nordic` rather than hardcoding.

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

## Cannot be verified without data

The registry's content was checked against tool source and literature, but every
assumption about *this* deployment's actual MRIQC output is unverified. Work
through these when a session has Talapas access — the one clean dataset is
`/projects/hulacon/bhutch/divatten_beta` (MRIQC and NORDIC derivatives, no
fMRIPrep yet, converted after the fieldmap-intent fix).

| # | To check | Why it matters |
|---|---|---|
| 1 | **IQM key names against real output.** MRIQC's own docs call the tissue-overlap keys `overlap_*_*` while the output uses `tpm_overlap_*`. The registry assumes the latter. | duckbrain pins `mriqc_version = "24.0.2"`; a wrong key renders a blank column silently. |
| 2 | **`file://` links under the OnDemand proxy.** The report links to MRIQC HTML as `file:///…`, which works when opened locally and is blocked by browsers when the page is served over HTTP. | "View report" would silently do nothing — the exact silently-degrading failure `CLAUDE.md` forbids. Likely needs relative paths or serving reports through the app. |
| 3 | **iframe height and payload at scale.** The mmmdata HTML is 4.8 MB, almost all inlined Plotly (deliberate, for offline HPC use). The iframe cannot share the parent page's JS. | Fine at 18 runs, unknown at 100+. Wants an `@st.cache_data` keyed on derivative mtimes — the same cache `#16.2` and `#22` both want, so build it once. |
| 4 | **Which fMRIPrep tree QC should read** when `use_nordic` is set. | A behavioural decision, not just a path fix. |
| 5 | **Sentinel `-1` values** for FBER and QI1 on real defaced or skull-stripped input. | Only observable on data that has been through defacing. |
| 6 | **Whether `fd_perc` is present** in this MRIQC version's BOLD output, and at what threshold it counts frames. | mmmdata's guidance states MRIQC's default is 0.2 mm; the Parkes 20% rule is only citable if that holds. |

**One cheap way to collapse most of this:** commit one real MRIQC output JSON per
modality (bold, T1w) into `tests/` as fixtures. A few KB each. They carry
`bids_meta` with subject identifiers, so it is a judgement call for a public
repo — but synthetic fixtures cannot catch a wrong key name, and items 1 and 6
above are exactly that failure.

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
