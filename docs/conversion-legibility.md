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

## Deferred, and why — binding granularity

**`FmapRule` is keyed on task label, not on run.** `bold_tasks` is built by
deduplicating sanitized task labels, so a session with two runs of one task cannot
bind them to different fieldmaps.

That is the `mmm_fmap_check` case exactly: a pair reshot mid-session, where runs
acquired afterwards should use pair 2. `#5` records that the automatic rule has no
temporal-proximity logic and that the explicit binding is the escape hatch — but
the escape hatch cannot express this particular escape.

It is deferred rather than folded in because it **changes a persisted config
schema** (`[fmap_mapping]` rows would need an optional `run`, and every existing
project config has to keep loading), and because there is a real design choice
underneath: per-run binding, or infer from acquisition time, or both. Presentation
work does not depend on the answer — a plan-derived view renders whatever the
binding says — so it is genuinely separable. **Settle it before Phase 4 ships a
view that implies a granularity the model doesn't have.**

## Not doing

- A Sankey / node-graph of series → BIDS. plotly is already a dependency so it is
  cheap, but it is a picture you look at once; the grouped sections are a thing
  you work in.
- Restyling the cockpit. Its hand-rolled `st.columns` grid exists because cells
  must be popovers, and that is the right call — see `docs/pipeline-cockpit.md`.
- A shared table component. Five tables that genuinely differ; the duplication is
  not the problem.
