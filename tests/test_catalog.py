"""Tests for the Contract A catalog engine (duckbrain.catalog).

One synthetic BIDS tree, built once per module and swept once through the full
``rebuild`` verb; every tier's assertions read the resulting catalog. The tree
is small but deliberately covers each resolution state (present / missing /
excepted / surplus), both QC decision schemas and locations, an excluded
dataset, an internal-kind dataset, and out-of-scope raw entries — the shapes
the engine exists to distinguish.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from duckbrain.catalog import __main__ as catalog_main
from duckbrain.catalog import expectations, supplemental, sweep
from duckbrain.catalog.qc_decisions import decision_dirs

# ---- the synthetic tree -----------------------------------------------------

DECLARATION = """\
[meta]
schema_version = "1.0"

[subjects]
active = ["01"]

[session_types]
main = ["01"]

# present: run-01 exists raw and in fmriprep
[[units]]
session_type = "main"
datatype = "func"
task = "rest"
suffix = "bold"
runs = 1
sbref = false
events = false
physio = false

# missing: declared, no files anywhere
[[units]]
session_type = "main"
datatype = "func"
task = "nback"
suffix = "bold"
runs = 1
sbref = false
events = false
physio = false

# excepted: declared, no files, accepted exception below
[[units]]
session_type = "main"
datatype = "dwi"
suffix = "dwi"
runs = 1

[derivatives]
complete_for_bold = ["derivatives/fmriprep"]

[[scope]]
dataset = "."
datatypes = ["func", "dwi"]

[[scope]]
dataset = "derivatives/fmriprep"
suffixes = ["bold"]
descs = ["preproc"]

[[exceptions]]
subject = "01"
sessions = ["01"]
datatype = "dwi"
suffix = "dwi"
category = "skipped-for-time"
disposition = "accepted"
description = "dwi skipped at acquisition"

# blanket annotation: names no unit dimension, so it must never flip a status
[[exceptions]]
subject = "*"
sessions = ["*"]
category = "note"
disposition = "accepted"
description = "toy dataset"

