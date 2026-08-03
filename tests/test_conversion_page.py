"""Conversion page: the plan surfaces the outcome, and the JSON override is explicit.

Covers TODO #13. Two things worth a regression test rather than an eyeball:
the page must show the *predicted BIDS filenames* alongside the inputs, and the
raw-JSON editor must not silently take over from the tables (it used to, because
the text area kept its own widget state).
"""

import json
import os

import pytest
from streamlit.testing.v1 import AppTest

from duckbrain.config import save_project_config, scaffold_project

PAGE = "src/duckbrain/gui/pages/3_BIDS_Conversion.py"

# One anat, a complete AP/PA pair, and a bold the classifier reads as func on its
# own — the minimum that exercises naming, the fieldmap relation, and a drop.
SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_ap"),
    ("04", "se_epi_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
]


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(
        str(proj),
        {"project": {"name": "test", "use_sessions": "auto"}},
    )
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def _tables(at):
    return [df.value for df in at.dataframe]


def _plan_table(at):
    """The Conversion Plan table — the only one carrying a 'becomes' column."""
    for table in _tables(at):
        if "becomes" in getattr(table, "columns", []):
            return table
    raise AssertionError("no plan table rendered")


def test_page_shows_predicted_bids_filenames(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    plan = _plan_table(at)
    becomes = dict(zip(plan["Series #"], plan["becomes"]))

    assert becomes[2] == "sub-001_ses-01_T1w.nii.gz"
    assert becomes[9] == "sub-001_ses-01_task-perFace_run-1_bold.nii.gz"
    # The scout is claimed by no description, and says so rather than vanishing.
    assert becomes[1] == "— not converted"


def test_plan_shows_which_pair_corrects_the_run(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    plan = _plan_table(at)
    fmap = dict(zip(plan["Series #"], plan["fieldmap"]))

    # One unnamed pair: the bold and both fieldmaps carry the same token.
    assert fmap[9] == fmap[3] == fmap[4]
    assert fmap[9].startswith("🔵")
    # Colour is never the only channel — the label rides along with it.
    assert "unnamed" in fmap[9]
    # Anat has no fieldmap relation at all, so no token.
    assert fmap[2] == ""


def test_clean_session_reports_no_blocking_problem(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not at.error
    assert any("will be written" in s.value for s in at.success)


def test_json_override_is_off_by_default_and_must_be_opted_into(project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    override = next(c for c in at.checkbox if c.key == "dcm2bids_json_override")
    assert override.value is False
    # Off: no editable text area, so the tables cannot be silently overridden.
    assert not [t for t in at.text_area if t.key == "dcm2bids_config_editor"]

    override.set_value(True).run()
    assert not at.exception
    assert [t for t in at.text_area if t.key == "dcm2bids_config_editor"]
    # And the takeover is stated rather than left to be discovered.
    assert any("no longer drive" in w.value for w in at.warning)


# ---- the unified table (TODO #13 phase 6) ----

TWO_PAIR_SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_ap"),
    ("04", "se_epi_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
    ("19", "cmrr_mbep2d_bold_task-perFace_run-2"),
    ("30", "se_epi_ap"),
    ("32", "se_epi_pa"),
]
EDITOR_KEY = "conversion_editor_001_01"


@pytest.fixture
def two_pair_project(tmp_path):
    """A pair re-shot mid-task: run 1 before it, run 2 after."""
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in TWO_PAIR_SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "auto"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_one_table_carries_every_decision_and_the_outcome(two_pair_project):
    """The three per-series tables are now one; these are its columns."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert not at.exception
    assert list(_plan_table(at).columns) == [
        "Series #",
        "Description",
        "Type",
        "Type from",
        "# Files",
        "convert",
        "task",
        "run",
        "fieldmap",
        "becomes",
    ]


def test_the_table_says_whether_a_type_was_read_or_guessed(project):
    """`classified_by` reaches the user, not just the dataclass.

    It was set and unit-tested from the day header classification landed, and its
    own comment said the Conversion page showed it — but no GUI code read it, so
    a datatype inferred from a study-specific string looked exactly like one the
    headers stated. This fixture's DICOMs are empty files, so the reader gets
    nothing and every row is the guess.
    """
    plan = _plan_table(at := AppTest.from_file(PAGE, default_timeout=60).run())
    assert not at.exception
    assert set(plan["Type from"]) == {"name"}


def test_fieldmap_rows_carry_their_own_pair_token(two_pair_project):
    """The relation reads off a single row in both directions, not across tables."""
    plan = _plan_table(at := AppTest.from_file(PAGE, default_timeout=90).run())
    assert not at.exception
    fmap = dict(zip(plan["Series #"], plan["fieldmap"]))

    # The two pairs get distinct, stable tokens...
    assert fmap[3] == fmap[4]
    assert fmap[30] == fmap[32]
    assert fmap[3] != fmap[30]
    # ...and by default both runs take the first complete pair.
    assert fmap[9] == fmap[19] == fmap[3]


def test_two_runs_of_one_task_can_take_different_pairs(two_pair_project):
    """The case the granularity decision was made for, end to end through the GUI."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    second_pair = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[30]

    # Row 5 is series 19 — run 2, acquired after the re-shoot.
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"fieldmap": second_pair}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert not at.error

    fmap = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))
    assert fmap[19] == second_pair
    assert fmap[9] != second_pair  # run 1 keeps the original pair


def test_editing_a_task_updates_becomes_in_the_same_rerun(two_pair_project):
    """`becomes` is computed from this run's edits, not a rerun behind them."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"task": "renamed"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[9] == "sub-001_ses-01_task-renamed_run-1_bold.nii.gz"


def test_a_task_run_collision_is_reported_as_an_error(two_pair_project):
    """Two runs given the same number would silently lose one file."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"run": 1}},  # series 19 -> run 1, colliding with series 9
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert any("same file" in e.value for e in at.error)


# ---- TODO #17.5 / #17.6: the page must describe the config that will ship -----


def _override_with(at, config_dict):
    """Turn the hand-edit override on and put *config_dict* in the text area."""
    import json

    at.session_state["dcm2bids_json_override"] = True
    at.session_state["dcm2bids_config_editor"] = json.dumps(config_dict)
    return at.run()


def test_override_reconciles_the_table_instead_of_leaving_it_stale(project):
    """With the JSON driving, the decision columns must show what the JSON says.

    They used to keep showing table state and stayed editable, so `task`, `run`
    and `fieldmap` were three controls that silently did nothing while a
    different config shipped.
    """
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    baseline = _plan_table(at)
    assert "perFace" in list(baseline["task"])

    at = _override_with(
        at,
        {
            "descriptions": [
                {
                    "id": "func-bold-renamed",
                    "datatype": "func",
                    "suffix": "bold",
                    "criteria": {"SeriesNumber": 9},
                    "custom_entities": "task-renamed_run-1",
                    "sidecar_changes": {"TaskName": "renamed"},
                }
            ]
        },
    )
    assert not at.exception

    table = _plan_table(at)
    assert "renamed" in list(table["task"]), (
        "the table still shows its own task while the JSON ships a different one"
    )
    # And `becomes` agrees with it — both now read from the same config.
    assert any("task-renamed" in str(b) for b in table["becomes"])


def test_override_state_is_announced_above_the_table(project):
    """The only notice used to live inside a collapsed expander at the bottom."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at = _override_with(at, {"descriptions": []})
    assert not at.exception
    blurb = " ".join(i.value for i in at.info) + " ".join(m.value for m in at.markdown)
    assert "hand-edited JSON" in blurb


def test_a_saved_config_is_surfaced_because_bulk_convert_uses_it(project):
    """`_build_dcm2bids` reuses a saved dcm2bids_config.json and only generates
    one when absent, so a saved review is what actually runs. The page wrote that
    file and never read it, so a reviewed session reopened looking unreviewed."""
    import json

    saved = project / "sourcedata" / "sub-001" / "ses-01" / "dcm2bids_config.json"
    saved.write_text(json.dumps({"descriptions": []}))

    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert any("reviewed config" in i.value for i in at.info), (
        "a saved config on disk — the one bulk convert will use — is not mentioned"
    )


# ---- DB-005: per-session submit is the same operation as bulk submit ---------


def _button(at, label):
    for b in at.button:
        if b.label == label:
            return b
    raise AssertionError(f"no button {label!r}; have {[b.label for b in at.button]}")


def test_per_session_submit_records_provenance_like_the_bulk_path(project, monkeypatch):
    """The most-used conversion path wrote no submission record at all.

    This page rendered and submitted its own sbatch, skipping `advance_one` and
    so `record_submission` — so the run had no provenance row, and the cockpit
    had no job id to hang a log viewer or a cancel button off. Its cells said
    "No job id recorded for this unit/stage" for every conversion launched here.
    """
    import duckbrain.slurm.submit as S

    monkeypatch.setattr(S, "submit_job", lambda *a, **kw: "424242")
    import duckbrain.core.pipeline as P

    monkeypatch.setattr(P, "submit_job", lambda *a, **kw: "424242")

    at = AppTest.from_file(PAGE, default_timeout=90).run()
    _button(at, "Submit Conversion Job").click().run()
    assert not at.exception

    log = project / "code" / "logs" / "submissions.tsv"
    assert log.exists(), "no durable submission record was written"
    rows = log.read_text().strip().splitlines()
    assert len(rows) >= 2  # header + the run
    assert "424242" in rows[-1]
    assert "dcm2bids" in rows[-1]


def test_export_only_submits_nothing_and_records_nothing(project, monkeypatch):
    """Export is a dry run; it must not look like a launch in the record."""
    import duckbrain.core.pipeline as P

    def _boom(*a, **kw):
        raise AssertionError("export must not submit")

    monkeypatch.setattr(P, "submit_job", _boom)

    at = AppTest.from_file(PAGE, default_timeout=90).run()
    _button(at, "Export SBATCH Script").click().run()
    assert not at.exception

    assert not (project / "code" / "logs" / "submissions.tsv").exists()
    assert list((project / "code" / "logs").glob("dcm2bids_*.sbatch"))


# ---- Stale saved config -----------------------------------------------------
#
# `_build_converted` reuses <sourcedata>/sub-XX/[ses-YY]/dcm2bids_config.json and
# only generates when it is absent. Right when the file records a review, wrong
# when the generator has moved on — and the file records no provenance, so
# nothing distinguished the two. Silence meant the saved plan won: the B0
# identifier fix could not reach any already-reviewed session, because the stale
# plan kept re-supplying the identifier the fix corrected, and the reconvert
# reported success.


def _saved_config_path(project):
    return project / "sourcedata" / "sub-001" / "ses-01" / "dcm2bids_config.json"


def _write_saved_config(project, mutate):
    """Persist the config the page would generate, with *mutate* applied."""
    import json

    from duckbrain.core.conversion import generate_session_config

    cfg = generate_session_config(
        project / "sourcedata" / "sub-001" / "ses-01" / "dicom", "001", "01"
    )
    mutate(cfg)
    path = _saved_config_path(project)
    path.write_text(json.dumps(cfg, indent=2))
    return cfg


def _warnings(at):
    return "\n".join(w.value for w in at.warning)


def test_saved_config_matching_the_generator_raises_no_drift_warning(project):
    """Opt-out by silence: an up-to-date saved config must stay quiet.

    A warning on every reviewed session is one people learn to scroll past.
    """
    _write_saved_config(project, lambda cfg: None)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert "no longer matches" not in _warnings(at)


def test_stale_sidecar_value_in_a_saved_config_is_surfaced(project):
    """The exact shape that hid the B0 fix: same descriptions, changed value."""

    def _staleify(cfg):
        for desc in cfg["descriptions"]:
            for key in ("B0FieldIdentifier", "B0FieldSource"):
                if key in (desc.get("sidecar_changes") or {}):
                    desc["sidecar_changes"][key] = "B0map_2.5mm"

    _write_saved_config(project, _staleify)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception

    warned = _warnings(at)
    assert "no longer matches" in warned
    assert "sidecar_changes.B0FieldIdentifier" in warned
    # It must say which plan actually runs; that is the actionable part.
    assert "the saved plan is what runs" in warned.lower()


def test_saved_config_missing_a_description_is_surfaced(project):
    _write_saved_config(project, lambda cfg: cfg["descriptions"].pop())
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert "newly generated, absent from the saved config" in _warnings(at)


def test_unparseable_saved_config_reports_instead_of_crashing(project):
    _saved_config_path(project).parent.mkdir(parents=True, exist_ok=True)
    _saved_config_path(project).write_text("{not json")
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception, "a corrupt saved config must not take the page down"
    assert "Couldn't compare the saved config" in _warnings(at)


# ---- duplicate reconstructions ----


@pytest.fixture
def nd_project(tmp_path):
    """A session that saved its mprage twice, corrected and _ND."""
    proj = tmp_path / "ndproj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    # The plain mprage is dropped: with it there are three T1w and the run-
    # disambiguation muddies exactly what this fixture is here to show.
    others = [(num, desc) for num, desc in SERIES if desc != "t1w_mprage"]
    twins = [("1009", "mprage_p2_ND_defaced"), ("1010", "mprage_p2_defaced")]
    for num, desc in others + twins:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(str(proj), {"project": {"name": "nd", "use_sessions": "auto"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_the_nd_choice_appears_only_where_there_is_something_to_choose(project, nd_project):
    """An abstract control about data that isn't there is worse than none."""
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(project)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert not [r for r in at.radio if r.key == "nd_duplicates_choice"]

    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(nd_project)
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert [r for r in at.radio if r.key == "nd_duplicates_choice"]


def test_the_nd_choice_is_seeded_from_the_project_config(nd_project):
    save_project_config(
        str(nd_project),
        {"conversion": {"nd_duplicates": "uncorrected"}},
        owned={"conversion": ("nd_duplicates",)},
    )
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert at.radio(key="nd_duplicates_choice").value == "uncorrected"

    plan = _plan_table(at)
    becomes = dict(zip(plan["Series #"], plan["becomes"]))
    assert becomes[1009] == "sub-001_ses-01_T1w.nii.gz"
    assert becomes[1010] == "— not converted"


def test_choosing_both_shows_two_anatomicals_in_becomes(nd_project):
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    at.radio(key="nd_duplicates_choice").set_value("both").run()
    assert not at.exception

    plan = _plan_table(at)
    becomes = dict(zip(plan["Series #"], plan["becomes"]))
    assert becomes[1009] == "sub-001_ses-01_acq-nd_T1w.nii.gz"
    assert becomes[1010] == "sub-001_ses-01_acq-dis_T1w.nii.gz"


# ---- the `convert` column: leaving a series out on purpose -------------------
# Row indices below are positions in TWO_PAIR_SERIES, which is what
# st.data_editor's edited_rows is keyed on.


def test_unticking_convert_leaves_the_series_out(two_pair_project):
    """The whole feature, end to end: `becomes` says so and no file is planned."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))[19].endswith(
        "run-2_bold.nii.gz"
    )

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"convert": False}},  # series 19, run 2
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert not at.error

    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[19] == "— not converted"
    # The rest of the session is untouched — a skip is not a bulk opt-out.
    assert becomes[9].endswith("run-1_bold.nii.gz")
    assert becomes[2] == "sub-001_ses-01_T1w.nii.gz"


def test_a_skipped_series_is_a_note_not_a_warning(two_pair_project):
    """It must not read as the 'nothing claimed this' warning, which means a bug."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"convert": False}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    assert not [w for w in at.warning if "matches no description" in w.value]
    assert any("you unticked" in c.value for c in at.caption)


def test_series_duckbrain_cannot_convert_start_unticked(two_pair_project):
    """So the box agrees with `becomes` instead of promising a file for a scout."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    plan = _plan_table(at)
    convert = dict(zip(plan["Series #"], plan["convert"]))

    assert convert[1] is False or not convert[1]  # the scout
    assert convert[2] and convert[9] and convert[3]


def test_skipping_one_fieldmap_half_takes_the_pair_and_says_so(two_pair_project):
    """The partner goes too — half a pair can estimate nothing — and it is stated."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {2: {"convert": False}},  # series 03, the AP half of pair 1
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[3] == becomes[4] == "— not converted"
    assert any("whole pair" in w.value for w in at.warning)


def test_unticking_a_fieldmap_half_does_not_hide_the_table(two_pair_project):
    """The regression that matters: the undo lives *in* the table.

    This shipped once as st.error + st.stop(), which fires above the table — so
    unticking a fieldmap half made the whole table vanish, taking the checkbox
    needed to put it back. A control whose misuse hides the control leaves the
    user with no way back and nothing to look at.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    before = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {2: {"convert": False}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    # Every row still there, and the unticked one is still visible and re-tickable.
    plan = _plan_table(at)
    assert list(plan["Series #"]) == [1, 2, 3, 4, 9, 19, 30, 32]
    assert not dict(zip(plan["Series #"], plan["convert"]))[3]

    # And re-ticking restores exactly the original plan. Stated as a re-tick,
    # which is what the browser sends: an *empty* delta used to pass this
    # assertion by losing the edit, which was the revert bug, not an undo.
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {2: {"convert": True}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"])) == before


def test_runs_bound_to_a_skipped_pair_are_still_written_uncorrected(two_pair_project):
    """Losing the fieldmap must not lose the run — that would be data, not correction.

    And *uncorrected* is half the claim, so it is checked rather than assumed.
    It used to be neither: dropping the orphaned rule let the run fall through to
    automatic assignment, which bound it to the session's other complete pair —
    a pair the user never picked — while the warning said it was uncorrected.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {2: {"convert": False}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception

    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[9].endswith("run-1_bold.nii.gz")
    assert becomes[19].endswith("run-2_bold.nii.gz")

    next(b for b in at.button if b.label == "Save Config JSON").click().run()
    saved = json.loads(
        (two_pair_project / "sourcedata/sub-001/ses-01/dcm2bids_config.json").read_text()
    )
    for num in (9, 19):
        entry = next(d for d in saved["descriptions"] if d["criteria"]["SeriesNumber"] == num)
        assert "B0FieldSource" not in (entry.get("sidecar_changes") or {}), (
            f"series {num} was silently corrected by a pair the user did not pick"
        )


def test_a_skip_survives_the_saved_config_round_trip(two_pair_project):
    """Reload must not silently re-tick a box while the saved JSON still omits it.

    The saved config *is* what a later convert runs (`_build_converted` reuses
    it), so a table that re-ticked itself would promise a file the conversion
    would not write — the drift this page exists to prevent.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    _skip_19 = {
        "edited_rows": {5: {"convert": False}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.session_state[EDITOR_KEY] = _skip_19
    at.run()
    # Stated once, exactly as a browser states it once. This used to need the
    # edit re-injected before the Save run, which was the bug wearing a
    # workaround: see test_save_writes_the_reviewed_plan_not_the_seed.
    next(b for b in at.button if b.label == "Save Config JSON").click().run()
    assert not at.exception

    saved_path = two_pair_project / "sourcedata/sub-001/ses-01/dcm2bids_config.json"
    saved = json.loads(saved_path.read_text())
    assert 19 not in {d["criteria"]["SeriesNumber"] for d in saved["descriptions"]}

    fresh = AppTest.from_file(PAGE, default_timeout=90).run()
    fresh.session_state["_pending_json_import"] = saved_path.read_text()
    fresh.run()
    assert not fresh.exception

    plan = _plan_table(fresh)
    assert not dict(zip(plan["Series #"], plan["convert"]))[19]
    assert dict(zip(plan["Series #"], plan["becomes"]))[19] == "— not converted"


# ---- an edit is a decision, not a delta ------------------------------------
# st.data_editor's state does not belong to its `key`: streamlit hashes the
# dataframe into the element id, so handing back a frame with the edit baked in
# (what keeps `becomes` current) remounts the table as a different widget whose
# delta starts empty. The page therefore has its own store; these pin it. A beta
# tester reported the visible half — "it soon changes back".


def test_a_row_edit_survives_a_later_rerun(two_pair_project):
    """The reported bug: a fieldmap toggle undid itself on the next rerun.

    The revert did not need the user to do anything recognisable — any rerun at
    all did it: another cell, a button, or a websocket reconnect through the
    OnDemand proxy. So the second `run()` here injects nothing, which is exactly
    what a browser sends once the remounted table has no delta of its own.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    fmap = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))
    other = fmap[30]  # the second pair — series 9 seeds to the first
    assert other != fmap[9]

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": other}},  # row 4 = series 9
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9] == other

    at.run()
    assert not at.exception
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9] == other


