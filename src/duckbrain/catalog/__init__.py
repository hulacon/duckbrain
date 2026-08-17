"""Contract A catalog engine: index a BIDS tree into a queryable DuckDB catalog.

The catalog answers "what data exists, how was it processed, and what did QC
decide" as SQL over one file (``<root>/inventory/catalog.duckdb``), replacing
directory walks and curated manifests. Four tiers, one module each, every one
rebuildable independently and idempotent (each replaces only its own tables):

- :mod:`.sweep` — bids2table over every discovered dataset (raw + each
  derivative) -> ``files`` + ``datasets`` (provenance) tables
- :mod:`.expectations` — a dataset-owned TOML declaration -> ``expected_units``,
  ``expectation_exceptions``, ``sessions``, ``phenotype`` tables and the
  four-state ``resolution`` view (present / missing / excepted / surplus)
- :mod:`.qc_decisions` — duckbrain QC decision JSONs -> ``qc_decisions`` table
- :mod:`.supplemental` — files bids2table emitted no row for ->
  ``files_supplemental`` table, so darkness itself is queryable

Run it as ``python -m duckbrain.catalog <verb>`` (verbs: ``rebuild`` and the
four tiers). The engine is generic; everything dataset-specific — the
declaration, scope rules, excludes — comes from the dataset's
``expectations/dataset.toml`` (``[catalog]`` section for indexing scope).

The heavy dependencies (bids2table, duckdb, pyarrow) install via the
``catalog`` extra: ``pip install 'duckbrain[catalog]'``. The CLI raises a
clear error when they are absent rather than degrading.

Migrated from mmmdata ``scripts/catalog_*.py`` 2026-08-17 under the Contract A
ownership ruling: the dataset owns the artifact and its declarations, duckbrain
owns this engine. Design record: mmmdata-agents
``docs/constellation-contracts.md`` §3 and the contract-a-catalog workbench log.
"""
