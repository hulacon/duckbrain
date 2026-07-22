"""TODO #16 Slice A: a declaration the data can't quietly agree with.

Everything else in duckbrain derives its expectations from the data it judges —
`discover_units` from the union of what exists, `_expected_bold_keys` from the
converted tree, `_expected_conversion_counts` from the config duckbrain emitted.
So a run that was never acquired shrinks the expectation to match and every view
reads complete. `test_surveyor_still_reads_complete_when_a_run_is_missing` is the
keystone here: it asserts that contrast directly, and it is the whole reason the
declaration exists.

The other load-bearing test is `test_no_declaration_means_no_issues`. Opt-out is
a *behaviour*, not an accident of there being nothing to compare — a project that
hasn't declared expectations is not thereby wrong, and if that ever regresses
every existing project starts shouting.
"""

import json

import pytest

from duckbrain.core.checks import CHEAP, EXPENSIVE, REGISTRY, run_checks
from duckbrain.core.expectations import (
    SessionExpectation,
    declared,
    elicit,
    expected_for,
    expected_participants,
    observe,
    unit_key,
)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 16)


def _session(root, sub="001", ses="", *, runs=4, task="div", t1w=1, fmap_dirs=("AP", "PA")):
    """A converted-looking unit: anat, a fieldmap group, and `runs` BOLDs."""
    unit = root / f"sub-{sub}" / (f"ses-{ses}" if ses else "")
    for i in range(t1w):
        _touch(unit / "anat" / f"sub-{sub}_run-{i + 1}_T1w.nii.gz")
    for d in fmap_dirs:
        _touch(unit / "fmap" / f"sub-{sub}_dir-{d}_epi.nii.gz")
        _write(unit / "fmap" / f"sub-{sub}_dir-{d}_epi.json", {"B0FieldIdentifier": "pair1"})
    for i in range(runs):
        _touch(unit / "func" / f"sub-{sub}_task-{task}_run-{i + 1}_bold.nii.gz")
    return unit


def _config(root, expected=None):
    config = {
        "paths": {
            "bids_dir": str(root),
            "sourcedata_dir": str(root / "sourcedata"),
            "derivatives_dir": str(root / "derivatives"),
        },
        "nordic": {"use_nordic": False},
    }
    if expected is not None:
        config["expected"] = expected
    return config


_FULL = {"session": {"anat": {"T1w": 1}, "fmap_pairs": 1, "task": {"div": 4}}}


# ---- observing --------------------------------------------------------------


def test_observe_counts_anat_fmap_pairs_and_runs(tmp_path):
    _session(tmp_path)
    got = observe(tmp_path, "001")
    assert got.anat == {"T1w": 1}
    assert got.fmap_pairs == 1
    assert got.task == {"div": 4}


def test_a_lone_phase_encoding_direction_is_not_a_pair(tmp_path):
    """One direction estimates nothing — it is an unusable field, not half of one.

    This is the same stance `_assign_fmap_group` takes when it refuses to bind a
    BOLD to a half group, and it is what makes the fmap check worth having: an
    aborted PA leaves a directory that *looks* populated.
    """
    _session(tmp_path, fmap_dirs=("AP",))
    assert observe(tmp_path, "001").fmap_pairs == 0


def test_fmap_pairs_group_by_identifier_not_filename(tmp_path):
    """Two pairs sharing filename entities but different fields still count two."""
    unit = tmp_path / "sub-001"
    for group in ("pair1", "pair2"):
        for d in ("AP", "PA"):
            name = f"sub-001_acq-{group}_dir-{d}_epi"
            _touch(unit / "fmap" / f"{name}.nii.gz")
            _write(unit / "fmap" / f"{name}.json", {"B0FieldIdentifier": group})
    assert observe(tmp_path, "001").fmap_pairs == 2


def test_observe_handles_a_session(tmp_path):
    _session(tmp_path, ses="02")
    assert observe(tmp_path, "001", "02").task == {"div": 4}


# ---- the declaration --------------------------------------------------------


def test_no_declaration_means_no_issues(tmp_path):
    """Opt-out is a behaviour and gets a test — see this module's docstring."""
    _session(tmp_path, runs=1)  # deficient by any standard
    assert declared(_config(tmp_path)) is None
    assert run_checks(_config(tmp_path)) == []
    assert run_checks(_config(tmp_path, {})) == []


def test_elicit_then_freeze_round_trips(tmp_path):
    _session(tmp_path)
    draft = elicit(_config(tmp_path), "001")
    assert draft == {"fmap_pairs": 1, "anat": {"T1w": 1}, "task": {"div": 4}}
    assert SessionExpectation.from_config_section(draft) == SessionExpectation(
        anat={"T1w": 1}, fmap_pairs=1, task={"div": 4}
    )


