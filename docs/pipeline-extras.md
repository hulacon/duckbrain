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

## 2. Skull-stripping of anatomical images
- **What:** Brain extraction / defacing of the T1w (and T2w).
- **Role / placement:** depends entirely on *intent* — three different features
  hide under this name:
  - **(a) Defacing / anonymization** (e.g. `pydeface`, `mri_deface`) — an
    **upstream, in-place** step on the raw BIDS anat, for sharing/privacy. Runs
    before fMRIPrep; fMRIPrep tolerates defaced anat.
  - **(b) Precomputed brain mask fed to fMRIPrep** — a **producer** for fMRIPrep's
    "anatomical fast-track": fMRIPrep (≥ ~23.2) can *consume* a precomputed brain
    mask / segmentation via BIDS derivatives (`--derivatives`), skipping its own
    (slow, sometimes imperfect) skull-strip. Lets us control/QC the mask and save
    runtime.
  - **(c) QC of fMRIPrep's own stripping** — a **consumer** concern (fMRIPrep
    already strips via ANTs/SynthStrip internally; is it good enough per subject?).
- **fMRIPrep interaction:** **fMRIPrep already skull-strips internally**, so this
  is only worth adding for defacing (a) or the precomputed-mask fast-track (b), not
  to duplicate (c).
- **Open questions:** which of (a)/(b)/(c) does Ben actually want? Likely (a)
  defacing for sharing and/or (b) a controllable precomputed mask.

## 3. Eye BOLD signal preservation / eye-movement reconstruction from BOLD
- **What:** Preserve the orbital/eyeball BOLD signal and decode gaze/eye movements
  from it (cf. MR-based eye tracking, e.g. Frey et al. 2021 — DeepMReye).
- **Role / placement:** **orthogonal branch that fMRIPrep actively fights.**
  fMRIPrep's brain extraction removes the eyes and its normalization warps the FOV,
  so eye signal is destroyed by the standard pipeline. Needs the eye-region
  timeseries extracted from **raw or minimally-processed** data (pre-mask), OR a
  parallel pipeline that keeps the orbital FOV.
- **fMRIPrep interaction:** **strongly negative / unknown** — this is the clearest
  "fMRIPrep works against you" case in the list. Likely a separate extraction on
  raw BOLD (or fMRIPrep's pre-normalization/native-space outputs if the eyes
  survive there), feeding an eye-movement regressor/estimate.
- **Open questions:** does any fMRIPrep intermediate retain the eyes (native-space
  `desc-preproc_bold` before MNI warp)? Or must this run entirely off raw data in
  parallel? Which decoding approach (DeepMReye vs. simpler orbital-signal methods)?
  Research-grade; highest uncertainty in the list.

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
- **Ties to:** TODO #4 (naming/discovery robustness) and the LCNI naming survey.
  duckbrain currently uses dcm2bids + its own discovery; ReproIn is a
  convention-first (heudiconv heuristic) alternative.
- **Open questions:** adopt ReproIn heuristics internally vs. *recommend* the naming
  convention to LCNI users (so their exports are BIDS-ready)? Interaction with
  duckbrain's existing dcm2bids-based ingestion; is retrofitting worth it vs. just
  hardening our own discovery (TODO #4)?
