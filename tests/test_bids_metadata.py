"""participants.tsv + dataset_description provenance generation."""

import csv
import json

from duckbrain import __version__
from duckbrain.core.bids_metadata import (
    generate_participants_from_sourcedata,
    write_dataset_description,
    write_derivative_description,
    write_participants_tsv,
)


def _rows(tsv_path):
    with open(tsv_path) as f:
        return list(csv.DictReader(f, dialect="excel-tab"))


def _json(path):
    with open(path) as f:
        return json.load(f)


# ---- dataset_description provenance -----------------------------------------


def test_write_dataset_description_versions_duckbrain_from_its_checkout(tmp_path):
    """duckbrain is distributed by git clone and served from a working copy, so
    users sit on arbitrary commits: stamp the actual checkout, not a
    hand-maintained __version__ that would go stale between releases — the very
    failure this codebase diagnoses upstream in NORDIC."""
    desc = _json(write_dataset_description(tmp_path / "bids", name="study"))
    (entry,) = desc["GeneratedBy"]
    assert entry["Name"] == "duckbrain"
    assert entry["Version"]  # a git describe here, or __version__ off a checkout


def test_duckbrain_version_falls_back_to_the_package_off_a_checkout(monkeypatch, tmp_path):
    """Installed from a wheel there is no git to ask, and the packaged version
    *is* the truth."""
    import duckbrain.core.bids_metadata as M

    monkeypatch.setattr(M, "_duckbrain_repo", lambda: tmp_path / "not-a-checkout")
    desc = _json(write_dataset_description(tmp_path / "bids", name="study"))
    assert desc["GeneratedBy"] == [{"Name": "duckbrain", "Version": __version__}]


def test_write_dataset_description_custom_generated_by(tmp_path):
    gen = [{"Name": "dcm2bids", "Version": "3.2.0"}]
    desc = _json(write_dataset_description(tmp_path / "bids", generated_by=gen))
    assert desc["GeneratedBy"] == gen


def test_write_derivative_description_records_tool_and_source(tmp_path):
    deriv = tmp_path / "derivatives" / "nordic"
    desc = _json(
        write_derivative_description(
            deriv,
            "nordic",
            tool="nordic",
            tool_version="",
            container="",
            source_dataset="/proj/bids",
        )
    )
    assert desc["DatasetType"] == "derivative"
    names = [g["Name"] for g in desc["GeneratedBy"]]
    assert names == ["duckbrain", "nordic"]
    assert desc["DatasetLinks"]["raw"] == "/proj/bids"
    assert desc["SourceDatasets"] == [{"URL": "/proj/bids"}]


def test_write_derivative_description_embeds_version_and_container(tmp_path):
    desc = _json(
        write_derivative_description(
            tmp_path / "d",
            "fmriprep-like",
            tool="fmriprep",
            tool_version="24.1.1",
            container="fmriprep-24.1.1.sif",
        )
    )
    tool_entry = next(g for g in desc["GeneratedBy"] if g["Name"] == "fmriprep")
    assert tool_entry["Version"] == "24.1.1"
    assert tool_entry["Container"]["Tag"] == "fmriprep-24.1.1.sif"
    # No source given → no link fields at all.
    assert "DatasetLinks" not in desc


def test_write_participants_empty_still_creates_file(tmp_path):
    # Regression: an empty participant list must still produce a real (header-
    # only) file at the returned path — the GUI reads it back immediately.
    tsv = write_participants_tsv(tmp_path, [])
    assert tsv.exists()
    assert tsv.read_text().strip() == "participant_id\tsex\tage"
    assert _rows(tsv) == []


def test_generate_from_empty_sourcedata(tmp_path):
    src = tmp_path / "sourcedata"
    src.mkdir()
    tsv = generate_participants_from_sourcedata(src, tmp_path)
    assert tsv.exists()
    assert _rows(tsv) == []


def test_generate_single_session_layout(tmp_path):
    # sub-XX/dicom (no ses- level) must be discovered.
    src = tmp_path / "sourcedata"
    for sub in ("sub-001", "sub-002"):
        (src / sub / "dicom").mkdir(parents=True)
    tsv = generate_participants_from_sourcedata(src, tmp_path)
    assert [r["participant_id"] for r in _rows(tsv)] == ["sub-001", "sub-002"]


def test_write_participants_append_dedupes(tmp_path):
    write_participants_tsv(tmp_path, [{"participant_id": "sub-001", "sex": "M", "age": 20}])
    write_participants_tsv(
        tmp_path,
        [
            {"participant_id": "sub-001", "sex": "M", "age": 20},  # dup
            {"participant_id": "sub-002", "sex": "F", "age": 21},
        ],
    )
    ids = [r["participant_id"] for r in _rows(tmp_path / "participants.tsv")]
    assert ids == ["sub-001", "sub-002"]


# ---- ingested BIDS root: converter provenance -------------------------------
#
# The raw BIDS root is duckbrain's output too (it ran dcm2bids to make it), so it
# must name the converter — dcm2bids' version determines the BIDS it emits.


def test_converter_generated_by_names_duckbrain_and_dcm2bids(monkeypatch, tmp_path):
    import duckbrain.core.conversion as C
    from duckbrain.core.bids_metadata import converter_generated_by

    img = tmp_path / "dcm2bids-3.2.0.sif"
    img.write_text("img")
    monkeypatch.setattr(C, "get_container_path", lambda cfg: img)
    cfg = {"paths": {"containers_dir": str(tmp_path)}, "containers": {"dcm2bids_version": "3.2.0"}}
    entries = converter_generated_by(cfg)
    assert [e["Name"] for e in entries] == ["duckbrain", "dcm2bids"]
    assert entries[1]["Version"] == "3.2.0"
    assert entries[1]["Container"]["Tag"] == "dcm2bids-3.2.0.sif"


