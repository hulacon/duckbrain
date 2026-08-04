"""AppTest smoke/interaction tests for gui.components.directory_picker."""

from streamlit.testing.v1 import AppTest


def _picker_app(default="", allow_create=False, must_exist=False):
    from duckbrain.gui.components import directory_picker

    directory_picker(
        "Pick a dir",
        key="t",
        default=default,
        allow_create=allow_create,
        must_exist=must_exist,
    )


def _run(tmp_path, **kwargs):
    at = AppTest.from_function(_picker_app, kwargs={"default": str(tmp_path), **kwargs})
    at.run()
    assert not at.exception
    return at


def _folder_button(at, name):
    for b in at.button:
        if b.label == f"\U0001f4c1 {name}":
            return b
    raise AssertionError(f"no folder button for {name!r}")


def test_renders_subdirs_and_selection_caption(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    (tmp_path / ".hidden").mkdir()
    at = _run(tmp_path)

    labels = [b.label for b in at.button]
    assert "\U0001f4c1 alpha" in labels
    assert "\U0001f4c1 beta" in labels
    assert not any(".hidden" in lbl for lbl in labels)
    assert at.session_state["__dp_t"] == str(tmp_path)
    assert any("✓ Selected" in c.value for c in at.caption)


def test_navigate_then_commit(tmp_path):
    (tmp_path / "alpha" / "inner").mkdir(parents=True)
    at = _run(tmp_path)

    _folder_button(at, "alpha").click().run()
    assert not at.exception
    # navigation alone must NOT change the committed selection
    assert at.session_state["__dp_t"] == str(tmp_path)
    assert at.session_state["__dp_t_cwd"] == str(tmp_path / "alpha")
    # the browsed dir's children are now listed
    assert any(b.label == "\U0001f4c1 inner" for b in at.button)

    at.button(key="t_use").click().run()
    assert not at.exception
    assert at.session_state["__dp_t"] == str(tmp_path / "alpha")


def test_breadcrumb_jumps_up(tmp_path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    at = _run(deep)

    crumbs = [b for b in at.button if b.key and b.key.startswith("t_bc")]
    assert [c.label for c in crumbs[-3:]] == ["a", "b", "c"]
    # click the "a" crumb → browser jumps two levels up in one click
    crumbs[-3].click().run()
    assert not at.exception
    assert at.session_state["__dp_t_cwd"] == str(tmp_path / "a")


def test_filter_narrows_list(tmp_path):
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    at = _run(tmp_path)

    at.text_input(key="__dp_t_flt").input("alp").run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert "\U0001f4c1 alpha" in labels
    assert "\U0001f4c1 beta" not in labels


def test_typed_path_commits_directly(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    at = _run(tmp_path)

    at.text_input(key="__dp_t").input(str(other)).run()
    assert not at.exception
    assert at.session_state["__dp_t"] == str(other)
    assert at.session_state["__dp_t_cwd"] == str(other)


def test_create_folder(tmp_path):
    at = _run(tmp_path, allow_create=True)

    at.text_input(key="__dp_t_new").input("newdir").run()
    at.button(key="t_mk").click().run()
    assert not at.exception
    assert (tmp_path / "newdir").is_dir()
    # browser follows into the newly created folder
    assert at.session_state["__dp_t_cwd"] == str(tmp_path / "newdir")


def test_must_exist_warns_on_missing_default(tmp_path):
    missing = tmp_path / "nope"
    at = _run(missing, must_exist=True)
    assert any("does not exist" in c.value for c in at.caption)


# ---------------------------------------------------------------------------
# embed_tool_report — the MRIQC/fMRIPrep report viewer
# ---------------------------------------------------------------------------


def _embed_app(report_path):
    from pathlib import Path

    import streamlit as st

    from duckbrain.gui.components import embed_tool_report

    st.write(f"complete={embed_tool_report(Path(report_path))}")


def _mriqc_report(tmp_path, *, with_figures=True):
    """An MRIQC-shaped report: one HTML naming figures in a subdirectory."""
    if with_figures:
        (tmp_path / "figures").mkdir()
        (tmp_path / "figures" / "carpet.svg").write_text("<svg/>")
    path = tmp_path / "sub-010_task-rest_run-1_bold.html"
    path.write_text('<html><body><img src="./figures/carpet.svg"/></body></html>')
    return path


def test_embed_tool_report_serves_the_figures(tmp_path):
    """The whole point: a figure MRIQC named relatively becomes a URL the app
    serves, so the report renders complete inside the GUI."""
    at = AppTest.from_function(_embed_app, kwargs={"report_path": str(_mriqc_report(tmp_path))})
    at.run()
    assert not at.exception
    assert at.markdown[0].value == "complete=True"
    assert not at.warning


def test_embed_tool_report_puts_the_rewritten_markup_in_the_frame(tmp_path):
    """The return value says the rewrite succeeded; this says the rewritten
    markup is what actually reached the browser.

    ``st.iframe`` sniffs its argument, and a path-shaped one would be re-read
    from disk — serving MRIQC's original relative ``src`` and a blank figure,
    with ``complete=True`` still returned. Assert on ``srcdoc`` so that swap
    fails here rather than in the GUI.
    """
    at = AppTest.from_function(_embed_app, kwargs={"report_path": str(_mriqc_report(tmp_path))})
    at.run()
    (frame,) = at.get("iframe")
    assert "./figures/carpet.svg" not in frame.proto.srcdoc
    assert "/media/" in frame.proto.srcdoc


def test_embed_tool_report_says_so_when_a_figure_is_missing(tmp_path):
    """A report with holes in it must announce them. Rendering it silently
    incomplete is the failure mode this feature exists to end."""
    at = AppTest.from_function(
        _embed_app,
        kwargs={"report_path": str(_mriqc_report(tmp_path, with_figures=False))},
    )
    at.run()
    assert not at.exception
    assert at.markdown[0].value == "complete=False"
    assert "could not be served" in at.warning[0].value


def test_embed_tool_report_reports_an_unreadable_file(tmp_path):
    at = AppTest.from_function(_embed_app, kwargs={"report_path": str(tmp_path / "nope.html")})
    at.run()
    assert not at.exception
    assert at.markdown[0].value == "complete=False"
    assert at.error


def test_media_urls_carry_the_ondemand_base_path(monkeypatch):
    """Streamlit hands back a root-absolute ``/media/…`` URL, which 404s under
    OnDemand's ``/node/<host>/<port>/`` mount. Prefixing it is the fix."""
    import streamlit as st

    from duckbrain.gui import components

    monkeypatch.setattr(st, "get_option", lambda name: "/node/n0123/8501/")
    assert components._media_url_prefix() == "/node/n0123/8501"

    monkeypatch.setattr(st, "get_option", lambda name: None)
    assert components._media_url_prefix() == ""


# ---- Confirmations that have to outlive an st.rerun() -----------------------


def _toast_app():
    """A button that confirms itself and reruns — the shape every save/launch has."""
    import streamlit as st

    from duckbrain.gui.components import flush_toasts, queue_toast

    flush_toasts()
    if st.button("save"):
        queue_toast("Saved it")
        st.rerun()


def test_a_queued_toast_survives_a_rerun():
    """The regression that shipped the day streamlit 1.61 was published.

    Every "Saved"/"Submitted"/"Cancelled" message in this GUI is written by a
    handler that then calls ``st.rerun()``. Raising it directly worked on
    streamlit 1.59 and silently stopped on 1.61, which discards a toast queued
    before a rerun — so a save, a job launch and a cancel all reported *nothing*
    while still doing the work. Asserting it here rather than only through the
    Setup page keeps the guarantee attached to the helper that provides it.
    """
    at = AppTest.from_function(_toast_app)
    at.run()
    assert not at.exception
    assert not at.toast, "nothing was queued yet"

    at.button[0].click().run()
    assert not at.exception
    assert [t.value for t in at.toast] == ["Saved it"]


def test_a_flushed_toast_is_not_shown_twice():
    """It is a confirmation of one action, so it must not survive into the run after."""
    at = AppTest.from_function(_toast_app)
    at.run()
    at.button[0].click().run()
    assert [t.value for t in at.toast] == ["Saved it"]

    at.run()
    assert not at.toast