def test_save_writes_the_reviewed_plan_not_the_seed(two_pair_project):
    """The silent half, and the one that cost data.

    The table said `— not converted` for series 19 while the config written on
    the very next click still contained it — and that file is what a later bulk
    convert runs. A review that does not reach the artifact is worse than no
    review, because it reports success.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {5: {"convert": False}},  # series 19, run 2
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))[19] == (
        "— not converted"
    )

    # She clicks Save. The browser has no edit left to re-send, and must not need one.
    next(b for b in at.button if b.label == "Save Config JSON").click().run()
    assert not at.exception

    saved = json.loads(
        (two_pair_project / "sourcedata/sub-001/ses-01/dcm2bids_config.json").read_text()
    )
    assert 19 not in {d["criteria"]["SeriesNumber"] for d in saved["descriptions"]}


def test_discarding_row_edits_puts_the_heuristic_back(two_pair_project):
    """Sticky edits need a way out that no edit can hide.

    Before, an edit that tripped a hard stop cleared itself on the next rerun.
    Now it doesn't, so the discard control renders above every `st.stop()` in
    the table region — including the half-pair error, which removes the table
    the user would otherwise fix the row in.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    seeded = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9]

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": "🟢 2"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9] == "🟢 2"

    # The browser ships the full widget state with every rerun, and the table
    # keeps its delta whenever its data didn't change — so the discard has to
    # survive the very edit it is discarding arriving alongside the click.
    next(b for b in at.button if b.key == "reset_row_edits").click()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": "🟢 2"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9] == seeded
    # And it takes itself off screen once there is nothing left to discard.
    assert not [b for b in at.button if b.key == "reset_row_edits"]


