# Releasing duckbrain

Semver, annotated git tags `vX.Y.Z`, and a Keep-a-Changelog `CHANGELOG.md`. This
file is the procedure; the *reasoning* behind the version rules is in
`CLAUDE.md`'s rules section and in `core/consistency.py`.

## Before you touch anything

- `git status` clean, `python -m pytest tests/ -q` green.
- `main` pushed and level with `origin/main` — releases are cut from `main`.

## Choosing the number

Pre-1.0, **minor carries the breaking signal** (`0.1` → `0.2`), because semver
reserves that role for major and there is no major yet. Patch is for fixes within
a line.

This is not only bookkeeping here. `core/consistency.py`'s `_release_line()`
reduces any version to `major.minor`, and `check_duckbrain_drift()` raises a
`duckbrain-drift` note against existing `converted` and `nordic` derivatives whose
recorded line differs from the running one. So:

- `0.1.0` → `0.1.1` is **invisible** to already-converted data.
- `0.1.0` → `0.2.0` **flags every dataset** produced under the 0.1 line.

That flag is `note` severity (cockpit shows `st.info`, not a warning) and it is
working as designed — but decide it deliberately rather than discovering it. Ask
whether the release changed a **recipe duckbrain authors** (the dcm2bids config,
the NORDIC m-file) or only the flags it passes to a container. A feature that
leaves every existing project's emitted config byte-identical is a weaker case for
minor than one that changes what gets written.

## What ships together

**The cut is by kind, not by size.** Two questions sort a queue of finished work
into releases, and neither one is "how much is it":

1. **Does it change a recipe duckbrain authors?** That is the minor-vs-patch test
   above, with the mechanical consequence `_release_line()` gives it — a minor
   bump flags every existing `converted` and `nordic` derivative. A release that
   changes what duckbrain *writes* should flag them; one that changes only how
   duckbrain is *installed* should not have to.
2. **Is it schedulable at all?** Some open work is blocked on data, or on another
   item's design settling, and not on effort. That cannot be committed to a
   release without making the release hostage to something nobody controls.

Bundling everything collapses both distinctions at once: finished, zero-risk
packaging work sits unreleased behind an open architectural question, and the
whole thing waits on fixtures that may never arrive. **Ship the schedulable
half.** `v0.5.0` was cut exactly that way — `#2`'s writing went out while the
rest of `#2`, which needs a non-maintainer account and an answer from an office
outside this project, stayed open below it. `core/updates.py` compares against
published Releases, so work held back is work the beta testers cannot see.

**The cost this accepts, stated once.** Several minor bumps instead of one means
a user sees the `duckbrain-drift` note several times rather than once. Accepted
deliberately: it is `note` severity, and a release that genuinely changes what
duckbrain writes is telling the truth each time it fires. The alternative —
suppressing real provenance drift to keep a notification quiet — is the trade
this project has consistently refused elsewhere.

## Steps

1. **Bump the version.** One place only: `__version__` in
   `src/duckbrain/__init__.py`. `pyproject.toml` declares `dynamic = ["version"]`
   and hatchling reads it from there — do not add a second literal.
2. **Close the changelog section.** Rename `## [Unreleased]` to
   `## [X.Y.Z] — YYYY-MM-DD`, and add a fresh empty `## [Unreleased]` above it.
   Update the link refs at the foot of the file: point `[Unreleased]` at
   `compare/vX.Y.Z...HEAD` and add `[X.Y.Z]` for the new tag.
3. **Commit** — `Release vX.Y.Z`, body summarizing the headline changes.
4. **Tag** — `git tag -a vX.Y.Z -m "duckbrain vX.Y.Z"`. Annotated, not
   lightweight: `git describe` is what stamps provenance into every derivative,
   and it prefers annotated tags.
5. **Push both** — `git push --follow-tags origin main`.
6. **Verify the stamp.** `git describe --tags` must print exactly `vX.Y.Z` with no
   `-N-g<sha>` suffix and no `-dirty`. That string is what lands in
   `GeneratedBy` for anything converted from this checkout, so a dirty tree at
   tag time is a permanently wrong provenance record.
7. **Publish the tag as a GitHub Release** — body is the `CHANGELOG.md` section
   you just closed, verbatim.

   With the `gh` CLI, on a machine that has it (Talapas does not):

   ```bash
   gh release create vX.Y.Z --title "duckbrain vX.Y.Z" --notes-file notes.md
   ```

   Otherwise the web UI: **Releases → Draft a new release → Choose an existing tag
   `vX.Y.Z` → paste the changelog section → Publish**.

   **Do not skip this.** A pushed tag notifies nobody and is invisible to the API.
   The Release is the whole announcement channel — it emails everyone watching
   Releases, and it is what `core/updates.py` queries, so the GUI's "newer version
   available" line stays dark until you publish. Tag pushed but Release unpublished
   is the one state where users are behind and *nothing* says so.

## After

Nothing is published to PyPI — distribution is `git clone`. Users on Talapas pick a
release up with `git pull` in their own checkout; this checkout also serves the
OnDemand app, so the code is live here the moment it is committed, tag or no tag.

That last property is why the announcement is a separate act from the tag. The
maintainer never experiences being out of date, so nothing about cutting a release
surfaces the fact that everyone else does — the two users who reported this
project's bugs have no signal at all beyond the Release notification and the GUI
line it drives.
