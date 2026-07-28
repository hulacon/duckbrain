"""Tests for the QC decision model — vocabulary, sign-off, and both schemas.

The rule these pin: a decision counts only when an identifiable person made it.
duckbrain wrote decisions for months with ``reviewer`` defaulting to ``""`` and
the page never passing one, so every record it produced is anonymous. Those
cannot be attributed retroactively, and the reader must surface them as such
rather than promote them.
"""

import json

import pytest

from duckbrain.core import qc, qc_report

KEY = "sub-015_task-rest_run-1_bold"


class TestVocabulary:
    def test_pending_is_a_decision(self):
        assert "pending" in qc.VALID_DECISIONS
        assert "pending" not in qc.SIGNED_OFF_DECISIONS

    def test_unknown_verdict_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid decision"):
            qc.save_decision(tmp_path, KEY, "maybe", reviewer="ben")

    def test_unknown_recommendation_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid recommendation"):
            qc.save_decision(tmp_path, KEY, "pending", automated=True, recommendation="maybe")


class TestHumanSignOffRequiresAName:
    def test_blank_reviewer_is_refused(self, tmp_path):
        """The failure this whole slice exists to stop happening again."""
        with pytest.raises(ValueError, match="identifiable reviewer"):
            qc.save_decision(tmp_path, KEY, "keep")

    def test_whitespace_reviewer_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="identifiable reviewer"):
            qc.save_decision(tmp_path, KEY, "keep", reviewer="   ")

    def test_automation_name_is_refused_for_a_human_sign_off(self, tmp_path):
        with pytest.raises(ValueError, match="identifiable reviewer"):
            qc.save_decision(tmp_path, KEY, "keep", reviewer="auto-stub")

    def test_named_reviewer_is_accepted_and_recorded(self, tmp_path):
        path = qc.save_decision(tmp_path, KEY, "keep", reason="looks fine", reviewer="ben")
        entry = json.loads(path.read_text())["decisions"][-1]
        assert entry["reviewer"] == "ben"
        assert entry["automated"] is False
        assert qc.is_signed_off(entry)


class TestAutomatedWritersMayOnlyRecordPending:
    @pytest.mark.parametrize("verdict", ["keep", "exclude", "investigate"])
    def test_automation_cannot_claim_a_verdict(self, tmp_path, verdict):
        with pytest.raises(ValueError, match="only record 'pending'"):
            qc.save_decision(tmp_path, KEY, verdict, reviewer="auto-stub", automated=True)

    def test_automation_records_pending_with_a_recommendation(self, tmp_path):
        path = qc.save_decision(
            tmp_path,
            KEY,
            "pending",
            reason="mean_fd=0.6mm",
            reviewer="auto-stub",
            automated=True,
            recommendation="investigate",
        )
        entry = json.loads(path.read_text())["decisions"][-1]
        assert entry["decision"] == "pending"
        assert entry["recommendation"] == "investigate"
        assert not qc.is_signed_off(entry)


class TestHistoryIsAppendOnly:
    def test_each_save_appends_and_the_last_is_current(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "keep", reviewer="ben")
        qc.save_decision(tmp_path, KEY, "exclude", reason="changed mind", reviewer="ben")
        record = qc.load_decisions(tmp_path)[KEY]
        assert [e["decision"] for e in record["history"]] == ["keep", "exclude"]
        assert record["latest"]["decision"] == "exclude"

    def test_written_in_the_shared_schema(self, tmp_path):
        """mmmdata writes this shape too, so neither tool needs a conversion."""
        path = qc.save_decision(tmp_path, KEY, "keep", reviewer="ben")
        data = json.loads(path.read_text())
        assert data["run_key"] == KEY
        assert isinstance(data["decisions"], list)


