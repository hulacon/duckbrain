"""Trusting the DICOM header over the filename, and letting dcm2bids validate.

Two changes with one theme. duckbrain used to force `PhaseEncodingDirection`
from the `_ap`/`_pa` token in a series name, overwriting the value dcm2niix
derives from the DICOM header — the same "trust the filename over the data"
error as the inverted B0 fields. The header now wins, and a disagreement is
*reported* rather than overwritten, because a name/header mismatch says
something real about the acquisition.
"""

import json

from duckbrain.core.consistency import _check_pe_direction
from duckbrain.core.dcm2bids_config import generate_config
from duckbrain.core.dicom_inspect import FieldmapDetection, SeriesInfo


def _series(num, desc, cls, n=300):
    s = SeriesInfo(series_number=num, description=desc, path=None, file_count=n)
    s.classification = cls
    return s


# ---- duckbrain no longer writes PhaseEncodingDirection ----


def test_fmap_descriptions_do_not_overwrite_phase_encoding_direction():
    series = [
        _series(3, "se_epi_ap", "fmap", n=3),
        _series(4, "se_epi_pa", "fmap", n=3),
    ]
    fmaps = FieldmapDetection(strategy="series_description", groups={"": {"ap": 3, "pa": 4}})
    cfg = generate_config(series, fmaps, subject="001")

    fmap_descs = [d for d in cfg["descriptions"] if d["datatype"] == "fmap"]
    assert fmap_descs, "expected fmap descriptions"
    for d in fmap_descs:
        changes = d["sidecar_changes"]
        # The association is still stated...
        assert changes["B0FieldIdentifier"] == "B0map_"
        # ...but the header value is left exactly as dcm2niix derived it.
        assert "PhaseEncodingDirection" not in changes


# ---- and a name/header disagreement is reported instead ----


def _fmap_sidecar(root, name, ped, datatype="fmap"):
    d = root / "sub-001" / datatype
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"PhaseEncodingDirection": ped}))


def _config(root):
    return {"paths": {"bids_dir": str(root)}}


def test_matching_direction_is_silent(tmp_path):
    _fmap_sidecar(tmp_path, "sub-001_dir-AP_epi.json", "j-")
    _fmap_sidecar(tmp_path, "sub-001_dir-PA_epi.json", "j")
    assert _check_pe_direction(_config(tmp_path)) == []


def test_mismatch_is_flagged_against_the_label_not_the_header(tmp_path):
    """A series named AP whose header says PA: the label is the suspect one."""
    _fmap_sidecar(tmp_path, "sub-001_dir-AP_epi.json", "j")
    issues = _check_pe_direction(_config(tmp_path))

    assert len(issues) == 1
    assert issues[0].check == "pe-direction"
    assert issues[0].subject == "001"
    assert "header is authoritative" in issues[0].message


def test_a_sidecar_without_the_field_is_not_a_finding(tmp_path):
    """Absent metadata degrades quietly rather than raising a false alarm."""
    d = tmp_path / "sub-001" / "fmap"
    d.mkdir(parents=True)
    (d / "sub-001_dir-AP_epi.json").write_text("{}")
    assert _check_pe_direction(_config(tmp_path)) == []


def test_missing_bids_dir_is_not_a_finding(tmp_path):
    assert _check_pe_direction({"paths": {"bids_dir": str(tmp_path / "nope")}}) == []


def test_unknown_dir_entity_is_ignored(tmp_path):
    """A direction with no entry in the table is skipped, not guessed at."""
    _fmap_sidecar(tmp_path, "sub-001_dir-IS_epi.json", "k")
    assert _check_pe_direction(_config(tmp_path)) == []


def test_lr_is_checked_now_that_diffusion_is_labelled_with_it(tmp_path):
    """``LR``/``RL`` entered the table with `#19.1`, so they stopped being ignored.

    They are also the table's least certain rows — measured at two sites rather
    than derived — which is the reason to check them against real headers rather
    than to exempt them.
    """
    _fmap_sidecar(tmp_path, "sub-001_dir-LR_epi.json", "i")
    assert len(_check_pe_direction(_config(tmp_path))) == 1


def test_diffusion_carries_the_same_label_and_gets_the_same_check(tmp_path):
    """The plan-time check and this one must cover the same files, or a
    mislabelled conversion passes one and is never seen by the other."""
    _fmap_sidecar(tmp_path, "sub-001_dir-RL_dwi.json", "i", datatype="dwi")
    _fmap_sidecar(tmp_path, "sub-001_dir-LR_dwi.json", "i", datatype="dwi")

    issues = _check_pe_direction(_config(tmp_path))

    # dir-RL reads `i` as expected; dir-LR should read `i-` and does not.
    assert [i.message.split("`")[1] for i in issues] == ["sub-001_dir-LR_dwi.json"]


