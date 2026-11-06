"""A project's Status board shows every member's jobs, and only the project's.

Job names (``fmriprep_04_01``) are per unit and stage, so two projects with a
``sub-04`` submit identical names, and the board used to tell its own jobs apart
only by asking squeue for the viewer's. Each job now carries the project's tag
as its Slurm comment; the board asks for the whole account and keeps the jobs
with its tag, whoever submitted them.
"""

import subprocess

import pandas as pd
import pytest

import duckbrain.core.pipeline as P
import duckbrain.slurm.monitor as M
from duckbrain.config import project_job_comment, project_key, unit_work_dir
from duckbrain.core.pipeline import (
    PipelineError,
    advance_one,
    belongs_to_project,
    read_submissions,
    record_submission,
    survey_live,
)
from duckbrain.slurm.monitor import JobInfo, job_history, list_jobs


def _config(root, account="lab"):
    return {
        "paths": {
            "bids_dir": str(root),
            "sourcedata_dir": str(root / "sourcedata"),
            "derivatives_dir": str(root / "derivatives"),
            "log_dir": str(root / "code" / "logs"),
            "work_dir": "/tmp",
        },
        "slurm": {"account": account},
    }


def _job(job_id, name, user, comment="", state="RUNNING"):
    return JobInfo(job_id=job_id, name=name, state=state, partition="c", user=user, comment=comment)


# ---- the project's identity ----------------------------------------------------


def test_project_key_is_stable_and_tells_projects_apart(tmp_path):
    a, b = _config(tmp_path / "study"), _config(tmp_path / "other" / "study")
    assert project_key(a) == project_key(_config(tmp_path / "study"))
    assert project_key(a) != project_key(b)  # same basename, different project
    assert project_key(a).startswith("study-")


def test_scratch_still_uses_the_same_qualifier(tmp_path):
    """Refactored out of unit_work_dir; a changed qualifier would orphan caches."""
    cfg = _config(tmp_path / "study")
    assert f"-{project_key(cfg)}/fmriprep_sub-04" in unit_work_dir(cfg, "fmriprep", "04")


# ---- squeue / sacct over an account ----------------------------------------------


def _fake_run(monkeypatch, stdout):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(M.subprocess, "run", run)
    return calls


def test_list_jobs_over_an_account_reads_every_user_and_the_comment(monkeypatch):
    calls = _fake_run(
        monkeypatch,
        "11|fmriprep_04_01|RUNNING|c|1:00|2:00|n1|n1|alice|duckbrain:study-0a1b2c3d\n"
        "12|mriqc_04_01|PENDING|c|0:00|1:00||(Priority)|bob|(null)\n"
        "13|odd|RUNNING|c|0:01|1:00|n2|n2|bob|a|comment|with bars\n",
    )
    jobs = list_jobs(account="lab", name="fmriprep_04_01")

    argv = calls[0]
    assert argv[argv.index("-A") + 1] == "lab" and "-u" not in argv
    assert argv[argv.index("-n") + 1] == "fmriprep_04_01"
    assert [(j.user, j.comment) for j in jobs] == [
        ("alice", "duckbrain:study-0a1b2c3d"),
        ("bob", ""),  # squeue spells an unset comment "(null)"
        ("bob", "a|comment|with bars"),  # free text keeps its separators
    ]


def test_list_jobs_without_an_account_is_the_viewers_own(monkeypatch):
    calls = _fake_run(monkeypatch, "")
    monkeypatch.setenv("USER", "carol")
    list_jobs()
    assert calls[0][calls[0].index("-u") + 1] == "carol"


def test_job_history_over_an_account_asks_for_all_users(monkeypatch):
    calls = _fake_run(
        monkeypatch,
        "21|fmriprep_04_01|FAILED|c|0:10|2:00|n1|2026-11-01T10:00:00|s|e|1:0|alice|duckbrain:x\n"
        "21.batch|batch|FAILED||0:10||n1|s|s|e|1:0||\n",
    )
    jobs = job_history(days=7, account="lab")
    argv = calls[0]
    assert "--allusers" in argv and argv[argv.index("--accounts") + 1] == "lab"
    assert [(j.job_id, j.user, j.comment) for j in jobs] == [("21", "alice", "duckbrain:x")]


# ---- which jobs are the project's ------------------------------------------------


def test_belongs_to_project():
    tag = "duckbrain:study-0a1b2c3d"
    assert belongs_to_project(_job("1", "n", "alice", tag), tag, set(), "me")
    # Another project's identically named job: the bug a name-only join had.
    assert not belongs_to_project(_job("2", "n", "me", "duckbrain:other-ffff"), tag, set(), "me")
    # Untagged jobs predate the tag: the viewer's own, or the project log's.
    assert belongs_to_project(_job("3", "n", "me"), tag, set(), "me")
    assert belongs_to_project(_job("4_2", "n", "alice"), tag, {"4"}, "me")
    assert not belongs_to_project(_job("5", "n", "alice"), tag, set(), "me")
    # A non-duckbrain comment is not a tag: judged as untagged.
    assert belongs_to_project(_job("6", "n", "me", "my note"), tag, set(), "me")


_COLS = ["subject", "session", "ingested", "converted", "fmriprep", "mriqc"]


