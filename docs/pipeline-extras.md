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

## 1. DTI/DWI preprocessing — QSIPrep

**Scoped 2026-08-01** at Ben's request ("how heavy a lift?"), in §9's voice: what
it costs, what it breaks, and what isn't ours to settle. The
facts below were read from `PennLINC/qsiprep@master` rather than the published
docs, **which are stale on two points that matter** — both flagged inline.

✅ **Slice A shipped 2026-08-21** — a launchable, tracked `qsiprep` stage
(`core/qsiprep.py`, `templates/sbatch/qsiprep.sbatch.j2`, a tracker, a cockpit
arm, a fourth Preprocessing tab, `tests/test_qsiprep.py`). Slice B (QC dashboard)
is untouched. **Nothing has run on real data yet**: the flag set is verified
against the pinned container's own argparse — every flag below is accepted by
`qsiprep-26.0.0.sif`, and the invocation then fails on dataset content rather
than on arguments — and the `[slurm.overrides.qsiprep]` numbers are the shape of
the fMRIPrep allocation rather than anything anyone watched. Say so when
re-measuring them.

🔴 **The container now exists on Talapas**, which this section listed as a real
cost to confirm before committing to a date:
`/projects/hulacon/shared/containers/qsiprep-26.0.0.sif`, pulled 2026-08-21 from
`docker://pennlinc/qsiprep:26.0.0`, 10.6 G, self-reporting `QSIPrep v26.0.0`.
Symlinked into `~/containers` beside `fmriprep-25.2.5.sif`.

🔴 **A fourth trap, found the same day and absent from the three below because it
only appears when you read the report code:** a **sessionless** subject run with
`--subject-anatomical-reference sessionwise` gets **no HTML report at all**.
`parser.py` puts such a subject in the processing group `[subject, []]` and
merely warns; `reports/core.py` then takes the sessionwise branch, which loops
over that empty session list and writes nothing. So Trap 2's fix — force
`sessionwise` — is exactly wrong for a sessionless project, and a tracker that
requires the report would have pinned every such unit at PARTIAL forever.
duckbrain passes `first-lex` there instead (`qsiprep.SESSIONLESS_REFERENCE`):
with no sessions the four choices are otherwise indistinguishable, so nothing is
lost by overriding a configured value. Trap 2 below still says "sessionless
projects are unaffected"; that was true of the clobber it is about and false of
this.

- **What:** A diffusion-MRI preprocessing branch (denoise, Gibbs, eddy/topup
  distortion + motion correction, tensor/other model fitting).
- **Role / placement:** **Orthogonal** — a whole separate modality, parallel to
  the BOLD pipeline. Shares only BIDS.
- **fMRIPrep interaction:** none. Same ecosystem, same reports/derivatives
  conventions. Alternatively FSL `eddy`/`topup` + MRtrix3 by hand.
- **Note:** ties back to the denoising discussion — MP-PCA/`dwidenoise` and NORDIC
  both originated in dMRI, so DWI denoising is where dwidenoise is actually the
  standard (unlike fMRI). If we add DWI, denoising placement is well-trodden there.

### Ground truth (verified against source, 2026-08-01)