# ---- duckbrain runs the validator itself ----


def _render_dcm2bids(cfg, bids_dir="/b"):
    from duckbrain.slurm.templates import build_context, render_sbatch

    cfg["paths"]["bids_dir"] = bids_dir
    ctx = build_context(
        cfg,
        "dcm2bids",
        subject="001",
        session="01",
        dicom_dir="/d",
        config_json="/c.json",
        config_json_dir="/",
        container_path="/x.sif",
        force=False,
    )
    return render_sbatch("dcm2bids", ctx)


def test_dcm2bids_template_requests_validation_by_default(tmp_path):
    """duckbrain calls bids-validator itself, and it must pass --ignoreSymlinks.

    Not dcm2bids' `--bids_validate`: that runs the validator with no flags, and
    without --ignoreSymlinks it follows the `sourcedata/sub-XX/dicom` symlink
    ingestion creates and reports every DICOM behind it as NOT_INCLUDED — 2540 of
    them on `dwi_eyeball`, drowning every real finding. No `.bidsignore` entry can
    fix that; see core/validation.py for why.
    """
    from duckbrain.config import load_config, scaffold_project

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    cfg = load_config(project_dir=str(proj))

    script = _render_dcm2bids(cfg)
    assert "bids-validator" in script
    assert "--ignoreSymlinks" in script
    # dcm2bids' own flag must be gone, or the flood comes back alongside the fix.
    assert "--bids_validate" not in script

    cfg["conversion"] = {"bids_validate": False}
    off = _render_dcm2bids(cfg)
    assert "bids-validator" not in off
    assert "--ignoreSymlinks" not in off


def test_the_sbatch_validator_call_is_the_one_core_validation_builds(tmp_path):
    """The template and core/validation must render the *same* argv.

    Two places construct a validator invocation — this template, for the job log,
    and `core.validation` for the cockpit panel. If they drift, the log and the
    panel validate the dataset differently and neither says so.
    """
    import shlex

    from duckbrain.config import load_config, scaffold_project
    from duckbrain.core.validation import validator_command

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    cfg = load_config(project_dir=str(proj))

    script = _render_dcm2bids(cfg, bids_dir="/projects/study")
    tokens = shlex.split(script.replace("\\\n", " "), comments=True)
    want = validator_command("/x.sif", "/projects/study")

    assert any(tokens[i : i + len(want)] == want for i in range(len(tokens))), (
        f"{want} is not a contiguous run of tokens in the rendered script"
    )


def test_validation_never_changes_the_jobs_exit_code(tmp_path):
    """dcm2bids' status stays the job's status; the validator only reports.

    bids-validator exits 1 whenever it finds an error, so letting it reach
    `exit` would fail conversions that succeeded. It also matches what
    `--bids_validate` already did: dcm2bids ran the validator under a Popen
    wrapper that never inspected the return code.
    """
    from duckbrain.config import load_config, scaffold_project

    proj = tmp_path / "p"
    scaffold_project(str(proj))
    cfg = load_config(project_dir=str(proj))

    lines = [ln.strip() for ln in _render_dcm2bids(cfg).replace("\\\n", " ").splitlines()]
    lines = [ln for ln in lines if ln]

    capture = lines.index("EXIT_CODE=$?")
    validate = next(i for i, ln in enumerate(lines) if "bids-validator" in ln)
    final = lines.index("exit $EXIT_CODE")

    # Nothing between the dcm2bids command and the capture could clobber `$?`,
    # and the validator runs strictly after it.
    assert lines[capture - 1].startswith("singularity run")
    assert capture < validate < final


def test_build_dcm2bids_command_force_includes_clobber():
    """The subprocess path needs the same two flags as the sbatch template.

    Two call sites build the dcm2bids invocation and they must agree, or `force`
    means one thing from the cockpit and another from a direct call. (Validation
    is deliberately not one of them — see the note at the end of
    `build_dcm2bids_command`.)
    """
    from duckbrain.core.conversion import build_dcm2bids_command

    cmd = build_dcm2bids_command("01", "", "/d", "/b", "/c.json", "/x.sif", force=True)
    assert "--clobber" in cmd
    assert "--force_dcm2bids" in cmd

    unforced = build_dcm2bids_command("01", "", "/d", "/b", "/c.json", "/x.sif", force=False)
    assert "--clobber" not in unforced
    assert "--force_dcm2bids" not in unforced