# A lone AP: pair 1 is complete, pair 2 holds one direction and can correct
# nothing. The dropdown still offers it, so a user can still pick it.
HALF_PAIR_SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_ap"),
    ("04", "se_epi_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
    ("30", "se_epi_ap"),
]


@pytest.fixture
def half_pair_project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in HALF_PAIR_SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "auto"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_binding_a_bold_to_a_half_pair_does_not_hide_the_table(half_pair_project):
    """The undo lives in the table, so the table has to still be there.

    This was st.error + st.stop(), which fires above the table and took away the
    very cell that made the binding — the same trap the skipped-half case learned
    a commit after it shipped. It used to resolve itself, because the row edit
    evaporated on the next rerun; once edits became durable, that accident was
    gone and the stop would have been a locked door.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[30] == "🟢 2"

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": "🟢 2"}},  # series 9, bound to the half pair
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert not at.error
    assert any("holds only one" in w.value for w in at.warning)

    # The table is still up, still shows what she picked, and every row survives.
    plan = _plan_table(at)
    assert list(plan["Series #"]) == [1, 2, 3, 4, 9, 30]
    assert dict(zip(plan["Series #"], plan["fieldmap"]))[9] == "🟢 2"
    # Two ways back, and both are on screen: change the cell, or discard.
    assert [b for b in at.button if b.key == "reset_row_edits"]


def test_a_bold_on_a_half_pair_is_written_uncorrected_not_re_bound(half_pair_project):
    """The warning says uncorrected, so the config must be uncorrected.

    Dropping the unsatisfiable rule would have fallen through to automatic
    assignment and bound the run to pair 1 — complete, plausible, and not what
    she picked. Silently substituting a fieldmap is the one outcome an explicit
    binding exists to prevent.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": "🟢 2"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    next(b for b in at.button if b.label == "Save Config JSON").click().run()
    assert not at.exception

    saved = json.loads(
        (half_pair_project / "sourcedata/sub-001/ses-01/dcm2bids_config.json").read_text()
    )
    bold = next(d for d in saved["descriptions"] if d["criteria"]["SeriesNumber"] == 9)
    assert "B0FieldSource" not in (bold.get("sidecar_changes") or {})
    # And the run itself is still written — losing the correction is not losing the data.
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))[9].endswith(
        "_bold.nii.gz"
    )


