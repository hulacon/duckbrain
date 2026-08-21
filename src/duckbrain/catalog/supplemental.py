"""Supplemental tier: files the indexer cannot see -> ``files_supplemental``.

Walks every discovered dataset tree and records each file bids2table emitted
no row for, so *darkness itself is queryable*: "what does the catalog not
understand" becomes SQL over ``files_supplemental``, never a silent gap.

Each row carries a ``category``:

  sidecar   — a .json whose stem pairs with a data file in the same dataset
              (bids2table emits no rows for JSON sidecars, so this also models
              the old ``has_json`` expectation). Two things the pairing is
              deliberately liberal about, and one it is not:

              * The companion need not be *indexed*. A derivative keyed by
                something other than BIDS entities has no indexed rows at all,
                and its sidecars are still sidecars.
              * One secondary suffix is stripped before matching, so
                ``clip.meta.json`` pairs with ``clip.csv``. ``.meta.json`` is a
                common sidecar idiom and the match stays exact.
              * Matching is **exact**, never by prefix. A convention where one
                sidecar covers a family of outputs sharing a prefix (as
                Contract B's stimulus-feature tables do: ``clap_text.meta.json``
                over ``clap_text_words.csv`` + ``clap_text_chunks.csv``) is a
                dataset convention, not something this engine should guess at.
                Those stay ``dark`` here until the dataset declares the rule --
                per contracts 3.2, supplemental-tier categories are
                dataset-owned.
  metadata  — dataset-level bookkeeping (dataset_description.json, README,
              CHANGES, LICENSE, .bidsignore, CITATION.cff)
  dark      — everything else: real files no catalog tier accounts for

Scope is explicit, not silent. For the raw dataset only the top-level entries
matching the dataset's declared ``raw_scope`` globs are walked (default:
``sub-*``, ``phenotype``, ``derivatives``); skipped top-level entries are
printed with file counts so the exclusion is visible in every run. A subtree
that is itself a discovered dataset is pruned — its files are its own
dataset's business — and ``internal``-kind datasets (pipeline scratch) are
dark by design, tagged on the ``datasets`` table and not walked.

Rebuild is cheap and idempotent; run after every sweep (needs the sweep's
``files`` + ``datasets`` tables; only replaces its own table).
"""

from __future__ import annotations

import fnmatch
import os
import pathlib
import re
from collections.abc import Iterator, Sequence
from typing import Any

import duckdb

#: Top-level entries of the *raw* dataset walked by default, as glob patterns.
#: A dataset overrides this in its declaration's ``[catalog] raw_scope`` —
#: e.g. mmmdata excludes ``stimuli/`` (Contract B registry territory) and
#: ``code/``/``inventory/`` (not data) by not listing them.
DEFAULT_RAW_SCOPE: tuple[str, ...] = ("sub-*", "phenotype", "derivatives")

METADATA_NAMES = {
    "dataset_description.json",
    "README",
    "README.md",
    "CHANGES",
    "LICENSE",
    "LICENSE.txt",
    ".bidsignore",
    "CITATION.cff",
}

SUB_RE = re.compile(r"sub-([0-9a-zA-Z]+)")
SES_RE = re.compile(r"ses-([0-9a-zA-Z]+)")


def _walk(
    top: pathlib.Path, root: pathlib.Path, dataset_relpaths: set[str]
) -> Iterator[pathlib.Path]:
    """Files under *top*, nested discovered datasets pruned, sorted order."""
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if str((pathlib.Path(dirpath) / d).relative_to(root)) not in dataset_relpaths
        )
        for f in sorted(filenames):
            yield pathlib.Path(dirpath) / f


def collect_files(
    ds_dir: pathlib.Path,
    root: pathlib.Path,
    dataset_relpaths: set[str],
    is_raw: bool,
    raw_scope: Sequence[str],
) -> tuple[list[pathlib.Path], dict[str, int]]:
    """Files under *ds_dir* with nested datasets pruned, plus, for the raw
    dataset, a tally of top-level entries skipped as out of scope."""
    files: list[pathlib.Path] = []
    skipped: dict[str, int] = {}
    if not is_raw:
        return list(_walk(ds_dir, root, dataset_relpaths)), skipped
    for e in sorted(os.scandir(ds_dir), key=lambda e: e.name):
        if e.is_file(follow_symlinks=False):
            files.append(pathlib.Path(e.path))
        elif e.is_dir(follow_symlinks=False):
            rel = str(pathlib.Path(e.path).relative_to(root))
            if rel in dataset_relpaths:
                continue  # a discovered dataset (e.g. derivatives/*)
            if any(fnmatch.fnmatch(e.name, pat) for pat in raw_scope):
                files.extend(_walk(pathlib.Path(e.path), root, dataset_relpaths))
            else:
                skipped[e.name] = sum(len(fs) for _, _, fs in os.walk(e.path))
    return files, skipped


def _ext_of(path: pathlib.Path) -> str | None:
    """Extension as the catalog spells it: ``.nii.gz`` stays whole."""
    return "".join(path.suffixes[-2:]) if path.name.endswith(".gz") else (path.suffix or None)


