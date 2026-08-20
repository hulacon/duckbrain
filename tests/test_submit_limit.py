"""Tests for the submit-limit preflight (`#42.4`).

SLURM caps how many jobs one user may have *submitted* — pending plus running —
under two names that can both apply: the association's ``MaxSubmitJobs`` and the
QOS's ``MaxSubmitJobsPerUser``. Talapas sets 30001 and nothing has ever met it
here, which is exactly why this is written against recorded ``sacctmgr`` output
rather than against the cluster: the case that matters is a site setting 100,
where a 200-unit bulk run walks into the ceiling halfway.

The real output, taken 2026-08-20 (`sacctmgr -nP`), is the fixture:

    show assoc where user=bhutch format=Account,QOS,MaxSubmitJobs
        hulacon|normal|
        psy607|normal|
    show qos format=Name,MaxSubmitJobsPerUser
        normal|30001
        interactive|
"""

import pytest

import duckbrain.slurm.monitor as M

TALAPAS = {
    "assoc": ["hulacon|normal|", "psy607|normal|"],
    "qos": ["normal|30001", "interactivegpu|", "interactive|", "memory|"],
}


@pytest.fixture
def sacctmgr(monkeypatch):
    """Answer sacctmgr from a recorded table; record what was asked."""
    asked = []
    table = dict(TALAPAS)

    def fake(args):
        asked.append(args)
        return table["assoc" if "assoc" in args else "qos"]

    monkeypatch.setattr(M, "_sacctmgr", fake)
    monkeypatch.setenv("USER", "bhutch")
    return table, asked


class TestSubmitLimit:
    def test_the_qos_limit_is_found_through_the_association(self, sacctmgr):
        """The association names a QOS and carries no limit of its own — the
        shape Talapas has, and the one a naive read of the assoc table misses."""
        assert M.submit_limit() == 30001

    def test_the_smaller_of_the_two_limits_wins(self, sacctmgr):
        table, _ = sacctmgr
        table["assoc"] = ["hulacon|normal|500"]
        assert M.submit_limit() == 500

    def test_an_account_narrows_to_its_own_association(self, sacctmgr):
        table, _ = sacctmgr
        table["assoc"] = ["hulacon|normal|100", "psy607|normal|900"]
        assert M.submit_limit(account="psy607") == 900

    def test_an_unknown_account_is_unknown_and_not_another_accounts_limit(self, sacctmgr):
        table, _ = sacctmgr
        table["assoc"] = ["hulacon|normal|100"]
        assert M.submit_limit(account="somebody-elses") is None

    def test_no_limit_anywhere_reads_as_unknown(self, sacctmgr):
        """Which the caller must treat as "cannot validate" and never as zero
        headroom — refusing a submission the cluster would have accepted is the
        worse failure, and it is what a `0` default would do."""
        table, _ = sacctmgr
        table["qos"] = ["normal|"]
        assert M.submit_limit() is None

    def test_no_slurm_at_all_reads_as_unknown(self, monkeypatch):
        monkeypatch.setattr(M, "_sacctmgr", lambda args: [])
        monkeypatch.setenv("USER", "bhutch")
        assert M.submit_limit() is None

    def test_the_condition_is_two_argv_words(self, sacctmgr):
        """`where user=x` as one word answers "Unknown condition", which
        `_sacctmgr` reports as an empty result — i.e. silently as "no limit"."""
        _, asked = sacctmgr
        M.submit_limit()
        assoc_call = next(a for a in asked if "assoc" in a)
        assert "where" in assoc_call and "user=bhutch" in assoc_call


class TestSacctmgrShell:
    def test_a_nonzero_exit_is_not_data(self, monkeypatch):
        class R:
            returncode = 1
            stdout = "Unknown condition: where user=x\n"

        monkeypatch.setattr(M.subprocess, "run", lambda cmd, **kw: R())
        assert M._sacctmgr(["show", "qos"]) == []

    def test_a_missing_sacctmgr_is_not_an_exception(self, monkeypatch):
        def boom(cmd, **kw):
            raise OSError("No such file or directory: 'sacctmgr'")

        monkeypatch.setattr(M.subprocess, "run", boom)
        assert M._sacctmgr(["show", "qos"]) == []


class TestRejectionRecognition:
    @pytest.mark.parametrize(
        "message",
        [
            "sbatch: error: AssocMaxSubmitJobLimit",
            "sbatch: error: QOSMaxSubmitJobPerUserLimit",
            "sbatch: error: Batch job submission failed: Job violates accounting/QOS policy "
            "(job submit limit, user's size and/or time limits)",
        ],
    )
    def test_a_full_queue_is_recognised(self, message):
        assert M.is_submit_limit_rejection(message)

    @pytest.mark.parametrize(
        "message",
        [
            "sbatch: error: invalid partition specified: medium",
            "sbatch: error: Invalid account or account/partition combination specified",
            "FileNotFoundError: no such container",
        ],
    )
    def test_every_other_failure_is_one_unit_s_problem(self, message):
        """The distinction is load-bearing: a limit rejection will refuse every
        remaining unit too, so the bulk loop stops on it and only on it."""
        assert not M.is_submit_limit_rejection(message)