def test_discarding_recovers_from_a_binding_that_warns(half_pair_project):
    """The escape hatch still works where the page is complaining loudest."""
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"fieldmap": "🟢 2"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    next(b for b in at.button if b.key == "reset_row_edits").click().run()
    assert not at.exception
    assert not [w for w in at.warning if "holds only one" in w.value]
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["fieldmap"]))[9] == "🔵 1"


# Two pairs whose names differ only by a period, which `_b0_identifier` has to
# strip: nipype rejects a node name containing one, so both groups reduce to
# `B0map_25mm_…` and fMRIPrep would estimate one field from four images.
COLLIDING_SERIES = [
    ("01", "AAhead_scout"),
    ("02", "t1w_mprage"),
    ("03", "se_epi_2.5mm_ap"),
    ("04", "se_epi_2.5mm_pa"),
    ("05", "se_epi_25mm_ap"),
    ("06", "se_epi_25mm_pa"),
    ("09", "cmrr_mbep2d_bold_task-perFace_run-1"),
]


@pytest.fixture
def colliding_fmap_project(tmp_path):
    proj = tmp_path / "proj"
    scaffold_project(str(proj))
    dicom = proj / "sourcedata" / "sub-001" / "ses-01" / "dicom"
    for num, desc in COLLIDING_SERIES:
        d = dicom / f"Series_{num}_{desc}"
        d.mkdir(parents=True)
        (d / "0001.dcm").touch()
    save_project_config(str(proj), {"project": {"name": "test", "use_sessions": "auto"}})
    os.environ["DUCKBRAIN_PROJECT_DIR"] = str(proj)
    yield proj
    os.environ.pop("DUCKBRAIN_PROJECT_DIR", None)