class TestReadsBothSchemas:
    """Neither reader used to understand the other's file. Both are read now."""

    def test_legacy_duckbrain_shape_is_read(self, tmp_path):
        (tmp_path / f"{KEY}_decision.json").write_text(
            json.dumps(
                {
                    "latest": {"decision": "keep", "reviewer": "", "reason": "r"},
                    "history": [{"decision": "investigate", "reviewer": ""}],
                }
            )
        )
        record = qc.load_decisions(tmp_path)[KEY]
        assert [e["decision"] for e in record["history"]] == ["investigate", "keep"]
        assert record["latest"]["decision"] == "keep"

    def test_mmmdata_shape_is_read(self, tmp_path):
        nested = tmp_path / "sub-015"
        nested.mkdir()
        (nested / f"{KEY}_decision.json").write_text(
            json.dumps(
                {
                    "run_key": KEY,
                    "decisions": [{"decision": "keep", "reviewer": "auto-stub", "automated": True}],
                }
            )
        )
        record = qc.load_decisions(tmp_path)[KEY]
        assert record["latest"]["decision"] == "keep"
        assert record["signed_off"] is False

    def test_legacy_anonymous_record_is_never_promoted(self, tmp_path):
        """It carries a verdict, but nobody can be named as its author."""
        (tmp_path / f"{KEY}_decision.json").write_text(
            json.dumps({"latest": {"decision": "keep", "reviewer": ""}, "history": []})
        )
        record = qc.load_decisions(tmp_path)[KEY]
        assert record["latest"]["decision"] == "keep"
        assert record["signed_off"] is False

    def test_reading_does_not_rewrite_the_file(self, tmp_path):
        """A legacy record must survive being read exactly as it was.

        Rewriting it would restamp a decision with provenance it does not have.
        """
        path = tmp_path / f"{KEY}_decision.json"
        original = json.dumps({"latest": {"decision": "keep", "reviewer": ""}, "history": []})
        path.write_text(original)
        qc.load_decisions(tmp_path)
        assert path.read_text() == original

    def test_appending_to_a_legacy_file_keeps_its_history(self, tmp_path):
        path = tmp_path / f"{KEY}_decision.json"
        path.write_text(json.dumps({"latest": {"decision": "keep", "reviewer": ""}, "history": []}))
        qc.save_decision(tmp_path, KEY, "exclude", reviewer="ben")
        data = json.loads(path.read_text())
        assert [e["decision"] for e in data["decisions"]] == ["keep", "exclude"]
        assert data["decisions"][0]["reviewer"] == ""

    def test_unreadable_file_is_skipped(self, tmp_path):
        (tmp_path / f"{KEY}_decision.json").write_text("{not json")
        assert qc.load_decisions(tmp_path) == {}

    def test_empty_history_is_not_a_decision(self, tmp_path):
        (tmp_path / f"{KEY}_decision.json").write_text(json.dumps({"decisions": []}))
        assert qc.load_decisions(tmp_path) == {}

    def test_missing_directory_is_empty(self, tmp_path):
        assert qc.load_decisions(tmp_path / "nope") == {}


class TestIsSignedOff:
    @pytest.mark.parametrize(
        "record",
        [
            None,
            {},
            {"decision": "pending", "reviewer": "ben"},
            {"decision": "keep", "reviewer": ""},
            {"decision": "keep", "reviewer": "auto-stub"},
            {"decision": "keep", "reviewer": "AUTO"},
            {"decision": "keep", "reviewer": "ben", "automated": True},
        ],
    )
    def test_rejects(self, record):
        assert qc.is_signed_off(record) is False

    def test_accepts_a_named_human_verdict(self):
        assert qc.is_signed_off({"decision": "exclude", "reviewer": "ben"}) is True


class TestDecisionCounts:
    def test_reports_each_kind_separately(self, tmp_path):
        qc.save_decision(tmp_path, "sub-01_bold", "keep", reviewer="ben")
        qc.save_decision(tmp_path, "sub-02_bold", "pending", reviewer="auto-stub", automated=True)
        (tmp_path / "sub-03_bold_decision.json").write_text(
            json.dumps({"latest": {"decision": "keep", "reviewer": ""}, "history": []})
        )
        (tmp_path / "sub-04_bold_decision.json").write_text(
            json.dumps({"decisions": [{"decision": "pending", "reviewer": ""}]})
        )
        assert qc.decision_counts(qc.load_decisions(tmp_path)) == {
            "signed_off": 1,
            "automated": 1,
            "unattributed": 1,
            "pending": 1,
        }

    def test_legacy_auto_stub_counts_as_automated_not_unattributed(self, tmp_path):
        """mmmdata's 609 records predate the flag and are named 'auto-stub'.

        A machine-written record and one whose author cannot be identified are
        different provenance situations; only the second is a gap someone could
        still close. Classifying by reviewer name is what keeps them apart
        without rewriting any file.
        """
        (tmp_path / "sub-01_bold_decision.json").write_text(
            json.dumps({"decisions": [{"decision": "keep", "reviewer": "auto-stub"}]})
        )
        counts = qc.decision_counts(qc.load_decisions(tmp_path))
        assert counts["automated"] == 1
        assert counts["unattributed"] == 0

    def test_empty_reviewer_is_unattributed_not_automated(self, tmp_path):
        """An absent name means unknown author — not a known machine."""
        (tmp_path / "sub-01_bold_decision.json").write_text(
            json.dumps({"decisions": [{"decision": "keep", "reviewer": ""}]})
        )
        counts = qc.decision_counts(qc.load_decisions(tmp_path))
        assert counts["unattributed"] == 1
        assert counts["automated"] == 0

    def test_empty_set_counts_nothing(self):
        assert qc.decision_counts({}) == {
            "signed_off": 0,
            "automated": 0,
            "unattributed": 0,
            "pending": 0,
        }