def _pairs_with_a_companion(
    stem: str, indexed_stems: set[str], walked_stems: set[str]
) -> bool:
    """Whether a .json stem names a data file beside it.

    Tries the stem as-is, then with one secondary suffix removed so
    ``clip.meta`` finds ``clip``. Both tests are exact: see the module
    docstring on why prefix matching is the dataset's call, not the engine's.
    """
    candidates = [stem]
    base, dot, suffix = stem.rpartition(".")
    # Guard against a "suffix" that is really part of the name (a version like
    # `clip.v2` should not be stripped down to `clip`): only strip something
    # that looks like an extension.
    if dot and base and suffix.isalpha() and len(suffix) <= 8:
        candidates.append(base)
    return any(c in indexed_stems or c in walked_stems for c in candidates)


def run_supplemental(
    root: pathlib.Path,
    db_path: pathlib.Path,
    raw_scope: Sequence[str] = DEFAULT_RAW_SCOPE,
) -> dict[str, Any]:
    """Walk every canonical dataset under *root*; record unindexed files in
    *db_path*. Returns a summary with the per-category tally."""
    root = root.resolve()
    con = duckdb.connect(str(db_path))

    datasets = con.execute("SELECT relpath, skipped, kind FROM datasets").fetchall()
    all_relpaths = {str(d[0]) for d in datasets}
    # Indexed paths per dataset, for the "already in `files`" membership test.
    indexed: dict[str, set[str]] = {}
    # Indexed stems: path minus ext. One half of the sidecar pairing test; the
    # other half is the stems of the files this walk itself sees, collected
    # per dataset below.
    stems: dict[str, set[str]] = {}
    for ds, path, ext in con.execute("SELECT dataset_relpath, path, ext FROM files").fetchall():
        indexed.setdefault(ds, set()).add(path)
        if ext and path.endswith(ext):
            stems.setdefault(ds, set()).add(path[: -len(ext)])

    rows: list[list[Any]] = []
    for rel, skipped_mark, kind in sorted(datasets):
        if skipped_mark:
            continue
        if kind == "internal":
            # pipeline scratch: dark by design, tagged on the datasets
            # table; walking it would flood the tier with Snakemake/work
            # files nobody will ever query for
            print(f"  kind-skip   {rel}  (internal)", flush=True)
            continue
        ds_dir = root if rel == "." else root / rel
        if not ds_dir.is_dir():
            continue
        is_raw = rel == "."
        ds_indexed = indexed.get(rel, set())
        ds_stems = stems.get(rel, set())
        files, scope_skipped = collect_files(ds_dir, root, all_relpaths - {rel}, is_raw, raw_scope)
        # Stems of the non-JSON files in this tree, so a .json can pair with a
        # companion bids2table never indexed. A .json is excluded from the
        # stems it is tested against: two JSONs sharing a stem do not make
        # either one a sidecar.
        walked_stems = {
            fp[: -len(x)]
            for f2 in files
            if not (fp := str(f2.relative_to(ds_dir))).endswith(".json")
            and (x := _ext_of(f2))
            and fp.endswith(x)
        }
        for f in files:
            fp = str(f.relative_to(ds_dir))
            if fp in ds_indexed:
                continue
            if f.name in METADATA_NAMES:
                category = "metadata"
            elif fp.endswith(".json") and _pairs_with_a_companion(
                fp[:-5], ds_stems, walked_stems
            ):
                category = "sidecar"
            else:
                category = "dark"
            try:
                st = f.stat()
                size, mtime = st.st_size, int(st.st_mtime)
            except OSError:
                size, mtime = None, None
            sub = m.group(1) if (m := SUB_RE.search(fp)) else None
            ses = m.group(1) if (m := SES_RE.search(fp)) else None
            rows.append([rel, fp, f.name, _ext_of(f), category, sub, ses, size, mtime])
        for name, n in scope_skipped.items():
            print(f"  scope-skip  {name}/  ({n} files; see module docstring)", flush=True)

    con.execute("""
        CREATE OR REPLACE TABLE files_supplemental (
            dataset_relpath VARCHAR, path VARCHAR, filename VARCHAR,
            ext VARCHAR, category VARCHAR, sub VARCHAR, ses VARCHAR,
            size_bytes BIGINT, mtime_epoch BIGINT)""")
    if rows:  # duckdb's executemany refuses an empty parameter list
        con.executemany("INSERT INTO files_supplemental VALUES (?,?,?,?,?,?,?,?,?)", rows)
    tally = con.execute("""
        SELECT category, count(*), count(DISTINCT dataset_relpath)
        FROM files_supplemental GROUP BY 1 ORDER BY 1""").fetchall()
    dark_by_ds = con.execute("""
        SELECT dataset_relpath, count(*) FROM files_supplemental
        WHERE category = 'dark' GROUP BY 1 ORDER BY 2 DESC LIMIT 15""").fetchall()
    con.close()

    print(f"\n{len(rows)} supplemental rows -> {db_path}")
    for category, n, nds in tally:
        print(f"  {category:9s} {n:7d} rows across {nds} datasets")
    if dark_by_ds:
        print("\ndark files by dataset (top 15):")
        for ds, n in dark_by_ds:
            print(f"  {n:7d}  {ds}")
    return {
        "rows": len(rows),
        "tally": [(c, int(n), int(nds)) for c, n, nds in tally],
    }
