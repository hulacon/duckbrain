# duckbrain — TODO

Prioritized backlog. Newest priorities at the top. See `PLAN.md` for the
original design and `CLAUDE.md` for current status.

## ★ TOP PRIORITY — Provenance recording + consistency checker (2026-07-15)
Make duckbrain provenance-aware and have it auto-flag inconsistencies. Combines the
provenance/metadata backlog item (was `docs/pipeline-extras.md` #5) with a
consistency checker — provenance is the foundation, the checker is the payoff. Two
phases, in order. Motivated by the NORDIC `use_nordic` coexistence problem: flipping
the toggle on a project that already had raw-provenance fMRIPrep produces
self-contradictory metadata, and nothing catches it today.

**Phase A — record provenance (do first; cheap, high-leverage). BUILT 2026-07-16.**
- ✅ Durable submission log (`code/logs/submissions.tsv`) now records per run:
  `tool`, `tool_version`, `container`, and *input variant* (`raw` vs `nordic`),
  via `run_provenance(config, stage)` threaded through `advance_one`
  (`core/pipeline.py`). Every field degrades to `""` off the resolvable path so
  provenance can never sink a submission; `read_submissions` backfills the new
  columns for legacy logs.
- ✅ BIDS-Derivatives `GeneratedBy` written for duckbrain-produced derivatives:
  `write_dataset_description` versions duckbrain from the package + accepts a
  custom `generated_by`; new `write_derivative_description` emits
  `DatasetType=derivative` + `GeneratedBy` (duckbrain + tool, version + container
  Tag) + `SourceDatasets`/`DatasetLinks.raw`. NORDIC (a MATLAB job that writes no
  provenance of its own) is stamped at launch. This puts duckbrain-produced and
  tool-written derivatives in the **same on-disk format** the checker reads.
- **Design decision (2026-07-16):** on-disk provenance is the *authoritative*
  substrate; the submission log is an *overlay* that only adds what on-disk can't
  represent (per-subject mixing within one dataset-level `dataset_description`).
  This keeps duckbrain's "no state store, fold in external data" principle intact
  — externally-produced derivatives are first-class, never flagged for lacking a
  log row. Phase B's `check_consistency` must honor this ordering.
- Not yet done: emit `GeneratedBy` for the *ingested BIDS root* with the dcm2bids
  entry (converter provenance); Nipoppy bagel export tie-in.

**Phase B — consistency / mismatch checker. BUILT 2026-07-16.**
- ✅ `check_consistency(config)` in `core/consistency.py`; surfaces ⚠️ in the
  Project Status cockpit (panel after the Overview rollup, silent when clean).
  On-disk provenance is authoritative (`read_derivative_provenance` reads any
  derivative's `dataset_description.json` → `GeneratedBy`/`DatasetLinks`), the
  submission log is the overlay for cross-subject mixing. Each check is guarded so
  one blowing up can't sink the panel. Checks implemented: **config-vs-provenance**
  (fMRIPrep `DatasetLinks.raw` vs `use_nordic`), **container-drift** (config-resolved
  container vs the one that produced the derivative), **mixed-provenance** + **mixed-version**
  (latest-per-subject from the log), **staleness** (NORDIC newer than fMRIPrep,
  mtime), **presence** (fMRIPrep present but NORDIC input missing). 17 new tests
  (`test_consistency.py` + 2 AppTest panel tests); 168 total pass. Externally-run
  derivatives fold in — never flagged merely for lacking a log row.
- Remaining polish: per-subject config-vs-provenance (currently dataset-level);
  add mriqc `DatasetLinks` check if MRIQC starts recording one; wire the two
  "not yet done" Phase A items (ingested-root dcm2bids `GeneratedBy`, bagel tie-in).

**Phase B — VALIDATED LIVE 2026-07-16** against real Talapas data
(`divatten_gui_beta` + the real containers dir). 183 tests pass. Two bugs found
and fixed. The checker is now silent on that project, which is the *correct*
reading: it is clean single-provenance raw with a correctly-configured container.
- **Fixed: `version-drift` was a guaranteed false positive → replaced by
  `container-drift`.** It compared the config-pinned `*_version` (a container
  *tag*, used to build `<tool>-<tag>.simg`) against the tool's self-reported
  `GeneratedBy.Version`. Different namespaces. Proven on real data: the container
  `mriqc-24.0.2.simg` self-reports `MRIQC v24.1.0.dev0+gd5b13cb5.d20240826`, so the
  panel warned about a correctly-configured project. fMRIPrep escaped only by
  coincidence (`fmriprep-24.1.1.simg` reports `24.1.1`) — which is why the fixtures
  missed it: they used matched clean semver, encoding the bad assumption. The check
  now compares **container identity**: `_configured_container` (same resolution the
  builder uses) vs `_recorded_container` (on-disk `GeneratedBy[].Container.Tag`,
  authoritative; submission-log `container` column as fallback, since fMRIPrep/MRIQC
  overwrite the description and omit the container). Unknowable → silent. A bumped
  pin still fires, since it resolves a different container file. Version strings are
  informational only now.
- **Fixed: the log overlay counted runs that produced nothing.** The log records
  *submissions* (job tracking, incl. in-flight/cancelled/deleted); the filesystem
  records what was *produced*. For provenance the files arbitrate, so
  `_latest_per_subject` now drops rows with no output on disk
  (`_subjects_with_output`, via the surveyor). Real case: `divatten_gui_beta`'s only
  fMRIPrep log row is sub-008 — a NORDIC-chained run that was cancelled and its
  output removed — which would have claimed phantom provenance for a subject the
  derivative doesn't contain, once Phase A starts populating `input_variant`.
- **Still unvalidated on real data: `mixed-provenance` / `mixed-version`.** Phase A
  records provenance only for *future* runs, and all 35 rows in the real log are the
  legacy 5-column schema (`tool`/`tool_version`/`container`/`input_variant` all
  empty — backfill works, no crash). So every log-overlay check is inert on existing
  projects. The handoff's premise was stale: `divatten_gui_beta` is **not** mixed —
  `derivatives/fmriprep` holds only sub-04 + sub-015, both raw (the sub-008 NORDIC
  run was cancelled and removed). Validating mixing needs new post-Phase-A runs
  under two variants.
- Verified live-correct against real trees: `config-vs-provenance` (silent when
  config agrees, fires when `use_nordic` flipped in-memory), `staleness` (real
  NORDIC 7/15 genuinely newer than fMRIPrep 7/10), `presence` (true negative —
  sub-04/sub-015 both have NORDIC output), `_configured_container` (resolves the
  real `fmriprep-24.1.1.simg` / `mriqc-24.0.2.simg`).
- **Where container versions come from (checked 2026-07-16).** duckbrain derives the
  version *purely from the filename*: `get_container_path` builds `<tool>-<pin>.sif`
  / `.simg` from the `[containers]` pin and returns the first that exists. Nothing
  reads inside the image. But three independent version facts do exist in each
  container, and they disagree:
  - `apptainer inspect` labels — `...deffile.from` records the **Docker source tag**
    the image was built from (the real build provenance), plus `label-schema.version`
    and `vcs-ref`.
  - the tool's own `--version` at runtime.
  - what the tool writes into `GeneratedBy.Version`.
  For fMRIPrep all three agree (`24.1.1`). For MRIQC they don't:
  `deffile.from = nipreps/mriqc:24.0.2` and `vcs-ref = d5b13cb5`, but the tool
  self-reports `24.1.0.dev0+gd5b13cb5.d20240826` — the same git ref (`g` is git's
  prefix). So **`mriqc-24.0.2.simg` is correctly named**: it faithfully matches the
  Docker tag it was built from. The discrepancy is *upstream* — nipreps cut the
  `24.0.2` image from a commit whose own version metadata said `24.1.0.dev0`.
  (Corrects an earlier note in this file calling the container misnamed.) This
  vindicates comparing container identity: the tag is an accurate, stable
  identifier; the self-reported version is an upstream packaging artifact.
- **✅ BUILT 2026-07-16: build provenance as container identity.** New
  `core/containers.py` reads `deffile.from` out of the image (`inspect_labels`,
  `container_build_tag`, `container_uri`), cached per (path, mtime, size) so an
  in-place rebuild re-inspects. Measured on Talapas: **~20–50 ms** even for a 5 GB
  image (`apptainer inspect` reads the SIF header, not the payload); full
  `check_consistency` on the real project is ~130 ms, dominated by the surveyor's
  filesystem walk — fine for a page render.
  - `run_provenance` now records `container_source` (new submission-log column);
    `write_derivative_description` records it as BIDS `Container.URI` alongside the
    filename in `Container.Tag`. Verified live: `fmriprep-24.1.1.simg` →
    `nipreps/fmriprep:24.1.1`, `mriqc-24.0.2.simg` → `nipreps/mriqc:24.0.2`,
    `dcm2bids-3.2.0.sif` → `unfmontreal/dcm2bids:3.2.0`.
  - `container-drift` now **prefers build tags** over filenames when both sides know
    them, falling back to the filename otherwise (legacy rows) and staying silent
    when neither is knowable. This catches an image **rebuilt in place** (same
    filename, different image — invisible to a filename check) and stops it crying
    wolf over a container merely **renamed**. `resolve_container(config, stage)` in
    `core/pipeline.py` is now the single source of truth for "which image does config
    point at", shared by the builder, provenance recording, and the checker.

- **✅ FIXED 2026-07-16 (latent, pre-existing, would have bitten on the next launch):
  appending a provenance row to a legacy submission log corrupted it.** Phase A added
  columns but never migrated existing logs, and `divatten_gui_beta`'s real log still
  had the original **5-column** header (`timestamp/subject/session/stage/job_id`).
  Appending a wider row under it produces a ragged file that `pd.read_csv` refuses
  outright (`Expected 5 fields, saw 10`) — which would have taken the submission log,
  the Job Monitor, and *every* log-overlay consistency check down on the first launch
  (silently, for the checks: the per-check guard swallows it). It had never fired only
  because all 35 real rows predate Phase A, so nothing had appended yet.
  `_migrate_log_header` now rewrites the header before appending — atomically
  (`os.replace`), remapping rows by column *name* so no data shifts and new fields
  fill empty — and `read_submissions` falls back to a tolerant hand parse so an
  already-ragged log still reads. Validated on a copy of the real 35-row log.

Original Phase B design notes (kept for reference):
- Cross-references config expectation, on-disk provenance, and mtimes.
- **Provenance signal (found 2026-07-15):** fMRIPrep records its input in
  `derivatives/fmriprep/dataset_description.json` → `DatasetLinks.raw` (a NORDIC run
  points it at `derivatives/nordic/bids_format`; a raw run at the project root), but
  it's a *single dataset-level* field overwritten by whichever run finished last —
  so it can't represent mixed provenance. Hence Phase A: duckbrain's own per-run
  record is what catches mixing.
- **Checks to flag:**
  - **Config vs provenance** — `use_nordic` on but a derivative's `DatasetLinks.raw`
    isn't the nordic tree (or vice-versa).
  - **Mixed provenance** — some subjects launched raw, some NORDIC, into the same
    `derivatives/fmriprep/` (only duckbrain's own record catches this).
  - **Staleness** — a derivative older than the input it derives from (e.g. NORDIC
    re-run after fMRIPrep) → "stale, re-run" (mtime check).
  - **Presence consistency** — fMRIPrep exists but NORDIC missing in a NORDIC project.
- **Not viable:** detecting denoising from pixel data (fMRIPrep resamples to float32;
  only heuristic). Provenance metadata is the only reliable basis.

## 0. Pipeline cockpit — actionable Project Status board — BUILT 2026-07-10 (phases 1–4)
The Project Status matrix is actionable: each `(subject, session) × stage` cell
shows filesystem status fused with live SLURM state (🔵 running / ⏳ queued /
🔴 failed), and a dependency-gated "Launch a step" strip runs the next stage per
unit via `core.pipeline.advance_one`. A running/queued job is never offered for
re-run (no double-submit); ingestion is read-only here by design (Ben agreed).
Built in four committed phases — controller extraction (`core/pipeline.py`),
live-state fusion (`survey_live`/`stage_runnable`), cockpit UI, and polish
(guarded bulk "run whole stage", opt-in 30s auto-refresh, durable submission log
`code/logs/submissions.tsv`, deep-links to full pages). 126 tests pass. Full plan
+ status tracker: **`docs/pipeline-cockpit.md`**.
Dogfooded 2026-07-10: **functionally working** end-to-end. Remaining:
- **Usability pass (deferred until functionality stable).** Ben's dogfood read:
  the interface is "a little clunky." Do this once behavior is locked; collect
  specific pain points before starting. Likely targets: the stacked
  selectbox → params → button launch flow (lots of vertical scanning); single
  launch vs. bulk vs. matrix reading as three separate blocks rather than one
  board; per-cell action being indirect (choose from a dropdown vs. acting on the
  cell you're looking at). Candidate directions: clickable/actionable matrix
  cells, per-cell popover for the run controls, tighter layout density.
  - **Concrete confusion caught 2026-07-10:** the "Ready to run" dropdown only
    lists *currently-runnable* (unit, stage) pairs, so a stage that's supported
    but momentarily gated disappears entirely — e.g. with MRIQC running on every
    subject, the dropdown showed only fMRIPrep and it read as "you can't run
    MRIQC from here." The matrix still shows 🔵 running for it, but the *launch*
    control hides it. A per-cell action (button on the cell you see, disabled +
    labelled "running"/"needs converted") would remove this ambiguity.

## 1. Folder picker UX — reworked 2026-07-09, needs live look

`components.directory_picker` was rebuilt (still in-house: `streamlit-explorer`'s
`DirPicker` was evaluated — it IS lazy/HPC-safe, but v0.1.0 with 2 commits and
no `must_exist`/create-folder/default-path support; we adopted its good ideas
instead of the dependency). Still lazy, one `iterdir` per level. New model:

- Text field = **committed** selection; browsing lives in a collapsed
  "📂 Browse" expander whose body is an `st.fragment` — folder clicks rerun
  only the fragment, not the page (fixes sluggishness/scroll loss).
- Clickable **breadcrumb** jumps up any number of levels; single-column list of
  tertiary `📁` buttons in a scrollable container (lighter than the old grid).
- Explicit **"✓ Use this folder"** commits (via `on_click` callback +
  `st.rerun(scope="app")`); typing/pasting a path still commits directly.
- Requires Streamlit ≥ 1.48 (horizontal containers) — pyproject bumped.
- Covered by `tests/test_gui_components.py` (AppTest: navigate/commit/
  breadcrumb/filter/create/must_exist).

Remaining: eyeball it in a real browser session (AppTest can't judge feel);
file-mode for fs_license deliberately deferred — dirs-only is all we need for
now, fs_license stays a text field.

## 2. Onboarding for external users
- Dogfood the GUI new-user path fully, fix rough edges, then write a lean
  QUICKSTART (access, container acquisition, launch) + refresh the README.
- Add in-GUI guidance at friction points (Setup, ingestion mapping, conversion).
- Resolve the **launch/distribution story**: OOD app is currently bhutch's
  personal sandbox; a new user needs their own OOD sandbox or `launch.sh` +
  tunnel. A shared/RACS-published OOD app is the long-term answer.

## 3. fMRIPrep step — run live (last unrun core stage)
- Command validated against mmmdata's `run_fmriprep.py` (every substantive flag
  matches); container `fmriprep-24.1.1.simg` present; FS license now in user
  config (`/home/bhutch/licenses/fs_license.txt`). Blocker is just the live run:
  submit one DIVATTEN subject (single-session, anat+func) via SLURM and monitor
  via the Jobs page. Runs via SLURM, not inline.

## 4. Naming / discovery robustness (from the LCNI survey)
- ✅ **`G##_S##` session style recognized (2026-07-16).** `_parse_session_folder`
  now reads the trailing `S##` token as the session when the preceding token is a
  `G##` subject (`_GS_SUBJECT_RE`/`_GS_SESSION_RE` in `core/ingestion.py`).
  Requiring the paired G-token keeps a bare `s01`/`S01` subject id from being
  misread as a session — the same safeguard the "ses"-prefix rule provides.
- ✅ **Phantom/test-folder filtering (2026-07-16).** `discover_sessions` skips
  non-subject folders via `_is_excluded_folder`: names containing whitespace, or a
  whole-token marker (`test`/`phantom`/`demo`/`qa`) paired with a *non-numeric*
  identity. A study that legitimately uses a marker as its project prefix
  (`TEST_01`) resolves to a numeric subject and is kept; `include_excluded=True`
  opts out of filtering. Whole-token match avoids substring false-positives
  ("Detest"). 5 new tests in `test_ingestion.py`.
- ✅ **Multiple fieldmap pairs no longer collapse (2026-07-16).** `detect_fieldmaps`
  now groups *unnamed* AP/PA fieldmaps by acquisition order (`_pair_by_acquisition`),
  so a reacquired plain pair (e.g. topup before/after the functionals) yields two
  distinct pairs instead of a spurious "Duplicate AP". `generate_config` gives each
  pair a distinguishing BIDS entity so their `dir-<X>_epi` files don't collide —
  `run-N` for order-numbered pairs, `acq-<name>` for named pairs (which also fixes
  the latent encoding/retrieval `dir-AP` collision) — placed in BIDS entity order
  and folded into the dcm2bids `id`. Lone-pair output is unchanged. New field
  `FieldmapDetection.group_entities`; 6 new tests. **Note:** with ≥2 pairs, bold→fmap
  linking still defaults every task to the first group (`_assign_fmap_group` has no
  temporal-proximity logic) — fine for conversion, a candidate refinement later.
- **DEFERRED (needs cluster/real data): mmmdata-style nested multi-session org.**
  `func_session_*/anat_session/` under the source breaks `discover_sessions`, which
  expects session folders directly under the source dir. The exact nesting (per
  subject? how func/anat sessions fold into one BIDS session?) isn't documented in
  this repo — the mmmdata reference lives on Talapas. Implementing discovery against
  a guessed structure is unverifiable offline and risks the working LCNI path; do
  this with a real example dir or on-cluster.

## 5. Config / mapping niceties
- Project-wide (vs per-subject/session) task/run mapping option: define once,
  inherit across subjects; per-subject override for exceptions.
- MRIQC now runnable — `mriqc-24.0.2.simg` present, user config aligned to
  `mriqc_version = "24.0.2"`. Still needs a live end-to-end run + QC-dashboard
  validation.

## 5c. NORDIC versioning + distribution — toolbox axis BUILT 2026-07-16
NORDIC *was* the only stage with zero version provenance (the container work
routes around it — it has no container). Now `run_provenance(cfg, "nordic")`
returns a full record, sourced from the toolbox's git checkout:
```
{'tool': 'nordic', 'tool_version': 'v1.0.2-24-g0861968', 'container': '',
 'container_source': 'SteenMoeller/NORDIC_Raw@0861968', 'input_variant': 'raw'}
```
- **`core/toolbox.py`** — `describe` (`git describe --tags --always --dirty`),
  `source_ref` (`Owner/Repo@sha`, the git analogue of a container's `deffile.from`),
  `code_url` (browsable commit URL; declines to guess for non-GitHub hosts).
  Uncached on purpose: these are fast local git reads (~60 ms for all three on the
  real toolbox) and a cache could serve a stale `-dirty` after an edit.
- **On-disk stamp** — NORDIC's `GeneratedBy` now carries
  `{"Name": "nordic", "Version": "v1.0.2-24-g0861968", "CodeURL": ".../tree/<sha>"}`
  (new `code_url=` on `write_derivative_description`); `container_source` records
  `Owner/Repo@sha` in the log.
- **`toolbox-drift` check** (`core/consistency.py`) — NORDIC's analogue of
  `container-drift`, deliberately a *separate* check since its artifact is a
  checkout, not an image. Comparing *versions* is sound here (unlike the container
  case): both sides are `git describe` of the same repo — one namespace. Reads
  on-disk first, log overlay as fallback; unknowable → silent. Validated live
  against the real toolbox (fires on a moved checkout, silent when unchanged).
  `check_consistency` on the real project: 0 issues, ~186 ms.
- **Caught during the build:** `Path("")` is `.`, so an unset `nordic_toolbox_dir`
  described the **current directory** — recording *duckbrain's own* git version
  (`a0b0763-dirty`) as the toolbox's. Silently wrong provenance is worse than
  none; `_is_checkout` now guards the empty path. Regression-tested.
- 222 tests pass (was 200): `test_toolbox.py` (13) + toolbox-drift/provenance tests.

**MATLAB runtime axis — BUILT 2026-07-16 (option 2: rename, no new column).**
Ben's call: fewer columns preferred. `container`/`container_source` → **`runtime`/
`code_source`**, which spans both kinds of stage with *zero* new columns — NORDIC's
runtime slot was empty precisely because it runs no image, so MATLAB fills existing
space, and the `container_source` misnomer retires at the same time:

| stage | `runtime` (what executed it) | `code_source` (where the code came from) |
|---|---|---|
| fMRIPrep | `fmriprep-24.1.1.simg` | `nipreps/fmriprep:24.1.1` |
| MRIQC | `mriqc-24.0.2.simg` | `nipreps/mriqc:24.0.2` |
| dcm2bids | `dcm2bids-3.2.0.sif` | `unfmontreal/dcm2bids:3.2.0` |
| NORDIC | `matlab/R2024a` | `SteenMoeller/NORDIC_Raw@0861968` |

For a container the image *is* the runtime and its tag names the code inside; for
NORDIC they are two genuinely independent artifacts. Verified live across all four
stages (table above is real output).
- **The cost, and it was real:** `_migrate_log_header` maps rows by *name* and
  rewrites the file in place, so a rename would have **silently and permanently
  dropped** legacy `container`/`container_source` values. `_SUBMISSION_RENAMES`
  now carries them across; `read_submissions` renames on read too (reading must
  never require a write); and the migration compares the *raw* header, since
  `_parse_log_rows` renames on the way in and an old-named log would otherwise
  look current and keep its stale header forever. All three are regression-tested.
- **On-disk:** BIDS has no runtime field, and MATLAB isn't a container — so it
  gets its own `GeneratedBy` entry (`{"Name": "matlab", "Version": "R2024a"}`),
  which is spec-legal since `GeneratedBy` is a list. NORDIC's stamp is now
  `[duckbrain, nordic, matlab]`.
- **New `matlab-drift` check** — NORDIC's second axis, independent of
  `toolbox-drift`: a `matlab_module` bump with an unchanged toolbox fires one and
  not the other.
- **`_check_mixed_provenance` generalized** beyond fMRIPrep: now also covers
  NORDIC (mixed toolbox versions across subjects in one `derivatives/nordic`) and
  adds **`mixed-runtime`**. Input-variant mixing stays fMRIPrep-only — NORDIC
  always consumes raw. Blank values count as *unknown*, not a distinct value, so a
  derivative half of whose runs predate a field doesn't read as mixed.
- 236 tests pass. `check_consistency` on the real project: 0 issues, ~213 ms.

**duckbrain's own version — deliberately flagged to a LOWER standard (2026-07-16).**
Ben's question: should duckbrain mismatches flag like fMRIPrep/NORDIC, given rapid
development would mean constant mismatches — but serious differences matter for
data/metadata management? Answer: **no, and not because of noise — because it's a
different kind of fact.** A tool's version *is* the computation; duckbrain's is the
recipe-writer. New `duckbrain-drift` check, scoped three ways:
- **Only where duckbrain authors the recipe** (`_DUCKBRAIN_RECIPE_STAGES`):
  `converted` (duckbrain generates the dcm2bids config — which series become
  T1w/bold, task names, fieldmap pairing) and `nordic` (duckbrain supplies the
  MATLAB entrypoint + sbatch recipe). **Not** fMRIPrep/MRIQC, where duckbrain only
  passes flags to a container — v0.1.0 and v0.9.0 with identical flags give
  identical output, so flagging would be noise with no signal under it.
  This repo proves the distinction: `eeede67` changed emitted BIDS filenames
  (collapsed `dir-AP` → `dir-AP_run-1/run-2`), and the NORDIC m-file `DIROUT` fix
  was the difference between *NORDIC never ran* and *NORDIC ran*.
- **Only on a release-line change** (`_release_line`): `v0.1.0`,
  `v0.1.0-47-gabc1234` and `v0.1.9` all reduce to `0.1`, so iteration between
  releases is invisible. Pre-1.0 the *minor* carries the breaking signal
  (`0.1`→`0.2`), major once ≥1.0. Unparseable (bare sha, untagged) → silent.
- **At `note` severity, not `warning`** — which finally wires up the dormant
  `ConsistencyIssue.severity` field. The cockpit now renders notes via `st.info`
  and warnings via `st.warning`, so a provenance note can't dilute a real
  contradiction.
Dataset-level by nature (duckbrain stamps the dataset root, not each subject), so
mixed duckbrain versions *within* one dataset are invisible. Accepted deliberately
rather than add a log column for a question metadata management doesn't ask
("which duckbrain converted sub-07"). **No new column** — both sides were already
on disk.
Validated live: `divatten_gui_beta`'s BIDS root is stamped `0.1.0` (the old static
`__version__`, no `v` prefix) while duckbrain now describes as
`v0.1.0-1-gd785993-dirty` — both reduce to line `0.1`, so it stays silent. That mix
is what real projects will hold, and `_release_line` handles pre- and post-describe
stamps alike. `check_consistency` ~350 ms (a `git describe` per render; fine).

**Per-file provenance in NORDIC sidecars — BUILT 2026-07-16.** Closes the
dataset-level gap accepted above. `write_nordic_sidecars` (`core/nordic.py`) writes
a BIDS-derivatives sidecar per denoised BOLD at launch — the same point, and for
the same reason, duckbrain stamps `dataset_description.json`.
- **Why per-file at all:** `dataset_description.json` is dataset-level (can't
  express per-subject mixing) and `submissions.tsv` doesn't travel with the data.
  Only sidecars keep a *copied or archived* NORDIC output self-describing.
- **It was also a plain BIDS gap:** NORDIC's MATLAB job emits bare NIfTIs —
  `derivatives/nordic/sub-04/func` held **13 `.nii.gz` and 0 `.json`**. A
  derivative BOLD should carry a sidecar with `Sources` regardless of provenance.
- **Contents:** the raw sidecar copied wholesale (derivatives don't inherit from
  raw, and denoising changes voxels not acquisition — `RepetitionTime`, `TaskName`,
  even the raw's own `Dcm2bidsVersion` lineage all stay true), plus `Sources`
  (`bids:raw:<relpath>`, resolvable via our `DatasetLinks.raw`) and a namespaced
  `Duckbrain` object (Version/Tool/ToolVersion/Runtime/CodeSource).
- **⚠️ Do NOT use sidecar `GeneratedBy`.** [BEP028](https://github.com/bids-standard/BEP028_BIDSprov)
  (BIDS-Prov, still in development) already claims sidecar `GeneratedBy` and
  `SidecarGeneratedBy` for URI *references* into a prov record
  (`"bids::prov#conversion-00f3a18f"`) — the **opposite** of what the same key means
  in `dataset_description.json`, where an inline object is correct. Ours is
  namespaced under `Duckbrain` to avoid squatting; keeping it one object makes the
  eventual BEP028 migration a swap, not a rewrite. Precedent for the whole idea is
  already on disk: dcm2bids writes `Dcm2bidsVersion`/`ConversionSoftware` into every
  raw sidecar, and fMRIPrep writes `Sources`.
- **Skip-if-present, mirroring the sbatch.** Only BOLDs whose output doesn't exist
  get a sidecar — the sbatch skips already-denoised runs, so restamping them would
  claim the *current* toolbox produced files an older one made.
- **Checked, not assumed:** rewriting sidecars can't disturb our own checks —
  `_check_staleness` stats only `.nii.gz`, and the surveyor globs `.json` for
  presence, not mtime. `_nordic_status` grades on `.nii.gz`, so a sidecar written
  at launch can't cause a false-green. `build_nordic_bids_input` copies func
  sidecars from *raw*, so the validated fMRIPrep chaining path is untouched.
- Validated live: on the real project every sub-04 output exists → **0 written**
  (skip rule holds, nothing mutated); against a temp derivatives dir off the real
  raw BIDS → 13 sidecars, 71 keys each (real dcm2bids sidecar + `Sources` +
  `Duckbrain`), no `GeneratedBy`. 253 tests pass.

**Known remaining wrinkle (minor):** `tool_version` is itself now overloaded — it
holds a container *tag* for container stages (`24.1.1`) but a `git describe` for
NORDIC (`v1.0.2-24-g0861968`). Both are "the version we pinned/ran", so it's
defensible, but it is the same class of misnomer the rename just fixed. Not worth
another migration on its own; fold in if the columns are ever touched again.

**Background — why the SHA is the only honest version.**
- Upstream's own version markers are **unusable**: the in-file
  `% VERSION 4/22/2021` comment is 4 years stale, and the newest release tag
  `v1.1` is from 2021-07-29 while HEAD is 24 commits past it (2025-05-28).
  Upstream commits to `main` without cutting releases — the SHA is the only
  honest identity.

**Fork / rewrite: decided against (2026-07-16).**
- **Forking solves nothing.** Upstream is dormant — commits/year: 28 (2021), 6,
  3, 1, 1. There is no churn to insulate from, and we have **never needed to
  patch upstream**: all three NORDIC bugs fixed on 2026-07-15 were in duckbrain's
  own wrapper, not `NIFTI_NORDIC.m`.
- **⚠️ Forking may not even be permitted.** `LICENCE.md`: © 2021 Regents of the
  University of Minnesota, covered by **US patent 10,768,260**, licensed "solely
  for educational and research purposes by non-profit institutions and US
  government agencies only", and **"may not be sold or redistributed without
  prior approval"** — while "one may make copies of the software for their use".
  So a public fork is a redistribution, and duckbrain **cannot vendor the source**.
  Confirm with UMN (`umotc@umn.edu`) before acting on this reading.
- **Python rewrite: cheap to write, expensive to own.** Only 2363 LOC and the math
  is unexotic (`svd` ×3, fft/ifft/fftshift; no `parfor`, no `gpuArray`, no
  license-gated toolboxes; `nibabel` replaces `niftiread`/`niftiwrite`). The cost
  is *validating it forever*: NORDIC's value is being the published, cited
  implementation, and the subtle parts (g-factor/noise-level estimation, threshold
  selection, patch geometry) are exactly where a reimplementation silently
  diverges — a scientific liability, not a fixable bug. The patent covers the
  *method*, so a rewrite doesn't route around the licence either.
- **A Python port already exists** — [patch-denoise](https://github.com/paquiteau/patch-denoising)
  (MIT, PyPI, ISBI 2023 paper; NORDIC + MP-PCA + optimal thresholding) — but makes
  **no published equivalence claim vs. the MATLAB reference**, is single-maintainer,
  and last released 2023-09. Adopting it *inherits* the validation burden from
  someone else's reimplementation. Interesting later as an **optional second engine**
  for comparison, not a replacement.

**Distribution to users beyond the hulacon PIRG (ties to TODO #2).**
- **Hard blocker:** the PIRG root is `drwxrws---` (0770, no world access), so
  non-hulacon users cannot traverse into the shared toolbox at all. They cannot
  share our copy, and permissions-hardening is a hulacon-only answer.
- Combined with the no-redistribution licence, **each user must obtain their own
  copy from upstream**, with `nordic_toolbox_dir` pointing at it — which is already
  the config shape, so we're accidentally right.
- **Consequence: every user drifts to a different SHA.** Version provenance stops
  being hygiene and becomes the only way to know what ran. This is the strongest
  argument for building the design above.
- **Suggested affordance:** the Setup page already validates containers exist; give
  NORDIC the same treatment ("toolbox not found → fetch pinned version"), cloning
  upstream at a duckbrain-pinned SHA into the user's own space. Not redistribution
  (the user pulls from UMN), and it gives version uniformity across users.
- **Same shape as containers**, which retroactively justifies `container_source`:
  across a heterogeneous user base filenames are *local convention* (two labs can
  name one image differently, or different images identically), whereas
  `nipreps/mriqc:24.0.2` is simultaneously what you tell a user to pull and what
  makes their provenance comparable to ours. Filename comparison would have quietly
  produced nonsense the moment duckbrain left this PIRG.

## 5b. NORDIC — producer + fMRIPrep chaining (Case 1) VALIDATED LIVE 2026-07-15
`nordic` is a surveyor stage (STAGES column, live-state overlay, cockpit
launch + bulk) — completion = denoised BOLDs under
`derivatives/nordic/sub-XX[/ses-YY]/func/*_bold.nii.gz`. The **producer is now
validated end-to-end** on real data: sub-04 in `divatten_gui_beta` (sessionless,
13 BOLD runs) denoised clean via the GUI/`advance_one` path (array job 45428802,
all tasks COMPLETED, ~2–3 min & ~5.8 GB peak each), every output dim matching its
raw input, and the surveyor flips the cell 🟢. Getting there fixed three latent
bugs (all in this commit):
- **m-file output path** — `scripts/nordic_denoise.m` set `ARG.DIROUT = out_dir`
  *and* `fn_out = fullfile(out_dir, fname)`; `NIFTI_NORDIC` concatenates
  `DIROUT + fn_out`, so it would have written `out_dir/out_dir/…`. Aligned to
  mmmdata's validated form (`ARG.DIROUT = [out_dir '/']`, `fn_out = basename`).
- **template render** — `nordic_denoise.sbatch.j2` used a bash array-length
  expansion whose `{#` collided with Jinja's comment-open, so the template never
  rendered. Replaced with a `wc -l` count. (Proof it had never been run.)
- **sessionless paths** — `nordic_output_dir` / `build_nordic_bids_input` (and
  the latter's default `bids_input` location) hardcoded `ses-{session}`; now
  derived from `sub_ses_relpath`, so sessionless data writes `sub-XX/func` not
  `ses-/func`.
- **Config (done):** `nordic_toolbox_dir =
  /gpfs/projects/hulacon/shared/mmmdata/code/NORDIC_Raw` in user config; MATLAB
  module default `matlab/R2024a` is the cluster default — no change needed.
- **Chaining — Case 1 BUILT + VALIDATED LIVE 2026-07-15.** fMRIPrep now reads the
  NORDIC-denoised input when a project sets `[nordic] use_nordic = true`. Principle
  held: **NORDIC stays a pure independent producer** and **fMRIPrep's input source
  is the only variable.** Implementation (`core/pipeline.py`, `core/nordic.py`):
  `effective_depends_on()` swings fMRIPrep's dependency `converted → nordic` when
  the toggle is on; `stage_runnable(row, stage, config)` gates the cockpit
  accordingly; `_build_fmriprep()` assembles the unit's `bids_format` tree and
  points fMRIPrep at `derivatives/nordic/bids_format` (raises if no denoised BOLDs
  yet). `build_nordic_bids_input()` builds a **self-contained** tree (folder
  renamed `bids_input → bids_format`): denoised BOLDs hardlinked, anat included
  (nifti hardlinked, sidecars copied), fmap + func sidecars copied, dataset root
  files copied once. Same `fmriprep.sbatch.j2` — no `fmriprep_nordic.sbatch.j2`
  needed. **Validated:** sub-008 in `divatten_gui_beta` — tree assembled (13
  hardlinked denoised BOLDs + anat + fmap + `dataset_description.json`), cockpit
  gated fMRIPrep on `nordic`, and the live run (job 45452962) indexed the tree and
  built the full 2426-node anat+func workflow ("fMRIPrep started!", no BIDS
  errors) — confirming fMRIPrep consumes the denoised input. 141 tests pass.
  **Coexistence caveat:** flipping `use_nordic` on makes the *whole* project
  NORDIC; sub-04/sub-015 keep their old non-NORDIC `derivatives/fmriprep` (mixed
  provenance — a dogfooding artifact, not a real project). Remaining tiers:
  2. **Case 2 — same-project comparison (opt-in, defer until actually needed).**
     Needs two fMRIPrep results per subject, which breaks one-cell-per-stage. Do
     NOT branch the pipeline; instead use **distinct derivative names**
     (`derivatives/fmriprep/` vs `derivatives/fmriprep-nordic/`) — parameterize
     the hardcoded derivative dir in `_fmriprep_status` (and the builder) so a
     variant shows up as an **additive extra column**, only when the project opts
     in. Matches BIDS-derivatives provenance norms. **Zero-code fallback to try
     first:** two project dirs over the same BIDS, one with `use_nordic` on.
  3. **Full named-pipeline DAG — PARKED.** Only if branch count grows (multiple
     denoisers / fMRIPrep configs routinely). Cases 1+2 don't need it; this is
     the complexity to avoid for now.
- Optional: NORDIC column is always-on; for non-NORDIC projects it's a column of
  ⚪. Fine for LCNI/mmmdata (NORDIC-common), revisit if noisy elsewhere.

## 6. Per-subject pipeline status matrix (state awareness) — IMPLEMENTED 2026-07-10
**Done:** `core/surveyor.py` (`survey_project` → matrix, `summarize`) grades each
`(subject, session)` × stage (ingested/converted/fmriprep/mriqc) as
complete/partial/missing by **expected-output globs**, not folder presence —
borrowing Nipoppy's tracker idea but for duckbrain's flat layout, with the
sessionless-glob and layout-shim pain points designed out. Surfaced in the new
`gui/pages/0_Project_Status.py` dashboard (color matrix + rollup). Validated on
`divatten_gui_beta` (correctly flags mid-run fMRIPrep as partial). 19 new tests.
Remaining ideas: durable submission log (Job Monitor is still ephemeral); a
`nipoppy`-compatible `processing_status.tsv` export; port `surveyor.py` back to
mmmdata. Original rationale below.

duckbrain keeps **no state store** — every page re-derives "what exists" live
from the filesystem via BIDS naming (ingestion reads `sourcedata/sub-XX/dicom`,
preprocessing globs `bids_dir/sub-*`, QC reads `derivatives/{fmriprep,mriqc}`).
This is nicely tool-agnostic (external heudiconv/fMRIPrep output is picked up so
long as it lands in the standard paths), but it has real gaps:
- **Presence ≠ completion.** A crashed/half-finished fMRIPrep leaves a
  `derivatives/fmriprep/sub-XX` dir that looks identical to a complete one.
  Nothing checks a success/completion marker.
- **No done-vs-todo view.** Pages list all candidates; they don't tell you which
  subjects still need conversion / fMRIPrep / MRIQC. User has to eyeball it.
- **Job Monitor is ephemeral** — only what SLURM still remembers, no durable
  record of what duckbrain submitted.

Proposal: a dashboard status matrix (rows = subjects, cols = ingested /
converted / fMRIPrep / MRIQC) computed from **completion markers**, not mere
folder presence — e.g. dcm2bids success, fMRIPrep's `.html` report or
`dataset_description.json` in the derivative, MRIQC group TSV. Distinguish
complete / partial-or-failed / missing. This is the concrete form of the
long-mooted "pipeline DAG/dependency tracking" idea.

## 7. Pipeline extras — candidate stages & integrations (backlog)
A set of odds-and-ends a typical pipeline involves, several with unknown fMRIPrep
interactions / pipeline placement. Captured 2026-07-15 with the NORDIC-work lens
(producer vs consumer vs orthogonal; placement vs fMRIPrep's resampling; does
fMRIPrep already do it / fight it). Full annotated backlog — candidate tools, ties
to existing duckbrain/mmmdata work, and open questions per item — in
**`docs/pipeline-extras.md`**. Each is its own focused effort; none started.
1. **DTI/DWI preprocessing** — orthogonal modality branch (candidate: QSIPrep).
2. **De-identification for sharing** (decided) — image defacing **+** metadata/header
   PII scrubbing (DICOM headers *and* BIDS sidecars), "derive-then-torch" policy
   (age ok, name/DOB auto-removed). Candidate combined tool: `bidsonym`. Precomputed
   -mask fast-track (2b) is a *different* feature, deferred.
3. **Eye-movement reconstruction from BOLD** (decided: DeepMReye-style) — orthogonal
   branch fMRIPrep *fights* (brain extraction removes the eyes); opt-in "preserve
   eyes" path off raw/minimal data. Low demand, unique requirements.
4. **Physiological data as BOLD regressors** — downstream consumer (PhysIO/TAPAS
   → confounds); fMRIPrep ingests physio but doesn't compute RETROICOR.
5. **Version/provenance documentation & metadata** — **promoted to the ★ TOP
   PRIORITY item** (paired with the consistency checker); see top of file.
6. **Scanning-notes/metadata integration** — input-shaping producer (exclude bad
   runs via bids-filter/scans.tsv); reuse mmmdata build_manifest/sessions.tsv.
7. **QC norms & best-practice dashboard** — consumer of fMRIPrep+MRIQC (mmmdata
   open item); layer norms on the existing surveyor/QC pages.
8. **ReproIn evaluation** — upstream naming convention (ties to #4); adopt
   internally vs. recommend to LCNI users.

## 8. Visual identity & branding (someday — polish, low priority)
duckbrain will eventually want a real visual identity, not just functional UI.
Gated behind functionality + onboarding (#2); capture now so it isn't forgotten.
- **Logo / wordmark** — lean into the "duck brain" concept; needs a mark that
  works small (favicon / browser tab) and as a header banner.
- **GUI theming** — a considered Streamlit theme (palette, accent, fonts) instead
  of defaults; consistent iconography across pages.
- **Favicon** for the GUI browser tab + the OnDemand app tile.
- **README banner / docs polish** — a header image and consistent styling once the
  QUICKSTART/README refresh (#2) happens.
- Design flourishes generally (empty-state art, page headers) — tasteful, not
  over-designed; do after the product behavior is locked.