class TestReportReflectsTheModel:
    """The renderer and the store must agree on what a sign-off is."""

    def _rows(self, latest):
        import pandas as pd

        df = pd.DataFrame([{"sub": "015", "task": "rest", "run": "1", "tsnr": 43.0}])
        return qc_report.build_run_rows(df, "bold", ["tsnr"], decisions={KEY: {"latest": latest}})

    def test_automated_record_shows_its_suggestion_not_a_verdict(self):
        rows = self._rows(
            {
                "decision": "pending",
                "reviewer": "auto-stub",
                "automated": True,
                "recommendation": "investigate",
            }
        )
        html = qc_report.render_report(rows, "bold", ["tsnr"])
        assert "suggests: investigate" in html
        assert ">PENDING<" in html
        assert '<div class="card card-ok">0<span>Signed off</span></div>' in html

    def test_automated_verdict_cannot_be_shown_as_signed_off(self):
        """Even if a file claims one, automated=True disqualifies it."""
        rows = self._rows({"decision": "keep", "reviewer": "ben", "automated": True})
        html = qc_report.render_report(rows, "bold", ["tsnr"])
        assert '<div class="card card-ok">0<span>Signed off</span></div>' in html


class TestDomainReviewsAreNotVerdicts:
    """The safety property Slice E rests on.

    Domain entries share the append-only list with run verdicts, and
    ``load_decisions`` reads ``latest`` straight into the run's badge, its
    sign-off state and its counts. If a domain note could land there, noting
    "SDC looks off" on the alignment page would silently flip the run's verdict
    in every view — the shape of the bug where typing a reason recorded an
    ``investigate`` nobody made, with the arrow reversed.
    """

    def test_the_two_vocabularies_share_only_pending(self):
        """Structural, not conventional — everything below depends on it.

        ``pending`` is common to both and harmless, because it is a sign-off in
        neither: it is the word for "nobody has said anything yet".
        """
        assert qc.VALID_DECISIONS & qc.VALID_DOMAIN_STATES == {"pending"}
        assert qc.SIGNED_OFF_DECISIONS.isdisjoint(qc.SIGNED_OFF_DOMAIN_STATES)

    def test_a_verdict_word_is_refused_for_a_domain(self, tmp_path):
        with pytest.raises(ValueError, match="a run verdict"):
            qc.save_decision(tmp_path, KEY, "keep", reviewer="ben", domain="signal")

    def test_a_domain_word_is_refused_as_a_verdict(self, tmp_path):
        with pytest.raises(ValueError, match="a domain review state"):
            qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben")

    def test_a_domain_entry_never_becomes_the_runs_verdict(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "keep", reviewer="ben")
        qc.save_decision(tmp_path, KEY, "concerns", reviewer="ben", domain="alignment")
        record = qc.load_decisions(tmp_path)[KEY]
        assert record["latest"]["decision"] == "keep"
        assert record["signed_off"] is True

    def test_a_domain_entry_alone_leaves_the_run_without_a_verdict(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain="signal")
        record = qc.load_decisions(tmp_path)[KEY]
        assert record["latest"] == {}
        assert record["signed_off"] is False

    def test_domain_entries_do_not_disturb_the_counts(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "keep", reviewer="ben")
        before = qc.decision_counts(qc.load_decisions(tmp_path))
        for key in ("signal", "temporal", "alignment", "artifact"):
            qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain=key)
        assert qc.decision_counts(qc.load_decisions(tmp_path)) == before

    def test_a_domain_review_is_recorded_and_readable(self, tmp_path):
        qc.save_decision(
            tmp_path, KEY, "concerns", reason="ringing", reviewer="ben", domain="artifact"
        )
        domains = qc.load_decisions(tmp_path)[KEY]["domains"]
        assert domains["artifact"]["latest"]["decision"] == "concerns"
        assert domains["artifact"]["latest"]["reason"] == "ringing"
        assert domains["artifact"]["signed_off"] is True

    def test_domain_history_is_append_only_too(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "concerns", reviewer="ben", domain="signal")
        qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain="signal")
        signal = qc.load_decisions(tmp_path)[KEY]["domains"]["signal"]
        assert [e["decision"] for e in signal["history"]] == ["concerns", "reviewed"]

    def test_domains_are_kept_apart(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "concerns", reviewer="ben", domain="signal")
        qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain="temporal")
        domains = qc.load_decisions(tmp_path)[KEY]["domains"]
        assert domains["signal"]["latest"]["decision"] == "concerns"
        assert domains["temporal"]["latest"]["decision"] == "reviewed"

    def test_a_domain_review_still_needs_a_named_reviewer(self, tmp_path):
        with pytest.raises(ValueError, match="identifiable reviewer"):
            qc.save_decision(tmp_path, KEY, "reviewed", domain="signal")

    def test_automation_may_only_record_pending_for_a_domain_too(self, tmp_path):
        with pytest.raises(ValueError, match="only record 'pending'"):
            qc.save_decision(tmp_path, KEY, "reviewed", automated=True, domain="signal")
        qc.save_decision(tmp_path, KEY, "pending", automated=True, domain="signal")
        assert qc.load_decisions(tmp_path)[KEY]["domains"]["signal"]["signed_off"] is False