[catalog]
exclude = ["derivatives/skipme"]
raw_scope = ["sub-*", "phenotype", "derivatives"]
"""


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_tree(root: Path) -> None:
    _write(root / "dataset_description.json", json.dumps({"Name": "toy", "BIDSVersion": "1.8.0"}))
    _write(root / "README", "toy dataset\n")
    _write(root / "notes.txt", "not a BIDS file\n")

    func = root / "sub-01" / "ses-01" / "func"
    _write(func / "sub-01_ses-01_task-rest_run-01_bold.nii.gz")
    _write(func / "sub-01_ses-01_task-rest_run-01_bold.json", json.dumps({"RepetitionTime": 1.0}))
    # observed but undeclared -> surplus
    _write(func / "sub-01_ses-01_task-extra_run-01_bold.nii.gz")

    _write(root / "sub-01" / "sub-01_sessions.tsv", "session_id\tacq_date\nses-01\t2026-01-01\n")
    _write(root / "phenotype" / "vviq.tsv", "participant_id\tscore\nsub-01\t42\n")
    # out of raw_scope -> scope-skip, visible in the walk report
    _write(root / "stimuli" / "img.png")

    fprep = root / "derivatives" / "fmriprep"
    _write(
        fprep / "dataset_description.json",
        json.dumps(
            {
                "Name": "fMRIPrep - toy",
                "DatasetType": "derivative",
                "GeneratedBy": [{"Name": "fMRIPrep", "Version": "24.0.0"}],
                "SourceDatasets": [{"URL": "../.."}],
            }
        ),
    )
    _write(
        fprep
        / "sub-01"
        / "ses-01"
        / "func"
        / "sub-01_ses-01_task-rest_run-01_space-T1w_desc-preproc_bold.nii.gz"
    )

    # a nested dataset whose path names pipeline scratch -> kind "internal"
    _write(
        root / "derivatives" / "scratch" / "work" / "dataset_description.json",
        json.dumps({"Name": "work", "BIDSVersion": "1.8.0"}),
    )
    _write(root / "derivatives" / "scratch" / "work" / "junk.bin")

    # excluded by the declaration's [catalog] exclude
    _write(
        root / "derivatives" / "skipme" / "dataset_description.json",
        json.dumps({"Name": "skipme", "BIDSVersion": "1.8.0"}),
    )

    # a derivative keyed by stimulus, not by BIDS entities: bids2table indexes
    # nothing here, so its sidecars have no *indexed* stem to pair with
    stimfeat = root / "derivatives" / "stimfeat"
    _write(
        stimfeat / "dataset_description.json",
        json.dumps({"Name": "stimfeat", "DatasetType": "derivative"}),
    )
    _write(stimfeat / "shared1000" / "clip.csv", "stimulus_id,f0\nimg0001,0.5\n")
    _write(stimfeat / "shared1000" / "clip.json", json.dumps({"schema_version": "1"}))
    _write(stimfeat / "shared1000" / "orphan.json", json.dumps({"no": "companion"}))
    # Contract B's actual shape: a `.meta.json` sidecar, and a prefix family
    # whose sidecar names no file exactly
    _write(stimfeat / "shared1000" / "aesthetics.csv", "stimulus_id,f0\nimg0001,0.5\n")
    _write(stimfeat / "shared1000" / "aesthetics.meta.json", json.dumps({"schema_version": "1"}))
    _write(stimfeat / "shared1000" / "clap_text_words.csv", "stimulus_id,f0\nw1,0.5\n")
    _write(stimfeat / "shared1000" / "clap_text_chunks.csv", "stimulus_id,f0\nc1,0.5\n")
    _write(stimfeat / "shared1000" / "clap_text.meta.json", json.dumps({"schema_version": "1"}))

    # QC decisions: legacy location + schema (latest/history) ...
    _write(
        root
        / "derivatives"
        / "preprocessing_qc"
        / "sub-01"
        / "sub-01_ses-01_task-rest_run-01_bold_decision.json",
        json.dumps(
            {
                "latest": {"decision": "keep", "reviewer": "", "timestamp": "t1"},
                "history": [{"decision": "pending", "reviewer": ""}],
            }
        ),
    )
    # ... and current location + schema (run_key/decisions), same run: its
    # entries must land last and carry the verdict
    decisions = root / "derivatives" / "duckbrain" / "qc" / "decisions"
    _write(
        decisions / "sub-01_ses-01_task-rest_run-01_bold_decision.json",
        json.dumps(
            {
                "run_key": "sub-01_ses-01_task-rest_run-01_bold",
                "decisions": [
                    {"decision": "keep", "reviewer": "Ben", "timestamp": "t2", "reason": "fine"},
                    {"domain": "alignment", "state": "concerns", "reviewer": "Ben"},
                ],
            }
        ),
    )
    # an automated-only run: a machine's suggestion must never read as a sign-off
    _write(
        decisions / "sub-01_ses-01_task-extra_run-01_bold_decision.json",
        json.dumps(
            {
                "run_key": "sub-01_ses-01_task-extra_run-01_bold",
                "decisions": [{"decision": "pending", "reviewer": "auto", "automated": True}],
            }
        ),
    )
    _write(decisions / "broken_decision.json", "{not json")

    _write(root / "expectations" / "dataset.toml", DECLARATION)


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("catalog_root")
    _build_tree(root)
    assert catalog_main.main(["rebuild", "--root", str(root)]) == 0
    return root


@pytest.fixture()
def con(built: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(built / "inventory" / "catalog.duckdb"), read_only=True)


# ---- sweep ------------------------------------------------------------------


def test_sweep_indexes_every_discovered_dataset(con: duckdb.DuckDBPyConnection) -> None:
    relpaths = {r[0] for r in con.execute("SELECT relpath FROM datasets").fetchall()}
    expected = {".", "derivatives/fmriprep", "derivatives/scratch/work", "derivatives/skipme"}
    assert expected <= relpaths


def test_sweep_records_provenance_from_dataset_description(
    con: duckdb.DuckDBPyConnection,
) -> None:
    row = con.execute(
        "SELECT pipeline, pipeline_version, sources FROM datasets"
        " WHERE relpath = 'derivatives/fmriprep'"
    ).fetchone()
    assert row == ("fMRIPrep", "24.0.0", "raw")


def test_sweep_marks_the_excluded_dataset_skipped_not_absent(
    con: duckdb.DuckDBPyConnection,
) -> None:
    row = con.execute(
        "SELECT skipped, n_rows FROM datasets WHERE relpath = 'derivatives/skipme'"
    ).fetchone()
    assert row is not None and row[0] == "excluded" and row[1] is None


def test_sweep_tags_scratch_path_components_internal(con: duckdb.DuckDBPyConnection) -> None:
    kinds = dict(con.execute("SELECT relpath, kind FROM datasets").fetchall())
    assert kinds["derivatives/scratch/work"] == "internal"
    assert kinds["."] == "canonical"


def test_files_carry_the_root_relative_join_key(con: duckdb.DuckDBPyConnection) -> None:
    n = con.execute(
        "SELECT count(*) FROM files WHERE dataset_relpath = '.' AND task = 'rest'"
        " AND suffix = 'bold'"
    ).fetchone()
    assert n is not None and n[0] == 1


def test_dataset_kind_is_rule_driven() -> None:
    assert sweep.dataset_kind(".") == "canonical"
    assert sweep.dataset_kind("derivatives/fmriprep") == "canonical"
    assert sweep.dataset_kind("derivatives/hippunfold/work") == "internal"
    assert sweep.dataset_kind("derivatives/nordic/bids_input") == "internal"


def test_dataset_slug_flattens_paths(tmp_path: Path) -> None:
    assert sweep.dataset_slug(tmp_path, tmp_path) == "raw"
    assert sweep.dataset_slug(tmp_path, tmp_path / "derivatives" / "x") == "derivatives__x"


def test_read_provenance_shapes(tmp_path: Path) -> None:
    # no dataset_description.json at all
    assert sweep.read_provenance(tmp_path, tmp_path) == {}
    # unparseable JSON is an error *value*, not an exception
    ds = tmp_path / "bad"
    _write(ds / "dataset_description.json", "{nope")
    assert "provenance_error" in sweep.read_provenance(tmp_path, ds)
    # DOI and unresolvable URLs are kept verbatim
    ds2 = tmp_path / "doi"
    _write(
        ds2 / "dataset_description.json",
        json.dumps({"SourceDatasets": [{"URL": "doi:10.1/x"}, {"URL": "../../../outside"}]}),
    )
    assert sweep.read_provenance(tmp_path, ds2)["sources"] == "doi:10.1/x;../../../outside"


# ---- expectations -----------------------------------------------------------


def _statuses(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, str, str], str]:
    rows = con.execute(
        "SELECT dataset_relpath, coalesce(task, ''), suffix, status FROM resolution"
    ).fetchall()
    return {(r[0], r[1], r[2]): r[3] for r in rows}


def test_resolution_reaches_all_four_states(con: duckdb.DuckDBPyConnection) -> None:
    statuses = _statuses(con)
    assert statuses[(".", "rest", "bold")] == "present"
    assert statuses[("derivatives/fmriprep", "rest", "bold")] == "present"
    assert statuses[(".", "nback", "bold")] == "missing"
    assert statuses[("derivatives/fmriprep", "nback", "bold")] == "missing"
    assert statuses[(".", "", "dwi")] == "excepted"
    assert statuses[(".", "extra", "bold")] == "surplus"


def test_excepted_unit_carries_its_disposition(con: duckdb.DuckDBPyConnection) -> None:
    row = con.execute(
        "SELECT disposition, exception_notes FROM resolution WHERE suffix = 'dwi'"
    ).fetchone()
    assert row is not None and row[0] == "accepted" and "skipped-for-time" in row[1]


def test_blanket_note_never_flips_a_status(con: duckdb.DuckDBPyConnection) -> None:
    # the sub-* x ses-* note matches every unit dimension-free; if it were
    # status-eligible the two missing units would read excepted
    n = con.execute("SELECT count(*) FROM resolution WHERE status = 'missing'").fetchone()
    assert n is not None and n[0] == 2


def test_sessions_and_phenotype_are_ingested(con: duckdb.DuckDBPyConnection) -> None:
    ses = con.execute("SELECT sub, ses FROM sessions").fetchall()
    assert ses == [("01", "01")]
    phen = con.execute("SELECT instrument, sub, score FROM phenotype").fetchall()
    assert phen == [("vviq", "01", "42")]


def test_expand_units_requires_a_run_count() -> None:
    decl = {
        "subjects": {"active": ["01"]},
        "session_types": {"main": ["01"]},
        "units": [{"session_type": "main", "datatype": "func", "suffix": "bold"}],
        "derivatives": {"complete_for_bold": []},
    }
    with pytest.raises(SystemExit, match="runs"):
        expectations.expand_units(decl)


def test_expand_units_bold_expansions() -> None:
    decl = {
        "subjects": {"active": ["01"]},
        "session_types": {"main": ["01"]},
        "units": [
            {
                "session_type": "main",
                "datatype": "func",
                "task": "nat",
                "suffix": "bold",
                "runs": 2,
                "events": True,
                "eyetracking": True,
            }
        ],
        "derivatives": {"complete_for_bold": ["derivatives/fmriprep"]},
    }
    units = expectations.expand_units(decl)
    keys = {(u["dataset_relpath"], u["suffix"], u["recording"]) for u in units}
    # bold + default sbref + events + physio + eye + the derivative unit
    assert keys == {
        (".", "bold", None),
        (".", "sbref", None),
        (".", "events", None),
        (".", "physio", "physio"),
        (".", "physio", "eye"),
        ("derivatives/fmriprep", "bold", None),
    }


def test_exception_status_eligibility_needs_a_unit_dimension() -> None:
    decl = {
        "exceptions": [
            {
                "subject": "01",
                "sessions": ["01"],
                "suffix": "dwi",
                "category": "c",
                "disposition": "accepted",
                "description": "d",
            },
            {
                "subject": "01",
                "sessions": ["01"],
                "category": "c",
                "disposition": "accepted",
                "description": "session-level note",
            },
        ]
    }
    eligible = [e["status_eligible"] for e in expectations.expand_exceptions(decl)]
    assert eligible == [True, False]


def test_scope_predicate_spells_each_clause() -> None:
    pred = expectations.scope_predicate(
        [{"dataset": ".", "datatypes": ["func"], "exclude_suffixes": ["stim"]}]
    )
    assert "dataset_relpath = '.'" in pred
    assert "datatype IN ('func')" in pred
    assert "suffix NOT IN ('stim')" in pred


# ---- qc decisions -----------------------------------------------------------


def test_qc_merges_locations_and_schemas_newest_last(con: duckdb.DuckDBPyConnection) -> None:
    row = con.execute(
        "SELECT decision, reviewer, signed_off, n_entries, n_domain_notes, source_files"
        " FROM qc_decisions WHERE run_key = 'sub-01_ses-01_task-rest_run-01_bold'"
    ).fetchone()
    assert row is not None
    decision, reviewer, signed_off, n_entries, n_domain_notes, source_files = row
    # the current location's entry lands last: Ben's keep, a real sign-off
    assert (decision, reviewer, signed_off) == ("keep", "Ben", True)
    assert (n_entries, n_domain_notes) == (3, 1)
    assert "preprocessing_qc" in source_files and "duckbrain/qc/decisions" in source_files


def test_qc_automated_entry_is_not_a_sign_off(con: duckdb.DuckDBPyConnection) -> None:
    row = con.execute(
        "SELECT decision, automated, signed_off FROM qc_decisions"
        " WHERE run_key = 'sub-01_ses-01_task-extra_run-01_bold'"
    ).fetchone()
    assert row == ("pending", True, False)


def test_qc_decision_dirs_order_is_oldest_first(tmp_path: Path) -> None:
    dirs = decision_dirs(tmp_path)
    assert dirs[0] == tmp_path / "derivatives" / "preprocessing_qc"
    assert dirs[-1] == tmp_path / "derivatives" / "duckbrain" / "qc" / "decisions"


# ---- supplemental -----------------------------------------------------------


def test_supplemental_categorizes_sidecar_metadata_dark(
    con: duckdb.DuckDBPyConnection,
) -> None:
    cats = dict(
        con.execute(
            "SELECT path, category FROM files_supplemental WHERE dataset_relpath = '.'"
        ).fetchall()
    )
    assert cats["sub-01/ses-01/func/sub-01_ses-01_task-rest_run-01_bold.json"] == "sidecar"
    assert cats["dataset_description.json"] == "metadata"
    assert cats["README"] == "metadata"
    assert cats["notes.txt"] == "dark"
    # derivatives/duckbrain has no sub-* dirs, so bids2table discovers no
    # dataset there and its files are raw-tree dark matter — proving the walk
    # reaches under derivatives/ for whatever no dataset claims
    assert any(p.startswith("derivatives/duckbrain/qc/") for p in cats)
    # preprocessing_qc DOES get discovered (sub-* dirs, no sidecar needed), so
    # its unindexable decision JSON is dark under its own dataset instead
    qc_cats = con.execute(
        "SELECT category FROM files_supplemental"
        " WHERE dataset_relpath = 'derivatives/preprocessing_qc'"
    ).fetchall()
    assert qc_cats == [("dark",)]


def test_sidecar_pairs_with_an_unindexed_companion(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """A derivative bids2table cannot index still has real sidecars.

    Pairing a .json only against *indexed* stems made every sidecar in a
    stimulus-keyed tree `dark`, because such a tree has no indexed rows at all.
    The companion is what makes a .json a sidecar, not whether bids2table
    understood the companion.
    """
    cats = dict(
        con.execute(
            "SELECT path, category FROM files_supplemental"
            " WHERE dataset_relpath = 'derivatives/stimfeat'"
        ).fetchall()
    )
    assert cats["shared1000/clip.csv"] == "dark"
    assert cats["shared1000/clip.json"] == "sidecar"
    # a .json with no companion is still dark -- and two JSONs sharing a stem
    # must not talk each other into being sidecars
    assert cats["shared1000/orphan.json"] == "dark"
    # one secondary suffix is stripped, so `.meta.json` finds its companion
    assert cats["shared1000/aesthetics.meta.json"] == "sidecar"
    # but a sidecar covering a prefix *family* names no file exactly, and the
    # engine does not guess: that convention is the dataset's to declare
    assert cats["shared1000/clap_text.meta.json"] == "dark"


def test_supplemental_never_walks_internal_or_excluded_datasets(
    con: duckdb.DuckDBPyConnection,
) -> None:
    n = con.execute(
        "SELECT count(*) FROM files_supplemental WHERE dataset_relpath IN"
        " ('derivatives/scratch/work', 'derivatives/skipme')"
    ).fetchone()
    assert n is not None and n[0] == 0


def test_collect_files_reports_out_of_scope_entries(built: Path) -> None:
    files, skipped = supplemental.collect_files(
        built, built, set(), True, raw_scope=("sub-*", "phenotype", "derivatives")
    )
    # inventory/ holds however many artifacts the rebuild wrote — the *keys*
    # are the contract (out-of-scope top-level dirs, each with a count)
    assert set(skipped) == {"expectations", "inventory", "stimuli"}
    assert skipped["stimuli"] == 1
    assert built / "notes.txt" in files


# ---- CLI --------------------------------------------------------------------


def test_rebuild_without_a_declaration_refuses_loudly(tmp_path: Path) -> None:
    _write(tmp_path / "dataset_description.json", json.dumps({"Name": "x"}))
    with pytest.raises(SystemExit, match="no declaration"):
        catalog_main.main(["rebuild", "--root", str(tmp_path)])


def test_declaration_free_verbs_run_without_one(tmp_path: Path) -> None:
    _write(tmp_path / "dataset_description.json", json.dumps({"Name": "x", "BIDSVersion": "1.8"}))
    _write(tmp_path / "sub-01" / "ses-01" / "func" / "sub-01_ses-01_task-a_bold.nii.gz")
    assert catalog_main.main(["sweep", "--root", str(tmp_path)]) == 0
    assert catalog_main.main(["qc", "--root", str(tmp_path)]) == 0
    assert catalog_main.main(["supplemental", "--root", str(tmp_path)]) == 0
    with duckdb.connect(str(tmp_path / "inventory" / "catalog.duckdb"), read_only=True) as c:
        row = c.execute("SELECT count(*) FROM files").fetchone()
        assert row is not None and row[0] == 1


def test_cli_exclude_flag_adds_to_the_declaration_list(built: Path, tmp_path: Path) -> None:
    # rerun the sweep into a scratch out-dir, excluding fmriprep on top of the
    # declaration's skipme
    assert (
        catalog_main.main(
            [
                "sweep",
                "--root",
                str(built),
                "--out-dir",
                str(tmp_path),
                "--exclude",
                "derivatives/fmriprep",
            ]
        )
        == 0
    )
    with duckdb.connect(str(tmp_path / "catalog.duckdb"), read_only=True) as c:
        skipped = {
            r[0]
            for r in c.execute("SELECT relpath FROM datasets WHERE skipped IS NOT NULL").fetchall()
        }
    assert {"derivatives/fmriprep", "derivatives/skipme"} <= skipped
