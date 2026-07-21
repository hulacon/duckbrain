# Conversion legibility — making the mapping tables readable

Design doc for `TODO.md` `#13`. Written 2026-07-21.

## The problem, stated precisely

The Conversion page asks the user to approve a **transformation** — these DICOM
series become those BIDS files — but it only ever shows them the **inputs**. The
output appears exactly once, as `custom_entities` strings buried in a 400-pixel
JSON text area. So the user's actual task is to simulate `generate_config()` in
their head and check the answer.

That is the whole diagnosis. Everything below follows from it.

The fieldmap binding makes it worse, because the thing being decided is a
*relation* (which pair corrects which run) and a relation is not a property of any
one row. Today it is answered by three surfaces jointly and none of them alone:

| Surface | Location | Shows |
|---|---|---|
| Fieldmap Detection | a markdown bullet list | group → AP/PA **series numbers** |
| DICOM Series | `st.dataframe` | those series as rows, **no group** |
| Fieldmap Binding | `st.data_editor` | **task** → group, by names listed only above |

Three namespaces — series numbers, group names, task labels — and the user joins
them by eye. No amount of styling inside any one table fixes a join.

## Principles this follows

1. **Show the outcome, not just the input.** The reviewable artifact is the
   predicted BIDS filename. It makes a whole class of error self-evident: two
   rows resolving to the same name is a collision you can *see*.
2. **Derive the preview from the generated config, never re-derive it.**
   `resolve_fmap_assignments()` already establishes this stance in
   `core/dcm2bids_config.py` — it reuses `_assign_fmap_group` so it "cannot drift
   from what is actually written". A second filename derivation that agreed with
   dcm2bids on Tuesday and not on Friday would be worse than no preview at all.
   So the plan is computed **from the config dict** that dcm2bids will consume.
3. **Colour must be redundant with text.** Roughly 1 in 12 men has some colour
   vision deficiency; a binding perceivable only as a hue is a binding some users
   cannot perceive. Every colour token carries its label.
4. **Editing stays declarative.** See "Why not drag-and-drop" below.
5. **Surface it, don't parse it** — `#5`'s standing rule applies unchanged. The
   preflight panel *reports*; it never silently repairs.

## Why not drag-and-drop

It was the obvious ask and it is the wrong tool, for one shallow reason and one
deciding reason.

**Shallow:** Streamlit has no native drag-and-drop, so it means a custom
bidirectional component with an npm build step. That fights the deployment model
— the OnDemand app runs *this working copy* via `pip install -e`, so built assets
would have to be committed and kept in sync with the checkout. `CLAUDE.md` calls
that launch path out as the thing that has to stay reliable.

**Deciding:** a gesture is the wrong *shape* for the data. A binding has to apply
across 37 subjects and survive a re-run — which is exactly what `[fmap_mapping]`
and `FmapRule` already are: declarative, persisted, dataset-wide. A drag is
per-session and inherently un-reproducible, so a drag UI would have to be
re-expressed as that rule anyway. `SelectboxColumn` *is* the connect-A-to-B
control; it merely doesn't look like one because the thing it connects to isn't
visible beside it. **Fix the visibility, keep the editing declarative.**

## Phases

### Phase 1 — `core/conversion_plan.py` (under the hood)

A new module deriving, from a generated dcm2bids config, exactly what will land
on disk. Pure functions, no Streamlit, unit-testable — same core/GUI split as the
rest of the repo.

- `PlannedFile` — one predicted BIDS file: series number, source description,
  datatype, suffix, entity string, **relative path**, and the fieldmap group it
  binds to (parsed back out of `B0FieldIdentifier` / `B0FieldSource`).
- `plan_conversion(config, series_list, subject, session) -> ConversionPlan` —
  walks `config["descriptions"]`, renders each into a filename, and records every
  series *no* description claims (dcm2bids will silently drop those).
- `ConversionPlan.by_series` — the join key the GUI needs, so the series table can
  gain a "becomes" column without knowing anything about entity ordering.

The `B0map_<group>_sub<X>ses<Y>` identifier is the only channel carrying the
binding, and it is already unique per group, so parsing the group back out of it
is exact rather than heuristic.

### Phase 2 — preflight checks

`plan_warnings(plan, fieldmaps) -> list[PlanWarning]`, each with a severity and a
human sentence. The set worth having:

- **collision** — two planned files with the same path. Real: dcm2bids will write
  one and lose the other.
- **uncorrected** — a bold with no `B0FieldIdentifier` while the session *has* a
  complete pair. Not always wrong (a deliberate `none`), so: info, not error.
- **half pair** — a group holding one direction. Already warned by
  `detect_fieldmaps`; surfaced here so all the warnings are in one place.
- **dropped** — a series no description claims. Usually right (scout, physio) and
  occasionally the bug, so it is reported with its classification and stays quiet
  for the classifications that are *expected* to be dropped.

This is the accessibility win that matters most: it does not depend on the user
knowing what to scan for.

### Phase 3 — the series table shows the outcome

Two new columns on the existing `st.dataframe`: **becomes** (the planned relative
path, or an explicit "not converted") and **fieldmap** (the bound group, as a
colour token). No new widget, no new interaction.