class TestLegacyRecordsAreUnaffected:
    def test_a_record_with_no_domains_reads_exactly_as_before(self, tmp_path):
        """Every record written before domains existed carries no domain key."""
        path = tmp_path / f"{KEY}_decision.json"
        path.write_text(
            json.dumps(
                {
                    "run_key": KEY,
                    "decisions": [
                        {"decision": "keep", "reviewer": "ben", "reason": "", "automated": False}
                    ],
                }
            )
        )
        record = qc.load_decisions(tmp_path)[KEY]
        assert record["latest"]["decision"] == "keep"
        assert record["signed_off"] is True
        assert record["domains"] == {}

    def test_reading_a_legacy_record_does_not_rewrite_it(self, tmp_path):
        path = tmp_path / f"{KEY}_decision.json"
        payload = json.dumps({"latest": {"decision": "keep", "reviewer": "ben"}, "history": []})
        path.write_text(payload)
        qc.load_decisions(tmp_path)
        assert path.read_text() == payload


class TestDomainProgressIsDisplayOnly:
    """Derived readiness may be shown. It may never be recorded.

    The four domains do not partition the question a verdict answers — none of
    them covers task timing, stimulus delivery, or a participant asleep with
    their eyes open. "Reviewed every domain" and "this run is usable" are
    different claims.
    """

    KEYS = ["signal", "temporal", "alignment", "artifact"]

    def test_it_counts_only_signed_off_domains(self, tmp_path):
        qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain="signal")
        qc.save_decision(tmp_path, KEY, "pending", automated=True, domain="temporal")
        record = qc.load_decisions(tmp_path)[KEY]
        assert qc.domain_progress(record, self.KEYS) == (1, 4)

    def test_a_full_house_still_leaves_the_run_without_a_verdict(self, tmp_path):
        for key in self.KEYS:
            qc.save_decision(tmp_path, KEY, "reviewed", reviewer="ben", domain=key)
        record = qc.load_decisions(tmp_path)[KEY]
        assert qc.domain_progress(record, self.KEYS) == (4, 4)
        assert record["latest"] == {}
        assert record["signed_off"] is False

    def test_it_is_empty_for_a_run_nobody_has_touched(self):
        assert qc.domain_progress({}, self.KEYS) == (0, 4)
        assert qc.domain_progress(None, self.KEYS) == (0, 4)


