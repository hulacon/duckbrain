"""Tests for duckbrain config loader."""

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_env(monkeypatch, tmp_path):
    """Keep the developer's real ~/.config/duckbrain and env vars out of tests."""
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(tmp_path / "no_user_config.toml"))
    monkeypatch.delenv("DUCKBRAIN_PROJECT_DIR", raising=False)
    monkeypatch.delenv("DUCKBRAIN_CONFIG_DIR", raising=False)


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary config directory with base.toml."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    base_toml = config_dir / "base.toml"
    base_toml.write_text(
        """
[project]
name = ""

[paths]
bids_dir = ""
sourcedata_dir = ""
work_dir = ""
containers_dir = ""

[slurm]
partition = "medium"
time = "12:00:00"
memory = "16G"
cpus = "4"
email = ""

[slurm.overrides.fmriprep]
time = "48:00:00"
memory = "48G"
cpus = "8"
partition = "computelong"
"""
    )
    return config_dir


def test_load_config_base_only(tmp_config_dir):
    from duckbrain.config import load_config

    config = load_config(tmp_config_dir)
    assert config["slurm"]["partition"] == "medium"
    assert config["project"]["name"] == ""


def test_load_config_with_local_override(tmp_config_dir):
    from duckbrain.config import load_config

    local = tmp_config_dir / "local.toml"
    local.write_text(
        """
[project]
name = "test_project"

[slurm]
email = "test@example.com"
"""
    )

    config = load_config(tmp_config_dir)
    assert config["project"]["name"] == "test_project"
    assert config["slurm"]["email"] == "test@example.com"
    # Base values should still be present
    assert config["slurm"]["partition"] == "medium"


def test_deep_merge_preserves_nested(tmp_config_dir):
    from duckbrain.config import load_config

    local = tmp_config_dir / "local.toml"
    local.write_text(
        """
[slurm]
email = "override@example.com"

[slurm.overrides.fmriprep]
time = "72:00:00"
"""
    )

    config = load_config(tmp_config_dir)
    assert config["slurm"]["email"] == "override@example.com"
    # Overridden
    assert config["slurm"]["overrides"]["fmriprep"]["time"] == "72:00:00"
    # Preserved from base
    assert config["slurm"]["overrides"]["fmriprep"]["memory"] == "48G"


def test_get_slurm_resources(tmp_config_dir):
    from duckbrain.config import get_slurm_resources, load_config

    config = load_config(tmp_config_dir)
    res = get_slurm_resources(config, "fmriprep")
    assert res["time"] == "48:00:00"
    assert res["partition"] == "computelong"

    # Unknown step falls back to defaults
    res2 = get_slurm_resources(config, "unknown_step")
    assert res2["time"] == "12:00:00"
    assert res2["partition"] == "medium"


@pytest.mark.parametrize(
    "memory,expected",
    [("48G", 48), ("48g", 48), ("49152M", 48), ("49152", 48), ("1T", 1024), ("500M", 0)],
)
def test_parse_mem_gb_reads_every_spelling_sbatch_accepts(memory, expected):
    """An unsuffixed ``--mem`` is MB, so ``49152`` and ``48G`` are one allocation.

    The first version of this stripped a ``"G"`` off the string, which reads
    ``49152M`` as 49152 GB and would have handed the tool a ceiling three orders
    of magnitude past the cgroup limit.
    """
    from duckbrain.config import parse_mem_gb

    assert parse_mem_gb(memory) == expected


def test_parse_mem_gb_rejects_a_non_memory_value():
    from duckbrain.config import parse_mem_gb

    with pytest.raises(ValueError, match="Not a SLURM memory value"):
        parse_mem_gb("plenty")


def test_tool_mem_gb_derives_from_the_allocation(tmp_config_dir):
    from duckbrain.config import MEM_HEADROOM_GB, load_config, tool_mem_gb

    config = load_config(tmp_config_dir)
    # Per-stage override (48G) and the [slurm] default (16G) alike.
    assert tool_mem_gb(config, "fmriprep") == 48 - MEM_HEADROOM_GB
    assert tool_mem_gb(config, "mriqc") == 16 - MEM_HEADROOM_GB


