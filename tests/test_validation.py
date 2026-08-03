"""BIDS validation — command construction, the can't-run contract, and parsing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from duckbrain.core.validation import (
    _MAX_FILES_PER_ISSUE,
    ValidationResult,
    parse_validator_output,
    validate_bids,
    validator_command,
    validator_unavailable_reason,
)

FIXTURE = Path(__file__).parent / "fixtures" / "bids_validator" / "dwi_eyeball.json"


# ---- the command ----


def test_the_command_skips_symlinked_directories():
    """--ignoreSymlinks is the whole point, and it cannot be omitted.

    Without it the validator follows `sourcedata/sub-XX/dicom` into the DICOM
    export and reports every file behind it as NOT_INCLUDED, with paths that have
    escaped the dataset root — so the ignore test, whose defaults already include
    /sourcedata, can never match them. Measured on `dwi_eyeball`: 2605 files
    indexed and 2540 NOT_INCLUDED errors without, 66 files and zero with.
    """
    cmd = validator_command("/x.sif", "/b")
    assert "--ignoreSymlinks" in cmd


def test_the_command_uses_exec_not_run():
    """The dcm2bids image's runscript IS dcm2bids.

    `singularity run <sif> bids-validator …` would hand those tokens to dcm2bids
    as arguments and never reach the validator.
    """
    cmd = validator_command("/x.sif", "/b")
    assert cmd[:2] == ["singularity", "exec"]
    assert "run" not in cmd[:3]


def test_the_bids_dir_is_bound_and_is_the_target():
    cmd = validator_command("/x.sif", "/projects/study")
    assert "-B" in cmd
    assert cmd[cmd.index("-B") + 1] == "/projects/study:/projects/study"
    assert cmd[-1] == "/projects/study"


def test_json_is_asked_for_only_by_the_gui():
    """The sbatch wants human-readable output; the panel needs to parse it."""
    assert "--json" not in validator_command("/x.sif", "/b")
    assert "--json" in validator_command("/x.sif", "/b", json_output=True)


# ---- the can't-run contract ----


def test_unavailable_reason_names_what_is_missing(tmp_path, monkeypatch):
    """Every arm is pinned, including whether singularity is on PATH.

    That last one has to be monkeypatched rather than inherited: a developer
    machine has singularity and CI does not, so an unpatched
    ``== ""`` passes locally and fails on both CI Pythons. It did — this test
    broke the build for four commits while every local run stayed green.
    """
    bids = tmp_path / "b"
    bids.mkdir()
    sif = tmp_path / "x.sif"
    sif.write_text("")
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/singularity")

    assert "BIDS directory" in validator_unavailable_reason(sif, "")
    assert "not found" in validator_unavailable_reason(sif, tmp_path / "nope")
    assert "container" in validator_unavailable_reason(None, bids)
    assert "not found" in validator_unavailable_reason(tmp_path / "missing.sif", bids)
    assert validator_unavailable_reason(sif, bids) == ""

    # And the arm that only a machine without a container runtime would reach —
    # which is exactly the machine this used to fail on.
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert "PATH" in validator_unavailable_reason(sif, bids)


def test_a_run_that_could_not_happen_says_so_rather_than_reading_clean(tmp_path):
    """An empty issue list from a run that never happened renders as a clean
    dataset, which is exactly the silently-wrong answer this must not give."""
    cfg = {"paths": {"bids_dir": str(tmp_path), "containers_dir": str(tmp_path)}}
    result = validate_bids(cfg)

    assert result.ran is False
    assert result.unavailable_reason
    assert result.issues == ()
    assert "could not run" in result.headline()


def test_a_subprocess_that_blows_up_is_reported_not_swallowed(tmp_path, monkeypatch):
    bids = tmp_path / "b"
    bids.mkdir()
    sif = tmp_path / "dcm2bids-3.2.0.sif"
    sif.write_text("")
    cfg = {
        "paths": {"bids_dir": str(bids), "containers_dir": str(tmp_path)},
        "containers": {"dcm2bids_version": "3.2.0"},
    }
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/singularity")

    def boom(cmd, timeout_s):
        raise subprocess.TimeoutExpired(cmd, timeout_s)

    monkeypatch.setattr("duckbrain.core.validation._run_validator", boom)
    result = validate_bids(cfg)

    assert result.ran is False
    assert "bids-validator" in result.unavailable_reason


# ---- parsing ----


def test_parses_errors_warnings_and_summary_from_real_validator_json():
    """Against output captured from a real run, so a validator upgrade that
    changes the JSON fails a test rather than blanking the panel."""
    issues, summary = parse_validator_output(FIXTURE.read_text())

    codes = [i.code for i in issues]
    assert codes[0] == "DATASET_DESCRIPTION_JSON_MISSING"
    assert set(codes) >= {"README_FILE_MISSING", "EVENTS_TSV_MISSING"}

    errors = [i for i in issues if i.severity == "error"]
    assert [i.code for i in errors] == ["DATASET_DESCRIPTION_JSON_MISSING"]

    events = next(i for i in issues if i.code == "EVENTS_TSV_MISSING")
    assert events.n_files == 7
    assert all(p.startswith("/sub-") for p in events.files)
    assert events.help_url

    assert summary["totalFiles"] == 66


def test_a_dataset_level_issue_with_no_file_entry_parses():
    """`DATASET_DESCRIPTION_JSON_MISSING` carries `file: null` — it is about a
    file that by definition is not there."""
    issues, _ = parse_validator_output(FIXTURE.read_text())
    missing = next(i for i in issues if i.code == "DATASET_DESCRIPTION_JSON_MISSING")

    assert missing.files == ()
    assert missing.n_files == 1
    assert missing.reason


def test_a_broad_error_is_summarised_not_repeated_per_file():
    """The flood this module fixes was 2540 paths in a log; repeating them in an
    expander would be the same failure one layer up."""
    payload = json.dumps(
        {
            "issues": {
                "errors": [
                    {
                        "key": "NOT_INCLUDED",
                        "code": 1,
                        "reason": "…",
                        "files": [{"file": {"relativePath": f"/x/{i}.dcm"}} for i in range(2540)],
                    }
                ],
                "warnings": [],
            },
            "summary": {"totalFiles": 2540},
        }
    )
    issues, _ = parse_validator_output(payload)

    assert len(issues) == 1
    assert issues[0].n_files == 2540
    assert len(issues[0].files) == _MAX_FILES_PER_ISSUE


def test_leading_noise_on_stdout_does_not_defeat_the_parse():
    """The container emits a Node warning about directory handles before the JSON."""
    noise = "(node:123) Warning: Closing directory handle on garbage collection\n"
    issues, summary = parse_validator_output(noise + FIXTURE.read_text())

    assert issues
    assert summary["totalFiles"] == 66


def test_output_that_is_not_json_parses_to_nothing_rather_than_raising():
    assert parse_validator_output("command not found") == ((), {})


# ---- freshness ----


def test_a_second_call_re_reads_the_dataset(tmp_path, monkeypatch):
    """Deliberately not memoised. A cache keyed on the dataset path would serve a
    stale 'clean' after a bad conversion — the failure this item exists to end."""
    bids = tmp_path / "b"
    bids.mkdir()
    (tmp_path / "dcm2bids-3.2.0.sif").write_text("")
    cfg = {
        "paths": {"bids_dir": str(bids), "containers_dir": str(tmp_path)},
        "containers": {"dcm2bids_version": "3.2.0"},
    }
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/singularity")

    payloads = iter(
        [
            json.dumps({"issues": {"errors": [], "warnings": []}, "summary": {"totalFiles": 1}}),
            FIXTURE.read_text(),
        ]
    )

    def fake(cmd, timeout_s):
        return subprocess.CompletedProcess(cmd, 0, next(payloads), "")

    monkeypatch.setattr("duckbrain.core.validation._run_validator", fake)

    first = validate_bids(cfg)
    second = validate_bids(cfg)

    assert first.issues == ()
    assert second.issues  # the dataset changed and the answer changed with it


# ---- the result's own reporting ----


@pytest.mark.parametrize(
    "issues,expected",
    [
        ((), "clean"),
        ((("error",),), "1 error"),
        ((("warning",), ("warning",)), "2 warnings"),
        ((("error",), ("warning",)), "1 error, 1 warning"),
    ],
)
def test_the_headline_folds_the_state_into_a_phrase(issues, expected):
    from datetime import datetime

    from duckbrain.core.validation import ValidationIssue

    result = ValidationResult(
        bids_dir="/b",
        ran_at=datetime(2026, 8, 3, 12, 3, 41),
        issues=tuple(ValidationIssue(code="X", severity=s, reason="") for (s,) in issues),
    )
    assert result.headline().startswith(expected)
