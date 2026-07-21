# Pipeline extras — candidate stages & integrations (backlog)

Odds-and-ends that a typical LCNI/Talapas neuroimaging pipeline involves and that
could fold into duckbrain. Captured 2026-07-15 (see the NORDIC Case-1 work for the
analytical lens used here). None are started; each is its own focused effort.

**The lens (from the NORDIC work).** For each item, the load-bearing questions are:
1. **Role** — *producer* (feeds fMRIPrep's input, like NORDIC), *consumer*
   (reads fMRIPrep/MRIQC output), or *orthogonal* (parallel branch / cross-cutting).
2. **Placement vs fMRIPrep's resampling** — must it run *before* any resampling
   (native space), can it run *after*, or is it independent? (NORDIC had to be
   upstream because interpolation breaks its noise model; other steps have their
   own constraints.)
3. **fMRIPrep interaction** — does fMRIPrep already do it, actively fight it, or
   ignore it?

Ordered roughly producer → orthogonal → consumer, not by priority.

---

## 1. DTI/DWI preprocessing
- **What:** A diffusion-MRI preprocessing branch (denoise, Gibbs, eddy/topup
  distortion + motion correction, tensor/other model fitting).
- **Role / placement:** **Orthogonal** — a whole separate modality, parallel to
  the BOLD pipeline. Shares only BIDS + the anatomical.
- **fMRIPrep interaction:** none directly. Natural analog is **QSIPrep** (nipreps'
  diffusion BIDS-App) — same ecosystem, same reports/derivatives conventions, and
  it can reuse sMRIPrep/anatomical derivatives. Alternatively FSL `eddy`/`topup` +
  MRtrix3 by hand.
- **Note:** ties back to the denoising discussion — MP-PCA/`dwidenoise` and NORDIC
  both originated in dMRI, so DWI denoising is where dwidenoise is actually the
  standard (unlike fMRI). If we add DWI, denoising placement is well-trodden there.
- **Open questions:** adopt QSIPrep wholesale (mirrors the fMRIPrep integration
  duckbrain already does) vs. a lighter custom branch? Shared anat derivatives
  between fMRIPrep and QSIPrep? Scope: this is a large, multi-stage addition.

## 2. De-identification for data sharing (DECIDED 2026-07-15: this is the goal)
Ben's intent (2026-07-15): **anonymize so data can be shared without
identification risk** — *not* the precomputed-mask or QC senses of "skull-strip".
This is two distinct jobs that belong together, both **upstream / in-place** and
**orthogonal to fMRIPrep**:

- **(a) Image defacing** — remove face/ear geometry from the anatomicals (T1w/T2w),
  which are reconstructable to a face. Tools: `pydeface`, `mri_deface`, `mideface`,
  or the combined BIDS-App below.
- **(b) Metadata / header PII scrubbing** — the load-bearing addition Ben flagged.
  Identifiers live in **two** places, both need scrubbing:
  - **Source DICOM headers** (before/at conversion): `PatientName`,
    `PatientID`, `PatientBirthDate`, institution, referring physician, device
    serial, study dates, etc. duckbrain sorts raw DICOMs (`core/dicom_sorter.py`),
    so PII is present at that stage too.
  - **BIDS JSON sidecars** produced by conversion — can retain `AcquisitionDateTime`,
    institution/device fields, and occasionally patient fields depending on the
    converter.
  - **Policy Ben stated — "derive then torch":** it's fine to *compute* demographics
    (e.g. age from birth date) into `participants.tsv`, but raw identifier fields
    (name, MRN, and the birth date itself) must be **automatically removed** from
    retained metadata. Note the standard nuances: exact dates and ages > 89 are
    HIPAA Safe-Harbor identifiers, so the safe pattern is *birthdate → age (capped
    at 90+) → discard birthdate*, and scan dates get relativized/dropped.
- **Candidate — one combined tool:** **`bidsonym`** (a BIDS-App) does exactly this
  pairing — defaces anatomicals (multiple algorithms) *and* scrubs metadata, with
  optional PII-leak checks. Worth evaluating vs. wiring `pydeface` + a custom
  sidecar/DICOM scrubber ourselves.
- **fMRIPrep interaction:** fMRIPrep tolerates defaced anat. **Open sub-question:**
  deface the *raw* data before fMRIPrep (simplest for sharing, but defacing can
  slightly perturb skull-strip/registration) vs. run fMRIPrep on intact data and
  deface + scrub only the *shared* copy/derivatives. Latter is safer for pipeline
  quality; former is simpler.
- **Open questions:** DICOM-level scrub (at `dicom_sorter`) vs. BIDS-level, or both;
  adopt `bidsonym` vs. roll our own; where the "share-ready" export lives; a
  verification/PII-audit pass so we can *assert* a dataset is clean before release.

### 2b. (deferred, different feature) Precomputed anatomical mask fast-track
Separate from the above and NOT what Ben wants now, but noting it so it isn't
conflated later: fMRIPrep (≥ ~23.2) can *consume* a precomputed brain mask /
segmentation via `--derivatives` to skip its own skull-strip (control + runtime).
That's a **producer** for fMRIPrep. Revisit only if that need arises.

## 3. Eye-movement reconstruction from BOLD (DeepMReye-style) — DECIDED 2026-07-15
- **What:** Decode gaze/eye position from the **orbital (eyeball) BOLD signal** in
  service of **DeepMReye-like analyses** (Frey et al. 2021). Ben: **most projects
  won't need this**, but it has *unique pipeline requirements* worth designing for
  so the standard pipeline doesn't silently preclude it.
- **Role / placement:** **orthogonal branch that fMRIPrep actively fights.**
  DeepMReye trains on the MR signal within the eyes; fMRIPrep's brain extraction
  removes the orbits and its normalization warps the FOV, so the standard pipeline
  **destroys exactly the signal this needs.** The requirement is to preserve /
  extract the orbital voxels from **raw or minimally-processed** data before that
  happens.
- **The unique requirement (why it needs designing in):** DeepMReye works on the
  eye region co-registered to its own eye template, typically from **raw/minimally
  preprocessed** functional data — it does *not* want fMRIPrep's brain-masked,
  MNI-normalized output. So enabling it means an **opt-in parallel path** that keeps
  the eyes, separate from the main fMRIPrep branch. The pipeline should let a
  project flag "preserve eye signal" and route accordingly, rather than assume
  every BOLD run is brain-only.
- **fMRIPrep interaction:** **strongly negative** — the clearest "fMRIPrep works
  against you" case. DeepMReye ingests raw/minimally-processed BOLD in parallel;
  fMRIPrep's outputs are the wrong input for it.
- **Open questions:** exact input DeepMReye wants (raw vs. motion-corrected-only);
  is this a duckbrain stage that *runs* DeepMReye, or just a "don't destroy the
  eyes / provide the right intermediate" affordance feeding a user's own DeepMReye
  run? A per-project opt-in flag (like `use_nordic`) fits. Research-grade; low
  demand but real requirements. Reference: DeepMReye
  (https://github.com/DeepMReye/DeepMReye).

## 4. Physiological data as BOLD regressors
- **What:** Cardiac/respiratory recordings → nuisance regressors (RETROICOR,
  RVT, HRV, respiration) for BOLD denoising.
- **Role / placement:** mostly a **consumer/parallel** step that produces
  regressors used **downstream** of fMRIPrep (at nuisance-regression / GLM time),
  merged into fMRIPrep's confounds table.
- **fMRIPrep interaction:** fMRIPrep ingests BIDS `_physio.tsv.gz` and emits a
  confounds table, but it does **not** compute RETROICOR-style physio regressors
  itself. Standard tool: **PhysIO (TAPAS)**, or `bioptions`/`peakdet`-style
  pipelines. Output regressors get concatenated with fMRIPrep confounds for the
  model.
- **Open questions:** is physio actually recorded for these projects (BIDS physio
  present)? Compute regressors as a duckbrain stage vs. leave to the analysis
  layer? Placement is post-fMRIPrep, so low interaction risk.

## 5. Version / provenance documentation & metadata
- **What:** Durable record of tool/container versions and pipeline provenance
  (BIDS-Derivatives `GeneratedBy`, `dataset_description.json` in each derivative,
  boilerplate methods text).
- **Role / placement:** **cross-cutting / orthogonal** infrastructure, not a
  pipeline stage.
- **fMRIPrep interaction:** fMRIPrep already writes its own `GeneratedBy` +
  boilerplate; the gap is duckbrain-level provenance across *all* stages.
- **Existing duckbrain hooks to build on:** container versions are already pinned
  in config; there's a durable submission log (`code/logs/submissions.tsv`) and the
  Nipoppy bagel export (`processing_status.tsv`). This item = extend those into
  proper per-derivative `dataset_description.json` + a project provenance manifest.
- **PROMOTED to the ★ TOP PRIORITY item in `TODO.md`** (paired with the
  consistency checker). Provenance isn't just documentation; it's the foundation
  for auto-flagging mismatches. Concrete signals found 2026-07-15: fMRIPrep records
  its input in
  `derivatives/fmriprep/dataset_description.json` → `DatasetLinks.raw` (a NORDIC run
  points it at `nordic/bids_format`; a raw run at the project root), and per-run
  sidecars carry `Sources: ["bids:raw:…"]` resolving through that link. **But
  `DatasetLinks.raw` is a single dataset-level field, overwritten per run**, so it
  can't represent mixed provenance — the last run's input is claimed for every
  subject. So duckbrain must record its *own* per-run provenance (extend
  `submissions.tsv` with the input variant) to catch mixing.
- **Open questions:** how much to emit (BIDS-Derivatives-compliant
  `dataset_description` per stage is the standards-aligned target). Relatively
  self-contained, low-risk, high-value.

## 6. Scanning notes & metadata integration (mmmdata does this)
- **What:** Ingest scanner/session notes (bad runs, task labels, session-level
  annotations) into BIDS metadata and have the pipeline respect them (e.g. exclude
  flagged runs from fMRIPrep via a bids-filter / scans.tsv).
- **Role / placement:** **producer of input-shaping metadata** — upstream of
  fMRIPrep, since it decides *what* gets fed in.
- **fMRIPrep interaction:** indirect but real — excluded runs simply aren't passed
  (via `--bids-filter-file` / `scans.tsv`), which duckbrain already knows how to
  write for sessions.
- **Reuse:** mmmdata's `build_manifest.py` / `generate_sessions_tsv.py` are the
  reference; port their shape (duckbrain already independently grew a surveyor/
  manifest sensibility).
- **Open questions:** notes source/format (spreadsheet? REDCap? free text?);
  mapping to a `scans.tsv`/manifest; UI for reviewing/overriding.

## 7. QC norms & best-practice dashboard (open item in mmmdata)
- **What:** A QC dashboard grounded in recommended best practices (motion metrics,
  MRIQC IQMs + group norms, fMRIPrep visual-report review, carpet plots,
  registration checks).
- **Role / placement:** **consumer** — reads fMRIPrep + MRIQC outputs, downstream.
- **fMRIPrep interaction:** consumes fMRIPrep's own reports + MRIQC IQMs; no
  pipeline placement question.
- **Existing duckbrain hooks:** the Project Status surveyor/cockpit, the MRIQC
  wiring, and the QC pages already exist — this item = layer best-practice norms
  (e.g. MRIQC IQM distributions/outlier flags, motion-exclusion thresholds,
  a structured fMRIPrep-report review flow) on top.
- **Open questions:** which norms/thresholds to codify (community QC protocols);
  automated flagging vs. human-in-the-loop review; group-level IQM comparison.

## 8. ReproIn — evaluate for adoption / user recommendation
- **What:** [ReproIn](https://github.com/ReproNim/reproin) — a heudiconv-based
  convention for naming scanner sequences so DICOM→BIDS conversion is automatic and
  consistent from the console onward.
- **Role / placement:** **upstream, at the ingestion/naming front-end** — orthogonal
  to fMRIPrep entirely.
- **fMRIPrep interaction:** none; this is about getting *into* BIDS cleanly.
- **Ties to:** TODO #5's standing rule on messy source labeling, and the LCNI
  naming survey. duckbrain currently uses dcm2bids + its own discovery; ReproIn is
  a convention-first (heudiconv heuristic) alternative.
- **This item got more interesting after the `#4` validation (2026-07-21).** Real
  exports are labeled inconsistently enough (`MMM03_sess04CR`, `MMM_15_sess3.2`,
  one `sess04` meaning two sessions) that the answer landed on *fix it at the
  console, don't parse around it*. ReproIn is precisely that fix, so the framing
  shifts: it is less "should we adopt heudiconv heuristics" and more "is a naming
  convention what we recommend to LCNI users so this class of problem stops
  arriving".
- **Open questions:** adopt ReproIn heuristics internally vs. *recommend* the naming
  convention to LCNI users (so their exports are BIDS-ready)? Interaction with
  duckbrain's existing dcm2bids-based ingestion; is retrofitting worth it vs.
  leaving discovery as-is and pushing the convention upstream?
