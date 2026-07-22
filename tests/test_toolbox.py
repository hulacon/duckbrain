"""Version provenance from a git-checkout toolbox (NORDIC).

NORDIC has no container, so its identity comes from the checkout it runs from.
The important behavior is the degrade path: a toolbox that isn't a git checkout,
or isn't configured at all, must yield "" — never a guess, and above all never
the *current directory's* repo.
"""

import subprocess

from duckbrain.core import toolbox as T


def _repo(path, remote=None, tag=None):
    path.mkdir(parents=True, exist_ok=True)
    def run(*a):
        return subprocess.run(["git", "-C", str(path), *a], check=True,
                              capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (path / "NIFTI_NORDIC.m").write_text("% stub\n")
    run("add", "-A")
    run("commit", "-qm", "initial")
    if tag:
        run("tag", tag)
    if remote:
        run("remote", "add", "origin", remote)
    return path


def _sha(path, short=True):
    args = ["rev-parse"] + (["--short"] if short else []) + ["HEAD"]
    return subprocess.run(["git", "-C", str(path), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


# ---- describe ---------------------------------------------------------------

def test_describe_falls_back_to_sha_when_untagged(tmp_path):
    repo = _repo(tmp_path / "tb")
    assert T.describe(repo) == _sha(repo)


def test_describe_uses_tag_and_distance(tmp_path):
    repo = _repo(tmp_path / "tb", tag="v1.0.2")
    (repo / "extra.m").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "second"], check=True,
                   capture_output=True)
    # Mirrors the real toolbox: commits past the last release tag.
    assert T.describe(repo).startswith("v1.0.2-1-g")


def test_describe_marks_local_edits_dirty(tmp_path):
    repo = _repo(tmp_path / "tb")
    (repo / "NIFTI_NORDIC.m").write_text("% hand-edited\n")
    assert T.describe(repo).endswith("-dirty")


# ---- source_ref -------------------------------------------------------------

def test_source_ref_is_owner_repo_at_sha(tmp_path):
    repo = _repo(tmp_path / "tb", remote="https://github.com/SteenMoeller/NORDIC_Raw.git")
    assert T.source_ref(repo) == f"SteenMoeller/NORDIC_Raw@{_sha(repo)}"


def test_source_ref_handles_ssh_remotes(tmp_path):
    repo = _repo(tmp_path / "tb", remote="git@github.com:SteenMoeller/NORDIC_Raw.git")
    assert T.source_ref(repo) == f"SteenMoeller/NORDIC_Raw@{_sha(repo)}"


def test_source_ref_without_remote_falls_back_to_bare_sha(tmp_path):
    repo = _repo(tmp_path / "tb")
    assert T.source_ref(repo) == _sha(repo)


# ---- code_url ---------------------------------------------------------------

def test_code_url_pins_the_exact_commit(tmp_path):
    repo = _repo(tmp_path / "tb", remote="https://github.com/SteenMoeller/NORDIC_Raw.git")
    assert T.code_url(repo) == (
        f"https://github.com/SteenMoeller/NORDIC_Raw/tree/{_sha(repo, short=False)}")


def test_code_url_declines_to_guess_for_unknown_hosts(tmp_path):
    """Better to say nothing than invent a URL scheme for an arbitrary host."""
    repo = _repo(tmp_path / "tb", remote="https://git.example.org/Owner/Repo.git")
    assert T.code_url(repo) == ""


# ---- degrade paths ----------------------------------------------------------

def test_unset_path_never_describes_the_current_directory(tmp_path, monkeypatch):
    """Regression: Path("") is `.`, so an unset toolbox dir would describe
    whatever repo duckbrain runs from and record it as the toolbox's version."""
    monkeypatch.chdir(_repo(tmp_path / "some_other_repo"))
    for value in ("", "   ", None):
        assert T.describe(value) == ""
        assert T.source_ref(value) == ""
        assert T.code_url(value) == ""


def test_plain_directory_is_not_a_checkout(tmp_path):
    """An unpacked copy (no .git) is a legitimate way to hold the toolbox —
    unknowable version, not an error."""
    plain = tmp_path / "NORDIC_Raw"
    plain.mkdir()
    (plain / "NIFTI_NORDIC.m").write_text("% stub\n")
    assert T.describe(plain) == ""
    assert T.source_ref(plain) == ""


def test_missing_path_degrades_quietly(tmp_path):
    assert T.describe(tmp_path / "nope") == ""
    assert T.source_ref(tmp_path / "nope") == ""


def test_no_git_on_path_degrades_quietly(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "tb")
    monkeypatch.setattr(T.shutil, "which", lambda exe: None)
    assert T.describe(repo) == ""
    assert T.source_ref(repo) == ""


def test_git_timeout_degrades_quietly(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "tb")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 15)

    monkeypatch.setattr(T.subprocess, "run", boom)
    assert T.describe(repo) == ""