def test_an_allocation_with_no_room_for_the_headroom_raises(tmp_config_dir):
    """Rather than flooring at some token ceiling and submitting anyway.

    Below the buffer there is no honest number to hand the tool, and a job that
    runs having been told 1 GB is the silent-degradation the buffer exists to
    prevent.
    """
    from duckbrain.config import MEM_HEADROOM_GB, load_config, tool_mem_gb

    config = load_config(tmp_config_dir)
    with pytest.raises(ValueError, match="leaves nothing"):
        tool_mem_gb(config, "fmriprep", alloc_gb=MEM_HEADROOM_GB)


@pytest.mark.parametrize("key", ["mem_gb", "nprocs"])
def test_no_stage_configures_a_resource_of_its_own(key):
    """The shipped config must state each resource once, in the SLURM allocation.

    Two independently-set numbers on one script is the defect this rule closes:
    ``[fmriprep] mem_gb = 32`` sat beside ``#SBATCH --mem=48G`` and nothing
    related them, so fMRIPrep scheduled against 32 GB while 16 GB it was never
    told about went unused. ``[fmriprep] nprocs`` was the same shape, agreeing
    with ``--cpus-per-task`` only by coincidence.

    Read from ``config/base.toml`` itself rather than through ``load_config``,
    which would merge in whatever the developer's own user config says and make
    this a claim about their machine.
    """
    from duckbrain.config import _find_config_dir, _load_toml

    shipped = _load_toml(_find_config_dir() / "base.toml")
    for section in ("fmriprep", "mriqc", "nordic"):
        assert key not in shipped.get(section, {})


def test_missing_base_toml_raises(tmp_path):
    from duckbrain.config import load_config

    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent")


def test_user_config_merged(tmp_config_dir, tmp_path, monkeypatch):
    """Shared machine resources come from the user config layer."""
    from duckbrain.config import load_config

    user_cfg = tmp_path / "user.toml"
    user_cfg.write_text('[paths]\ncontainers_dir = "/shared/containers"\n')
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(user_cfg))

    config = load_config(tmp_config_dir)
    assert config["paths"]["containers_dir"] == "/shared/containers"
    assert config["slurm"]["partition"] == "medium"  # base still present


def test_project_config_and_derived_paths(tmp_config_dir, tmp_path):
    """Project config is merged and sourcedata/derivatives/code are derived."""
    from duckbrain.config import load_config, save_project_config

    project = tmp_path / "myproject"
    save_project_config(project, {"project": {"name": "myproject"}})

    config = load_config(tmp_config_dir, project_dir=project)
    assert config["project"]["name"] == "myproject"
    assert config["paths"]["bids_dir"] == str(project)
    assert config["paths"]["sourcedata_dir"] == str(project / "sourcedata")
    assert config["paths"]["derivatives_dir"] == str(project / "derivatives")
    assert config["paths"]["code_dir"] == str(project / "code")


def test_project_dir_from_env(tmp_config_dir, tmp_path, monkeypatch):
    from duckbrain.config import load_config

    project = tmp_path / "envproject"
    monkeypatch.setenv("DUCKBRAIN_PROJECT_DIR", str(project))
    config = load_config(tmp_config_dir)
    assert config["paths"]["bids_dir"] == str(project)


def test_derived_paths_dont_override_explicit(tmp_config_dir, tmp_path):
    """An explicit path in project config wins over the derived default."""
    from duckbrain.config import load_config, save_project_config

    project = tmp_path / "p"
    save_project_config(project, {"paths": {"sourcedata_dir": "/elsewhere/raw"}})
    config = load_config(tmp_config_dir, project_dir=project)
    assert config["paths"]["sourcedata_dir"] == "/elsewhere/raw"
    assert config["paths"]["derivatives_dir"] == str(project / "derivatives")


def test_scaffold_writes_bidsignore(tmp_path):
    """scaffold_project drops a .bidsignore covering duckbrain's non-BIDS dirs."""
    from duckbrain.config import scaffold_project

    scaffold_project(tmp_path)
    entries = (tmp_path / ".bidsignore").read_text().split()
    assert "work/" in entries
    # logs live under code/ (BIDS-reserved) now, so they need no ignore entry.
    assert "logs/" not in entries
    assert (tmp_path / "code" / "logs").is_dir()


def test_write_bidsignore_idempotent_and_preserves_user_lines(tmp_path):
    from duckbrain.config import write_bidsignore

    (tmp_path / ".bidsignore").write_text("my_custom_scratch/\n")
    write_bidsignore(tmp_path)
    write_bidsignore(tmp_path)  # second call must not duplicate
    lines = [line for line in (tmp_path / ".bidsignore").read_text().splitlines() if line.strip()]
    assert "my_custom_scratch/" in lines
    assert lines.count("work/") == 1


