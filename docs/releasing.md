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

## After

Nothing is published to PyPI — distribution is `git clone`, so the tag *is* the
release. Users on Talapas pick it up with `git pull` in their own checkout; this
checkout also serves the OnDemand app, so the release is live here the moment it
is committed, tag or no tag.