def test_elicit_never_proposes_a_roster(tmp_path):
    """The roster is the one thing disk can't know — deriving it would re-close
    exactly the loop this module opens."""
    _session(tmp_path)
    assert "participants" not in elicit(_config(tmp_path), "001")


def test_participants_accepts_a_count_or_a_list(tmp_path):
    assert expected_participants(_config(tmp_path, {"participants": 37})) == ([], 37)
    labels, count = expected_participants(_config(tmp_path, {"participants": ["sub-002", "001"]}))
    assert (labels, count) == (["001", "002"], 2)


@pytest.mark.parametrize("junk", [{"session": "nonsense"}, {"session": {"task": {"div": "four"}}}])
def test_a_malformed_declaration_narrows_rather_than_raises(tmp_path, junk):
    """A hand-edited config must not take the cockpit down with it."""
    _session(tmp_path)
    assert expected_for(_config(tmp_path, junk), "001") is None
    assert run_checks(_config(tmp_path, junk)) == []


# ---- exceptions -------------------------------------------------------------


def test_an_exception_overrides_key_by_key_not_wholesale(tmp_path):
    config = _config(
        tmp_path,
        {**_FULL, "exceptions": {"013": {"task": {"div": 3}, "reason": "aborted"}}},
    )
    want = expected_for(config, "013")
    assert want.task == {"div": 3}
    assert want.anat == {"T1w": 1}  # not dropped by an exception that never mentioned it
    assert want.fmap_pairs == 1
    assert want.reason == "aborted"
    assert expected_for(config, "001").task == {"div": 4}  # everyone else unaffected


def test_a_unit_scoped_exception_beats_a_subject_scoped_one(tmp_path):
    config = _config(
        tmp_path,
        {**_FULL, "exceptions": {"013": {"task": {"div": 3}}, "013/02": {"task": {"div": 2}}}},
    )
    assert expected_for(config, "013", "02").task == {"div": 2}
    assert expected_for(config, "013", "01").task == {"div": 3}
    assert unit_key("013", "02") == "013/02"


def test_zero_is_a_declaration_not_an_absence(tmp_path):
    """ "This subject has no resting run" is the commonest real deviation there is.

    Found live against `divatten_beta`: with zero parsed as "unstated" the
    exception fell through to the study default and could never turn anything
    off, so the one deviation people actually need to record was unrecordable.
    """
    _session(tmp_path, sub="017", runs=4)
    (tmp_path / "sub-017" / "func" / "sub-017_task-resting_run-1_bold.nii.gz").parent.mkdir(
        parents=True, exist_ok=True
    )
    declaration = {"session": {"task": {"div": 4, "resting": 1}}}
    assert [i.check for i in run_checks(_config(tmp_path, declaration))] == ["expected-task"]

    accepted = {**declaration, "exceptions": {"017": {"task": {"resting": 0}, "reason": "n/a"}}}
    assert expected_for(_config(tmp_path, accepted), "017").task == {"div": 4, "resting": 0}
    assert run_checks(_config(tmp_path, accepted)) == []


def test_a_declared_zero_fmap_pair_count_also_silences(tmp_path):
    _session(tmp_path, sub="017", fmap_dirs=())
    noisy = {"session": {"fmap_pairs": 1}}
    assert [i.check for i in run_checks(_config(tmp_path, noisy))] == ["expected-fmap"]
    accepted = {**noisy, "exceptions": {"017": {"fmap_pairs": 0, "reason": "none acquired"}}}
    assert run_checks(_config(tmp_path, accepted)) == []


def test_an_accepted_deviation_silences_the_check(tmp_path):
    _session(tmp_path, sub="013", runs=3)
    noisy = _config(tmp_path, _FULL)
    assert [i.check for i in run_checks(noisy)] == ["expected-task"]
    accepted = _config(
        tmp_path,
        {**_FULL, "exceptions": {"013": {"task": {"div": 3}, "reason": "scanner aborted"}}},
    )
    assert run_checks(accepted) == []


# ---- the checks -------------------------------------------------------------


def test_a_missing_run_is_reported(tmp_path):
    _session(tmp_path, runs=3)
    issues = run_checks(_config(tmp_path, _FULL))
    assert [i.check for i in issues] == ["expected-task"]
    assert issues[0].severity == "warning"
    assert "expected 4, found 3" in issues[0].message
    assert issues[0].subject == "001"


