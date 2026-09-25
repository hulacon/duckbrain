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

## Licence

The patched files are QSIPrep's, BSD-3-Clause; `26.0.0/LICENSE` is the licence
shipped in that image, retained as its terms require.