# ---- recent-projects MRU -----------------------------------------------------
#
# Lives in the USER config: "which projects do I work on" is a property of the
# person at this machine, and a project cannot sensibly list itself.

import pytest


@pytest.fixture
def user_cfg(tmp_path, monkeypatch):
    path = tmp_path / "user.toml"
    monkeypatch.setenv("DUCKBRAIN_USER_CONFIG", str(path))
    return path


def _mkproj(tmp_path, name):
    p = tmp_path / name
    p.mkdir()
    return str(p)


def test_remember_project_is_mru_newest_first(user_cfg, tmp_path):
    from duckbrain.config import recent_projects, remember_project

    a, b = _mkproj(tmp_path, "a"), _mkproj(tmp_path, "b")
    remember_project(a)
    remember_project(b)
    assert recent_projects() == [b, a]
    remember_project(a)  # re-opening moves it to the front, never duplicates
    assert recent_projects() == [a, b]


def test_remember_project_caps_the_list(user_cfg, tmp_path):
    from duckbrain.config import recent_projects, remember_project

    for i in range(12):
        remember_project(_mkproj(tmp_path, f"p{i}"))
    got = recent_projects()
    assert len(got) == 8  # _MAX_RECENT_PROJECTS
    assert got[0].endswith("p11")  # newest kept, oldest dropped


def test_remember_project_preserves_other_user_settings(user_cfg, tmp_path):
    """Read-modify-write: the MRU must not clobber shared machine resources."""
    from duckbrain.config import _load_toml, remember_project, save_user_config

    save_user_config({"paths": {"fs_license": "/l/lic.txt"}, "containers": {"x": "y"}})
    remember_project(_mkproj(tmp_path, "a"))
    data = _load_toml(user_cfg)
    assert data["paths"]["fs_license"] == "/l/lic.txt"
    assert data["containers"] == {"x": "y"}
    assert len(data["recent"]["projects"]) == 1


def test_recent_projects_hides_but_does_not_erase_missing_dirs(user_cfg, tmp_path):
    """A deleted/unmounted project stops being offered but stays in the file.

    An unmounted filesystem is a temporary condition; erasing history over it
    would be destructive.
    """
    from duckbrain.config import _load_toml, recent_projects, remember_project

    gone = _mkproj(tmp_path, "gone")
    kept = _mkproj(tmp_path, "kept")
    remember_project(gone)
    remember_project(kept)
    Path(gone).rmdir()

    assert recent_projects() == [kept]
    assert recent_projects(existing_only=False) == [kept, gone]
    assert len(_load_toml(user_cfg)["recent"]["projects"]) == 2


def test_forget_project_removes_one_entry(user_cfg, tmp_path):
    from duckbrain.config import forget_project, recent_projects, remember_project

    a, b = _mkproj(tmp_path, "a"), _mkproj(tmp_path, "b")
    remember_project(a)
    remember_project(b)
    forget_project(a)
    assert recent_projects() == [b]


def test_recent_projects_tolerates_a_junk_section(user_cfg):
    """A hand-edited config must never take the GUI down."""
    from duckbrain.config import recent_projects, remember_project, save_user_config

    save_user_config({"recent": "not-a-table"})
    assert recent_projects() == []
    remember_project("/tmp")  # repairs the section rather than raising
    assert recent_projects(existing_only=False) == ["/tmp"]


def test_recent_projects_normalizes_without_resolving_symlinks(user_cfg, tmp_path):
    """Trailing slashes collapse, but a symlinked path is NOT rewritten.

    On GPFS the user-facing /projects/... is a symlink to /gpfs/projects/...;
    rewriting the path the user chose would be a surprise, not a normalization.
    """
    from duckbrain.config import recent_projects, remember_project

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    remember_project(f"{link}/")
    remember_project(str(link))  # same entry once slashes collapse
    assert recent_projects() == [str(link)]


def test_bidsignore_covers_dcm2bids_working_dir(tmp_path):
    """`tmp_dcm2bids/log/sub-XXX_ses-YY_*.log` makes the validator infer a phantom
    subject with no valid data — three of four errors on a real dataset."""
    from duckbrain.config import write_bidsignore

    write_bidsignore(tmp_path)
    entries = (tmp_path / ".bidsignore").read_text().split()
    assert "tmp_dcm2bids/" in entries
    assert "work/" in entries