def test_colliding_b0_identifiers_stop_the_page(colliding_fmap_project):
    """The one thing that still reaches the page's st.stop(), pinned as such.

    Its two neighbours warn instead of stopping, because the binding they catch
    is undone in the table and a stop fires above it. This is the opposite case
    and it is why the stop stays: the collision comes off the series descriptions
    alone, so no cell repairs it (the fix is renaming a sequence on the console),
    and `generate_config` has already raised, so there is no config to render the
    plan from. Nothing else survives the two repair passes to get here — if this
    test ever becomes the only caller of that branch, the branch is still live.
    """
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert not at.exception
    assert any("B0map_25mm" in e.value for e in at.error)
    # Stopped above the table, which is the point: there is no plan to show.
    assert not [t for t in _tables(at) if "becomes" in getattr(t, "columns", [])]


# ---- TODO #13.1: the Type column is editable, and honest about it -------------


def test_type_shows_the_suffix_where_the_datatype_alone_underdetermines_it(project):
    """An anat names its file; everything else is determined by the datatype.

    Not cosmetic — it is what makes the dropdown's values legal declarations.
    """
    plan = _plan_table(at := AppTest.from_file(PAGE, default_timeout=60).run())
    assert not at.exception
    types = dict(zip(plan["Series #"], plan["Type"]))
    assert types[2] == "anat/T1w"
    assert types[9] == "func"
    assert types[1] == "scout"


