# duckbrain — TODO

Prioritized backlog. Newest priorities at the top. See `PLAN.md` for the
original design and `CLAUDE.md` for current status.

## 1. Folder picker UX (TOP PRIORITY)

`components.directory_picker` works and is HPC-safe (lazy, one `iterdir` per
level — a recursive-glob tree component like `streamlit-file-browser` chokes on
`/projects/lcni/dcm`), but the UX is **still suboptimal** and needs another pass.

Known/candidate issues to address (confirm specifics with user):
- Every folder click triggers a full Streamlit rerun → feels sluggish, loses
  scroll position on long folder lists.
- Grid of `📁` buttons is visually heavy; no breadcrumb to jump up multiple
  levels at once (only single-step ⬆ Up).
- Selection model ("the current directory is the selection") may be unclear vs.
  an explicit "Use this folder" button.
- Folders only — no file view (needed for e.g. FreeSurfer license, which is
  currently a plain text field; picker is dirs-only).
- "➕ New folder" is tucked in an expander.

Directions to consider: breadcrumb navigation; an explicit select button; a
lighter list style; a file-mode for single-file selection (fs_license);
possibly a custom lazy-loading tree if worth the effort. Get concrete feedback
from the user on what felt off before reworking again.

## 2. Onboarding for external users
- Dogfood the GUI new-user path fully, fix rough edges, then write a lean
  QUICKSTART (access, container acquisition, launch) + refresh the README.
- Add in-GUI guidance at friction points (Setup, ingestion mapping, conversion).
- Resolve the **launch/distribution story**: OOD app is currently bhutch's
  personal sandbox; a new user needs their own OOD sandbox or `launch.sh` +
  tunnel. A shared/RACS-published OOD app is the long-term answer.

## 3. fMRIPrep step
- Validate end-to-end (container `fmriprep-24.1.1.simg` present). Needs a
  FreeSurfer license (still a TODO in the user config). Runs via SLURM, not inline.

## 4. Naming / discovery robustness (from the LCNI survey)
- `G##_S##` session style not recognized (parser needs "ses" prefix).
- Phantom/test-folder filtering (skip `test`/`phantom`/`demo`/QA, space-containing).
- Multiple fieldmap pairs per session collapse into one group ("Duplicate AP").
- mmmdata-style nested multi-session org (`func_session_*/anat_session/` under
  the source) breaks `discover_sessions`, which expects session folders directly
  under the source dir.

## 5. Config / mapping niceties
- Project-wide (vs per-subject/session) task/run mapping option: define once,
  inherit across subjects; per-subject override for exceptions.
- MRIQC container not present — QC-via-MRIQC not runnable until one is pulled.
