# QC review domains — grouping the dashboard by the question being asked

Design for `TODO.md` `#24`. Written 2026-07-28, with Slice A landed.

`docs/qc-dashboard-migration.md` is the prior record: it brought the guidance
registry, the report renderer and the decision model over from mmmdata. This doc
takes the next step — organising what those produce so a reviewer can read it.

## The problem

`5_QC_Dashboard.py` presents everything about a run at once: a per-subject
fMRIPrep panel, a modality selector, an IQR slider, a 4.9 MB embedded HTML
report, then a flat list of per-run expanders each holding every IQM as a bullet.
The guidance explaining why a number matters lives in a glossary section at the
bottom of the report, far from the number it explains.

The complaint that started this was navigational — the page is cumbersome — but
the fix is not a smaller page. It is that **the page has no organising question**.
Thirty measures presented as one list ask the reviewer to hold the whole of QC in
their head at once, and to rediscover each time which numbers speak to which
concern.

## The taxonomy

Four domains, each a question a reviewer can answer on its own.

| key | label | review question |
|---|---|---|
| `signal` | Signal & contrast | *Is there enough signal, and enough contrast between tissues, to measure anything at all?* |
| `temporal` | Temporal stability | *Did the timeseries hold still, and hold steady, frame to frame?* |
| `alignment` | Alignment & distortion | *Is everything where it should be — distortion corrected, BOLD on the T1w, brain in the template?* |
| `artifact` | Artifacts & inhomogeneity | *Is the image corrupted by something other than noise — ghosting, ringing, bias, blur?* |

Assignment of all 30 registry keys:

- **signal** (8) — `tsnr`, `snr`, `snr_total`, `snr_gm`, `snr_wm`, `cnr`, `cjv`, `fber`
- **temporal** (10) — `fd_mean`, `fd_num`, `fd_perc`, `mean_fd`, `pct_high_motion`, `dvars_std`, `dvars_nstd`, `aqi`, `aor`, `gcor`
- **alignment** (3) — `tpm_overlap_gm`, `tpm_overlap_wm`, `tpm_overlap_csf`, plus all the fMRIPrep visual evidence
- **artifact** (9) — `efc`, `gsr_x`, `gsr_y`, `qi_1`, `qi_2`, `inu_range`, `inu_med`, `wm2max`, `fwhm_avg`

### Why it must be a partition, and why there is no "other"

A measure in two domains renders two `<details id="guidance-{key}">` blocks into
the same document, and an in-page anchor then lands wherever the browser decides.
`_render_header_cells` already emits `href="#guidance-{key}"` from every column,
so duplicate ids are a broken document, not a tidiness question. `_register` in
`core/qc_domains.py` enforces the partition at import for that reason.

An "other" bucket would also be where every arguable assignment went to die,
which is how a taxonomy stops meaning anything. Each measure below was placed,
and the arguable ones are recorded as arguable rather than dodged.

### Assignments that are genuinely arguable

- **`dvars_*` → temporal, not signal.** DVARS is a signal-change measure and
  could sit in `signal`. It stays in `temporal` because the highest-yield visual
  is the carpet plot with FD and DVARS stacked above it, and that figure is
  unassignable if the two split. `PROCESS_GUIDANCE["visual_report"]` already says
  to read them together. **The assignment most likely to be challenged.**
- **`inu_range` / `inu_med` → artifact.** Bias field is arguably a
  preprocessing-success question and therefore alignment-adjacent. But as MRIQC
  IQMs they describe the raw image before anything corrected it.
- **`gcor` → temporal.** `direction="context"`; it indexes residual global signal,
  which is closer to a confound-modelling question than a quality one. Defensible
  as a fifth domain of its own; not worth one for a single key.
- **`efc` → artifact on both modalities, while doing `temporal`'s job on anat.**
  It is the strongest anatomical proxy for subject motion, and `temporal` is empty
  for T1w/T2w. It is not reassigned; instead the temporal not-applicable note
  cross-links to it. That cross-link is content the *domain* owns, which is part
  of why the taxonomy is not a field on `MeasureGuidance`.
- **`fber` → signal.** Behaves like an SNR measure, but its `-1` sentinel makes
  it "is there a usable background at all", which is an artifact question. The
  sentinel is covered by `PROCESS_GUIDANCE["sentinel_values"]` and restated as the
  artifact domain's caveat.
- **`fwhm_avg` → artifact**, and **`wm2max` → artifact.** MRIQC frames `wm2max`
  as intensity *normalization*, which sounds spatial; it is not — it catches
  hyper-intense outliers such as fat and vessels.

### The two empty projections, which must never render blank

`CLAUDE.md`'s rule that a silently-degrading option is worse than one that fails
applies directly: a blank section and a section that failed to load look
identical to the reader. Both cases carry a sentence, and
`ReviewDomain.explain_absence` cannot return the empty string even for a modality
nobody filled in.

