"""QC tier: duckbrain QC decision artifacts -> ``qc_decisions`` table.

duckbrain owns the QC review process and the decision artifact (append-only
per-run JSON); the catalog ingests it. This reads every ``*_decision.json``
from the known decision locations, oldest location first (the same order as
:func:`duckbrain.core.qc.decision_search_dirs`), and materializes one row per
run: the latest run-level verdict (the newest entry carrying no ``domain``
key — domain notes share the file and must never read as the run's verdict),
whether that verdict is a sign-off an identifiable person made, and history
counts.

The read semantics come straight from :mod:`duckbrain.core.qc`
(:func:`~duckbrain.core.qc._history_of`,
:func:`~duckbrain.core.qc.is_signed_off`) — imported, not replicated, which is
half the point of this module living in duckbrain. Both on-disk schemas are
accepted and nothing is ever rewritten: the catalog is derived, never
canonical. The file walk stays local rather than reusing
:func:`~duckbrain.core.qc.load_decisions` because the catalog also records
*which files* contributed to each run (``source_files``), which that loader
does not report.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import duckdb

# _history_of is private to core.qc but this is the same package; importing it
# is what keeps the two on-disk schemas readable from exactly one place.
from duckbrain.core.qc import (
    DECISIONS_SUBDIR,
    LEGACY_DECISION_DIRS,
    QC_SUBDIR,
    _history_of,
    is_signed_off,
)

ENTITY_RE = {
    "sub": re.compile(r"sub-([0-9a-zA-Z]+)"),
    "ses": re.compile(r"ses-([0-9a-zA-Z]+)"),
    "task": re.compile(r"task-([0-9a-zA-Z]+)"),
    "run": re.compile(r"run-([0-9a-zA-Z]+)"),
}
SUFFIX_RE = re.compile(r"_([a-zA-Z0-9]+)$")


def decision_dirs(root: pathlib.Path) -> list[pathlib.Path]:
    """Everywhere decisions may live under *root*, oldest location first.

    Mirrors :func:`duckbrain.core.qc.decision_search_dirs` with the default
    duckbrain derivatives location, from a BIDS root rather than a config —
    the engine judges a tree, not a project."""
    derivatives = root / "derivatives"
    legacy = [derivatives / name for name in LEGACY_DECISION_DIRS]
    return [*legacy, derivatives / "duckbrain" / QC_SUBDIR / DECISIONS_SUBDIR]


def run_qc_decisions(root: pathlib.Path, db_path: pathlib.Path) -> dict[str, Any]:
    """Ingest decision JSONs under *root* into *db_path*. Returns a summary."""
    root = root.resolve()

    # Merge per run_key across locations, oldest location first, so the
    # current location's entries land last and read as most recent.
    merged: dict[str, list[dict[str, Any]]] = {}
    sources: dict[str, list[str]] = {}
    n_files = 0
    unreadable: list[str] = []
    for base in decision_dirs(root):
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*_decision.json")):
            n_files += 1
            try:
                data = json.loads(f.read_text())
            except Exception:
                unreadable.append(str(f.relative_to(root)))
                continue
            if not isinstance(data, dict):
                unreadable.append(str(f.relative_to(root)))
                continue
            run_key = str(data.get("run_key") or f.name.removesuffix("_decision.json"))
            merged.setdefault(run_key, []).extend(_history_of(data))
            sources.setdefault(run_key, []).append(str(f.relative_to(root)))

    rows: list[list[Any]] = []
    for run_key, entries in sorted(merged.items()):
        run_level = [e for e in entries if not e.get("domain")]
        domain_notes = [e for e in entries if e.get("domain")]
        latest = run_level[-1] if run_level else None
        ents = {
            k: (m.group(1) if (m := rx.search(run_key)) else None) for k, rx in ENTITY_RE.items()
        }
        m = SUFFIX_RE.search(run_key)
        rows.append(
            [
                run_key,
                ents["sub"],
                ents["ses"],
                ents["task"],
                ents["run"],
                m.group(1) if m else None,
                latest.get("decision") if latest else None,
                latest.get("reviewer") if latest else None,
                bool(latest.get("automated")) if latest else None,
                is_signed_off(latest),
                latest.get("timestamp") if latest else None,
                latest.get("reason") if latest else None,
                len(run_level),
                len(domain_notes),
                ";".join(sources[run_key]),
            ]
        )

    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE OR REPLACE TABLE qc_decisions (
            run_key VARCHAR, sub VARCHAR, ses VARCHAR, task VARCHAR,
            run VARCHAR, suffix VARCHAR,
            decision VARCHAR, reviewer VARCHAR, automated BOOLEAN,
            signed_off BOOLEAN, "timestamp" VARCHAR, reason VARCHAR,
            n_entries INTEGER, n_domain_notes INTEGER, source_files VARCHAR)""")
    if rows:  # duckdb's executemany refuses an empty parameter list
        con.executemany("INSERT INTO qc_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    tally = con.execute("""
        SELECT decision, signed_off, count(*) FROM qc_decisions
        GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
    con.close()

    print(f"{n_files} decision files -> {len(rows)} runs -> {db_path}")
    for decision, signed, n in tally:
        print(f"  {str(decision):12s} signed_off={str(signed):5s} {n:5d}")
    if unreadable:
        print(f"unreadable ({len(unreadable)}):")
        for u in unreadable:
            print(f"  {u}")
    return {
        "files": n_files,
        "runs": len(rows),
        "unreadable": unreadable,
        "tally": [(d, bool(s), int(n)) for d, s, n in tally],
    }
