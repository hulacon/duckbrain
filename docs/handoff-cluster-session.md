# Handoff → next on-cluster session

> **DISCHARGED 2026-07-21. Nothing in this doc is outstanding.** §1 closed
> 2026-07-16; §2, §3 and the deferred nested-multi-session item were all
> validated live on 2026-07-21 and their bugs fixed on `main`. What was learned
> is in `memory/validation-discovery-and-fieldmaps`; the accepted residuals are
> the "accepted edges" of `#5` in `TODO.md`, along with the standing rule on how
> much messy source labeling duckbrain accommodates. **The sections below are kept as the
> record of what was asked and what the answers turned out to be — read the
> §2/§3 notes for how each hypothesis actually resolved, not as work to do.**
> The next on-cluster session should start from `TODO.md`, not from here.

**Everything below is the 2026-07-16 snapshot, preserved as written.** At that
point the provenance item had just closed and §2/§3 had not been reached — they
were the live-validation work still waiting for a Talapas session. They were
reached on 2026-07-21; see the ✅ notes on each.

## State of `main` *(as of 2026-07-16)*

- Full suite green, working tree clean, pushed. Don't trust a test count or a
  commit hash quoted in a doc — run `python -m pytest tests/ -q` and
  `git log --oneline -1`. (This line used to quote a number, which was stale
  within the week.)
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

### 2. Discovery fixes against real LCNI export dirs — ✅ CLOSED 2026-07-21
**How it resolved.** The premise was too narrow: `divatten` is not the only real
export. `/projects/lcni/dcm/hulacon/Hutchinson/` also holds `PSY607`, `AttTime`,
`New Program`, `RTPILOT` and `realtime` — the small ones being almost entirely
real phantom/test folders, i.e. the fixtures this section wanted — and
`/projects/lcni/dcm/hulacon/mmmdata/` holds 104 sessions.
- **`G##_S##`: unverifiable, and still is.** No export on this filesystem uses
  that style; mmmdata is `MMM_003_sess04`. Left unit-tested only.
- **Phantom/test filtering: held.** All 8 real phantom/test folders dropped, no
  real subject dropped. The numeric-subject guard behaved as designed.
- **But three real bugs the section didn't anticipate:** a session label with a
  qualifier (`sess04CR`, `sess3.2`) was adopted as the *subject*, so real
  subjects vanished; an unreadable folder raised `PermissionError` and took down
  the ingestion page; and a nested source found nothing at all. All fixed.

<details><summary>Original §2 text</summary>
Sanity-check `discover_sessions` on actual source dirs — synthetic fixtures can't
prove the heuristics match real folder names:
- **`G##_S##`:** point at any mmmdata-style export; confirm `S##` is read as the
  session and the paired `G##` as the subject (not misparsed).
- **Phantom/test filtering:** confirm real phantom/QA/setup folders drop out of the
  ingestion list, and that **no real subject is dropped**. The guard keeps a
  numeric-subject folder even under a marker prefix (`TEST_01` stays; `TEST_phantom`
  goes) — eyeball this against a real export. `discover_sessions(..., include_excluded=True)`
  bypasses the filter if you need to see everything.
</details>

### 3. Multiple-fieldmap-pair conversion end-to-end — ✅ CLOSED 2026-07-21
**How it resolved.** The acceptance criterion was met exactly, and getting there
exposed the bug the section was really about — in the branch it wasn't looking at.
- **Constructing a subject wasn't needed.** mmmdata has plenty:
  `MMM_003_sess02` (two plain AP/PA pairs), `MMM_003_sess04` (three).
- **`detect_fieldmaps` reported the pairs correctly, no "Duplicate AP".** ✅
- **A real conversion produced `dir-AP_run-1`, `dir-AP_run-2`, `dir-PA_run-1`,
  `dir-PA_run-2`** — four files, none overwritten, with distinct
  `B0map_1_…`/`B0map_2_…` `B0FieldSource` and correct `j-`/`j`. Project
  `/projects/hulacon/bhutch/mmm_fmap_check`, SLURM job 45578124, ~4 min.
- **The bug: *named* pairs were not covered by the 2026-07-16 fix.** Unnamed
  pairs were paired by acquisition order; named groups stayed a
  direction-keyed dict, so a reshot `se_epi_ap_encoding` overwrote its
  predecessor. `MMM_005_sess19` has three `encoding` pairs and kept one. The
  code comment asserting a repeated direction in a named group is "a genuine
  config smell" was wrong — reacquisition is normal in both branches.
- **And bolds could link to a half group** — an aborted opening AP sorts first
  and `_assign_fmap_group` took the first group, handing fMRIPrep an SDC it
  cannot run. Now only both-direction groups are candidates.
- Known limitation confirmed unchanged: linking still picks the first group.

<details><summary>Original §3 text</summary>
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
</details>

## Deferred — needs cluster / real data to even start

### TODO #4 item 4 — mmmdata nested multi-session discovery — ✅ CLOSED 2026-07-21
**The guessed structure below was wrong, which is exactly why it was deferred.**
The real tree is `/projects/lcni/dcm/hulacon/mmmdata/`, and the nesting is one
level of *protocol* folders — `anat_session/`, `func_session/`,
`func_session_localizers/`, `func_session_cued_recall/`,
`func_session_free_recall/`, `func_session_final_cued_recall/` — each holding
flat `MMM_003_sess02_<date>` session folders. There is no
`func_session_*/anat_session/` nesting, and func- and anat-sessions do not "fold
into" BIDS sessions: subject and session both come from the leaf folder name, the
same as the flat layout, and session numbers run across the whole set rather than
restarting per folder. The grouping folder is a protocol label — recorded as
`SessionInfo.source_group`, and the natural unit for the `#10` template groups.

`discover_sessions` now descends one level, but **only when the top level yields
nothing parseable**, so the working flat LCNI path cannot be affected. One caveat
found in the process: session labels are *not* unique per subject (sub-003 has
`sess04` under two protocol folders), and ingestion is idempotent, so a naive
mapping would quietly put two scans in one session — now flagged in the
ingestion table's Notes column.

<details><summary>Original (incorrect) guess</summary>
`func_session_*/anat_session/` under the source breaks `discover_sessions`, which
expects session folders directly under the source dir. **Not attempted this
session on purpose:** the exact nesting isn't documented in this repo (the mmmdata
reference is at `/gpfs/projects/hulacon/shared/mmmdata/code`, on Talapas), and
guessing the structure risks the working LCNI path. To do it: paste/inspect one
real mmmdata source tree (`ls -R` a subject or two), pin down how func- and
anat-sessions fold into BIDS sessions, then extend `discover_sessions` +
`_parse_session_folder` with fixtures modeled on the real layout.
</details>

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