def _plan_columns(at):
    """The plan editor's column config, where `disabled` and the options live."""
    for el in at.dataframe:
        if "becomes" in str(getattr(el.proto, "columns", "")):
            return json.loads(el.proto.columns)
    raise AssertionError("no plan table rendered")


def test_type_is_editable_and_offers_only_what_can_be_written(project):
    columns = _plan_columns(AppTest.from_file(PAGE, default_timeout=60).run())
    assert not columns["Type"].get("disabled")

    options = columns["Type"]["type_config"]["options"]
    assert "anat/T1w" in options and "func" in options and "sbref" in options
    # `dwi` joined them with `#19.1`, which gave diffusion an emission path — a
    # declaration is offered exactly when duckbrain can honour it.
    assert "dwi" in options
    # `fmap` and `scout` appear only because this session holds rows classified
    # that way and a Selectbox cell cannot render a value outside its options —
    # picking either is refused, by the test below.
    assert "anat" not in options


def test_the_hand_edited_json_locks_type_like_every_other_decision_column(project):
    """With the JSON driving, a Type edit would be a fourth control that silently
    did nothing — the exact shape TODO #17.5 closed for task/run/fieldmap."""
    at = _override_with(AppTest.from_file(PAGE, default_timeout=60).run(), {"descriptions": []})
    assert not at.exception
    assert _plan_columns(at)["Type"]["disabled"] is True


