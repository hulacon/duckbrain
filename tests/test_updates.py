"""The "a newer release exists" check — ``core.updates``.

The check runs on every GUI page against a network it may not have, so what these
pin is mostly what it *doesn't* do: never raise, never nag a current checkout, and
never claim to know when it couldn't find out. The one thing it must do is fire
when a real release is genuinely newer, because that is the only channel a
correctness fix has to a user who isn't reading the commit log.
"""

import subprocess

import pytest

from duckbrain.core import updates


@pytest.fixture(autouse=True)
def _check_enabled(monkeypatch):
    """Undo the suite-wide opt-out in ``tests/conftest.py``.

    This module is the one place that tests the check itself, and the opt-out
    returns ``None`` — the same value as every "says nothing" case below. Without
    this, all of them pass without executing a line of the code they name. Caught
    by the one test whose expected value *isn't* ``None``, which is the argument
    for keeping that test first among equals.
    """
    monkeypatch.delenv(updates.OPT_OUT_ENV, raising=False)


@pytest.fixture
def repo(tmp_path):
    """A throwaway checkout tagged ``v0.2.0`` with a GitHub ``origin``."""
    root = tmp_path / "checkout"
    root.mkdir()
    run = lambda *a: subprocess.run(  # noqa: E731 — terse on purpose, five call sites
        ["git", "-C", str(root), *a], check=True, capture_output=True
    )
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    run("config", "remote.origin.url", "git@github.com:hulacon/duckbrain.git")
    (root / "f.txt").write_text("x")
    run("add", "f.txt")
    run("commit", "-qm", "init")
    run("tag", "-a", "v0.2.0", "-m", "v0.2.0")
    return root


def _serving(monkeypatch, tag, url="https://example.invalid/rel"):
    monkeypatch.setattr(updates, "latest_release", lambda slug, **kw: (tag, url))


# --- version parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "tag,expected",
    [("v0.2.0", (0, 2, 0)), ("0.2.0", (0, 2, 0)), ("v1.2", (1, 2, 0)), ("v3", (3, 0, 0))],
)
def test_plain_semver_tags_parse(tag, expected):
    assert updates._parse(tag) == expected


@pytest.mark.parametrize(
    "tag", ["", "v0.2.0-rc1", "v0.2.0+build", "release-2", "v0.2.x", "v1.2.3.4"]
)
def test_anything_not_plain_semver_is_refused_rather_than_guessed(tag):
    """A misparse here nags a user who is already current — the one unforced error."""
    assert updates._parse(tag) is None


def test_pre_releases_never_trigger_a_notice(repo, monkeypatch):
    """``releases/latest`` excludes them, but a hand-cut tag must not sneak through."""
    _serving(monkeypatch, "v0.3.0-rc1")
    assert updates.update_available(repo) is None


# --- the comparison --------------------------------------------------------


def test_a_newer_release_is_reported_with_its_url(repo, monkeypatch):
    _serving(monkeypatch, "v0.3.0", "https://example.invalid/v030")
    assert updates.update_available(repo) == ("v0.3.0", "https://example.invalid/v030")


def test_the_same_release_is_not_an_update(repo, monkeypatch):
    _serving(monkeypatch, "v0.2.0")
    assert updates.update_available(repo) is None


def test_a_checkout_ahead_of_the_latest_release_is_not_behind_it(repo, monkeypatch):
    """The maintainer's own checkout lives here permanently.

    ``describe --abbrev=0`` reports the nearest *tag*, so commits past v0.2.0 still
    read ``v0.2.0`` — which is the point. Comparing full ``git describe`` output, or
    comparing against ``origin/main``, would nag on every unreleased commit.
    """
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "wip"], check=True
    )
    _serving(monkeypatch, "v0.2.0")
    assert updates.update_available(repo) is None
    assert updates.current_tag(repo) == "v0.2.0"


def test_an_older_published_release_never_suggests_a_downgrade(repo, monkeypatch):
    _serving(monkeypatch, "v0.1.0")
    assert updates.update_available(repo) is None


# --- degrading to "could not tell" -----------------------------------------