`st.dataframe` cells do not render markdown, so a badge is not available inside
the table. The token is therefore a coloured circle emoji plus the group label —
`🔵 encoding` — which gives the colour scan *and* the redundant text, and works
identically in light and dark themes. (The repo's one existing styled table,
`5_QC_Dashboard.py`, hardcodes `#ffcccc`, which reads poorly on a dark theme;
don't repeat that.) Colour assignment is by group order and stable across every
surface on the page, which is what makes the colour carry information rather than
decorate.

### Phase 4 — the fieldmap view becomes grouped

Replace the bullet list with one section per group: its colour token, its AP/PA
series, and **the bolds bound to it**, plus a final "no distortion correction"
section. The correspondence becomes structural — you read it rather than
reconstruct it. The binding editor stays exactly as it is; it just now sits under
a picture of what it is editing.

### Phase 5 — the JSON/table divergence bug

`3_BIDS_Conversion.py` declares the task/run table the source of truth and
regenerates the JSON from it, but the text area is seeded with `value=auto_json`
under its own widget key. Once the user types in the JSON, later table edits do
not reconcile and which one gets submitted is not visible. That is the
silently-degrading pattern `CLAUDE.md` forbids, so: keep the JSON an explicit
opt-in override, show plainly which source is live, and offer a revert.

## Phase 6 — one table (the point of all of the above)

**Decided 2026-07-21.** Phases 1–5 made each surface more legible but left the
page with *four* tables plus a JSON box — the count went the wrong way. The
per-session review collapses to a single editor, one row per series:

```
Series #  Description           Type   task       run  fieldmap   becomes
2         t1w_mprage            anat   —          —    —          sub-003_ses-02_T1w.nii.gz
3         se_epi_ap             fmap   —          —    🔵 1       sub-003_ses-02_acq-…_dir-AP_epi.nii.gz
9         localizerAuditory_r1  func   localizer  1    🔵 1       sub-003_ses-02_task-localizer_run-1_bold.nii.gz
```

Editable `task` / `run` / `fieldmap`; `becomes` computed from the plan. What
merges is the three surfaces that already share a grain (DICOM Series, Task/Run
Mapping, Conversion Plan). What blocked it was the fourth, which is keyed on
*task* — hence the granularity work below being a **precondition**, not a
nice-to-have.

Notes for whoever builds on this:

- **`st.data_editor` disables columns, not cells.** An anat row's `task` cell
  will look editable even though it means nothing. Validate on read and warn;
  don't try to prevent it.
- **The fieldmap token appears on the fmap rows too**, not just the bolds, so the
  pair↔run link is readable from one row in either direction. It lives in the
  `fieldmap` column rather than being prefixed onto `becomes`, so `becomes` stays
  a real filename you can copy.

## Phase 7 — JSON back-import, explicitly and once

**Bidirectional sync was considered and rejected.** Two editable representations
of one thing means that when both change something has to lose, and Streamlit's
per-key widget state is precisely where that goes wrong — it is the mechanism
behind the Phase 5 bug. More fundamentally **the table is lossy relative to the
JSON**: the JSON can carry criteria beyond `SeriesNumber`, arbitrary
`sidecar_changes`, custom description ids, dcm2bids options. A continuous round
trip would silently drop whatever the table can't represent, which is data loss
dressed as convenience.

Instead: one direction (table → JSON) plus an explicit, user-initiated **"load
this JSON back into the table"** that *reports what it could not represent*. The
reading half already exists — `plan_conversion` parses task, run and group back
out of the descriptions today.

## The granularity decision — settled 2026-07-21

**Bindings attach at series/run level.** Ben's call, on the case of a fieldmap
re-shot *within* one task ("rare, not impossible"), which a task-keyed rule
cannot express at all.

Shape:

- `FmapRule` gains an optional `run`. `run = None` keeps its current meaning —
  *every* run of the task — so every existing `[fmap_mapping]` section keeps
  loading and meaning what it meant.
- A rule naming a run wins over one that doesn't; specific beats general, the
  same precedence explicit-beats-inferred already has.
- Assignment is keyed on `(task, run)` rather than task, which is also what lets
  the unified table put an editable fieldmap cell on a *series* row honestly.

Keying the persisted rule on task+run rather than series number is deliberate:
series numbers are per-session, so a series-keyed rule could not generalize
across subjects, and `[fmap_mapping]` is a project-level statement like
`[task_mapping]` beside it.

## Still open — temporal proximity

Even with run-level bindings, `_assign_fmap_group`'s *automatic* path never
reasons about acquisition time: an unbound task still goes to the first complete
pair. The explicit binding now covers every case that limitation produces, at the
cost of saying so once per study. Inferring it from timestamps stays a candidate
refinement, and the explicit binding is the thing to measure it against. See
`TODO.md` `#5`.

## Not doing

- A Sankey / node-graph of series → BIDS. plotly is already a dependency so it is
  cheap, but it is a picture you look at once; the grouped sections are a thing
  you work in.
- Restyling the cockpit. Its hand-rolled `st.columns` grid exists because cells
  must be popovers, and that is the right call — see `docs/pipeline-cockpit.md`.
- A shared table component. Five tables that genuinely differ; the duplication is
  not the problem.