def test_bidsignore_covers_the_companions_a_diffusion_sbref_drags_along(tmp_path):
    """BIDS defines `.bval`/`.bvec` for the `_dwi` suffix only, but dcm2niix writes
    them for a single-volume diffusion reference too and dcm2bids' move step
    whitelists extensions without looking at the datatype. duckbrain asks for a
    legal `dwi/…_sbref.nii.gz` and gets two illegal companions it cannot decline.
    Found by converting real multi-shell data for `#19.1`."""
    from duckbrain.config import write_bidsignore

    write_bidsignore(tmp_path)
    entries = (tmp_path / ".bidsignore").read_text().split()
    assert "*_sbref.bval" in entries
    assert "*_sbref.bvec" in entries


def test_a_conversion_tops_up_bidsignore_for_a_project_scaffolded_earlier(tmp_path):
    """Entries added after a project was created still have to reach it, or a
    tree that acquired diffusion fails validation with nothing to explain why."""
    from duckbrain.config import load_config, scaffold_project, write_bidsignore
    from duckbrain.core.pipeline import _build_dcm2bids

    scaffold_project(tmp_path)
    # A project from before the entry existed.
    (tmp_path / ".bidsignore").write_text("work/\ntmp_dcm2bids/\n")
    config = load_config(project_dir=str(tmp_path))

    session = tmp_path / "sourcedata" / "sub-01" / "dicom"
    session.mkdir(parents=True)
    (session / "dcm2bids_config.json").write_text("{}")
    (tmp_path / "sourcedata" / "sub-01" / "dcm2bids_config.json").write_text('{"descriptions": []}')
    try:
        _build_dcm2bids(config, "01", "", str(tmp_path / "code" / "logs"), {})
    except Exception:
        # Container resolution may fail in a bare tmp project; the top-up runs first.
        pass

    assert "*_sbref.bval" in (tmp_path / ".bidsignore").read_text().split()
    write_bidsignore(tmp_path)  # still idempotent afterwards
    assert (tmp_path / ".bidsignore").read_text().count("*_sbref.bval") == 1


def _convert_once(project_dir, config):
    """Drive `_build_dcm2bids` far enough for its top-up block to run."""
    from duckbrain.core.pipeline import _build_dcm2bids

    session = project_dir / "sourcedata" / "sub-01" / "dicom"
    session.mkdir(parents=True, exist_ok=True)
    (project_dir / "sourcedata" / "sub-01" / "dcm2bids_config.json").write_text(
        '{"descriptions": []}'
    )
    try:
        _build_dcm2bids(config, "01", "", str(project_dir / "code" / "logs"), {})
    except Exception:
        # Container resolution may fail in a bare tmp project; the top-up runs first.
        pass


def test_a_conversion_writes_the_two_root_files_the_validator_requires(tmp_path):
    """`dataset_description.json` is compulsory and `README` is required, and both
    were reachable only from a button nobody had to press — so a project could
    convert cleanly and then fail validation for something duckbrain owed it."""
    from duckbrain.config import load_config, scaffold_project

    scaffold_project(tmp_path)
    config = load_config(project_dir=str(tmp_path))
    config.setdefault("project", {})["name"] = "My Study"

    _convert_once(tmp_path, config)

    desc = json.loads((tmp_path / "dataset_description.json").read_text())
    assert desc["Name"] == "My Study"
    assert desc["BIDSVersion"] == "1.9.0"
    assert "My Study" in (tmp_path / "README").read_text()


def test_a_conversion_does_not_overwrite_a_hand_edited_dataset_description(tmp_path):
    """It runs at every submission, so it must decline an existing file."""
    from duckbrain.config import load_config, scaffold_project

    scaffold_project(tmp_path)
    mine = {"Name": "Mine", "BIDSVersion": "1.8.0", "Authors": ["Jane Doe"]}
    (tmp_path / "dataset_description.json").write_text(json.dumps(mine))
    (tmp_path / "README").write_text("my own README")
    config = load_config(project_dir=str(tmp_path))
    config.setdefault("project", {})["name"] = "Something Else"

    _convert_once(tmp_path, config)

    assert json.loads((tmp_path / "dataset_description.json").read_text()) == mine
    assert (tmp_path / "README").read_text() == "my own README"