def test_an_untagged_checkout_says_nothing_and_makes_no_request(tmp_path, monkeypatch):
    """A shallow clone or an unpacked zip has no tags; there is nothing to compare."""
    root = tmp_path / "bare"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)

    def _boom(*a, **kw):
        raise AssertionError("must not reach the network with nothing to compare")

    monkeypatch.setattr(updates, "latest_release", _boom)
    assert updates.update_available(root) is None


def test_a_directory_that_is_not_a_checkout_says_nothing(tmp_path):
    assert updates.update_available(tmp_path) is None


def test_an_unreachable_or_rate_limited_api_says_nothing(repo, monkeypatch):
    """403, DNS failure and timeout are indistinguishable here — all mean silence."""
    monkeypatch.setattr(updates, "latest_release", lambda slug, **kw: None)
    assert updates.update_available(repo) is None


def test_the_opt_out_env_var_short_circuits_before_any_request(repo, monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("opt-out must be checked first")

    monkeypatch.setattr(updates, "latest_release", _boom)
    monkeypatch.setenv(updates.OPT_OUT_ENV, "1")
    assert updates.update_available(repo) is None


# --- the API call itself ---------------------------------------------------


class _Resp:
    """Barely enough of an ``http.client.HTTPResponse`` for ``urlopen``'s context."""

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _answering(monkeypatch, body):
    monkeypatch.setattr(updates.urllib.request, "urlopen", lambda req, timeout=None: _Resp(body))


def test_a_release_payload_yields_its_tag_and_page(monkeypatch):
    _answering(
        monkeypatch,
        '{"tag_name": "v0.3.0", "html_url": "https://github.com/hulacon/duckbrain/'
        'releases/tag/v0.3.0"}',
    )
    tag, url = updates.latest_release("hulacon/duckbrain")
    assert tag == "v0.3.0"
    assert url.endswith("/releases/tag/v0.3.0")


def test_a_payload_without_html_url_still_produces_a_usable_link(monkeypatch):
    """GitHub always sends one; a link that 404s is still better than a dead notice."""
    _answering(monkeypatch, '{"tag_name": "v0.3.0"}')
    _, url = updates.latest_release("hulacon/duckbrain")
    assert url == "https://github.com/hulacon/duckbrain/releases/tag/v0.3.0"


@pytest.mark.parametrize("body", ["not json at all", "{}", '{"tag_name": ""}', "null"])
def test_an_unusable_payload_says_nothing_rather_than_raising(monkeypatch, body):
    """This runs while a page renders; an exception here would blank the whole GUI."""
    _answering(monkeypatch, body)
    assert updates.latest_release("hulacon/duckbrain") is None


def test_a_network_failure_says_nothing_rather_than_raising(monkeypatch):
    def _refuse(req, timeout=None):
        raise updates.urllib.error.URLError("no route to host")

    monkeypatch.setattr(updates.urllib.request, "urlopen", _refuse)
    assert updates.latest_release("hulacon/duckbrain") is None


def test_a_nonsense_slug_is_never_sent(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("must not build a URL from a slug that is not Owner/Repo")

    monkeypatch.setattr(updates.urllib.request, "urlopen", _boom)
    assert updates.latest_release("duckbrain") is None
    assert updates.latest_release("") is None


# --- which repo gets asked -------------------------------------------------


def test_the_slug_comes_from_the_checkouts_own_remote(repo):
    """A fork is checked against the fork.

    Telling a fork's user they are behind *our* release would be both wrong and
    unactionable from their side.
    """
    assert updates.repo_slug(repo) == "hulacon/duckbrain"

    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "remote.origin.url",
            "https://github.com/someone/fork.git",
        ],
        check=True,
    )
    assert updates.repo_slug(repo) == "someone/fork"


def test_a_remoteless_checkout_asks_nobody(repo, monkeypatch):
    subprocess.run(["git", "-C", str(repo), "config", "--unset", "remote.origin.url"], check=True)
    assert updates.repo_slug(repo) == ""
    assert updates.latest_release("") is None
    assert updates.update_available(repo) is None