class TestOutputMovedUnderDuckbrain:
    """Decisions are written to one place and read from everywhere they have been.

    Everything duckbrain authors now lives under ``derivatives/duckbrain/``. The
    old ``derivatives/preprocessing_qc/`` is still read, and never written or
    moved — mmmdata still writes it, and a project reviewed before the move must
    not silently lose its history. Same treatment ``_history_of`` gives the two
    on-disk *schemas*, applied to the two on-disk *locations*.
    """

    def _config(self, tmp_path):
        return {
            "paths": {
                "derivatives_dir": str(tmp_path / "derivatives"),
                "duckbrain_dir": str(tmp_path / "derivatives" / "duckbrain"),
            }
        }

    def test_writes_land_under_duckbrain(self, tmp_path):
        config = self._config(tmp_path)
        target = qc.decisions_dir(config)
        assert target == tmp_path / "derivatives" / "duckbrain" / "qc" / "decisions"

    def test_the_legacy_location_is_still_searched(self, tmp_path):
        config = self._config(tmp_path)
        roots = qc.decision_search_dirs(config)
        assert tmp_path / "derivatives" / "preprocessing_qc" in roots
        assert qc.decisions_dir(config) in roots

    def test_the_current_location_is_searched_last(self, tmp_path):
        """Order carries meaning: the last root's entries are the newest."""
        assert qc.decision_search_dirs(self._config(tmp_path))[-1] == qc.decisions_dir(
            self._config(tmp_path)
        )

    def test_a_decision_written_before_the_move_is_still_read(self, tmp_path):
        config = self._config(tmp_path)
        legacy = tmp_path / "derivatives" / "preprocessing_qc"
        legacy.mkdir(parents=True)
        (legacy / f"{KEY}_decision.json").write_text(
            json.dumps(
                {
                    "run_key": KEY,
                    "decisions": [
                        {"decision": "investigate", "reviewer": "bhutch", "automated": False}
                    ],
                }
            )
        )
        loaded = qc.load_decisions(qc.decision_search_dirs(config))
        assert loaded[KEY]["latest"]["decision"] == "investigate"
        assert loaded[KEY]["signed_off"] is True

    def test_a_new_verdict_supersedes_the_pre_move_one(self, tmp_path):
        """Reviewing again writes to the new place and must become current."""
        config = self._config(tmp_path)
        legacy = tmp_path / "derivatives" / "preprocessing_qc"
        legacy.mkdir(parents=True)
        (legacy / f"{KEY}_decision.json").write_text(
            json.dumps(
                {"run_key": KEY, "decisions": [{"decision": "investigate", "reviewer": "a"}]}
            )
        )
        qc.save_decision(qc.decisions_dir(config), KEY, "keep", reviewer="b")
        loaded = qc.load_decisions(qc.decision_search_dirs(config))
        assert loaded[KEY]["latest"]["decision"] == "keep"
        assert [e["decision"] for e in loaded[KEY]["history"]] == ["investigate", "keep"]

    def test_reading_never_moves_or_rewrites_the_legacy_file(self, tmp_path):
        config = self._config(tmp_path)
        legacy = tmp_path / "derivatives" / "preprocessing_qc"
        legacy.mkdir(parents=True)
        path = legacy / f"{KEY}_decision.json"
        payload = json.dumps({"run_key": KEY, "decisions": [{"decision": "keep", "reviewer": "a"}]})
        path.write_text(payload)
        qc.load_decisions(qc.decision_search_dirs(config))
        assert path.exists() and path.read_text() == payload

    def test_a_domain_review_recorded_after_the_move_joins_the_old_history(self, tmp_path):
        """The two locations are one history, so the verdict rule still holds."""
        config = self._config(tmp_path)
        legacy = tmp_path / "derivatives" / "preprocessing_qc"
        legacy.mkdir(parents=True)
        (legacy / f"{KEY}_decision.json").write_text(
            json.dumps({"run_key": KEY, "decisions": [{"decision": "keep", "reviewer": "a"}]})
        )
        qc.save_decision(qc.decisions_dir(config), KEY, "concerns", reviewer="b", domain="signal")
        loaded = qc.load_decisions(qc.decision_search_dirs(config))
        assert loaded[KEY]["latest"]["decision"] == "keep"
        assert loaded[KEY]["domains"]["signal"]["latest"]["decision"] == "concerns"

    def test_a_single_directory_is_still_accepted(self, tmp_path):
        """The one-root call is the common case and must not need a list."""
        qc.save_decision(tmp_path, KEY, "keep", reviewer="ben")
        assert qc.load_decisions(tmp_path)[KEY]["latest"]["decision"] == "keep"