def test_project_authors_round_trip_and_partial_write_guard(tmp_path):
    """Authors is a list, and the section it lives in is only partly owned."""
    from duckbrain.config import load_config, project_config_path, save_project_config

    path = project_config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[project]\nname = "study"\nuse_sessions = "auto"\nhand_written = "keep me"\n')

    owned = {"project": ("name", "use_sessions", "authors")}
    save_project_config(
        tmp_path,
        {"project": {"name": "study", "use_sessions": "auto", "authors": ["Jane Doe", "John Roe"]}},
        owned=owned,
    )

    cfg = load_config(project_dir=str(tmp_path))
    assert cfg["project"]["authors"] == ["Jane Doe", "John Roe"]
    assert cfg["project"]["hand_written"] == "keep me"

    # Omitting it removes the key rather than leaving a stale list behind.
    save_project_config(
        tmp_path, {"project": {"name": "study", "use_sessions": "auto"}}, owned=owned
    )
    assert "authors" not in load_config(project_dir=str(tmp_path))["project"]

    # And writing it against an ownership list that does not declare it raises,
    # rather than saving once and vanishing on the next save.
    with pytest.raises(ValueError):
        save_project_config(
            tmp_path,
            {"project": {"authors": ["Jane Doe"]}},
            owned={"project": ("name", "use_sessions")},
        )


# ---- TODO #17.1 / #17.2: saving must not destroy, settings must take effect ---


def test_saving_project_settings_preserves_the_studys_mappings(tmp_path):
    """The Setup page writes four sections; the rest of the file must survive.

    This was a silent data-loss bug: `save_project_config` was a whole-file dump
    while its siblings `save_project_task_map`/`save_project_fmap_map` were
    read-modify-write, so saving anything on Setup deleted the task labels and
    fieldmap bindings the Conversion page had persisted — and said "Saved".
    """
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(
        tmp_path,
        {
            "project": {"name": "study"},
            "task_mapping": {"rule": [{"description": "rest_bold", "task": "rest"}]},
            "fmap_mapping": {"rule": [{"task": "rest", "group": "2.5mm"}]},
            "fmriprep": {"output_spaces": "MNI152NLin2009cAsym:res-2"},
        },
    )
    # Exactly what the Setup page's "Save project settings" button writes.
    save_project_config(
        tmp_path,
        {
            "project": {"name": "study"},
            "dcm_source": {"dir": "/dicom/study"},
            "slurm": {"account": "hulacon"},
        },
    )

    stored = _load_toml(project_config_path(tmp_path))
    assert stored["task_mapping"]["rule"][0]["task"] == "rest"
    assert stored["fmap_mapping"]["rule"][0]["group"] == "2.5mm"
    assert stored["fmriprep"]["output_spaces"] == "MNI152NLin2009cAsym:res-2"
    assert stored["dcm_source"]["dir"] == "/dicom/study"


def test_a_saved_section_is_replaced_not_merged(tmp_path):
    """Clearing a field must remove it, or the cleared value keeps taking effect."""
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(tmp_path, {"slurm": {"account": "old", "partition": "gone"}})
    save_project_config(tmp_path, {"slurm": {"account": "new"}})

    stored = _load_toml(project_config_path(tmp_path))
    assert stored["slurm"] == {"account": "new"}


# ---- DB-001: a section a form owns only PARTLY needs field-level ownership ----

_SETUP_OWNS = {"slurm": ("account", "partition", "partition_long", "time")}


def test_owned_fields_preserve_a_nested_subtable(tmp_path):
    """The reopened half of TODO #17.1.

    Section-level replace saved the file from a whole-file dump but not from a
    *partial* section: the Setup page writes four of [slurm]'s keys, so a
    hand-tuned [slurm.overrides.fmriprep] — live config, read by
    `slurm_resources` — was deleted on any Setup save, and the page said "Saved".
    """
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(
        tmp_path,
        {
            "slurm": {
                "account": "hulacon",
                "memory": "64G",
                "overrides": {"fmriprep": {"time": "48:00:00", "mem": "96G"}},
            }
        },
    )
    save_project_config(tmp_path, {"slurm": {"partition": "compute"}}, owned=_SETUP_OWNS)

    stored = _load_toml(project_config_path(tmp_path))["slurm"]
    assert stored["overrides"]["fmriprep"]["time"] == "48:00:00"
    assert stored["memory"] == "64G"  # hand-written scalar survives too
    assert stored["partition"] == "compute"


