# Handoff → next on-cluster session

**Updated 2026-07-16 at the end of an on-cluster session.** The provenance item
that headed this doc is now closed and validated live; §2 and §3 below were *not*
reached and are still the live-validation work waiting for a Talapas session
(shared FS, real scanner exports, `dcm2bids`/SLURM behavior).

## State of `main`

- **255 tests pass** (`python -m pytest tests/ -q`); working tree clean, pushed.
  Don't trust a commit hash quoted in a doc — check `git log --oneline -1`.
- **Licensed GPL-3.0-or-later; released + tagged `v0.1.0`.** Semver + `CHANGELOG.md`.
  Note the accepted trade-off: GPL blocks upstreaming duckbrain code into the
  Apache-2.0 nipreps tools or MIT nipoppy (so the mooted `surveyor.py` → mmmdata
  port needs dual-licensing). Open: confirm with UO/RACS that Ben can license it.
- **★ Provenance + consistency: CLOSED.** Provenance per run; BIDS `GeneratedBy` on
  every duckbrain-produced dataset (incl. the ingested root's dcm2bids converter and
  per-file NORDIC sidecars); seven checks in the cockpit. **The rule:** provenance
  for derivatives duckbrain *produces* lives in the data (sidecars → dataset stamp);
  for tool-produced ones (fMRIPrep/MRIQC) the submission log is the only channel.
  **Never** compare a config-pinned container *tag* to a tool's *self-reported*
  version — different namespaces (that bug shipped, see TODO ★).
- **Nipoppy bagel export removed** (write path with no reader; its version column
  came from config, not provenance). Verified spec preserved in memory for a re-add.

**First thing on-cluster:** `cd ~/code/duckbrain && git pull origin main`. The
OnDemand app serves *this checkout*, so the GUI keeps running old code until you
pull.

## A caution this session earned

The previous version of this doc asserted `divatten_gui_beta` was
"genuinely mixed" provenance and that the checker just needed confirming. **Both
were wrong** — the derivative held only sub-04/sub-015, both raw, and the checker
failed its own "stays silent when clean" criterion on first run. Treat the claims
below as *hypotheses to check*, not findings. Verify before building on them.

## VALIDATE LIVE (priority order)

### 1. Provenance consistency checker — ✅ CLOSED 2026-07-16. Nothing to do.
Validated live; the whole ★ item is closed (see `TODO.md`). Five bugs found that
unit tests could not have caught: the container-tag-vs-self-reported-version false
positive, a latent submission-log corruption that would have fired on the next
launch, phantom provenance from cancelled runs, `Path("")` describing duckbrain's
own repo as the NORDIC toolbox, and NORDIC having no sidecars at all.
**One accepted residual — do not re-open the item for it:** the mixing check has
never been driven by two *completed* real fMRIPrep runs (hours of compute, and it
works by deliberately corrupting a derivative to prove a warning fires). Every
*input* is live-validated and the grouping logic was driven end-to-end on real
`run_provenance` values → `mixed-provenance ... (nordic: 015; raw: 04)`. Close it
for free the next time a project genuinely mixes variants.

### 2. Discovery fixes against real LCNI export dirs
Sanity-check `discover_sessions` on actual source dirs — synthetic fixtures can't
prove the heuristics match real folder names:
- **`G##_S##`:** point at any mmmdata-style export; confirm `S##` is read as the
  session and the paired `G##` as the subject (not misparsed).
- **Phantom/test filtering:** confirm real phantom/QA/setup folders drop out of the
  ingestion list, and that **no real subject is dropped**. The guard keeps a
  numeric-subject folder even under a marker prefix (`TEST_01` stays; `TEST_phantom`
  goes) — eyeball this against a real export. `discover_sessions(..., include_excluded=True)`
  bypasses the filter if you need to see everything.

### 3. Multiple-fieldmap-pair conversion end-to-end
The riskiest to validate offline — it changes emitted `dcm2bids` config. Find (or
construct) a subject whose session has **two** SE-EPI AP/PA pairs (e.g. a topup
pair before and after the functionals):
- Confirm `detect_fieldmaps` reports two groups, **no "Duplicate AP" warning**.
- Convert it and check the BIDS `fmap/` output: files should be
  `..._dir-AP_run-1_epi` / `..._dir-AP_run-2_epi` (unnamed pairs) or
  `..._acq-<name>_dir-AP_epi` (named pairs) — **not** a single overwritten
  `dir-AP`. Verify `dcm2bids` doesn't skip either pair and the sidecars carry
  distinct `B0FieldSource` group ids.
- Known limitation (acceptable for now): bold→fmap linking still defaults every
  task to the *first* group (`_assign_fmap_group` has no temporal-proximity
  logic). Fine for conversion; note if any real project needs nearest-pair linking.

## Deferred — needs cluster / real data to even start

### TODO #4 item 4 — mmmdata nested multi-session discovery
`func_session_*/anat_session/` under the source breaks `discover_sessions`, which
expects session folders directly under the source dir. **Not attempted this
session on purpose:** the exact nesting isn't documented in this repo (the mmmdata
reference is at `/gpfs/projects/hulacon/shared/mmmdata/code`, on Talapas), and
guessing the structure risks the working LCNI path. To do it: paste/inspect one
real mmmdata source tree (`ls -R` a subject or two), pin down how func- and
anat-sessions fold into BIDS sessions, then extend `discover_sessions` +
`_parse_session_folder` with fixtures modeled on the real layout.

### ~~Provenance Phase A leftovers~~ — both closed 2026-07-16
- ✅ Ingested BIDS root now records the `dcm2bids` converter
  (`converter_generated_by`). Still pairs naturally with §3: a real conversion is
  the way to eyeball the emitted root description.
- ~~Nipoppy bagel export tie-in~~ — moot; the bagel export was **removed** (it was
  a write path with no reader, and its version column came from config rather than
  provenance). The verified spec is preserved in `memory/nipoppy-status-tracking`
  if it's ever wanted back.

## Notes
- No `MEMORY.md`/`memory/` exists in this checkout (they live on-cluster per
  `CLAUDE.md`); fold any live-validation findings back into `memory/` and update
  `CLAUDE.md`'s status + `TODO.md` as you go.
- Working convention holds: commit small verified changes straight to `main`,
  push to `origin`.
