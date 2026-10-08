"""The bug-report bundle: complete, readable, and never raising."""

import os
import time

from duckbrain.core import bug_report
from duckbrain.core.bug_report import build_bug_report, newest_logs, report_filename


def _config(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    return {
        "paths": {"log_dir": str(log_dir), "work_dir": str(tmp_path)},
        "fmriprep": {"version": "25.2.5", "output_spaces": ["T1w"]},
        "slurm": {"account": "lab", "api_token": "s3cret"},
    }


def _touch(path, text, age_s):
    path.write_text(text)
    t = time.time() - age_s
    os.utime(path, (t, t))


def test_without_a_project_every_section_still_says_something():
    text = build_bug_report(None, what_happened="")
    assert text.startswith("duckbrain bug report. Read it before sending")
    assert "== What happened ==\n(not filled in)" in text
    assert "duckbrain: " in text
    assert "none shown in this browser session" in text
    assert text.count("no project open") == 3  # submissions, logs, config


def test_the_users_words_come_first_and_the_config_last(tmp_path):
    text = build_bug_report(_config(tmp_path), what_happened="Run fMRIPrep did nothing")
    assert text.index("Run fMRIPrep did nothing") < text.index("== Environment ==")
    assert text.index("== Newest logs") < text.index("== Config")
    assert "fmriprep.version = '25.2.5'" in text


def test_credential_shaped_keys_are_redacted(tmp_path):
    text = build_bug_report(_config(tmp_path), what_happened="x")
    assert "s3cret" not in text
    assert "slurm.api_token = '<redacted>'" in text
    assert "slurm.account = 'lab'" in text


def test_the_last_error_is_bundled_whole():
    err = {"page": "Preprocessing", "at": "now", "message": "Launch failed: boom", "trace": "Tb"}
    text = build_bug_report(None, what_happened="x", last_error=err)
    assert "page: Preprocessing" in text
    assert "message: Launch failed: boom" in text
    assert "Tb" in text


def test_newest_logs_are_slurm_and_tool_logs_only_newest_first(tmp_path):
    cfg = _config(tmp_path)
    log_dir = tmp_path / "logs"
    _touch(log_dir / "fmriprep_1.out", "old", 300)
    _touch(log_dir / "fmriprep_2.err", "mid", 200)
    _touch(log_dir / "mriqc_3.out", "new", 100)
    _touch(log_dir / "nordic_4.log", "newest", 50)
    _touch(log_dir / "submissions.tsv", "not a log", 0)
    _touch(log_dir / "bids_filter_01.json", "{}", 0)
    names = [p.name for p in newest_logs(log_dir, 3)]
    assert names == ["nordic_4.log", "mriqc_3.out", "fmriprep_2.err"]
    text = build_bug_report(cfg, what_happened="x")
    assert "newest" in text and "fmriprep_1.out" not in text


def test_a_long_log_is_tailed(tmp_path):
    cfg = _config(tmp_path)
    (tmp_path / "logs" / "big.out").write_text("head\n" + "x" * 20_000 + "\nTHE END\n")
    text = build_bug_report(cfg, what_happened="x", log_bytes=500)
    assert "THE END" in text
    assert "head\n" not in text


def test_a_failing_section_degrades_instead_of_raising(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(bug_report, "_logs_section", boom)
    text = build_bug_report(_config(tmp_path), what_happened="x")
    assert "== Section failed ==\nRuntimeError: disk on fire" in text
    assert "== Config" in text  # the sections after it still ran


def test_report_filename_is_dated():
    assert report_filename().startswith("duckbrain-report-")
    assert report_filename().endswith(".txt")