def test_owned_fields_are_removed_when_cleared(tmp_path):
    """Ownership must not resurrect a field the user cleared — the deep-merge trap."""
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(tmp_path, {"slurm": {"account": "old", "time": "12:00:00"}})
    save_project_config(tmp_path, {"slurm": {"time": "24:00:00"}}, owned=_SETUP_OWNS)

    stored = _load_toml(project_config_path(tmp_path))["slurm"]
    assert "account" not in stored
    assert stored["time"] == "24:00:00"


def test_owned_section_absent_from_data_still_clears(tmp_path):
    """`_clean_dict` drops an all-empty section, and that must still mean "cleared".

    Otherwise clearing every SLURM field on the form leaves the old values in the
    file, still taking effect — the exact bug section-replace exists to prevent.
    """
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(
        tmp_path,
        {
            "slurm": {
                "account": "old",
                "overrides": {"fmriprep": {"time": "48:00:00"}},
            }
        },
    )
    save_project_config(tmp_path, {"project": {"name": "s"}}, owned=_SETUP_OWNS)

    stored = _load_toml(project_config_path(tmp_path))["slurm"]
    assert "account" not in stored
    assert stored["overrides"]["fmriprep"]["time"] == "48:00:00"


def test_writing_an_undeclared_key_raises(tmp_path):
    """A new widget must fail loudly, not save once and vanish on the next save."""
    from duckbrain.config import save_project_config

    with pytest.raises(ValueError, match="qos"):
        save_project_config(tmp_path, {"slurm": {"qos": "high"}}, owned=_SETUP_OWNS)


def test_an_unowned_section_is_still_replaced_wholesale(tmp_path):
    """Ownership is opt-in per section; everything else keeps the old contract."""
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(tmp_path, {"conversion": {"a": "1", "b": "2"}})
    save_project_config(tmp_path, {"conversion": {"a": "9"}}, owned=_SETUP_OWNS)

    assert _load_toml(project_config_path(tmp_path))["conversion"] == {"a": "9"}


def test_clearing_every_owned_key_drops_the_section(tmp_path):
    """A section reconciled to nothing shouldn't linger as an empty table."""
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(tmp_path, {"dcm_source": {"dir": "/dicom/x"}})
    save_project_config(tmp_path, {}, owned={"dcm_source": ("dir",)})

    assert "dcm_source" not in _load_toml(project_config_path(tmp_path))


def test_project_partition_reaches_every_stage(tmp_path, monkeypatch):
    """A project's partition is site policy and must beat the shipped defaults.

    It did not: base.toml named a partition on every stage override, and
    `get_slurm_resources` reads overrides first, so the value the Setup page
    displayed reached no job at all. Stages declare `long` now; the two role
    names resolve from [slurm].
    """
    from duckbrain.config import (
        get_slurm_resources,
        load_config,
        save_project_config,
        scaffold_project,
    )

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    save_project_config(str(proj), {"slurm": {"partition": "mypart", "partition_long": "mylong"}})
    cfg = load_config(project_dir=str(proj))

    assert get_slurm_resources(cfg, "dcm2bids")["partition"] == "mypart"
    assert get_slurm_resources(cfg, "mriqc")["partition"] == "mypart"
    assert get_slurm_resources(cfg, "nordic")["partition"] == "mypart"
    # fMRIPrep is the long stage, so it follows partition_long.
    assert get_slurm_resources(cfg, "fmriprep")["partition"] == "mylong"
    # ...while the tuned per-stage values are NOT retuned by a project default.
    assert get_slurm_resources(cfg, "fmriprep")["time"] == "48:00:00"
    assert get_slurm_resources(cfg, "dcm2bids")["memory"] == "8G"


def test_shipped_partition_defaults_are_unchanged(tmp_path):
    """Removing the per-stage partition lines must not move where jobs land."""
    from duckbrain.config import get_slurm_resources, load_config, scaffold_project

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    cfg = load_config(project_dir=str(proj))
    landed = {
        s: get_slurm_resources(cfg, s)["partition"]
        for s in ("dcm2bids", "mriqc", "nordic", "fmriprep")
    }
    assert landed == {
        "dcm2bids": "compute",
        "mriqc": "compute",
        "nordic": "compute",
        "fmriprep": "computelong",
    }