def test_converter_generated_by_degrades_to_duckbrain_alone(tmp_path):
    """No containers configured: record what we know, never block the write."""
    from duckbrain.core.bids_metadata import converter_generated_by

    entries = converter_generated_by({"paths": {}})
    assert entries[0]["Name"] == "duckbrain"


def test_root_description_records_the_converter(monkeypatch, tmp_path):
    import duckbrain.core.conversion as C
    from duckbrain.core.bids_metadata import converter_generated_by

    img = tmp_path / "dcm2bids-3.2.0.sif"
    img.write_text("img")
    monkeypatch.setattr(C, "get_container_path", lambda cfg: img)
    cfg = {"paths": {"containers_dir": str(tmp_path)}, "containers": {"dcm2bids_version": "3.2.0"}}
    desc = _json(
        write_dataset_description(
            tmp_path / "bids", name="study", generated_by=converter_generated_by(cfg)
        )
    )
    assert [g["Name"] for g in desc["GeneratedBy"]] == ["duckbrain", "dcm2bids"]


# ---- the root files BIDS requires, and not destroying what we didn't write ----


def test_write_dataset_description_preserves_hand_added_fields(tmp_path):
    """The raw root's description is shared with the user.

    BIDS defines License, Funding, EthicsApprovals, DatasetDOI and more; duckbrain
    elicits none of them, and the old whole-file dump destroyed every one each
    time the Ingestion page's "Generate" button was pressed.
    """
    bids = tmp_path / "bids"
    bids.mkdir()
    (bids / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": "study",
                "BIDSVersion": "1.8.0",
                "License": "CC0",
                "Funding": ["NSF 1234"],
                "EthicsApprovals": ["IRB #7"],
                "DatasetDOI": "doi:10.0/xyz",
            }
        )
    )

    desc = _json(write_dataset_description(bids, name="study", generated_by=[{"Name": "x"}]))

    assert desc["License"] == "CC0"
    assert desc["Funding"] == ["NSF 1234"]
    assert desc["EthicsApprovals"] == ["IRB #7"]
    assert desc["DatasetDOI"] == "doi:10.0/xyz"
    # …while the keys duckbrain does own are refreshed.
    assert desc["BIDSVersion"] == "1.9.0"
    assert desc["GeneratedBy"] == [{"Name": "x"}]


def test_an_empty_name_does_not_blank_an_existing_one(tmp_path):
    """The project name is a config field a user may never have filled in."""
    bids = tmp_path / "bids"
    bids.mkdir()
    (bids / "dataset_description.json").write_text(json.dumps({"Name": "Hand written"}))

    assert _json(write_dataset_description(bids, name=""))["Name"] == "Hand written"


def test_no_generated_by_does_not_blank_an_existing_one(tmp_path):
    """The sibling of the `Name` rule above, and the one branch coverage caught.

    `converter_generated_by` is best-effort and degrades to duckbrain's entry
    alone; a caller that cannot build one at all passes nothing, and that must
    leave the recorded converter intact rather than dropping it. Statement
    coverage reported this line as covered because it always *ran* — every test
    happened to pass `generated_by`, so the false branch never executed.
    """
    bids = tmp_path / "bids"
    bids.mkdir()
    existing = [{"Name": "dcm2bids", "Version": "3.2.0"}]
    (bids / "dataset_description.json").write_text(json.dumps({"GeneratedBy": existing}))

    assert _json(write_dataset_description(bids, name="study"))["GeneratedBy"] == existing


def test_authors_absent_from_config_never_blanks_an_existing_list(tmp_path):
    """`dataset_extra_fields` omits the key rather than passing [], so clearing
    the Setup field cannot destroy a hand-written Authors list."""
    from duckbrain.core.bids_metadata import dataset_extra_fields

    assert dataset_extra_fields({}) == {}
    assert dataset_extra_fields({"project": {"authors": []}}) == {}
    assert dataset_extra_fields({"project": {"authors": [" ", ""]}}) == {}
    assert dataset_extra_fields({"project": {"authors": ["Jane Doe"]}}) == {"Authors": ["Jane Doe"]}

    bids = tmp_path / "bids"
    bids.mkdir()
    (bids / "dataset_description.json").write_text(json.dumps({"Authors": ["Jane Doe"]}))
    desc = _json(write_dataset_description(bids, extra_fields=dataset_extra_fields({})))
    assert desc["Authors"] == ["Jane Doe"]


def test_ensure_dataset_description_writes_only_when_absent(tmp_path):
    from duckbrain.core.bids_metadata import ensure_dataset_description

    bids = tmp_path / "bids"
    assert ensure_dataset_description(bids, name="study") is not None
    before = (bids / "dataset_description.json").read_bytes()

    # A second call declines rather than rewriting — which is what makes it safe
    # on a path that runs at every conversion.
    assert ensure_dataset_description(bids, name="renamed") is None
    assert (bids / "dataset_description.json").read_bytes() == before


def test_ensure_readme_writes_a_stub_only_when_none_exists(tmp_path):
    from duckbrain.core.bids_metadata import ensure_readme

    bids = tmp_path / "bids"
    bids.mkdir()
    path = ensure_readme(bids, name="My Study")
    assert path is not None
    assert "My Study" in path.read_text()
    assert ensure_readme(bids) is None


def test_any_of_the_three_readme_spellings_counts(tmp_path):
    """BIDS 1.9 accepts README, README.md and README.txt."""
    from duckbrain.core.bids_metadata import ensure_readme

    for name in ("README", "README.md", "README.txt"):
        bids = tmp_path / name
        bids.mkdir()
        (bids / name).write_text("mine")
        assert ensure_readme(bids) is None
        assert (bids / name).read_text() == "mine"
