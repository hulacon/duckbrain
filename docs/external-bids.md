# Adopting an existing BIDS dataset

*Written 2026-08-18, alongside `TODO.md` `#41`. This is the user-facing account;
the design decisions live in the code comments this page points at.*

duckbrain's downstream half — fMRIPrep / MRIQC / NORDIC submission, the Status
cockpit, QC review — does not require that duckbrain performed the DICOM→BIDS
conversion. Every judgement is made against the BIDS tree on disk, not against
conversion records. This was true by design before it was a feature: the
surveyor's unit discovery and `converted` grading carry explicit external-BIDS
branches, and the consistency checker deliberately treats a derivative without
duckbrain provenance as a first-class citizen rather than a foreigner
(`core/consistency.py`'s module docstring).

## How to use it

1. On **Project Setup**, point the project directory at your existing BIDS root
   (or a fresh directory you then fill — the project directory *is* the BIDS
   root; `sourcedata/`, `derivatives/`, `code/` are created beneath it and an
   existing tree is never touched by scaffolding).
2. Turn on **"This project uses an existing BIDS dataset (no DICOM
   conversion)"** and save. This writes `[project] external_bids = true` to
   `<project>/code/duckbrain.toml`.
3. Work from **Status** as usual: conversion reads COMPLETE wherever the tree
   holds data, and fMRIPrep / MRIQC / NORDIC are launchable per unit.

## What the declaration changes

- **The Status board stops billing you for ingestion.** `ingested` grades *n/a*
  instead of a permanent "0/N missing", so the "only unfinished" filter and the
  all-stages-complete state work. (`core/surveyor.py`, `survey_project` — the
  same reasoning as NORDIC's *n/a*, `#17.4`.) `converted` deliberately keeps
  grading from presence: downstream stages gate on it, and "this unit has BIDS
  data" is real information.
- **`participants.tsv` is rostered from the BIDS tree**, not from DICOM
  demographics (`bids_metadata.generate_participants_from_bids`): one row per
  `sub-*` directory, other columns left at `n/a` rather than invented. Rows are
  appended in the existing file's own column order; a curated file gains its
  missing subjects and loses nothing.
- **Setup stops asking for a DICOM source or a dcm2bids container.**

## What holds with or without the declaration (fixed 2026-08-18)

- The metadata buttons never destroy what your dataset brought:
  `participants.json` is written only when absent, `dataset_description.json`'s
  `GeneratedBy` merges by `Name` (your converter's entry survives), and
  duckbrain claims a dcm2bids entry only when it actually converted.
- Uncompressed NIfTI (`.nii`) is seen everywhere compressed is
  (`ingestion.nii_glob`): the surveyor, run counts, expectations, NORDIC.

## Caveats

- **The BIDS validator runs inside the dcm2bids container**, so validating from
  the Project page still requires that ~1 GB image even though you will never
  convert. The panel says so rather than failing cryptically
  (`core/validation.py`).
- **Phasediff/GRE fieldmaps count as 0 fieldmap pairs** in the expectations
  panel — `_fmap_pair_count` recognizes only `*_epi` (PEPOLAR) pairs today
  (`TODO.md` `#19.6`). Preprocessing itself is unaffected; fMRIPrep reads the
  fieldmaps regardless.
- **A DataLad / git-annex clone with unfetched content** (broken symlinks in
  place of image files) grades MISSING throughout — fetch the data first.
- The declaration is project-wide: a project that *mixes* external BIDS with
  duckbrain-converted subjects should leave the toggle off (everything still
  works; you just keep the ingestion column).
