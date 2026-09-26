# QSIPrep patches

Files here are bind-mounted **read-only over the matching file inside the
pinned QSIPrep image** when a project opts in. Each is a whole-file copy from one
release, so each lives under that release's version directory and is refused for
any other (`core/qsiprep.py:grouping_patch_binds`). The package path inside each
image is pinned in `core/qsiprep.py:QSIPREP_PACKAGE_DIRS`.

## `26.0.0/qsiprep/utils/grouping.py` — eddy groups with colliding names

Enabled by `[qsiprep] patch_grouping = true` in the project's `duckbrain.toml`.
`grouping.diff` beside it is the change against the file shipped in
`qsiprep-26.0.0.sif`.

**The bug.** A session with opposing-PE pairs on two axes (e.g. `dir-AP`/`dir-PA`
and `dir-LR`/`dir-RL`) gives `group_for_eddy` two groups, one per axis. Each is
named by `get_concatenated_bids_name`, which keeps only the entities common to
the group's files; each pair has two `dir-` values, so both names reduce to
`sub-XX_ses-YY`. `workflows/base.py` then keys a dict on that name, and the
second group overwrites the first before any workflow is built. One pair is
never preprocessed, the run exits 0, and the output looks complete (half the
volumes). `--distortion-group-merge` cannot help: the mapping it reads is built
from the same names.

**The fix.** Only when names collide within a session, each colliding group is
renamed `<shared name>_dir-<its PE labels>` (e.g. `sub-XX_ses-YY_dir-PAAP`),
and the concatenation mapping sends each renamed group to the shared name — the
destination `--distortion-group-merge` merges into. Non-colliding groups are
returned exactly as before, so a single-axis session is unaffected.

**Use it with `--distortion-group-merge concat`.** Under the default `none`
each group is written as its own output under its renamed prefix. `average`
does not work for this layout in 26.0.0: `AveragePEPairs` counts distortion
groups by PE direction (four here, it requires two) and pairs volumes by
position, which assumes each group is one PE direction carrying the full scheme.

**Verified** (2026-09-25) in the image: grouping on a four-PE session yields two
distinct groups mapped to one destination and a two-PE session is unchanged;
`init_qsiprep_wf()` then builds one `dwi_preproc_*` workflow per group feeding
one `*_final_merge_wf`.

**Retire it** when a QSIPrep release names these groups distinctly: rerun the
grouping check against the new image, and if it passes, unset the key rather than
porting the patch.

## The `concat` merge — five files backporting upstream's repair

Mounted by the same `patch_grouping = true`: the grouping fix is what makes a
session reach the merge with two groups, and these are what let the merge run.
Each file has a `<name>.diff` beside it against the file in `qsiprep-26.0.0.sif`;
every changed site is marked `# duckbrain patch`.

**The bug.** In 26.0.0 `--distortion-group-merge concat` cannot complete. It fails
in stages, each hidden behind the one before, and only after eddy (hours in):

1. `workflows/base.py` builds every group's `init_dwi_finalize_wf` with
   `write_derivatives=not merging`, and `finalize.py` passes that on as
   `concatenate=` and as part of `do_biascorr=`. So each merged group reaches
   `*_final_merge_wf` as one 3D file per volume; the merge's `niu.Merge` flattens
   the groups into one list (216 volumes beside 2 bval files), and `MergeDWIs` →
   `harmonize_b0s` indexes a 3D volume as a series: `DimensionError: Expected
   dimension is 4D and you provided a 3D image` (PennLINC/qsiprep#971, open).
   The same flag switches off each merged group's final B1 bias correction, and
   the merge workflow has none, so merged and unmerged sessions would differ.
2. `MergeDWIs` never sets `merged_b0_ref`, `merged_raw_dwi` or `merged_raw_bvec`
   (only `AveragePEPairs` does), so the b=0 masking and the raw QC downstream get
   no input (`Resample requires a value for input 'in_file'`). It also reads the
   per-group `confounds.tsv` as CSV, and the merged confounds CSV is later read as
   TSV by `calculate_motion_summary` — mangled rather than failing.
3. A destination with a single group (any AP/PA-only session under `concat`) still
   gets a merge workflow, and `MergeDWIs` returns before writing those outputs when
   it has one input.

**The fix.** Upstream's own, from PennLINC/qsiprep `main` (none of it released at
26.0.0):

- `workflows/dwi/finalize.py`, `interfaces/dwi_merge.py`,
  `workflows/dwi/distortion_group_merge.py` — commit 1a9efb6 (#1092, 2026-08-21):
  `concatenate=True` and `do_biascorr = stage == 'final'` (each group concatenated
  and bias-corrected exactly as an unmerged session is); `MergeDWIs` takes
  `original_bvec_files`, writes the merged b=0 reference, raw series and raw bvecs,
  reads confounds by extension, and promotes a single-volume input to 4D; the concat
  merger is connected to the original bvecs. Those hunks applied to 26.0.0 unchanged
  (26.0.0 differs from their parent only in `AveragePEPairs` helpers).
- `interfaces/reports.py` — the `calculate_motion_summary` hunk of the same commit
  (separator by extension). Its other hunk depends on the new grouping schema and is
  not taken.
- `workflows/base.py` — upstream main's rule that a destination with fewer than two
  groups is not merged: it keeps the direct path (`write_derivatives=True`), which is
  also exactly how an AP/PA-only session runs under `none`.

The job log carries "duckbrain finalize patch: … concatenated and bias-corrected
before merge" once per merged group.

**Verified** (2026-09-25) by building `init_qsiprep_wf()` in the image with all six
files mounted: a four-PE session gets one merge workflow fed by two finalize
workflows that each concatenate and bias-correct, with `original_bvec_files` and
`raw_concatenated_files` connected to the merger; a two-PE session gets no merge
workflow. Without the patches the finalize workflows do neither.

**Retire them** when a QSIPrep release contains 1a9efb6 and the single-group rule:
check `init_dwi_finalize_wf`, `MergeDWIs._run_interface` and the merge-workflow
loop in `init_single_subject_wf` in the new image, and run one four-PE session.

## Licence

The patched files are QSIPrep's, BSD-3-Clause; `26.0.0/LICENSE` is the licence
shipped in that image, retained as its terms require.
