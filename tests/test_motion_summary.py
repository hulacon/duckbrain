"""Tests for ``qc.summarize_motion`` — the only reader of fMRIPrep's confounds.

The numbers it produces were never pinned, and `#42.1` narrowed the read that
produces them to a single column. Both halves are here: what the summary says,
and the fact that it does not parse the other ~200 columns to say it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from duckbrain.core import qc

#: Shaped like a real fMRIPrep confounds file: framewise displacement is one
#: column among many, its first row is the ``n/a`` fMRIPrep writes because the
#: first volume has no predecessor, and the rest are regressors nothing here
#: wants.
OTHER_COLUMNS = ("csf", "white_matter", "global_signal", "trans_x", "a_comp_cor_00")


def _confounds(func_dir, name, fd, columns=OTHER_COLUMNS):
    func_dir.mkdir(parents=True, exist_ok=True)
    header = "\t".join(("framewise_displacement", *columns))
    rows = "".join("\t".join((str(v), *("1.0" for _ in columns))) + "\n" for v in fd)
    path = func_dir / name
    path.write_text(f"{header}\n{rows}")
    return path


class TestNumbers:
    def test_one_row_per_run_with_the_entities_of_its_filename(self, tmp_path):
        _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_run-1_desc-confounds_timeseries.tsv",
            ["n/a", 0.1, 0.3],
        )
        _confounds(
            tmp_path / "sub-02" / "func",
            "sub-02_task-rest_run-1_desc-confounds_timeseries.tsv",
            ["n/a", 0.2, 0.2],
        )

        df = qc.summarize_motion(tmp_path)

        assert df["sub"].tolist() == ["01", "02"]
        assert df["task"].tolist() == ["rest", "rest"]
        assert df["mean_fd"].tolist() == [pytest.approx(0.2), pytest.approx(0.2)]
        assert df["max_fd"].tolist() == [pytest.approx(0.3), pytest.approx(0.2)]

    def test_the_leading_na_is_dropped_and_not_counted_as_a_volume(self, tmp_path):
        """fMRIPrep writes ``n/a`` for the first volume — it has no predecessor
        to be displaced from. Counting it would divide every mean by one too
        many."""
        _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_desc-confounds_timeseries.tsv",
            ["n/a", 0.4, 0.6],
        )

        df = qc.summarize_motion(tmp_path)

        assert df["n_volumes"].tolist() == [2]
        assert df["mean_fd"].tolist() == [pytest.approx(0.5)]

    def test_pct_high_motion_is_measured_against_the_given_threshold(self, tmp_path):
        _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_desc-confounds_timeseries.tsv",
            [0.1, 0.2, 0.9, 1.1],
        )

        lenient = qc.summarize_motion(tmp_path, fd_threshold=0.5)
        strict = qc.summarize_motion(tmp_path, fd_threshold=0.15)

        assert lenient["pct_high_motion"].tolist() == [50.0]
        assert strict["pct_high_motion"].tolist() == [75.0]

    def test_a_tree_with_no_confounds_gives_an_empty_frame(self, tmp_path):
        """Not a raise and not a one-row frame of NaNs: the caller renders the
        absence as a banner, and ``build_run_rows`` takes ``None``-or-empty."""
        assert qc.summarize_motion(tmp_path).empty


class TestNarrowedRead:
    def test_a_confounds_file_without_framewise_displacement_is_skipped(self, tmp_path):
        """Older fMRIPrep confounds have no such column, and this is what makes
        the ``usecols`` selector a callable rather than a list — a list raises on
        the file instead of passing over it."""
        func = tmp_path / "sub-01" / "func"
        func.mkdir(parents=True)
        (func / "sub-01_task-rest_desc-confounds_timeseries.tsv").write_text(
            "csf\twhite_matter\n1.0\t1.0\n"
        )

        assert qc.summarize_motion(tmp_path).empty

    def test_only_the_one_column_is_parsed(self, tmp_path, monkeypatch):
        """The point of `#42.1`: four numbers per run were costing a full parse
        of every CompCor and cosine regressor — ~1 GB across a 100-subject
        study. Asserted on the selector because the saving is memory, which no
        return value shows."""
        _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_desc-confounds_timeseries.tsv",
            [0.1, 0.2],
        )

        seen: list = []
        real_read_csv = pd.read_csv

        def recording(*args, **kwargs):
            seen.append(kwargs.get("usecols"))
            return real_read_csv(*args, **kwargs)

        monkeypatch.setattr(qc.pd, "read_csv", recording)
        qc.summarize_motion(tmp_path)

        assert len(seen) == 1
        selector = seen[0]
        assert callable(selector), "a list selector raises on the older no-FD confounds"
        header = ["framewise_displacement", *OTHER_COLUMNS]
        assert [c for c in header if selector(c)] == ["framewise_displacement"]


class TestUnreadable:
    """`D33`: a confounds file that failed to parse used to vanish from the
    summary, so its run looked like a run that never existed. Now it is named."""

    def test_an_unreadable_file_is_named_and_the_rest_still_summarised(self, tmp_path):
        good = _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_desc-confounds_timeseries.tsv",
            [0.1, 0.3],
        )
        bad = good.parent / "sub-01_task-motor_desc-confounds_timeseries.tsv"
        bad.write_text("")  # empty: pandas raises EmptyDataError

        with pytest.warns(RuntimeWarning, match="1 confounds file"):
            df = qc.summarize_motion(tmp_path)

        assert df["task"].tolist() == ["rest"]
        assert len(df.attrs["unreadable"]) == 1
        assert df.attrs["unreadable"][0].startswith(f"{bad}: EmptyDataError")

    def test_a_clean_tree_reports_nothing_unreadable(self, tmp_path):
        _confounds(
            tmp_path / "sub-01" / "func",
            "sub-01_task-rest_desc-confounds_timeseries.tsv",
            [0.1, 0.3],
        )
        assert qc.summarize_motion(tmp_path).attrs["unreadable"] == []

    def test_a_file_without_framewise_displacement_is_not_unreadable(self, tmp_path):
        """Older fMRIPrep confounds lack the column by design; that skip stays
        silent, since the file was read and simply has nothing to summarise."""
        func = tmp_path / "sub-01" / "func"
        func.mkdir(parents=True)
        (func / "sub-01_task-rest_desc-confounds_timeseries.tsv").write_text("csf\n1.0\n")
        assert qc.summarize_motion(tmp_path).attrs["unreadable"] == []