- **temporal / T1w+T2w** — a structural scan is one volume, so there is no
  frame-to-frame anything to measure; the nearest question surfaces as ringing
  and ghosting, graded under Artifacts as `efc`.
- **alignment / bold** — MRIQC computes no registration measure for functional
  data, so alignment is reviewed entirely from fMRIPrep's per-run figures. **This
  is the section's purpose, not a gap in it.**

### The caveat the alignment domain must state

`tpm_overlap_*` measures overlap with template tissue maps after **MRIQC's own**
registration. It says nothing about whether **fMRIPrep's** normalization worked.
A reviewer seeing the only three numbers in the domain will assume otherwise, so
the domain carries the distinction as a `caveat` rather than leaving it to be
inferred.

## Decisions that are settled

### The taxonomy lives outside `MeasureGuidance`

`core/qc_domains.py`, not a `domain` field on the frozen dataclass. Two reasons,
and the second is decisive:

1. `qc_guidance.py` is a near-byte-identical port from mmmdata, and
   `docs/qc-dashboard-migration.md` records that as precisely what makes the
   eventual "mmmdata depends on duckbrain" end state *a deletion rather than a
   merge*. Editing 30 call sites and the validator spends that.
2. **A domain's content is not only measures.** `desc-sdc_bold`,
   `desc-coreg_bold`, `dseg`, `space-*_T1w` and the rest have no key, no
   direction and no auto_flag, so they can never be registry entries — and they
   are the *entire* content of `alignment` on functional data. A dataclass field
   cannot express them. `EvidenceFigure` can.

The cost is two registries that could drift, paid for by enforcing the partition
at import plus `TestPartition` in `tests/test_qc_domains.py`.

### The run stays the unit of review

Considered and rejected: transposing to a cohort-first axis where each domain
page reviews all runs at once and is signed off once. That would cut sign-offs
from a possible 260 to 4, but it removes the place where one run is seen whole,
and the verdict is a per-run judgement.

The cost of keeping the run is real and is not hidden: four domains × 65 runs is
260 possible sign-offs where there are 65 today. Three things hold it down —
domain sign-off is optional and gates nothing; the overview's run × domain matrix
is what keeps a reviewer from touring everything; and a per-run "mark remaining
reviewed" bulk action is available **if real use shows one is needed**. That last
is deliberately deferred: it is defensible only as an explicit human act, and it
should be designed against observed friction rather than a prediction.

### An overall verdict is never derived from domain sign-offs

Not only because it manufactures a sign-off nobody made — the `#17.10` shape, and
the same error as the 609 machine-written `keep`s that
`docs/qc-dashboard-migration.md` calls the strongest argument for the `pending`
rule. The sharper reason is that **the four domains do not partition the question
a verdict answers**: none of them covers task timing, stimulus delivery, or a
participant asleep with their eyes open. "All four domains reviewed" and "this
run is usable" are different claims.

