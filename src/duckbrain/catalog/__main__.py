"""CLI for the Contract A catalog engine: ``python -m duckbrain.catalog``.

Verbs — each idempotent, each replacing only its own tables:

  rebuild        sweep + expectations + qc + supplemental, in that order
  sweep          index every discovered dataset -> files + datasets tables
  expectations   declaration -> expected_units/exceptions + resolution view
  qc             decision JSONs -> qc_decisions table
  supplemental   unindexed files -> files_supplemental table

Defaults derive from ``--root``: the catalog lands in ``<root>/inventory/``,
the declaration is read from ``<root>/expectations/dataset.toml``. The
declaration's ``[catalog]`` section carries the dataset-owned indexing scope
(``exclude`` — root-relative dataset paths the sweep skips; ``raw_scope`` —
top-level globs the supplemental walk covers in the raw tree).
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections.abc import Sequence
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    # `tomllib` is 3.11+; pyproject's `tomli; python_version < '3.11'` marker
    # guarantees the fallback below the floor (same spelling as config.py).
    import tomli as tomllib


def load_declaration(path: pathlib.Path) -> dict[str, Any]:
    """Parse the dataset declaration TOML."""
    with open(path, "rb") as f:
        # `dict(...)` so 3.10's untyped tomli fallback doesn't turn the
        # return into `Any` (same reasoning as config._load_toml).
        return dict(tomllib.load(f))


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m duckbrain.catalog", description=__doc__)
    sub = ap.add_subparsers(dest="verb", required=True)
    for verb, doc in (
        ("rebuild", "run all four tiers in order"),
        ("sweep", "index every discovered dataset"),
        ("expectations", "ingest the declaration; define the resolution view"),
        ("qc", "ingest QC decision JSONs"),
        ("supplemental", "record files the indexer emitted no row for"),
    ):
        p = sub.add_parser(verb, help=doc)
        p.add_argument("--root", required=True, type=pathlib.Path, help="BIDS root")
        p.add_argument(
            "--out-dir",
            type=pathlib.Path,
            default=None,
            help="where the catalog lands (default <root>/inventory)",
        )
        p.add_argument(
            "--declaration",
            type=pathlib.Path,
            default=None,
            help="dataset declaration TOML (default <root>/expectations/dataset.toml)",
        )
        if verb in ("rebuild", "sweep"):
            p.add_argument(
                "--exclude",
                action="append",
                default=[],
                help="root-relative dataset path to skip (repeatable; adds to "
                "the declaration's [catalog] exclude list)",
            )
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a catalog verb. Returns the exit code."""
    args = _parse(argv)
    try:
        from duckbrain.catalog import expectations, qc_decisions, supplemental, sweep
    except ImportError as exc:
        # A clear refusal, not a degraded run: pip install 'duckbrain[catalog]'
        raise SystemExit(
            f"the catalog engine needs the 'catalog' extra ({exc}); "
            "fix: pip install 'duckbrain[catalog]'"
        ) from exc

    root: pathlib.Path = args.root.resolve()
    out_dir: pathlib.Path = args.out_dir or root / "inventory"
    db_path = out_dir / "catalog.duckdb"
    decl_path: pathlib.Path = args.declaration or root / "expectations" / "dataset.toml"

    decl: dict[str, Any] | None = None
    if decl_path.is_file():
        decl = load_declaration(decl_path)
    elif args.verb in ("rebuild", "expectations"):
        # rebuild includes the expectations tier, so a missing declaration must
        # refuse loudly rather than quietly produce a catalog with no judgment.
        raise SystemExit(
            f"no declaration at {decl_path}; fix: write one (see the mmmdata "
            "dataset.toml for the schema), pass --declaration, or run the "
            "declaration-free verbs (sweep/qc/supplemental) individually"
        )

    catalog_cfg: dict[str, Any] = decl.get("catalog", {}) if decl else {}
    exclude = [*catalog_cfg.get("exclude", []), *getattr(args, "exclude", [])]
    raw_scope: Sequence[str] = catalog_cfg.get("raw_scope", supplemental.DEFAULT_RAW_SCOPE)

    if args.verb in ("rebuild", "sweep"):
        sweep.run_sweep(root, out_dir, exclude=exclude)
    if args.verb == "expectations" or (args.verb == "rebuild" and decl is not None):
        assert decl is not None  # guarded above; for the type checker
        expectations.run_expectations(root, db_path, decl)
    if args.verb in ("rebuild", "qc"):
        qc_decisions.run_qc_decisions(root, db_path)
    if args.verb in ("rebuild", "supplemental"):
        supplemental.run_supplemental(root, db_path, raw_scope=raw_scope)
    return 0


if __name__ == "__main__":
    sys.exit(main())
