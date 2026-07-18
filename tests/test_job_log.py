"""Tests for SLURM log resolution (find_job_logs / job_log).

The key case: NORDIC denoise runs as an array job written as ``nordic_%A_%a.out``
(one file per subject/task), which the plain ``*_<job_id>.out`` glob misses.
"""

from duckbrain.slurm.monitor import find_job_logs, job_log


def test_plain_per_job_log_resolves(tmp_path):
    (tmp_path / "fmriprep_45452962.out").write_text("done\n")
    files = find_job_logs("45452962", str(tmp_path))
    assert [p.name for p in files] == ["fmriprep_45452962.out"]
    assert job_log("45452962", str(tmp_path))["stdout"] == "done\n"


def test_array_job_logs_resolve_all_tasks(tmp_path):
    # nordic_<A>_<a>.out — one per array task; the trailing _<a> defeats *_<A>.out.
    for a in (1, 2, 10):
        (tmp_path / f"nordic_45428802_{a}.out").write_text(f"task {a}\n")
    files = find_job_logs("45428802", str(tmp_path))
    assert {p.name for p in files} == {
        "nordic_45428802_1.out", "nordic_45428802_2.out", "nordic_45428802_10.out"}
    combined = job_log("45428802", str(tmp_path))["stdout"]
    assert "task 1" in combined and "task 10" in combined


def test_stderr_routed_separately(tmp_path):
    (tmp_path / "mriqc_5.out").write_text("out\n")
    (tmp_path / "mriqc_5.err").write_text("err\n")
    logs = job_log("5", str(tmp_path))
    assert logs["stdout"] == "out\n"
    assert logs["stderr"] == "err\n"


def test_no_match_returns_empty(tmp_path):
    assert find_job_logs("99999", str(tmp_path)) == []
    assert job_log("99999", str(tmp_path)) == {"stdout": "", "stderr": ""}


def test_job_id_is_not_a_prefix_false_match(tmp_path):
    # job 454 must not pick up job 45428802's files.
    (tmp_path / "nordic_45428802_1.out").write_text("other\n")
    (tmp_path / "fmriprep_454.out").write_text("mine\n")
    files = find_job_logs("454", str(tmp_path))
    assert [p.name for p in files] == ["fmriprep_454.out"]


def test_cancel_job_invokes_scancel(monkeypatch):
    import duckbrain.slurm.monitor as M

    calls = {}

    class R:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        return R()

    monkeypatch.setattr(M.subprocess, "run", fake_run)
    M.cancel_job("12345")
    assert calls["cmd"] == ["scancel", "12345"]


def test_cancel_job_raises_on_failure(monkeypatch):
    import duckbrain.slurm.monitor as M
    import pytest

    class R:
        returncode = 1
        stderr = "Invalid job id"

    monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: R())
    with pytest.raises(RuntimeError, match="scancel failed"):
        M.cancel_job("999")