- **Latest release is `26.0.0`** (2026-04-20). QSIPrep moved to CalVer with
  "Adopt NiPreps-style packaging" (PR #1028), so `1.1.1` → `26.0.0`; a version
  that looks like a year is not a typo. Container: `pennlinc/qsiprep`.
- **`--output-resolution` is `required=True`, `type=float`, no default**
  (`qsiprep/cli/parser.py`) — the isotropic mm everything is resampled to.
- **Reconstruction is gone.** Recon split into a separate app, **QSIRecon**, at
  1.0; there is no `--recon-spec` in the parser. Tractography/model fitting is a
  second tool and a second decision, not part of this one.
- 🔴 **Output lands directly in `output_dir`, not `<output_dir>/qsiprep/`**
  (`qsiprep/interfaces/bids.py`, `DerivativesDataSink.out_path_base = ''`). The
  `<out>/qsiprep/…` shown in `docs/preprocessing.rst` is **stale**. duckbrain's
  convention — one derivative dir per stage, named for the stage — still works,
  because we pass `<derivatives>/qsiprep` as `output_dir` itself. Worth knowing
  before someone "fixes" a path that is already right.
- **`--session-id` is native** (nargs='+', strips `ses-`), so a session-scoped
  run needs **no BIDS filter file**. `core/fmriprep.py:write_session_filter`
  exists only because fMRIPrep must leave anat *unfiltered*; QSIPrep handles the
  same concern with `--subject-anatomical-reference`. Don't port the filter.
- 🔴 **There is no `--derivatives`, no `--anat-derivatives`, no
  `--fs-subjects-dir` — no precomputed-anat flag of any kind.** This corrects
  what this section previously claimed ("it can reuse sMRIPrep/anatomical
  derivatives"), which was wrong.
- Uses TemplateFlow, and needs the FreeSurfer license for SynthStrip/SynthSeg.
- Key outputs: `<ss>/dwi/*_space-ACPC_desc-preproc_dwi.{nii.gz,bval,bvec,b}`,
  `*_desc-confounds_timeseries.tsv`, `*_desc-image_qc.tsv`, `*_desc-slice_qc.tsv`,
  CNR maps, and `<ss>/anat/*_space-ACPC_desc-preproc_T1w.nii.gz`.

### 🔴 Trap 1: merging breaks the surveyor's grader

**QSIPrep concatenates DWI scans that share a warped space before head-motion
correction**, dropping the entity that distinguished them: three inputs
`…acq-multishell_run-{1,2,3}` become **one** `…acq-multishell_desc-preproc_dwi.nii.gz`.

`surveyor._grade` is superset semantics — `expected <= found` — and that is
correct for every stage duckbrain has today because all of them are
one-output-per-input. Against a merged output it is **false forever**: a
completely successful run grades PARTIAL, which `stage_runnable` then reads as
"not done", and the cockpit invites a re-run that will produce exactly the same
result. This is the one piece of genuinely new logic the feature needs — a
`_covers`/`_grade_merged` sibling that treats a found key as satisfying an
expected one when its entities are *coarser but never contradictory*
(`core/qc.py:parse_entities` is already public and does the parsing). **Built as
`surveyor._covers` / `surveyor._grade_merged` 2026-08-21**, off the surveyor's
own `_entity_key` rather than `parse_entities` — it already strips
representation entities (`space-`, `desc-`) that the identity test must ignore,
so reaching for the other parser would have needed that filtering rebuilt.

**The honest cost of that fix, which must be written down wherever it lands:**
coarsening means **a genuinely dropped run inside a merged group cannot be
detected from filenames**. There is no per-input artifact to fall back on —
`desc-confounds_timeseries.tsv` and `desc-image_qc.tsv` are per-*output* and
merge too. This is a real limit on what the board can claim, not a bug to paper
over, and it is the kind of thing `[expected]` exists for.

**Rejected fix, recorded so it isn't re-proposed:** forcing `--separate-all-dwis`
to restore 1:1 tracking. That trades preprocessing quality — less data for
head-motion correction — for the convenience of duckbrain's status column. The
tail wagging the dog, and a silent science change at that.

### 🔴 Trap 2: per-session jobs clobber each other's anat

duckbrain's unit is `(subject, session)`. With the default
`--subject-anatomical-reference first-lex`, **each session's job builds its own
ACPC anatomical reference from that session alone and writes it to the *subject*
level** — `sub-XX/anat/` and `sub-XX.html`. Launch two sessions and the second
silently overwrites the first; last writer wins, nothing says so.

`--subject-anatomical-reference sessionwise` puts anat and the report under
`sub-XX/ses-YY/` and matches duckbrain's per-unit model exactly. So: make it a
config key defaulting to `sessionwise`, and **raise from the builder** if a
multi-session project sets it to anything else, rather than letting the run
proceed and clobber. Sessionless projects are unaffected. Note the knock-on for
whoever writes the tracker: the report path is then *conditional*
(`<out>/sub-XX.html` vs `<out>/sub-XX/ses-YY/sub-XX_ses-YY.html`), and so is the
figures directory — see Slice B. **Both shapes verified against
`reports/core.py` 2026-08-21**, and `surveyor._qsiprep_report_present` asks for
either rather than picking one: duckbrain controls which shape its own projects
produce, but an externally-run tree is not duckbrain's to predict.

### 🔴 Trap 3: `--output-resolution` has no defensible default

It sets the isotropic voxel size everything is resampled to, in a single
interpolation, and a wrong value produces data that looks entirely usable and is
wrongly sampled. It is a **study-level scientific choice**, not a tuning knob.

Ship `[qsiprep] output_resolution` **commented out** — the `[expected]` precedent
— and raise when it is unset, naming the choice rather than guessing at it. A
`2.0` default would be a guess dressed as a setting. This is the clearest
application in the whole feature of `CLAUDE.md`'s rule that a silently-degrading
option is worse than one that fails.

### What it would cost inside duckbrain

Two independently shippable slices. **Slice A is a real stopping point** — it
delivers a launchable, tracked stage with no QC work at all.

**Slice A — launchable + tracked stage (~2–3 focused days).**
New `core/qsiprep.py` (model: `core/mriqc.py`, the thinnest tool module) and
`templates/sbatch/qsiprep.sbatch.j2` — modelled on `fmriprep.sbatch.j2`, **not**
`mriqc.sbatch.j2`, because QSIPrep needs both the FreeSurfer-license bind and the
per-job TemplateFlow home that exists to avoid the `#21` race. Then the checklist,
which is short because the stage model is well factored: `STAGES` +
`_qsiprep_status` + `_TRACKERS` + a `run_progress` arm (`surveyor.py`);
`_build_qsiprep` + a `STAGE_SPECS` row + `_STAGE_TOOL` + `resolve_container` + the
`input_variant="raw"` branch (`pipeline.py`); `build_context`'s hardcoded sub-dict
list (`slurm/templates.py`); a `[containers]` pin, a `[qsiprep]` section and
`[slurm.overrides.qsiprep]` with `long = true` (`config/base.toml`); one row in
`consistency.py`'s drift tuple.

**The cockpit board needs nothing** — it iterates `STAGES`/`SLURM_STAGES`, so the
column, rollup, bulk popover, job popover, log tail and cancel/re-run all arrive
free. What the GUI *does* need, and §9's "the GUI needs nothing" undersold: one
`_stage_params` arm (`0_Project_Status.py`), a fourth tab in
`4_Preprocessing.py`, and all **five** coordinated edits in `1_Project_Setup.py`
— a version widget without its `_USER_OWNED` entry raises on save, by design.

One more tracker requirement, easy to miss: **`Status.NA` when a unit has no
DWI**, and it is not the same shape as NORDIC's. NORDIC's NA is a project-level
config question (`use_nordic`); QSIPrep's is **per-unit data** — one session can
have DWI and the next not. Without it the rollup, the bulk "run all", and the
all-complete message are all poisoned (the `#17.4` lesson).

**Slice B — QC dashboard (~2.5–3 days).**
Use the **per-figure SVG evidence path**, not `embed_tool_report`. That is the
architecture `#24` deliberately moved *to* (~1.1 MB for the figure a reviewer
wants vs ~80 MB for a whole subject report), the argument transfers to QSIPrep
unchanged because its reports are the same nireports shape and size class, and
`embed_tool_report` is the *opt-in* path, not the default one. As of 2026-08-03
it has a call site again — `qc_panels.full_report_panel` on the Overview, behind
a toggle that names the payload in MB first — which is where the sampling-scheme
animation and the boilerplate become reachable. So QSIPrep needs no new embed:
add its report to `full_report_panel`'s candidates (a `find_qsiprep_reports`
alongside the other two finders) and spend the rest of the slice on figures.

The structural edits, in rough order of size: replace `evidence_for`'s hardcoded
`if modality == "bold"` (`qc_domains.py`) with a per-figure `modalities` field,
or QSIPrep's run figures are simply unreachable; generalize `qc_evidence`'s
`fmriprep_dir` parameter to a tool-neutral root; teach `figures_dir` that
QSIPrep's figures can be **session-level** (`sub-X[/ses-Y]/figures`), which its
docstring currently denies in as many words; and drop the `task`-entity
requirement in `runs_with_figures`, since DWI runs have no task. The figure
inventory itself is transcribable straight from QSIPrep's `reports-spec.yml`,
which ships captions.

### One pre-existing inaccuracy this surfaced

Worth fixing whether or not QSIPrep is ever built. `gui/qc_panels.py`'s
`MODALITIES` omits `dwi` while `core/qc_domains.py`'s includes it, and
`qc.iqm_columns("dwi")` would dutifully project the registry onto a modality no
page offers. Meanwhile six measures
already declare `dwi` in `qc_guidance.py` — `fd_mean`, `fd_num`, `fd_perc`,
`gsr_x`, `gsr_y`, `snr` — but MRIQC's diffusion IQMs are `snr_cc`, `ndc`,
`fa_nans`, `fa_degenerate`, `spikes_ppm` and the per-shell
`fber_shell01`/`efc_shell01` family. **Only the three `fd_*` are real**; `gsr_x`,
`gsr_y` and `snr` are aspirational for DWI and would render wrong or empty.
Turning `dwi` on in the dashboard without settling that makes the dashboard lie
about what it measured — so it is Slice B's first task, not a footnote.

### The real costs, and what isn't ours to settle

- ✅ **The hard prerequisite `#19.1` is met (closed 2026-07-30).** DWI now
  converts: `dwi/…_dwi.nii.gz` with `.bval`/`.bvec`, plus `…_sbref` for a
  diffusion reference, validated on real multi-shell data from two scanners. So
  QSIPrep has something to read, and what was the blocking cost is now a fixture.

  **Its caveat is inherited whole and lands squarely on validation here:** the
  LCNI curator dropped the diffusion series too, so **there is no canonical BIDS
  output to diff against**. Validation will be internal consistency plus "QSIPrep
  accepts it" — not the curator comparison every other conversion capability was
  checked against. `#19.1` answered that for the *conversion* by asserting
  against the acquisition (shell count, bvec shape, `PhaseEncodingDirection`
  against the `dir-` label); the same stance is what this stage will need.

  **One thing `#19.1` deliberately left for this item to decide** (`#19.10`): a
  diffusion series carries **no `B0FieldSource`**. duckbrain had nothing that
  consumed it, and its fieldmap binding is keyed on `(task, run)` — which
  diffusion has neither of — so choosing one would have been an unreviewable
  guess, invisible in the Conversion page's `fieldmap` column. QSIPrep is the
  consumer that makes the question real, and the answer belongs here rather than
  in the emitter.
- ~~**A container must be built or pulled** for `pennlinc/qsiprep`~~ — **done
  2026-08-21**, see the note under the heading. Was one more instance of `#2`.
- **eddy is hours per subject.** This is a scheduling change, not just a stage.
- **Fixture:** `/projects/hulacon/shared/mmmsourcedata` is the DWI-bearing tree —
  diffusion SBRefs and LR/RL phase encoding, neither of which the LCNI corpus has
  at all. Read-only; symlink at the `dicom` level into scratch, as `fmap_eyeball`
  does. The two facts this section asserts *from source rather than observation*
  — the merge behaviour and the figures-directory level — are the two the first
  real run should confirm, and they belong in `memory/` when it does.

### The good news, stated plainly

**QSIPrep is not a forcing function for the parked `#5b` Case 3 DAG** — unlike
§9's external-FreeSurfer item, which is. Two independent reasons, and the second
is the stronger: QSIPrep has no anat-reuse flag at all, *and* its anatomical is
LPS+ and AC-PC realigned where fMRIPrep's is RAS+ in original orientation
(`docs/preprocessing.rst` calls this out as the one major difference). Sharing
anat derivatives between them is not merely unsupported, it is **wrong**. So
`depends_on` is the plain string `"converted"`, `effective_depends_on` needs no
new arm, and the dependency graph stays as simple as it is today. Say this in
the builder's docstring when it is written: "why doesn't qsiprep reuse the anat
like fMRIPrep does" is the first question a reader will have.

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

🔴 **CORRECTION 2026-08-21 — the two claims above about fMRIPrep are wrong, and
one open question is answered.** Measured against mmmdata, recorded in
`mmmdata-agents/docs/workbench/reprocessing-campaign/log.md`.

- **"fMRIPrep's brain extraction removes the orbits" is false for the output
  that matters.** `desc-preproc_bold` is **not** brain-extracted — fMRIPrep
  ships the brain mask as a *separate file* and does not apply it. In
  `sub-03_ses-02_task-auditory` (MNI152NLin2009cAsym, mean of 20 volumes) the
  orbital boxes carry mean 1224 / 746 with **temporal SD 200 / 103** — the same
  order as occipital cortex at 218 — while being **0.5-0.7% inside the brain
  mask**. An air box in the same run is exactly 0.0. Replicated over 6 runs x 3
  subjects: orbital SD 112-206, every run. This is why bidsMReye can run on
  fMRIPrep derivatives at all.
- **"orthogonal branch that fMRIPrep actively fights" therefore overstates it.**
  Normalization does warp the FOV, and that part stands; brain extraction
  destroying the eyes does not.
- **Answered: DeepMReye needs no anatomical image.** `preprocess.py` registers
  the *functional* series to a group template shipped with the package
  (`register_to_eye_masks(dme_template, func, ...)`, `fixed=dme_template`,
  `moving=ants.get_average_of_timeseries(func)`). No T1w/T2w anywhere. So
  **`#7.1` defacing and `#7.8` are orthogonal as long as defacing stays
  anat-only** — the hazard is a defacer or anat-derived mask applied to the EPI,
  not the ordering of the two items.
- **What replaces the retracted worry:** the orbital boxes are 56-62% nonzero,
  so **partial EPI FOV coverage of the orbits** is the live risk to `#7.8` on
  this dataset, and it is an acquisition property no pipeline flag can fix.
  Check it before committing to the item.

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
- **SHIPPED 2026-07-16 as the ★ item** (paired with the consistency checker); see
  the `TODO.md` ledger, and "Provenance / consistency residuals" there for the
  accepted edges. Provenance isn't just documentation; it's the foundation
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

> **Superseded as a backlog entry — scoped 2026-07-24.** mmmdata built this layer
> and it is migrating here; the execution plan, the settled design decisions and
> the data-dependent checks live in **`docs/qc-dashboard-migration.md`**. The
> three "open questions" below are answered there: norms are codified as a cited
> registry that mostly documents the *absence* of defensible cutoffs, flagging is
> relative-and-advisory with human sign-off required, and group-level comparison
> is the one question still genuinely open. Kept here for the framing.

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
- **Reading the convention is implemented (2026-07-21).** `dicom_inspect`'s
  `reproin_entities()` / `is_reproin_name()` parse the sequence name, and every
  consumer prefers an explicit entity to an inferred one: seqtype → datatype,
  `acq-` → fieldmap group, `run-` → fieldmap pairing (which survives an
  all-APs-then-all-PAs acquisition order that the acquisition-order heuristic
  cannot read), `task-`/`run-` → func entities, `anat-<label>` → BIDS suffix.
  **duckbrain still converts with dcm2bids** — the heudiconv ReproIn *heuristic*
  is not used, only the naming convention. Verified byte-identical on all 141
  real non-ReproIn sessions, so it is purely additive.
- **Open questions, now narrower:** the `ses-` entity is parsed but not acted on
  (session comes from the ingestion mapping) — worth wiring, or a mismatch worth
  warning about? And the social half is untouched: do we *recommend* the
  convention to LCNI users so exports arrive BIDS-ready? No ReproIn-named study
  exists locally to test against, so the implementation is unit-tested only.

## 9. External FreeSurfer (8.x) feeding fMRIPrep, instead of fMRIPrep's own recon

> **Taken 2026-08-19** — the stage is built (`core/freesurfer.py`, the
> `freesurfer` stage, `[freesurfer]` config; the `#7.7` ledger row is the
> implementation record, and the `#5b` forcing question below was answered by
> `effective_dependencies` returning a tuple). This section stays as the
> scoping record: the traps below are real and their closures cite this text.
> Live validation + the LCNI/nipreps validity ask are tracked in mmmdata-agents
> `docs/workbench/fs8-external-recon/`.

- **What:** run `recon-all` from FreeSurfer 8 as its own stage, then have fMRIPrep
  (25.x) import that reconstruction rather than building its own with the
  FreeSurfer bundled in its container. **Asked for by LCNI** (relayed 2026-07-24),
  whose pipeline already does this; the stated reason is that FS 8 is materially
  better than 7.
- **Role / placement:** a **producer upstream of fMRIPrep**, structurally the same
  shape as NORDIC — a second thing fMRIPrep waits for.
- **The plumbing is cheaper than it looks, and the facts below were checked on
  Talapas 2026-07-24 rather than assumed.**
  - **FreeSurfer 8.2.0 is already installed system-wide** (8.1.0 too, alongside
    6.0 through 7.4.1), and **there is nothing to build** — which means this one
    candidate stage sidesteps `#2`'s container-distribution blocker entirely.
    Precisely: it is *itself* an Apptainer image
    (`/packages/freesurfer/8.2.0/freesurfer-8.2.0.sif`) fronted by thin bash
    wrappers in `bin/` that `apptainer exec` into it, and that `bin/` is already on
    the default `PATH`. So `recon-all` is callable as a plain command from an
    sbatch running on the host — but note it is a container underneath, so it must
    never be invoked from *inside* another container. NORDIC is the precedent for
    a module-style `--array` sbatch stage; a FreeSurfer stage is close to a copy
    of it. The existing `fs_license` config key already covers it.
  - **fMRIPrep has the flags for it**, verified against the 24.1.1 image on disk:
    `--fs-subjects-dir PATH` ("Path to existing FreeSurfer subjects directory to
    reuse") and `--fs-no-resume` ("EXPERT: Import pre-computed FreeSurfer
    reconstruction without resuming. The user is responsible for ensuring that
    all necessary files are present").
  - **Better than either flag: write to the path fMRIPrep already looks in.** With
    the default `--output-layout bids`, `fs_subjects_dir` defaults to
    `<output_dir>/sourcedata/freesurfer` (`fmriprep/cli/parser.py`). So a stage
    that writes `<derivatives>/fmriprep/sourcedata/freesurfer/sub-XX/` is found
    with **no flag at all**, inside a directory the template already bind-mounts
    read-write. Checked against the surveyor: that subtree does not match
    `_fmriprep_status`'s globs (`sub-XX.html`, `sub-XX/**/anat/…`,
    `_has_match(root, "sub-XX")`), so pre-creating it does not flip the fMRIPrep
    cell off MISSING. 🔴 **But that directory is also the shared SUBJECTS_DIR every
    concurrent fMRIPrep job writes `fsaverage` into — see TODO `#21`.** Seeding it
    once before fan-out is a precondition of this item, not an optional extra: an
    external FreeSurfer stage adds a *second* writer to a directory that already
    races against itself.
  - **It can be driven from `extra_flags` today with zero code changes** — that
    field is deliberately unquoted and word-splits — **but see the two traps
    below.** Good as a one-off experiment, not as the shipped answer.
- 🔴 **Trap 1: `--fs-subjects-dir` without `--fs-no-resume` is the anat-reuse bug
  again.** If fMRIPrep judges the imported recon incomplete it *resumes* it using
  the FreeSurfer inside its own container — you get a partly-FS7 surface while
  believing you got FS8, and nothing says so. That is exactly the
  silently-degrading-option rule in `CLAUDE.md`. A real stage must gate on the
  recon actually being complete (`scripts/recon-all.done`) and raise otherwise —
  the same shape as `has_anat_derivatives`. `extra_flags` is the one field with no
  validation, which is why the stopgap should not become the feature.
- 🔴 **Trap 2: spell container-visible paths `/projects/…`, never
  `/gpfs/projects/…`.** Talapas's `apptainer.conf` default-binds `/projects`,
  `/tmp` and `/scratch`, and `/projects` is a symlink to `/gpfs/projects`.
  Verified: inside a container `/projects/hulacon/bhutch` resolves and
  `/gpfs/projects/hulacon/bhutch` does not exist. duckbrain's own paths are saved
  by the template's explicit `-B`; anything arriving through `extra_flags` gets no
  bind and only works by way of that default mount.
- **What it would actually cost inside duckbrain** (the stage model is well
  factored, so this is mostly a checklist): `STAGES` + one `_freesurfer_status`
  tracker + one arm in the expectations branch (`surveyor.py`); one
  `_build_freesurfer` + one `STAGE_SPECS` row + a `_STAGE_TOOL` entry, with
  `resolve_container` returning `None` as it does for NORDIC (`pipeline.py`); one
  sbatch template; a `[slurm.overrides]` block; one row in `consistency.py`'s
  provenance tuple. **The GUI needs nothing** — the cockpit iterates
  `STAGES`/`SLURM_STAGES` and renders a new column itself.
- 🔴 **The one structural stretch is the dependency graph.** `StageSpec.depends_on`
  is a single string, and fMRIPrep already needs `effective_depends_on` to special
  -case NORDIC. A FreeSurfer stage makes fMRIPrep depend on *two* producers, and
  stacking a second special case is how that function stops being readable. This
  is precisely the DAG that TODO `#5b` Case 3 parks — if this item is taken, it is
  the forcing function for that decision, and it should be made deliberately
  rather than by adding one more `elif`.
- **The real cost is outside duckbrain, and it is not ours to settle.** (a) An
  fMRIPrep 25 image has to be built — one more instance of `#2`'s container
  problem. (b) `recon-all` is hours per subject, a scheduling change, not just a
  stage. (c) **Whether nipreps considers fMRIPrep 25 valid against FS 8 outputs is
  an open question we cannot answer from here**: fMRIPrep ships its own FreeSurfer
  and runs some of its binaries against the imported surfaces, so "FS 8 is better"
  does not by itself establish that the hybrid is sound. Ask LCNI what they
  validated, and check the nipreps position, *before* building the stage — the
  plumbing is a week, the wrong answer here is a re-run of every subject.