def test_relabelling_a_series_converts_it_in_the_same_rerun(project):
    """The half-applied version of this edit is the bug TODO #13.1 warned about:
    the column would follow the new type while the emission followed the old one."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))[1] == (
        "— not converted"
    )

    # Row 0 is series 1, the scout — really a functional run this study named badly.
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {0: {"Type": "func"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert not at.error

    plan = _plan_table(at)
    row = dict(zip(plan["Series #"], plan["becomes"]))
    assert row[1].endswith("_bold.nii.gz")
    assert dict(zip(plan["Series #"], plan["Type from"]))[1] == "project"


def test_relabelling_an_anat_writes_the_declared_suffix_not_the_named_one(project):
    """`t1w_mprage` says T1w in its name, so this is the case a suffix *hint*
    could never have reached — the hint is consulted last and only rescues a
    series the name dropped."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {1: {"Type": "anat/FLAIR"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    becomes = dict(zip(_plan_table(at)["Series #"], _plan_table(at)["becomes"]))
    assert becomes[2] == "sub-001_ses-01_FLAIR.nii.gz"


def test_a_type_that_cannot_be_declared_is_refused_by_name(project):
    """The dropdown must offer `scout` (a Selectbox cell can't render a value
    outside its options), so picking one has to be refused rather than ignored."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    at.session_state[EDITOR_KEY] = {
        "edited_rows": {4: {"Type": "scout"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    assert not at.exception
    assert any("can't be declared" in w.value for w in at.warning)
    # And the row keeps the type duckbrain read, rather than showing a dead value.
    plan = _plan_table(at)
    assert dict(zip(plan["Series #"], plan["Type"]))[9] == "func"
    assert dict(zip(plan["Series #"], plan["becomes"]))[9].endswith("_bold.nii.gz")


def test_saving_types_as_the_project_default_makes_every_session_follow(project):
    """A datatype duckbrain misreads it misreads for the whole study, which is
    why the correction is keyed on description and lives in the project config."""
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    save = next(b for b in at.button if b.key == "save_project_series_types")
    assert save.disabled  # nothing declared yet

    at.session_state[EDITOR_KEY] = {
        "edited_rows": {0: {"Type": "func"}},
        "added_rows": [],
        "deleted_rows": [],
    }
    at.run()
    next(b for b in at.button if b.key == "save_project_series_types").click().run()
    assert not at.exception
    assert any("type declaration" in s.value for s in at.success)

    from duckbrain.config import load_config
    from duckbrain.core.series_types import TypeRule, type_rules_from_config

    saved = type_rules_from_config(load_config(project_dir=str(project)))
    assert saved == [TypeRule("AAhead_scout", "func", "bold")]


def test_a_project_declaration_seeds_the_table(project):
    """Read back through the same path bulk convert reads it: the page must not
    be the only thing that honours a declaration."""
    from duckbrain.config import save_project_series_types
    from duckbrain.core.series_types import TypeRule

    save_project_series_types(str(project), [TypeRule("AAhead_scout", "anat", "T2w")])
    plan = _plan_table(at := AppTest.from_file(PAGE, default_timeout=60).run())
    assert not at.exception
    assert dict(zip(plan["Series #"], plan["Type"]))[1] == "anat/T2w"
    assert dict(zip(plan["Series #"], plan["Type from"]))[1] == "project"
    assert dict(zip(plan["Series #"], plan["becomes"]))[1] == "sub-001_ses-01_T2w.nii.gz"
