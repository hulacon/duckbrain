# Duckbrain Initial Code Review

**Repository:** [`hulacon/duckbrain`](https://github.com/hulacon/duckbrain)  
**Snapshot reviewed:** [`c732e9e767467b9ae9fe58a6a272e16dd6ca3af6`](https://github.com/hulacon/duckbrain/commit/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6)  
**Review date:** 2026-07-22  
**Review type:** Read-only baseline audit  
**Primary focus:** Correctness, GUI/backend consistency, filesystem safety, implementation efficiency, redundancy, SLURM orchestration, and test-suite effectiveness

## Executive summary

Duckbrain has a strong core for a compact application. The repository is organized around domain-focused modules, several nontrivial conversion and consistency components have excellent tests, and the code contains unusually useful comments explaining historical failure modes and design intent. The complete test suite passed during this review.

The most significant risks occur at boundaries between otherwise well-tested components:

- GUI forms and layered TOML configuration;
- filesystem state and the status shown in the cockpit;
- source-session mappings and ingestion results;
- per-session GUI actions and the shared pipeline controller;
- multi-session BIDS organization and NORDIC's assembled input dataset;
- SLURM history and the representation of the latest attempt.

Four findings merit priority-one attention:

1. Setup saves can erase nested SLURM settings while reporting success.
2. Pipeline stages can be shown as complete when only one of several expected outputs exists.
3. Ingestion collisions can be reported as successful even when the selected source was not ingested.
4. NORDIC input assembly can be order-dependent when anatomy and functional data occur in different sessions, and its persistent staging tree can retain stale data.

The first three are directly confirmed by the implementation. The fourth follows from the code path and should be validated with a representative multi-session dataset because the real study filesystem was not available.

The automated test baseline is encouraging: **431 tests passed** in approximately 41 seconds. Measured coverage was **58% overall**, with high coverage in several core modules but little or no coverage in the DICOM sorter, QC persistence, SLURM submission, and some integration-heavy paths. No checked-in continuous-integration workflow or lint/type-check enforcement was found.

## Scope and method

The review covered:

- Python source under `src/duckbrain`;
- Streamlit pages and shared GUI components;
- BIDS conversion, ingestion, surveying, consistency, QC, and NORDIC logic;
- SLURM monitoring, submission, and sbatch templates;
- project and user configuration loading/saving;
- the test suite and development configuration;
- repository documentation and the open audit items in `TODO.md`.

The following checks were run against a disposable checkout of the reviewed commit:

```text
python -m compileall ...          passed
pytest tests -q --cov=duckbrain  431 passed
```

The effective test command was equivalent to:

```bash
PYTHONPATH=src python -m pytest tests -q \
  --cov=duckbrain --cov-report=term-missing:skip-covered
```

No repository source or configuration was edited, no commits were created, and nothing was pushed to GitHub.

### Important limitations

This review did not have access to:

- the production DICOM and BIDS filesystems;
- live Talapas/SLURM commands or job accounting;
- the installed neuroimaging containers and MATLAB/NORDIC runtime;
- realistic large job logs;
- a live end-to-end Streamlit session against production data.

Findings that depend on those systems are identified as data-dependent. They are based on reachable code paths rather than a claim that the failure has already occurred in production.

## Severity model

- **P1 — High:** Can lose or misrepresent data/configuration, permit an invalid downstream action, or make results depend on execution order.
- **P2 — Medium:** Material correctness, traceability, safety, or performance defect with a narrower trigger or recoverable impact.
- **P3 — Low:** Robustness, maintainability, or reproducibility weakness unlikely to corrupt results by itself.

## Detailed findings

### DB-001 — P1 — Setup saves can delete nested SLURM configuration

**Status:** Confirmed

The section-scoped save helper performs a shallow top-level replacement:

```python
stored = _load_toml(path)
stored.update(data)
```

This preserves top-level sections absent from the new data, but a supplied section replaces its stored counterpart in full. Both Setup save buttons provide partial `slurm` dictionaries:

- Project settings write `account`, `partition`, `partition_long`, and `time`.
- Shared resources write only `email`.

As a result:

- saving project settings can delete project-specific `[slurm.overrides.*]` values and other hand-maintained SLURM keys;
- saving shared resources can delete user-level defaults such as `mail_type`, account/partition values, or user-level overrides.

This conflicts with the helper's own comment, which says `[slurm.overrides.*]` and hand-written keys are preserved. The recent TODO #17.1 change fixed whole-file loss across unrelated top-level sections, but it did not preserve nested values inside a section the GUI partially owns.

**Evidence**

- [`config.py` lines 226–247](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/config.py#L226-L247)
- [`1_Project_Setup.py` lines 195–206](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/1_Project_Setup.py#L195-L206)
- [`1_Project_Setup.py` lines 252–266](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/1_Project_Setup.py#L252-L266)

**Example failure scenario**

1. A project has a hand-tuned `[slurm.overrides.fmriprep]` section.
2. A user changes the project's display name or DICOM source in Setup.
3. Setup saves a newly constructed partial `slurm` dictionary.
4. The stored `slurm` section is replaced, deleting the fMRIPrep override.
5. Later submissions silently use different resources.

**Recommended direction**

Avoid a generic deep merge because the GUI deliberately needs to remove fields that the user clears. Instead, give each form explicit field ownership:

- load the stored section;
- update or remove only the keys represented by that form;
- retain unowned keys and nested tables;
- write the resulting complete section atomically.

Dedicated helpers such as `save_project_setup_fields()` and `save_shared_resource_fields()` would make ownership clearer than another generic dictionary merge.

**Regression tests**

- Preserve `[slurm.overrides.fmriprep]` after saving project Setup fields.
- Preserve `mail_type`, account, and overrides after saving only the shared email field.
- Verify that clearing a GUI-owned field still removes that field.
- Verify that unrelated hand-written nested keys survive.

---

### DB-002 — P1 — Stage completion is often based on any output, not all expected outputs

**Status:** Confirmed

The Project Status page advertises completion based on expected outputs rather than directory presence. The surveyor improves on directory-only detection, but most checks still ask whether at least one broadly matching artifact exists:

- Conversion becomes complete when any NIfTI exists under the unit.
- fMRIPrep requires a subject report, any matching preprocessed T1w, and—if functional input exists—any matching preprocessed BOLD.
- MRIQC requires any T1w IQM and any BOLD IQM when functional data exists.
- NORDIC uses one wildcard requirement, which passes when any denoised BOLD exists.

For a session with multiple runs, one successful run and several failed or absent runs can therefore produce a green completion state. This is especially risky because the pipeline controller uses stage status to determine whether downstream work is runnable.

**Evidence**

- [`surveyor.py` lines 145–220](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/surveyor.py#L145-L220)
- [`0_Project_Status.py` lines 26–28](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/0_Project_Status.py#L26-L28)

**Impact**

- Partial conversion may unlock preprocessing.
- Missing fMRIPrep or MRIQC runs can be hidden by one successful output.
- One completed NORDIC array task can make the whole unit appear complete.
- Operators may reasonably interpret a green cell as evidence that every expected acquisition was processed.

**Recommended direction**

Create an explicit expected-output manifest per subject/session and stage:

- Conversion: derive expected output identities from the reviewed conversion plan.
- NORDIC: enumerate all input BOLD runs and map each to a denoised output.
- fMRIPrep: enumerate BOLD inputs selected by the session filter and the expected preprocessed outputs, plus required anatomical products.
- MRIQC: enumerate every input image that should yield an IQM JSON.

Define status consistently:

- `missing`: none of the expected outputs exist;
- `partial`: a proper subset exists, or artifacts indicate an interrupted run;
- `complete`: every expected output exists and passes minimal integrity checks such as nonzero size;
- optionally `unexpected`: extra outputs exist that are not part of the current manifest.

Persisting the manifest at submission time would also make status robust against later configuration changes.

**Regression tests**

- Multiple BOLD inputs with only one output must remain partial for every applicable stage.
- All expected outputs must produce complete.
- Extra stale output must not compensate for a missing expected output.
- Anat-only sessions must remain valid without invented functional requirements.

---

### DB-003 — P1 — Ingestion collisions are reported as successful

**Status:** Confirmed; also recorded as TODO #17.9

`ingest_session()` returns immediately when the target exists. It does not verify that an existing symlink points to the requested source, that an existing copied tree represents the same source, or that two selected rows did not map to the same BIDS destination. The GUI treats every returned path as `success`.

Consequently, if two source folders are mapped to the same subject/session, the first source wins and the second is not ingested, but both rows appear green.

Manual subject and session values also reach `sub_ses_relpath()` without a strong BIDS-label validator. Invalid entities or path separators can produce invalid or unintended directory structures.

**Evidence**

- [`ingestion.py` lines 310–361](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/ingestion.py#L310-L361)
- [`2_Data_Ingestion.py` lines 153–178](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/2_Data_Ingestion.py#L153-L178)

**Recommended direction**

Return a structured result rather than a bare path, for example:

- `created`;
- `already_same`;
- `conflict`;
- `failed`.

For symlinks, compare the resolved target to the selected source. For copied data, either reject any pre-existing destination unless the user explicitly confirms replacement, or maintain a provenance marker that records the original source. Preflight the entire selected mapping for duplicate destinations before writing anything.

Validate BIDS subject/session entities before path construction and verify that the resolved destination remains under `sourcedata_dir`.

**Regression tests**

- Two different sources mapped to one destination must produce a blocking conflict.
- Re-ingesting the same source to the same symlink may report `already_same`.
- Invalid labels containing separators, `..`, or nonconforming characters must be rejected.
- A broken existing symlink should produce an explicit recoverable error.

---

### DB-004 — P1 — NORDIC BIDS assembly is order-dependent and can retain stale files

**Status:** Data-dependent, strongly indicated by the implementation

The regular fMRIPrep path intentionally does not restrict anatomical suffixes to the current session because anatomy is often acquired in one session and shared across functional sessions. NORDIC's BIDS input builder does not preserve that behavior: it copies anatomy only from the current `sub/ses` directory.

The output is a persistent shared `derivatives/nordic/bids_format` tree. Every copy or hardlink is skipped when its destination already exists, and files that disappeared from the source are never removed.

This creates two problems:

1. **Order dependence:** a functional session with no local T1w can assemble an anatomy-free NORDIC input tree unless another operation has already populated the shared tree with anatomy from a different session.
2. **Staleness:** after reconversion, corrected metadata, replaced NIfTIs, removed runs, updated participant files, or changed fieldmaps may not propagate into the NORDIC input tree.

**Evidence**

- [`fmriprep.py` lines 10–29](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/fmriprep.py#L10-L29)
- [`nordic.py` lines 135–211](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/nordic.py#L135-L211)

**Recommended direction**

- Assemble all anatomy available to the subject, not only the current session's anatomy.
- Build a desired-file manifest and reconcile the staged subtree to that manifest.
- Refresh changed sidecars and root metadata rather than treating destination presence as equivalence.
- Remove stale files within the explicitly owned subject/session scope.
- Consider building in a temporary directory and atomically replacing the scoped subtree.
- Protect concurrent subject/session builders with a lock or otherwise avoid one job pruning another job's files.

**Regression/integration tests**

- Subject with T1w only in session A and BOLD only in session B.
- Build session B first and verify that fMRIPrep's staged input still contains usable anatomy.
- Change a sidecar and rebuild; the staged copy must update.
- Remove a BOLD run and rebuild; the stale staged run must disappear.
- Concurrent or interleaved builds for two sessions must not remove each other's desired files.

---

### DB-005 — P2 — Single-session conversion bypasses shared pipeline orchestration

**Status:** Confirmed

The per-session conversion page renders an sbatch template and calls `submit_job()` directly. Bulk conversion and preprocessing use the shared `advance_one()` controller, which submits and writes a durable submission/provenance record.

The direct path therefore omits the record used for durable job lookup and consistency checking. This can leave Project Status unable to associate a single-session conversion with its exact job after transient SLURM state disappears. It also duplicates submission logic in the GUI, increasing the likelihood that validation, provenance, or behavior will drift.

**Evidence**

- [`3_BIDS_Conversion.py` lines 735–766](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/3_BIDS_Conversion.py#L735-L766)
- [`pipeline.py` lines 350–375](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/pipeline.py#L350-L375)

**Recommended direction**

Route per-session submission and export through the same pipeline service used elsewhere. If the conversion page needs to pass a reviewed JSON artifact, make that artifact or its path an explicit controller parameter. Keep validation, script rendering, submission, job naming, and provenance in one code path.

**Regression tests**

- Per-session submission produces the same durable record as bulk submission.
- Export-only remains non-submitting and records no launched job.
- A submission failure does not create a false success record.

---

### DB-006 — P2 — Job history can suppress the latest failed retry

**Status:** Confirmed

Recent history is reduced to two sets keyed only by job name: names that have failed and names that have completed. The overlay reports failure only when a name is in the failed set and not in the completed set.

If attempt 1 completed and attempt 2 later failed, the job name is in both sets and the latest failure is hidden. The current test suite checks the opposite chronology—failure followed by successful completion—but not success followed by failure.

**Evidence**

- [`pipeline.py` lines 660–729](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/pipeline.py#L660-L729)
- [`test_pipeline.py` lines 317–328](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/tests/test_pipeline.py#L317-L328)

**Recommended direction**

Select the latest attempt per logical job name using a reliable ordering field such as submission/start/end timestamp or numeric job ID. Preserve the selected `JobInfo`, not only a state membership set. Continue to let live `squeue` state outrank history and filesystem-complete status outrank stale failures where that policy is intentional.

**Regression tests**

- Failed then completed → completed/no failure badge.
- Completed then failed → failure badge when filesystem evidence is incomplete.
- Active retry → running/queued regardless of older history.
- Array tasks and decorated SLURM job IDs are ordered correctly.

---

### DB-007 — P2 — DICOM sorter trusts metadata as filesystem paths

**Status:** Confirmed

The sorter places `PatientName`, `StudyDescription`, and `SeriesDescription` directly into destination paths. It does not sanitize separators or traversal components and does not verify that the resolved destination remains below the configured output directory.

`os.walk(..., followlinks=True)` also permits symlink cycles. The implementation does not reject output directories located inside the input tree, so old output can be discovered and processed as new input. Once dry-run is disabled, the GUI defaults to moving rather than copying.

These issues do not require malicious DICOMs; unusual scanner/site metadata can contain punctuation or separator-like content.

**Evidence**

- [`dicom_sorter.py` lines 71–125](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/dicom_sorter.py#L71-L125)
- [`2_Data_Ingestion.py` lines 237–251](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/2_Data_Ingestion.py#L237-L251)

**Recommended direction**

- Normalize every metadata-derived path component with a strict filename sanitizer.
- Reject `.`/`..`, separators, empty results, and absolute components.
- Resolve each destination and enforce containment under the resolved output root.
- Reject overlapping input/output roots.
- Do not follow directory symlinks unless there is a clear requirement and cycle detection.
- Consider making copy the default for a destructive GUI tool, with move as an explicit opt-in.
- Write a manifest during dry-run and require the real run to use the reviewed manifest.

**Regression tests**

- Metadata containing `/`, `\\`, `..`, absolute-looking text, empty values, and Unicode.
- Output nested under input and input nested under output.
- Symlink loops.
- Duplicate destinations, overwrite behavior, copy behavior, and move behavior.
- Containment invariant for every generated destination.

---

### DB-008 — P2 — Editing a QC reason silently creates or changes a decision

**Status:** Confirmed; also recorded as TODO #17.10

The decision buttons save immediately without the reason field. Separately, changing a nonempty reason automatically saves a decision; for an undecided run, the fallback decision is `investigate`. No rerun follows the reason save, so the expander title and aggregate table remain stale in the current render.

This creates several confusing states:

- Typing a note on an undecided run creates an `investigate` decision without an explicit decision action.
- Clicking Keep or Exclude after entering a reason can make the newest record omit the reason.
- Note edits generate audit-history entries as if a decision transition occurred.

**Evidence**

- [`5_QC_Dashboard.py` lines 145–172](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/5_QC_Dashboard.py#L145-L172)
- [`qc.py` lines 182–236](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/core/qc.py#L182-L236)

**Recommended direction**

Use one form containing the decision and reason, with an explicit Save/Update button. Write both values in one transaction and rerun after success. If notes must be independently editable, model note revisions separately from decision transitions in the audit format.

**Regression tests**

- Typing alone must not persist anything before explicit submission.
- Saving a decision must persist the displayed reason.
- Updating only a reason must preserve the decision intentionally.
- The rendered header and aggregate table must reflect the latest stored record after submission.

---

### DB-009 — P2 — Conversion controls can describe state that is not submitted

**Status:** Confirmed by code inspection; substantially acknowledged as TODO #17.5–#17.7

When direct JSON editing is enabled, the effective preview correctly reads the JSON. However:

- the task/run/fieldmap table remains editable even though its edits no longer drive submission;
- the warning that the table is inactive is inside the Advanced expander;
- the two “Save as project default” actions still persist table-derived state rather than the effective JSON;
- the page does not reliably seed itself from an already reviewed `dcm2bids_config.json`, even though the launch path reuses that file;
- `directory_picker()` initializes its committed selection only once per Streamlit session-state key, so switching projects can retain the previous project's path.

This is a classic GUI/backend drift problem: controls remain active and credible while affecting a different representation than the one ultimately submitted.

**Evidence**

- Effective JSON selection: [`3_BIDS_Conversion.py` lines 473–496](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/3_BIDS_Conversion.py#L473-L496)
- Still-editable table: [`3_BIDS_Conversion.py` lines 523–545](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/3_BIDS_Conversion.py#L523-L545)
- Table-derived project defaults: [`3_BIDS_Conversion.py` lines 561–612](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/3_BIDS_Conversion.py#L561-L612)
- Override warning location: [`3_BIDS_Conversion.py` lines 645–674](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/3_BIDS_Conversion.py#L645-L674)
- Picker initialization: [`components.py` lines 48–57](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/components.py#L48-L57)

**Recommended direction**

- Make the effective artifact the single source of truth for preview, persistence, and launch.
- When JSON override is active, disable or visually suppress controls that no longer apply.
- Move the override-state warning to the main page near the table and submit button.
- Make project-default actions parse and explicitly report what can and cannot be represented from the effective JSON.
- Detect an existing reviewed config and ask whether to load, replace, or regenerate it.
- Namespace/reset picker state by active project identity, not only widget purpose.

---

### DB-010 — P2 — Failed-job log rendering hides stderr and reads unbounded files

**Status:** Confirmed

The Project Status popover chooses `stdout` when it is nonempty and falls back to `stderr` only when stdout is empty. A failure reason written to stderr is therefore invisible whenever the job also produced stdout, and the download contains only the selected stream.

`job_log()` reads every matching stdout/stderr file completely and concatenates it in memory. The GUI displays only the last 4,000 characters, but the full cost has already been paid. Array jobs can have many large log files, and repeated Streamlit renders can amplify metadata and read pressure on the shared filesystem.

**Evidence**

- [`0_Project_Status.py` lines 190–216](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/gui/pages/0_Project_Status.py#L190-L216)
- [`monitor.py` lines 264–281](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/slurm/monitor.py#L264-L281)

**Recommended direction**

- Display stderr and stdout separately, prioritizing stderr for failed jobs.
- Implement bounded tail reads using file seeking rather than full `read_text()`.
- Load logs only after an explicit user action if Streamlit's popover body is otherwise evaluated during normal page rendering.
- Report file count and sizes before loading large array logs.
- Provide per-task logs for arrays rather than concatenating all tasks by default.

**Regression/performance tests**

- Nonempty stdout plus nonempty stderr must expose both streams.
- Tail retrieval from a large file must read a bounded amount.
- Invalid encodings remain readable with replacement behavior.
- Array-job log selection is deterministic and does not concatenate unrelated task output unexpectedly.

---

### DB-011 — P2 — Rendered shell paths are not consistently quoted

**Status:** Confirmed; exposure depends on configured path names

The sbatch templates interpolate filesystem paths directly into shell commands, bind specifications, variable assignments, and `mkdir` arguments. Setup accepts arbitrary server paths, so spaces, glob characters, quotes, or other shell metacharacters can split arguments or alter execution.

Examples include unquoted DICOM, BIDS, config, output, work, license, derivative, and container paths. `extra_flags` is intentionally shell-like and should remain an explicitly trusted advanced field, but path and identifier fields should not be treated as shell fragments.

**Evidence**

- [`dcm2bids.sbatch.j2` lines 16–26](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/templates/sbatch/dcm2bids.sbatch.j2#L16-L26)
- [`fmriprep.sbatch.j2` lines 16–50](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/templates/sbatch/fmriprep.sbatch.j2#L16-L50)

**Recommended direction**

Add a narrowly scoped Jinja shell-quote filter backed by `shlex.quote()` and apply it to every value that represents one shell argument. Treat composite bind specifications carefully: quote the complete `source:destination:mode` argument or construct it from individually validated absolute paths. Validate SLURM directive values separately because `#SBATCH` parsing is not normal shell parsing.

**Regression tests**

- Render templates with spaces, parentheses, wildcard characters, and single quotes in paths.
- Parse or execute the rendered argument construction in a harmless stub environment and assert exact argv boundaries.
- Explicitly document and test the trust model for `extra_flags`.

---

### DB-012 — P3 — Repeat submissions overwrite the recorded sbatch script

**Status:** Confirmed

When `scripts_dir` is supplied, the submission helper writes a deterministic filename based only on the logical job name. Retrying the same subject/session/stage overwrites the earlier script before submission. The durable submission log records useful metadata, but it does not preserve the exact rendered recipe of each historical attempt.

This weakens reproducibility and incident analysis: after a configuration change, the script on disk represents only the newest attempt, not necessarily the job whose logs are being inspected.

**Evidence**

- [`submit.py` lines 37–51](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/slurm/submit.py#L37-L51)
- [`submit.py` lines 91–108](https://github.com/hulacon/duckbrain/blob/c732e9e767467b9ae9fe58a6a272e16dd6ca3af6/src/duckbrain/slurm/submit.py#L91-L108)

**Recommended direction**

Preserve an immutable script per attempt. Because the job ID is known only after submission, options include:

- write a timestamp/nonce-named script, submit it, then rename or copy it to include the job ID;
- store the rendered script content or a content hash in the submission record;
- retain a stable “latest” convenience copy in addition to immutable historical copies.

## GUI and documented-state observations

The repository's own TODO file already captures a useful subset of the GUI drift found here, particularly #17.5 through #17.10. This is a positive sign: the project is recognizing the correct class of failure.

Two caveats are worth recording for whoever maintains that list:

1. TODO #17.1 should not be considered fully closed until nested keys inside partially owned sections are preserved.
2. TODO #17.8 says the shared-resource save drops `[recent]`; the current top-level section-scoped saver appears to preserve `[recent]`. The more important part of #17.8 remains valid: shared-resource widgets are seeded from fully merged configuration and can promote a project-specific value into the global user layer.

The broader design principle suggested by these findings is:

> Every display, persistence action, and launch action should derive from the same effective artifact, and every form should explicitly own only the configuration fields it edits.

## Test-suite assessment

### Result

- **431 tests passed**.
- Runtime was approximately **40.6 seconds** in the disposable review environment.
- Overall measured statement coverage was **58%**.
- Compilation/import checks completed successfully.

### Coverage profile

Selected stronger modules:

| Module | Coverage |
|---|---:|
| `core/conversion_plan.py` | 98% |
| `core/dcm2bids_config.py` | 98% |
| `core/dicom_inspect.py` | 97% |
| `core/consistency.py` | 96% |
| `core/surveyor.py` | 96% |
| `config.py` | 92% |
| `core/pipeline.py` | 92% |
| `core/ingestion.py` | 93% |
| `core/nordic.py` | 88% |

Selected weaker or uncovered modules:

| Module | Coverage | Risk relevance |
|---|---:|---|
| `core/dicom_sorter.py` | 0% | Destructive filesystem operations and metadata-derived paths |
| `core/qc.py` | 0% | Decision persistence and audit history |
| `slurm/submit.py` | 18% | External submission, failure handling, and script retention |
| `core/mriqc.py` | 20% | QC workflow construction |
| `core/conversion.py` | 62% | Saved conversion artifact lifecycle |
| `slurm/monitor.py` | 65% | Scheduler parsing and potentially large log reads |
| `core/fmriprep.py` | 66% | Multi-session filters and preprocessing command construction |

The Streamlit page files appeared as 0% in this coverage run even though the repository contains AppTests. This likely reflects separate Streamlit execution rather than proof that every page is untested. Coverage collection should be configured to include those processes, or the project should report GUI behavioral coverage separately.

### Missing quality gates

No repository-owned configuration was found for:

- GitHub Actions or another checked-in CI workflow;
- a minimum coverage threshold;
- linting such as Ruff;
- static type checking such as mypy or pyright;
- formatter enforcement.

The current suite can be healthy on one developer's machine while regressions still merge without an automatic gate.

### Highest-value test additions

The following tests would address the findings more effectively than pursuing uniform percentage coverage:

1. Nested SLURM configuration preservation through real Setup save payloads.
2. Expected-output cardinality for multi-run conversion, NORDIC, fMRIPrep, and MRIQC.
3. Ingestion collision and idempotency outcomes.
4. NORDIC multi-session shared anatomy and stale-tree reconciliation.
5. Complete-then-failed SLURM retry chronology.
6. QC decision/reason transaction behavior.
7. DICOM sorter path sanitation, containment, overlap, and symlink tests.
8. Per-session conversion provenance parity with the pipeline controller.
9. Bounded log-tail behavior and simultaneous stdout/stderr presentation.
10. Shell-quoting tests for rendered templates.

### Suggested CI baseline

A practical initial CI workflow could run on supported Python versions and enforce:

```text
compile/import check
unit and Streamlit AppTests
coverage report with an initially realistic non-decreasing floor
Ruff lint
Ruff format --check
```

Type checking can be introduced incrementally, beginning with new or high-risk core modules rather than requiring an immediate repository-wide clean result.

## Recommended remediation sequence

### Phase 1 — Prevent silent loss and false success

1. Fix form-owned nested configuration saving (DB-001).
2. Add ingestion collision preflight and structured outcomes (DB-003).
3. Harden the DICOM sorter before broader use (DB-007).
4. If `use_nordic` is currently active on multi-session projects, validate and fix NORDIC anatomy/staleness immediately (DB-004).

### Phase 2 — Make displayed state trustworthy

1. Introduce exact expected-output manifests (DB-002).
2. Select the latest logical SLURM attempt rather than set membership (DB-006).
3. Make QC decision/reason updates transactional (DB-008).
4. Resolve JSON/table/picker source-of-truth drift (DB-009).

### Phase 3 — Consolidate orchestration and provenance

1. Route per-session conversion through the shared controller (DB-005).
2. Preserve immutable submitted scripts or exact script content (DB-012).
3. Quote and validate generated shell arguments (DB-011).

### Phase 4 — Reduce operational cost and strengthen gates

1. Use bounded, on-demand log reads and show stderr separately (DB-010).
2. Add targeted regression tests for the high-risk filesystem and GUI boundaries.
3. Add CI, linting, formatting checks, and a non-decreasing coverage floor.

## Questions for production validation

These questions are not blockers to the code findings, but their answers determine priority and the most representative fixtures:

1. Do multi-session studies commonly acquire T1w anatomy in only one session while processing BOLD from other sessions? If yes, DB-004 should be treated as urgent.
2. Do project or user TOML files currently contain hand-tuned `[slurm.overrides.*]` sections? If yes, ordinary Setup saves are presently capable of removing live settings.
3. Are project, container, license, DICOM, or derivative paths guaranteed never to contain spaces or shell metacharacters? If not, DB-011 is a current portability defect.
4. For ingestion, should selecting the exact same source twice be treated as successful idempotency, a warning, or a blocking duplicate?
5. How much job history needs to remain reproducible after SLURM accounting ages out—only status and parameters, or the exact submitted script and container identity?

## Overall assessment

Duckbrain's domain logic and test culture are stronger than the raw coverage percentage suggests. The main opportunity is to make state transitions explicit and shared across layers. Several bugs arise because the GUI, persistent configuration, filesystem, pipeline controller, and status survey each maintain a slightly different representation of the same operation.

Addressing the P1 findings first, then consolidating every action around an effective configuration artifact and an expected-output manifest, would materially improve safety without requiring a broad rewrite.

