# Pipeline Cockpit — design & build plan

Turn the Project Status page from a **read-only** status matrix into an
**actionable cockpit**: each `(subject, session) × stage` cell shows what exists
*and*, where it's safe, offers a one-click "run this step" that advances the unit
to the next stage. "Almost but not quite a kanban" — see *Why not a literal
kanban* below.

Owner: Ben Hutchinson. Started 2026-07-10. Extends the project surveyor
(`core/surveyor.py`, TODO #6) and the existing per-stage GUI pages.

> **Resumability note.** This doc is written to survive a dropped SSH session
> (broken-pipe rate is high right now). It is self-contained: a cold-start
> Claude session should be able to read *only this file* + the referenced source
> and continue. **Keep the Status tracker below current** — it is the resume
> anchor. Each phase is independently committable; commit at every checkpoint so
> progress is never lost. Line numbers in this doc drift — always re-anchor by
> function/symbol name, not line.

---

## Status tracker  ← UPDATE THIS AS YOU GO

| Phase | State | Commit | Notes |
|---|---|---|---|
| 0. Plan written | ✅ done | (this file) | — |
| 1. Controller extraction (`core/pipeline.py`) | ✅ done | (see git log) | `advance_one` + `STAGE_SPECS`; pages 3/4 refactored; 11 tests; 109 suite. Ingestion OUT of board for v1 (Ben agreed 2026-07-10). Per-session dcm2bids *review* submit in page 3 left inline (uses UI-reviewed config path — different semantics; follow-up if worth unifying). |
| 2. Live-state fusion (`survey_live`) | ✅ done | (see git log) | `survey_live` + `stage_runnable` in `core/pipeline.py`; `<stage>_job` overlay (running/queued/failed). 8 tests; 117 suite. Validated live: the 2 running fMRIPrep jobs now read `running` + are correctly NOT runnable (double-submit closed). |
| 3. Cockpit UI (rework `0_Project_Status.py`) | ✅ done | (see git log) | Job-aware matrix (🔵running/⏳queued/🔴failed overlay) + "Launch a step" strip: dependency-gated selectbox of runnable (unit,stage) → params (fmriprep knobs / dcm2bids force) → Run via `advance_one`. 6 AppTests; 120 suite. Live-rendered vs real project: running fMRIPrep shows 🔵 + is NOT offered for re-run (double-submit closed). **Still wants a human eyeball in a real browser** (AppTest can't judge feel). |
| 4. Polish (bulk/guards/durable log) | ⬜ optional | — | defer. Candidates: guarded "run whole column", auto-refresh (`st.fragment(run_every=)` — beware squeue hammering), durable submission log under `code/logs/`, deep-links to full pages. |

Legend: ⬜ not started · 🟡 in progress · ✅ done. When resuming, read this row,
then the matching phase section, then `git log --oneline` to confirm what landed.

---

## Load-bearing facts (verified against the code 2026-07-10)

These are *why* this is a medium lift, not a rewrite. Confirm they still hold if
resuming after significant drift.

1. **Consistent SLURM job-naming convention = the join key.** Every SLURM stage
   submits as `f"{step}_{tag}"` where
   `tag = f"{sub}_{ses}" if ses else sub`:
   - `dcm2bids_{tag}` — `gui/pages/3_BIDS_Conversion.py`
   - `fmriprep_{tag}`, `nordic_{tag}`, `mriqc_{tag}` — `gui/pages/4_Preprocessing.py`
   This string maps a surveyor cell ↔ a squeue/sacct row with no new plumbing.

2. **Every SLURM stage's submit action is the same trio**, differing only in how
   the context is assembled:
   ```python
   ctx    = build_context(config, step, subject=sub, session=ses, **stage_specifics)
   script = render_sbatch(step, ctx)          # slurm/templates.py
   job_id = submit_job(script, f"{step}_{tag}", scripts_dir=log_dir)  # slurm/submit.py
   ```
   So a per-cell controller is a mechanical extraction of existing loop bodies.

3. **The surveyor already is the read model + dependency graph.**
   `survey_project(config) -> DataFrame` (rows = units, cols = `STAGES =
   (ingested, converted, fmriprep, mriqc)`, values = `Status`
   complete/partial/missing/n-a). `summarize()` gives the rollup.

4. **Job-state API exists.** `slurm/monitor.py`:
   - `list_jobs(user=None) -> list[JobInfo]` — squeue (pending/running only).
   - `job_history(user=None, days=7) -> list[JobInfo]` — sacct (completed/failed,
     carries `exit_code`, `state`, `end_time`).
   - `JobInfo` fields: `job_id, name, state, partition, time_used, time_limit,
     nodes, reason, submit_time, start_time, end_time, exit_code`.
   The `name` field is what we join on `{step}_{tag}`.

5. **Ingestion is the exception — it does NOT submit a SLURM job.** It runs
   synchronously in the GUI process via `core.ingestion.ingest_session(session,
   mapping, sourcedata_dir, method=...)`, and it maps *raw scanner folders →
   `(sub, ses)`* — i.e. the unit does not exist until *after* ingestion. It
   therefore does not fit the "click a missing cell to advance an existing unit"
   model. **Decision (v1): ingestion is read-only in the cockpit** (status +
   deep-link to the Ingestion page). Revisit later.

---

## Why not a literal kanban

A kanban card sits in exactly one column and moves rightward. Here a unit is
simultaneously in *every* column at some status (e.g. `converted:complete` **and**
`fmriprep:running` **and** `mriqc:missing`). The truthful visual is the existing
matrix (row × stage), with each **cell** made independently actionable and
dependency-gated — not a card sliding across lanes.

---

## Architecture — three layers

```
┌ Layer 3: Cockpit UI  (gui/pages/0_Project_Status.py, reworked)
│   actionable matrix · dependency-gated run popovers · job-state-aware cells · auto-refresh
├ Layer 2: Live-state fusion  (survey_live in core/pipeline.py)
│   survey_project()  +  join list_jobs()/job_history() on {step}_{tag}
│   → overlays running / queued / failed onto filesystem status
├ Layer 1: Controller  (core/pipeline.py, NEW)
│   advance_one(config, stage, sub, ses, **overrides) -> job_id|None
│   STAGE_META: deps, job-name prefix, param defaults
└ (existing) surveyor · slurm/{templates,submit,monitor} · core/{fmriprep,mriqc,nordic,ingestion}
```

The existing full GUI pages **remain** as the "advanced / bulk / full-parameter"
surface. The cockpit is the fast path; it does not replace them.

---

## Phase 1 — Controller extraction  (foundation, no visible change)

**Goal:** a pure, testable `advance_one` that the pages *and* the future cockpit
both call. Behavior-preserving: after this phase the GUI works exactly as before,
but submit logic lives in one place.

**New file `src/duckbrain/core/pipeline.py`:**

```python
# Sketch — refine against actual page code when implementing.
from dataclasses import dataclass

@dataclass(frozen=True)
class StageSpec:
    name: str                 # "converted" | "fmriprep" | "mriqc" | "nordic"
    step: str                 # render_sbatch/build_context step key ("dcm2bids", ...)
    job_prefix: str           # "dcm2bids" | "fmriprep" | "mriqc" | "nordic"
    depends_on: str | None    # prior stage that must be COMPLETE (surveyor stage name)
    is_slurm: bool = True

# NB: surveyor STAGES use "converted"; the step/template key is "dcm2bids".
STAGE_SPECS = { ... }  # keyed by surveyor stage name

def tag_for(sub: str, ses: str) -> str:
    return f"{sub}_{ses}" if ses else sub

def advance_one(config, stage, subject, session, *, export_only=False, **overrides) -> str | None:
    """Submit (or export) the job that advances one unit through `stage`.

    Returns the SLURM job_id, or the exported script path if export_only, or
    None for synchronous stages (ingestion — not handled here in v1).
    Raises on misconfig (missing container/license) so the caller surfaces it.
    """
    # 1. assemble stage_specifics (container path, fs license, session filter,
    #    dcm2bids config json, flags) — lifted verbatim from the page loop body
    # 2. ctx = build_context(config, spec.step, subject=..., session=..., **specifics, **overrides)
    # 3. script = render_sbatch(spec.step, ctx)
    # 4. return submit_job(script, f"{spec.job_prefix}_{tag_for(...)}", scripts_dir=log_dir)
```

**Extract from (exact current locations — re-anchor by symbol):**
- `converted`: `gui/pages/3_BIDS_Conversion.py`, the bulk-submit block
  (`build_context(config, "dcm2bids", ...)` → `submit_job(..., f"dcm2bids_{tag}", ...)`).
  Note it auto-generates `dcm2bids_config.json` if missing (`generate_session_config`
  / `save_dcm2bids_config`) — that logic moves into the controller.
- `fmriprep`: `gui/pages/4_Preprocessing.py`, `tab_fmriprep` submit block
  (session filter via `write_session_filter`; params: output_spaces, nprocs,
  mem_gb, anat_only, use_derivatives, extra_flags).
- `mriqc`: `4_Preprocessing.py`, `tab_mriqc` block.
- `nordic`: `4_Preprocessing.py`, `tab_nordic` block (uses `get_bold_runs`).

**Then refactor** each page's loop body to call `advance_one(...)` instead of
inlining the trio. Keep the pages' widgets/validation; only the submit core moves.

**Tests** (`tests/test_pipeline.py`, new): monkeypatch `submit_job` to capture
`(script, job_name, scripts_dir)`; assert job_name == `f"{prefix}_{tag}"` for
sessionless and multi-session; assert misconfig raises; assert `export_only`
writes a script. Reuse tmp-project fixtures from `tests/test_surveyor.py`.

**Checkpoint 1 (commit):** full suite green; GUI submits behave identically.
Commit msg: `Extract per-stage submit into core.pipeline.advance_one`.

---

## Phase 2 — Live-state fusion  (correctness linchpin — must land before UI)

**Why first-before-UI:** the surveyor reads only the filesystem, so a *running*
job reads as `partial` (verified: the two live fMRIPrep jobs on 2026-07-10 grade
`partial` while actively running). A cockpit that offered "re-run" on those cells
would double-submit. The UI cannot be safe until job state is fused in.

**Add to `core/pipeline.py`:**

```python
def survey_live(config) -> pd.DataFrame:
    """survey_project() overlaid with SLURM job state.

    Adds, per (unit, stage), a job-state overlay derived by matching
    f"{prefix}_{tag}" against list_jobs() (active) and job_history() (recent).
    """
    matrix = survey_project(config)
    active = { j.name: j for j in list_jobs() }          # squeue
    recent = { j.name: j for j in job_history(days=7) }  # sacct
    # for each row/stage: key = f"{spec.job_prefix}_{tag}"
    #   in active & state RUNNING/PENDING  -> overlay "running"/"queued"
    #   in recent & state FAILED/CANCELLED/TIMEOUT -> overlay "failed"
    #   else keep filesystem Status
    ...
```

**Representation choice (decide at implementation):** either (a) extend the
`Status` enum with `RUNNING/QUEUED/FAILED`, or (b) add a parallel `*_job` column
overlay and let the UI merge for display. **Leaning (b)** — keeps `survey_project`
and the Nipoppy bagel export (which maps the 4 canonical statuses) untouched, and
keeps filesystem-truth and scheduler-truth as separate, debuggable facts.

**Tests:** fake `list_jobs`/`job_history` returning `JobInfo(name="fmriprep_04",
state="RUNNING")` etc.; assert overlay flips the right cell; assert an unmatched
job name is ignored; assert a completed-on-disk unit isn't downgraded by a stale
sacct FAILED for an older attempt (prefer filesystem COMPLETE over stale failure).

**Checkpoint 2 (commit):** `survey_live` covered; Project Status still renders
(can optionally show running/failed badges now, still read-only).
Commit msg: `Add survey_live: overlay SLURM job state on the status matrix`.

---

## Phase 3 — Cockpit UI  (the actionable board)

Rework `gui/pages/0_Project_Status.py` to drive `survey_live` + `advance_one`.

**Per-cell behavior (dependency- and job-state-gated):**
- `complete` → 🟢, no action (optional: "re-run" under an "advanced" toggle).
- `running`/`queued` → 🔵/⏳ badge, **no run button** (prevents double-submit),
  optional link to Job Monitor / log.
- `failed` → 🔴, offer "retry" (same as run).
- `missing` **and** `depends_on` is `complete` → ▶ **run** affordance.
- `missing` **and** dependency not met → ⚪ inert (greyed; tooltip "needs
  {dependency} first").
- `partial` (filesystem, no live job) → 🟡, offer "resume/re-run".

**Run affordance = `st.popover`** per actionable cell: shows stage param defaults
from config (fMRIPrep: spaces/nprocs/mem/flags), a Run + an "open full page"
button. Run calls `advance_one(config, stage, sub, ses, **overrides)`, then
`st.toast` + `st.rerun`.

**Layout:** `st.dataframe` is display-only; actionable cells need widgets, so
render the matrix as a grid of `st.columns` rows (one row per unit, one column
per stage) OR keep the dataframe overview + a compact "actions" panel for the
selected unit. **Leaning:** dataframe stays as the at-a-glance overview (already
built), plus a **"Run next step" action strip**: pick a unit (or "all units whose
next step is X"), see the dependency-valid next action, run it. Avoids fighting
`st.dataframe`'s non-interactivity while still being a cockpit.

**Auto-refresh:** `st_autorefresh` (or a manual ↻ + `survey_live` cache with
short ttl) so running jobs animate toward done.

**Safety guards:**
- Never show run on `running`/`queued`.
- A "run all missing in column X" bulk button (optional) MUST show a count and a
  confirm (one click could otherwise submit ~37 fMRIPrep jobs).
- Respect misconfig: if `advance_one` raises (no container/license), surface it
  in the cell/toast, don't crash the page.

**Tests** (`tests/test_status_page.py`, extend): AppTest — a `missing` cell with
met dependency exposes a run control; a `running` cell does not; clicking run
invokes `advance_one` (monkeypatched) with the right args; dependency-unmet cell
is inert.

**Checkpoint 3 (commit):** cockpit usable end-to-end in AppTest; eyeball in a
live browser session (AppTest can't judge feel — same caveat as the folder
picker, TODO #1). Commit msg: `Make Project Status actionable: run next step per unit`.

---

## Phase 4 — Polish (optional, defer)

- Guarded "run whole column" bulk submit (count + confirm).
- Durable submission log (Job Monitor is ephemeral; surveyor notes flagged this).
  A small append-only TSV under `code/logs/` recording `{ts, unit, stage, job_id}`
  would also give the cockpit a "what did I launch" history independent of sacct's
  7-day window.
- Deep-links from cockpit cells into the full stage pages with the unit
  preselected.

---

## Open decisions

1. **Ingestion in/out of the actionable board for v1?** Recommendation: **out**
   (read-only status + deep-link). Rationale in load-bearing fact #5 — it's
   synchronous and maps raw folders → units, so it doesn't fit the cell-action
   model without importing most of the Ingestion page's complexity. *(Confirm
   with Ben — this is the one commitment that shapes Phase 3.)*
2. **Status representation for job state:** extend enum vs. parallel overlay
   column. Leaning overlay (keeps bagel export + `survey_project` untouched).
3. **Matrix interactivity:** action-strip vs. full widget grid. Leaning
   action-strip (don't fight `st.dataframe`).

## Risks

- **Double-submit** if job-state fusion is incomplete → Phase 2 gates Phase 3.
  Non-negotiable ordering.
- **Stale sacct** downgrading a genuinely-complete unit → prefer filesystem
  COMPLETE over a `failed` overlay for a prior attempt.
- **Streamlit rerun/popover ergonomics** — the fiddly part of Phase 3; budget
  time for live-browser tuning, not just AppTest.
- **Mass-submit footgun** — bulk actions need count + confirm.

## Lift summary

| Phase | Rough size | Risk |
|---|---|---|
| 1 Controller | ~200 LOC new + edits to 2–3 pages + tests | Low (behavior-preserving; de-dups) |
| 2 Live-state | ~120 LOC + tests | Low–med (join key exists; stale-sacct edge) |
| 3 Cockpit UI | `0_Project_Status.py` ~150→~350 LOC + AppTest | Med (Streamlit ergonomics) |
| 4 Polish | modest | Low |

Medium lift overall. Phase 1 is worth doing regardless (detangles submit logic
from the pages). Phases 2–3 are additive; 2 makes the existing board *safe* to
act on, 3 makes it the cockpit.

---

## How to resume (cold-start checklist)

1. Read the **Status tracker** row states above.
2. `git log --oneline -8` — confirm which checkpoint commits landed.
3. `python -m pytest tests/ -q` — confirm green baseline.
4. Re-anchor the "Extract from" locations by **symbol name** (line numbers drift):
   `grep -n "submit_job\|build_context" src/duckbrain/gui/pages/{3_BIDS_Conversion,4_Preprocessing}.py`.
5. Continue at the first ⬜/🟡 phase. Commit at its checkpoint before stopping.
