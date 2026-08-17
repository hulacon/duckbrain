"""Expectations tier: a declared-expectations TOML -> the ``resolution`` view.

Reads the dataset-owned declaration (``<root>/expectations/dataset.toml``),
expands it into per-unit expected rows keyed like observed ``files`` rows,
ingests the canonical ``sub-*_sessions.tsv`` files and the root ``phenotype/``
instrument TSVs, loads disposition-tagged exceptions, and defines the
four-state ``resolution`` view:

  present  — observed count within [runs_min, runs_max]
  missing  — below runs_min, no status-eligible exception
  excepted — out of range, matched by a status-eligible exception
             (disposition: pending dominates accepted)
  surplus  — present but undeclared, or above runs_max with no exception

Judgment is the SQL join in the view — no engine code. The declaration is
DECLARED knowledge (acquisition notes, protocol), never derived from the data
it judges: a shortfall must read as a shortfall, never shrink the expectation.
Rebuild is cheap and idempotent; run it after every sweep (it only replaces
its own tables/views, never ``files``/``datasets``).
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from typing import Any

import duckdb

#: Entities that individuate acquisitions within a unit. Observed run counts
#: are distinct combinations of these — collapsing space/res/den/hemi so a
#: derivative run in three output spaces still counts once.
IDENTITY_ENTITIES: tuple[str, ...] = ("acq", "ce", "rec", "dir", "run", "echo", "part")


def expand_units(decl: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Session-type templates + per-subject overrides -> expected unit rows."""
    active: list[str] = decl["subjects"]["active"]
    session_types: Mapping[str, list[str]] = decl["session_types"]
    rows: list[dict[str, Any]] = []

    def add(
        dataset: str,
        sub: str,
        ses: str,
        datatype: str,
        task: str | None,
        suffix: str,
        desc: str | None,
        lo: int,
        hi: int,
        recording: str | None = None,
    ) -> None:
        rows.append(
            dict(
                dataset_relpath=dataset,
                sub=sub,
                ses=ses,
                datatype=datatype,
                task=task,
                suffix=suffix,
                des=desc,
                runs_min=lo,
                runs_max=hi,
                recording=recording,
            )
        )

    for unit in decl["units"]:
        subjects = [unit["subject"]] if "subject" in unit else active
        sessions = unit.get("sessions") or session_types[unit["session_type"]]
        lo = unit.get("runs_min", unit.get("runs"))
        hi = unit.get("runs_max", unit.get("runs"))
        if lo is None or hi is None:
            raise SystemExit(f"unit missing runs/runs_min+runs_max: {unit}")
        task = unit.get("task")
        for sub in subjects:
            for ses in sessions:
                add(".", sub, ses, unit["datatype"], task, unit["suffix"], None, lo, hi)
                if unit["suffix"] == "bold":
                    if unit.get("sbref", True):
                        add(".", sub, ses, "func", task, "sbref", None, lo, hi)
                    if unit.get("events", False):
                        add(".", sub, ses, "func", task, "events", None, lo, hi)
                    # physio expected for every bold run (protocol intent);
                    # eyetracking only where a unit opts in. Both share
                    # suffix "physio", split by the recording dimension.
                    if unit.get("physio", True):
                        add(".", sub, ses, "func", task, "physio", None, lo, hi, recording="physio")
                    if unit.get("eyetracking", False):
                        add(".", sub, ses, "func", task, "physio", None, lo, hi, recording="eye")
                    for deriv in decl["derivatives"]["complete_for_bold"]:
                        add(deriv, sub, ses, "func", task, "bold", "preproc", lo, hi)
    return rows


