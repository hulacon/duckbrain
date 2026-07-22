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
        "nordic_45428802_1.out",
        "nordic_45428802_2.out",
        "nordic_45428802_10.out",
    }
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


# ---- DB-010: reads are bounded ----------------------------------------------


def test_job_log_reads_only_the_tail_of_a_large_file(tmp_path):
    """job_log used read_text() on every matching file and concatenated the lot,
    to display the last few thousand characters. The cockpit's popover body is
    evaluated on every render — and the dashboard auto-refreshes every 30s — so
    a failed fMRIPrep cell re-read tens of megabytes twice a minute."""
    from duckbrain.slurm.monitor import job_log

    big = tmp_path / "fmriprep_123.out"
    big.write_text("".join(f"line {i}\n" for i in range(200_000)))
    assert big.stat().st_size > 1_000_000

    logs = job_log("123", str(tmp_path), max_bytes=8_000)

    assert len(logs["stdout"]) <= 8_200  # tail plus the elision marker
    assert "line 199999" in logs["stdout"]  # ...and it is the *end*
    assert "line 0\n" not in logs["stdout"]


def test_tail_text_returns_a_short_file_whole(tmp_path):
    from duckbrain.slurm.monitor import tail_text

    p = tmp_path / "small.out"
    p.write_text("just a few lines\nand another\n")
    assert tail_text(p, max_bytes=64_000) == "just a few lines\nand another\n"


def test_tail_text_survives_invalid_encoding(tmp_path):
    from duckbrain.slurm.monitor import tail_text

    p = tmp_path / "binary.out"
    p.write_bytes(b"before\n\xff\xfe not utf-8 \n after\n")
    assert "after" in tail_text(p)


def test_tail_text_drops_the_partial_first_line(tmp_path):
    """Seeking lands mid-line; a truncated fragment reads as corrupt output."""
    from duckbrain.slurm.monitor import tail_text

    p = tmp_path / "log.out"
    p.write_text("aaaaaaaaaaaaaaaaaaaa\nbbbb\ncccc\n")
    out = tail_text(p, max_bytes=12)
    assert out.startswith("…\n")
    assert "aaaa" not in out