def _board(monkeypatch, tmp_path, active=(), hist=()):
    cfg = _config(tmp_path)
    row = {
        "subject": "04",
        "session": "01",
        "ingested": "complete",
        "converted": "complete",
        "fmriprep": "missing",
        "mriqc": "missing",
    }
    seen = {}

    def fake_list(**kw):
        seen["list"] = kw
        return list(active)

    def fake_hist(days=7, **kw):
        seen["hist"] = kw
        return list(hist)

    monkeypatch.setenv("USER", "me")
    monkeypatch.setattr(P, "survey_project", lambda c: pd.DataFrame([row], columns=_COLS))
    monkeypatch.setattr(P, "list_jobs", fake_list)
    monkeypatch.setattr(P, "job_history", fake_hist)
    matrix, jobs = survey_live(cfg, with_jobs=True)
    return cfg, matrix.iloc[0], jobs, seen


def test_a_labmates_running_job_reads_running_on_my_board(monkeypatch, tmp_path):
    tag = project_job_comment(_config(tmp_path))
    _, row, jobs, seen = _board(
        monkeypatch, tmp_path, active=[_job("11", "fmriprep_04_01", "alice", tag)]
    )
    assert seen["list"] == {"account": "lab"} and seen["hist"] == {"account": "lab"}
    assert row["fmriprep_job"] == "running"
    assert not P.stage_runnable(row, "fmriprep")
    assert jobs["by_id"]["11"].user == "alice"


def test_another_projects_job_with_the_same_name_stays_off_the_board(monkeypatch, tmp_path):
    _, row, jobs, _ = _board(
        monkeypatch,
        tmp_path,
        active=[
            _job("12", "fmriprep_04_01", "me", "duckbrain:other-ffffffff"),
            _job("13", "mriqc_04_01", "alice", "duckbrain:other-ffffffff"),
        ],
    )
    assert row["fmriprep_job"] == "" and row["mriqc_job"] == ""
    # The viewer's own job from another project stays in the all-jobs panel;
    # a labmate's job from another project does not appear at all.
    assert [j.job_id for j in jobs["active"]] == ["12"]


def test_with_no_account_the_board_is_the_viewers_own(monkeypatch, tmp_path):
    cfg = _config(tmp_path, account="")
    monkeypatch.setattr(P, "survey_project", lambda c: pd.DataFrame(columns=_COLS))
    seen = {}
    monkeypatch.setattr(P, "list_jobs", lambda **kw: seen.setdefault("list", kw) and [])
    monkeypatch.setattr(P, "job_history", lambda days=7, **kw: seen.setdefault("hist", kw) and [])
    survey_live(cfg)
    assert seen == {"list": {}, "hist": {}}


# ---- submitting --------------------------------------------------------------------


def _stub_build(monkeypatch):
    """Skip the MRIQC builder (it wants a real container); keep everything after."""
    import dataclasses

    spec = dataclasses.replace(P.STAGE_SPECS["mriqc"], build=lambda *a: ("mriqc", {}))
    monkeypatch.setitem(P.STAGE_SPECS, "mriqc", spec)
    monkeypatch.setattr(P, "render_sbatch", lambda template, ctx: "#script")


def test_a_launch_is_refused_while_a_labmate_has_the_same_job(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    _stub_build(monkeypatch)
    monkeypatch.setenv("USER", "me")
    tag = project_job_comment(cfg)
    asked = {}

    def fake_list(**kw):
        asked.update(kw)
        return [_job("31", "mriqc_04_01", "alice", tag, state="PENDING")]

    monkeypatch.setattr(P, "list_jobs", fake_list)
    monkeypatch.setattr(P, "submit_job", lambda *a, **k: pytest.fail("submitted twice"))
    with pytest.raises(PipelineError, match=r"already pending as job 31, submitted by alice"):
        advance_one(cfg, "mriqc", "04", "01")
    assert asked == {"account": "lab", "name": "mriqc_04_01"}


def test_a_launch_goes_ahead_when_only_another_project_has_the_name(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    _stub_build(monkeypatch)
    monkeypatch.setattr(
        P, "list_jobs", lambda **kw: [_job("32", "mriqc_04_01", "me", "duckbrain:other-ffffffff")]
    )
    monkeypatch.setattr(P, "submit_job", lambda *a, **k: "33")
    assert advance_one(cfg, "mriqc", "04", "01") == "33"


def test_a_launch_is_not_blocked_when_slurm_cannot_be_asked(monkeypatch, tmp_path):
    cfg = _config(tmp_path)
    _stub_build(monkeypatch)

    def boom(**kw):
        raise OSError("no squeue")

    monkeypatch.setattr(P, "list_jobs", boom)
    monkeypatch.setattr(P, "submit_job", lambda *a, **k: "34")
    assert advance_one(cfg, "mriqc", "04", "01") == "34"


# ---- who ran what ------------------------------------------------------------------


def test_the_submission_log_and_request_record_name_the_submitter(monkeypatch, tmp_path):
    import json

    cfg = _config(tmp_path)
    _stub_build(monkeypatch)
    monkeypatch.setenv("USER", "alice")
    monkeypatch.setattr(P, "list_jobs", lambda **kw: [])
    monkeypatch.setattr(P, "submit_job", lambda *a, **k: "41")
    advance_one(cfg, "mriqc", "04", "01")

    log = read_submissions(cfg)
    assert log.iloc[-1]["user"] == "alice"
    request = json.loads(open(log.iloc[-1]["request_path"]).read())
    assert request["user"] == "alice"


def test_the_log_lock_leaves_a_group_writable_lock_file(tmp_path):
    import os
    import stat

    cfg = _config(tmp_path)
    old = os.umask(0o002)
    try:
        record_submission(cfg, "mriqc", "04", "01", "51")
    finally:
        os.umask(old)
    lock = tmp_path / "code" / "logs" / "submissions.tsv.lock"
    assert lock.exists() and stat.S_IMODE(lock.stat().st_mode) & stat.S_IWGRP