def expand_exceptions(decl: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Declaration ``[[exceptions]]`` entries -> one row per (subject, session)."""
    rows: list[dict[str, Any]] = []
    for exc in decl.get("exceptions", []):
        # Status rule: only exceptions naming task/datatype/suffix/recording
        # may flip a unit to "excepted"; session-level notes are annotation-only.
        eligible = any(k in exc for k in ("task", "datatype", "suffix", "recording"))
        for ses in exc["sessions"]:
            rows.append(
                dict(
                    sub=exc["subject"],
                    ses=ses,
                    task=exc.get("task"),
                    datatype=exc.get("datatype"),
                    suffix=exc.get("suffix"),
                    recording=exc.get("recording"),
                    category=exc["category"],
                    disposition=exc["disposition"],
                    status_eligible=eligible,
                    description=exc["description"],
                )
            )
    return rows


def scope_predicate(scopes: list[Mapping[str, Any]]) -> str:
    """One OR-branch per scoped dataset, over the observed ``files`` table."""
    branches = []
    for sc in scopes:
        conds = [f"dataset_relpath = '{sc['dataset']}'", "ext != '.json'"]
        if "datatypes" in sc:
            vals = ", ".join(f"'{v}'" for v in sc["datatypes"])
            conds.append(f"datatype IN ({vals})")
        if "suffixes" in sc:
            vals = ", ".join(f"'{v}'" for v in sc["suffixes"])
            conds.append(f"suffix IN ({vals})")
        if "descs" in sc:
            vals = ", ".join(f"'{v}'" for v in sc["descs"])
            conds.append(f'"desc" IN ({vals})')
        if "exclude_suffixes" in sc:
            vals = ", ".join(f"'{v}'" for v in sc["exclude_suffixes"])
            conds.append(f"suffix NOT IN ({vals})")
        branches.append("(" + " AND ".join(conds) + ")")
    return " OR ".join(branches)


def run_expectations(
    root: pathlib.Path,
    db_path: pathlib.Path,
    decl: Mapping[str, Any],
) -> dict[str, Any]:
    """Ingest *decl* into *db_path* and (re)define the ``resolution`` view.

    Returns a summary: unit/exception/session/phenotype row counts and the
    per-status tally of the resolution view.
    """
    root = root.resolve()
    units = expand_units(decl)
    exceptions = expand_exceptions(decl)
    con = duckdb.connect(str(db_path))

    # -- canonical session metadata (the BIDS-tree sub-*_sessions.tsv win;
    # acquisition-time copies elsewhere are scratch) --
    if sorted(root.glob("sub-*/sub-*_sessions.tsv")):
        con.execute(f"""
            CREATE OR REPLACE TABLE sessions AS
            SELECT regexp_extract(filename, 'sub-([0-9a-zA-Z]+)_sessions', 1) AS sub,
                   replace(session_id, 'ses-', '') AS ses, *
            FROM read_csv('{root}/sub-*/sub-*_sessions.tsv', delim='\t',
                          header=true, union_by_name=true, all_varchar=true,
                          filename=true)""")
    else:
        # A dataset with no session TSVs still gets the table, empty — a
        # missing table reads as "tier not built", which would be a lie here.
        con.execute("CREATE OR REPLACE TABLE sessions (sub VARCHAR, ses VARCHAR)")

    # -- phenotype instruments (root phenotype/*.tsv; one wide row per
    # participant x instrument, columns unioned across instruments; the JSON
    # data dictionaries stay on disk, visible via files_supplemental) --
    if sorted(root.glob("phenotype/*.tsv")):
        con.execute(f"""
            CREATE OR REPLACE TABLE phenotype AS
            SELECT regexp_extract(filename, '([^/]+)\\.tsv$', 1) AS instrument,
                   replace(participant_id, 'sub-', '') AS sub, *
            FROM read_csv('{root}/phenotype/*.tsv', delim='\t', header=true,
                          union_by_name=true, all_varchar=true, filename=true)""")
    else:
        con.execute("CREATE OR REPLACE TABLE phenotype (instrument VARCHAR, sub VARCHAR)")

    con.execute("""
        CREATE OR REPLACE TABLE expected_units (
            dataset_relpath VARCHAR, sub VARCHAR, ses VARCHAR,
            datatype VARCHAR, task VARCHAR, suffix VARCHAR, des VARCHAR,
            recording VARCHAR, runs_min INTEGER, runs_max INTEGER)""")
    if units:  # duckdb's executemany refuses an empty parameter list
        con.executemany(
            "INSERT INTO expected_units VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                [
                    u["dataset_relpath"],
                    u["sub"],
                    u["ses"],
                    u["datatype"],
                    u["task"],
                    u["suffix"],
                    u["des"],
                    u["recording"],
                    u["runs_min"],
                    u["runs_max"],
                ]
                for u in units
            ],
        )

    con.execute("""
        CREATE OR REPLACE TABLE expectation_exceptions (
            sub VARCHAR, ses VARCHAR, task VARCHAR, datatype VARCHAR,
            suffix VARCHAR, recording VARCHAR, category VARCHAR,
            disposition VARCHAR, status_eligible BOOLEAN,
            description VARCHAR)""")
    if exceptions:  # a declaration with no exceptions is legal
        con.executemany(
            "INSERT INTO expectation_exceptions VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                [
                    e["sub"],
                    e["ses"],
                    e["task"],
                    e["datatype"],
                    e["suffix"],
                    e["recording"],
                    e["category"],
                    e["disposition"],
                    e["status_eligible"],
                    e["description"],
                ]
                for e in exceptions
            ],
        )

    identity = ", ".join(f"coalesce(CAST({e} AS VARCHAR), '')" for e in IDENTITY_ENTITIES)
    con.execute(f"""
        CREATE OR REPLACE VIEW observed_units AS
        SELECT dataset_relpath, sub, ses, datatype, task, suffix,
               "desc" AS des,
               CASE WHEN suffix = 'physio' THEN
                    CASE WHEN recording = 'eye' THEN 'eye' ELSE 'physio' END
               END AS recording_class,
               count(DISTINCT concat_ws('|', {identity})) AS observed_n
        FROM files
        WHERE {scope_predicate(decl["scope"])}
        GROUP BY ALL""")

    # Exception matching happens at unit grain; pending dominates accepted so
    # to-do items keep reporting even when an accepted note also matches.
    con.execute("""
        CREATE OR REPLACE VIEW resolution AS
        WITH joined AS (
            SELECT
                coalesce(e.dataset_relpath, o.dataset_relpath) AS dataset_relpath,
                coalesce(e.sub, o.sub) AS sub,
                coalesce(e.ses, o.ses) AS ses,
                coalesce(e.datatype, o.datatype) AS datatype,
                coalesce(e.task, o.task) AS task,
                coalesce(e.suffix, o.suffix) AS suffix,
                coalesce(e.des, o.des) AS des,
                coalesce(e.recording, o.recording_class) AS recording,
                e.runs_min, e.runs_max,
                coalesce(o.observed_n, 0) AS observed_n,
                e.dataset_relpath IS NOT NULL AS declared
            FROM expected_units e
            FULL OUTER JOIN observed_units o
              ON e.dataset_relpath = o.dataset_relpath
             AND e.sub = o.sub AND e.ses = o.ses
             AND coalesce(e.task, '') = coalesce(o.task, '')
             AND e.datatype = o.datatype AND e.suffix = o.suffix
             AND coalesce(e.des, '') = coalesce(o.des, '')
             AND coalesce(e.recording, '') = coalesce(o.recording_class, '')
        ),
        annotated AS (
            SELECT j.*,
                max(CASE WHEN x.status_eligible THEN 1 ELSE 0 END) AS has_eligible_exc,
                max(CASE WHEN x.status_eligible AND x.disposition = 'pending'
                         THEN 1 ELSE 0 END) AS has_pending,
                string_agg(DISTINCT x.category || ': ' || x.description,
                           ' | ') AS exception_notes
            FROM joined j
            LEFT JOIN expectation_exceptions x
              -- dataset-level blanket notes (sub-* x ses-*, no unit narrowing)
              -- stay out of the per-unit annotation join: they would annotate
              -- every unit and drown the column in noise
              ON NOT (x.sub = '*' AND x.ses = '*' AND NOT x.status_eligible)
             AND (x.sub = '*' OR x.sub = j.sub)
             AND (x.ses = '*' OR x.ses = j.ses)
             AND (x.task IS NULL OR x.task = j.task)
             AND (x.datatype IS NULL OR x.datatype = j.datatype)
             AND (x.suffix IS NULL OR x.suffix = j.suffix)
             AND (x.recording IS NULL OR x.recording = j.recording)
            GROUP BY ALL
        )
        SELECT dataset_relpath, sub, ses, datatype, task, suffix, des,
               recording, runs_min, runs_max, observed_n,
               CASE
                   WHEN NOT declared THEN 'surplus'
                   WHEN observed_n BETWEEN runs_min AND runs_max THEN 'present'
                   WHEN has_eligible_exc = 1 THEN 'excepted'
                   WHEN observed_n > runs_max THEN 'surplus'
                   ELSE 'missing'
               END AS status,
               CASE WHEN has_eligible_exc = 1 AND NOT
                         (observed_n BETWEEN runs_min AND runs_max)
                    THEN CASE WHEN has_pending = 1
                              THEN 'pending' ELSE 'accepted' END
               END AS disposition,
               exception_notes
        FROM annotated""")

    tally = con.execute("""
        SELECT status, coalesce(disposition, '') AS disposition, count(*)
        FROM resolution GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()

    def _count(table: str) -> int:
        row = con.execute(f"SELECT count(*) FROM {table}").fetchone()
        return int(row[0]) if row else 0

    summary: dict[str, Any] = {
        "units": len(units),
        "exceptions": len(exceptions),
        "sessions": _count("sessions"),
        "phenotype": _count("phenotype"),
        "tally": [(status, disposition, int(n)) for status, disposition, n in tally],
    }
    print(
        f"{summary['units']} expected units, {summary['exceptions']} exception "
        f"rows, {summary['sessions']} session rows, "
        f"{summary['phenotype']} phenotype rows -> {db_path}"
    )
    for status, disposition, n in summary["tally"]:
        print(f"  {status:9s} {disposition:9s} {n:5d}")
    not_ok = con.execute("""
        SELECT dataset_relpath, sub, ses, task, suffix, runs_min, runs_max,
               observed_n, status
        FROM resolution WHERE status IN ('missing', 'surplus')
        ORDER BY status, dataset_relpath, sub, ses, task""").fetchall()
    if not_ok:
        print("\nmissing / surplus:")
        for r in not_ok:
            print("  " + "  ".join(str(v) for v in r))
    con.close()
    return summary