def test_surveyor_still_reads_complete_when_a_run_is_missing(tmp_path):
    """The keystone: the declaration sees what the catalogue structurally can't.

    `_expected_bold_keys` gets its expectation from the converted tree, so three
    runs where four were acquired is three-of-three — complete. Nothing in the
    surveyor can notice, and that is not a surveyor bug: it has no independent
    statement of what should exist. This asserts both halves at once, so the
    contrast can't silently stop being true.
    """
    from duckbrain.core.surveyor import Status, survey_project

    _session(tmp_path, runs=3)
    (tmp_path / "sourcedata" / "sub-001" / "dicom").mkdir(parents=True)
    (tmp_path / "sourcedata" / "sub-001" / "dicom" / "a.dcm").write_bytes(b"x")

    matrix = survey_project(_config(tmp_path, _FULL))
    assert matrix.loc[0, "converted"] == Status.COMPLETE.value  # catalogue: all green
    assert [i.check for i in run_checks(_config(tmp_path, _FULL))] == ["expected-task"]


def test_a_task_absent_entirely_is_an_error_not_a_warning(tmp_path):
    _session(tmp_path, runs=0)
    (issue,) = run_checks(_config(tmp_path, _FULL))
    assert (issue.check, issue.severity) == ("expected-task", "error")


def test_a_missing_fieldmap_pair_is_reported(tmp_path):
    _session(tmp_path, fmap_dirs=("AP",))
    (issue,) = run_checks(_config(tmp_path, _FULL))
    assert issue.check == "expected-fmap"
    assert "distortion correction `None`" in issue.message


def test_a_missing_t1w_is_reported(tmp_path):
    _session(tmp_path, t1w=0)
    (issue,) = run_checks(_config(tmp_path, _FULL))
    assert (issue.check, issue.severity) == ("expected-anat", "error")


def test_more_than_declared_is_never_flagged(tmp_path):
    """Same asymmetry `surveyor._grade` takes: a re-scan or an extra T1w is a
    normal thing for real data to hold, and a check that fires on every
    legitimate difference gets switched off."""
    _session(tmp_path, runs=6, t1w=2)
    assert run_checks(_config(tmp_path, _FULL)) == []


def test_an_unconverted_subject_is_pending_not_deficient(tmp_path):
    """Ingested but not yet converted must stay silent, or the panel is useless
    on day one of a study."""
    (tmp_path / "sourcedata" / "sub-002" / "dicom").mkdir(parents=True)
    _session(tmp_path, sub="001")
    assert run_checks(_config(tmp_path, _FULL)) == []


def test_a_declared_participant_with_no_data_at_all_is_reported(tmp_path):
    """The only check that can see a subject scanned but never ingested — every
    other view of the project is built from the union of what is on disk."""
    _session(tmp_path, sub="001")
    config = _config(tmp_path, {**_FULL, "participants": ["001", "002"]})
    roster = [i for i in run_checks(config) if i.check == "expected-roster"]
    assert len(roster) == 1
    assert roster[0].severity == "error"
    assert "sub-002" in roster[0].message


def test_a_subject_outside_the_roster_is_a_note_not_a_warning(tmp_path):
    _session(tmp_path, sub="001")
    _session(tmp_path, sub="001sess02")  # what a mis-parsed folder looks like
    config = _config(tmp_path, {**_FULL, "participants": ["001"]})
    (extra,) = [i for i in run_checks(config) if i.check == "expected-roster"]
    assert extra.severity == "note"
    assert "sub-001sess02" in extra.message


def test_a_participant_count_short_of_the_roster_is_reported(tmp_path):
    _session(tmp_path, sub="001")
    config = _config(tmp_path, {**_FULL, "participants": 3})
    (roster,) = [i for i in run_checks(config) if i.check == "expected-roster"]
    assert "1 of 3" in roster.message


# ---- the registry -----------------------------------------------------------


def test_no_expensive_check_is_registered_yet(tmp_path):
    """Slice A ships cheap checks only. The `cost` field exists so adding an
    expensive one doesn't mean reshaping the registry — but until there is a
    cached, fingerprinted result to render, nothing expensive may join the
    cockpit's per-render path."""
    assert {c.cost for c in REGISTRY} == {CHEAP}
    assert EXPENSIVE not in {c.cost for c in REGISTRY}


def test_one_broken_check_cannot_sink_the_panel(tmp_path, monkeypatch):
    import duckbrain.core.checks as checks

    def boom(_config):
        raise RuntimeError("nope")

    monkeypatch.setattr(checks, "REGISTRY", (checks.Check("boom", CHEAP, boom), *checks.REGISTRY))
    _session(tmp_path, runs=3)
    assert [i.check for i in run_checks(_config(tmp_path, _FULL))] == ["expected-task"]