Derived readiness may be *displayed* ("4/4 domains reviewed · no verdict
recorded"). It is never *recorded*. And the verdict buttons must not be gated
behind domain completion — a reviewer who sees a wrecked run must be able to
exclude it without touring four pages first.

### The HTML export is punted on, not regrouped

Decided 2026-07-28. The original plan had a slice that reorganised the exported
report by domain. That is dropped: the export keeps working exactly as it does,
and effort goes into the pages instead. If the dashboard ever grows persistent
artifacts worth keeping, they belong in `derivatives/duckbrain` — note that
today's `REPORT_SUBDIR` is `duckbrain_qc`, and nothing has ever been written to
it on this filesystem, so that rename is still free whenever it is wanted.

**Accept the consequence knowingly:** until this is revisited, the export shows a
flat table with a floating glossary while the pages show domains. The two
disagree about how QC is organised, and that is a real cost of punting, not an
oversight.

### Domain pages render natively; the export keeps its single renderer

This **amends** `docs/qc-dashboard-migration.md`'s "one renderer, two delivery
paths". Six pages each embedding the 4.9 MB payload would be worse than the one
page that exists now, and `TODO.md` `#23` would get six times worse rather than
better.

The amendment is narrow: `qc_report.render_report` remains the single renderer of
the **exported document**, and the app reads the same `build_run_rows` +
`qc_domains` structures through native Streamlit widgets. The original decision's
own justification — *"QC is the exception because it is the one surface that is
mostly read; its output is a document"* — is an argument about the export, which
is untouched. Drift risk is bounded to styling, because both paths consume the
same structures and content is what the tests pin.

It also closes `#23` for the whole interactive QC surface as a side effect,
leaving only `embed_tool_report`, which serves the tools' own reports and
genuinely needs an iframe.

### Guidance is tethered by moving the section, not by writing a new renderer

`render_guidance_section(measures_for(modality, domain))` is called once per
domain section. No new renderer, and no change to `qc_guidance.py`. The
`#measure-guidance` glossary is deleted *as a glossary* and returns as
`#references`, rendered from `qc_guidance.all_references()` — which has **no
production caller today**, so this gives dead code a job while keeping the
citations, which are the part of the guidance layer with value away from the
metric. Every `#guidance-{key}` anchor still resolves; the cards moved sections,
they did not disappear.

## What real data settled

Checked 2026-07-28 against `/projects/hulacon/bhutch/divatten_beta_v2`.

- **fMRIPrep's alignment evidence is per-run.** `sub-010/figures/` holds
  `desc-sdc_bold`, `desc-coreg_bold`, `desc-fmapCoreg_bold`,
  `desc-carpetplot_bold`, `desc-rois_bold`, `desc-compcorvar_bold` and
  `desc-confoundcorr_bold` **per run**; only `dseg`, `space-*_T1w`,
  `desc-reconall_T1w` and `fmapid-*_desc-pepolar_fieldmap` are per subject. The
  existing panel is per-subject only because `find_fmriprep_reports` globs the
  aggregated `sub-*.html`, not because the evidence is.
- **Serving one figure costs 1.1 MB against 80 MB** for the subject's figures
  directory — a 70× reduction, and the honest caption changes from "80 MB of
  figures" to "1.1 MB".
- **The SDC flicker survives standalone serving.** Each `desc-sdc_bold.svg`
  carries its own `<style>` with `@keyframes` and a `flicker` animation, so the
  before/after alternation — without which SDC cannot be reviewed at all — does
  not depend on the enclosing report. `tests/test_qc_evidence.py` pins that the
  served bytes still contain `@keyframes`, so a future size optimisation that
  strips SVG styles fails loudly instead of quietly killing the animation.
- **The output-space template must not be hardcoded.** The normalization figure
  is `space-MNI152NLin2009cAsym_T1w.svg` here, but output space is a project
  choice, so `EvidenceFigure.pattern` is a glob (`space-*_T1w.svg`).

Checked again 2026-07-28 while building Slice C, against `mmmdata`'s seven-session
tree as well:

- **`figures/` sits at the subject level even with sessions.** fMRIPrep puts the
  session in the *filename*. Assuming a `ses-XX/figures` level would find nothing
  for every session project.
- **Matching must be by entity, not by string prefix.** mmmdata's anatomical
  figures are `sub-03_acq-MPR_dseg.svg` — an entity the run key never carries —
  so joining a prefix to a pattern finds nothing there while working fine on
  `divatten_beta_v2`. Every candidate is globbed by its filename tail and then
  filtered on the entities both sides carry.
- **A "subject" figure still has to respect the session.** `desc-pepolar` carries
  `ses` and matches 58 files for one subject on mmmdata; filtering on subject
  alone would offer another session's fieldmap as if it were this one's. It must
  *not* respect `run`, though — a fieldmap's `run` index counts fieldmaps, not
  BOLD runs, and comparing them would reject every fieldmap.
- **Several matches is normal, not an error.** Two fieldmap pairs in a session
  give two estimation figures; a multi-acquisition anatomical gives one
  segmentation figure per acquisition. All are shown, labelled by what
  distinguishes them.
- **One run in mmmdata has a carpet plot and no SDC figure** (202 against 203).
  The absence case is real, not hypothetical.
- **`Path.glob` returns empty rather than raising** for a directory that is
  missing, unreadable, or not a directory. So there is deliberately no `try/except
  OSError` around it: the guard would be unreachable, and unreachable guards rot.
  Pinned by a test that points the viewer at a regular file.
- **Verified live end-to-end**: the SDC figure reaches the browser as a
  self-contained 1.13 MB `data:image/svg+xml` URI with `@keyframes` intact, so
  the flicker survives. A data URI also has no URL to get wrong under OnDemand's
  `/node/<host>/<port>/` prefix, which is the bug class `report_embed` exists to
  fix — here it is avoided by construction rather than handled.

## Coverage, since it gates CI

Measured before starting: 5937 statements, 4205 covered, **70.83%**, floor 65%,
and every page scores 0% — `AppTest` does not put page bodies under coverage, so
the `pyproject.toml` comment is accurate. The floor therefore tolerates ~532 new
uncovered statements; five thin pages cost roughly 142 net once page 5 shrinks.

The structural rule is unchanged from the migration doc — logic goes in `core/`,
pages stay thin — with one addition: shared per-domain rendering goes in
`gui/qc_panels.py`, which is importable and therefore testable via
`AppTest.from_function`, exactly as `tests/test_gui_components.py` drives
`directory_picker`. Slice A landed at 100% coverage of the new module and moved
the total *up*, to 71.17%.

The real risk is suite wall-clock rather than the gate: `test_qc_page.py` runs
with `default_timeout=60` because the page renders the full Plotly report twice.
That is a design constraint on the split, not a test trick — **a domain page must
render only its own domain's chart and must not embed the full report.**