def test_an_explicit_per_stage_partition_still_wins(tmp_path):
    from duckbrain.config import (
        get_slurm_resources,
        load_config,
        save_project_config,
        scaffold_project,
    )

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    save_project_config(
        str(proj),
        {"slurm": {"partition": "mypart", "overrides": {"mriqc": {"partition": "pinned"}}}},
    )
    cfg = load_config(project_dir=str(proj))
    assert get_slurm_resources(cfg, "mriqc")["partition"] == "pinned"
    assert get_slurm_resources(cfg, "dcm2bids")["partition"] == "mypart"


# --- [conversion] nd_duplicates -------------------------------------------
def test_an_absent_nd_policy_is_the_historical_behaviour():
    from duckbrain.core.dicom_inspect import nd_policy_from_config

    assert nd_policy_from_config({}) == "corrected"
    assert nd_policy_from_config({"conversion": {}}) == "corrected"


def test_an_unknown_nd_policy_raises():
    """Unlike a malformed task rule, which is skipped and then reported.

    A skipped rule falls back to a heuristic duckbrain states out loud. A
    mistyped policy would silently ship the other image, and both convert
    cleanly — nothing downstream could notice.
    """
    import pytest

    from duckbrain.core.dicom_inspect import nd_policy_from_config

    with pytest.raises(ValueError, match="nd_duplicates"):
        nd_policy_from_config({"conversion": {"nd_duplicates": "uncorected"}})


def test_saving_the_nd_choice_preserves_bids_validate(tmp_path):
    """[conversion] is shared, so a section-wide write would delete its neighbour."""
    from duckbrain.config import _load_toml, project_config_path, save_project_config

    save_project_config(tmp_path, {"conversion": {"bids_validate": False}})
    save_project_config(
        tmp_path,
        {"conversion": {"nd_duplicates": "both"}},
        owned={"conversion": ("nd_duplicates",)},
    )
    stored = _load_toml(project_config_path(tmp_path))["conversion"]
    assert stored["nd_duplicates"] == "both"
    assert stored["bids_validate"] is False


# --- unit_work_dir: the qualifier's edges --------------------------------------
#
# The happy path and the collision it exists to prevent are pinned next to the
# templates that consume it, in test_sbatch_templates.py. What is here is the
# set of degenerate inputs a real config can hand it — every one of which used
# to produce a *shorter* path, and a shorter path is a shared one.


def test_scratch_qualifier_survives_a_project_dir_with_nothing_nameable_in_it():
    """Neither half of the qualifier may collapse to empty: the digest is the
    part that actually separates two projects, and the slug is only there so a
    human can recognise the tree on the node."""
    from duckbrain.config import unit_work_dir

    def scratch(bids_dir):
        cfg = {"paths": {"work_dir": "/tmp", "bids_dir": bids_dir}}
        return unit_work_dir(cfg, "fmriprep", "04")

    # A name with no ASCII-safe character left in it, and one that is nothing but
    # dots — which unstripped would name a directory that walks back up the tree.
    for bids_dir in ("/projects/仕事", "/a/.."):
        assert "-project-" in scratch(bids_dir)
        assert "/.." not in scratch(bids_dir)
    # ...and two such projects are still told apart, because the digest and not
    # the slug is what separates them.
    assert scratch("/projects/仕事") != scratch("/a/..")


def test_scratch_falls_back_to_tmp_when_work_dir_is_unset():
    """`base.toml` ships "/tmp", but a project config may blank it — and an empty
    base would put the tree at the filesystem root."""
    from duckbrain.config import unit_work_dir

    assert unit_work_dir({"paths": {"work_dir": ""}}, "mriqc", "04").startswith("/tmp/duckbrain-")
    assert unit_work_dir({}, "mriqc", "04").startswith("/tmp/duckbrain-")


def test_scratch_for_a_stage_with_no_subject_is_still_a_directory():
    from duckbrain.config import unit_work_dir

    assert unit_work_dir({"paths": {}}, "mriqc", "").endswith("/mriqc_all")


def test_scratch_owner_falls_back_when_the_environment_has_no_login_name(monkeypatch):
    """`getpass.getuser()` raises when there is no passwd entry and no
    LOGNAME/USER/USERNAME — a real state inside a stripped container. The name is
    a nicety (it keeps two users off one /tmp tree); failing to build a work dir
    at all over its absence would not be."""
    import getpass

    from duckbrain.config import unit_work_dir

    def boom():
        raise OSError("no login name")

    monkeypatch.setattr(getpass, "getuser", boom)
    assert "-user-" in unit_work_dir({"paths": {}}, "mriqc", "04")
