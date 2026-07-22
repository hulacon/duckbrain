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
