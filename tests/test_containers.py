"""Reading build provenance out of a container image.

The value here is the *degrade* path: duckbrain must never raise or block a
submission because an image is unreadable, apptainer is missing, or a container
carries no labels. Unknown provenance is "", never a guess.
"""

import subprocess

from duckbrain.core import containers as C


def _fake_inspect(monkeypatch, stdout, returncode=0):
    C._inspect_labels_cached.cache_clear()
    monkeypatch.setattr(C.shutil, "which", lambda exe: "/usr/bin/apptainer")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(C.subprocess, "run", fake_run)


# Real label output, trimmed (mriqc-24.0.2.simg on Talapas, 2026-07-16).
_REAL_LABELS = """org.label-schema.build-arch: amd64
org.label-schema.name: MRIQC
org.label-schema.usage.singularity.deffile.bootstrap: docker
org.label-schema.usage.singularity.deffile.from: nipreps/mriqc:24.0.2
org.label-schema.vcs-ref: d5b13cb5
org.label-schema.version:
"""


def test_build_tag_read_from_real_label_shape(monkeypatch, tmp_path):
    img = tmp_path / "mriqc-24.0.2.simg"
    img.write_text("img")
    _fake_inspect(monkeypatch, _REAL_LABELS)
    assert C.container_build_tag(img) == "nipreps/mriqc:24.0.2"


def test_container_uri_prefixes_recorded_bootstrap_scheme(monkeypatch, tmp_path):
    img = tmp_path / "mriqc-24.0.2.simg"
    img.write_text("img")
    _fake_inspect(monkeypatch, _REAL_LABELS)
    assert C.container_uri(img) == "docker://nipreps/mriqc:24.0.2"


def test_labels_parse_values_containing_colons(monkeypatch, tmp_path):
    """The Docker tag itself contains a colon — split on the first only."""
    img = tmp_path / "x.simg"
    img.write_text("img")
    _fake_inspect(monkeypatch, "org.label-schema.usage.singularity.deffile.from: a/b:1.2.3\n")
    assert C.container_build_tag(img) == "a/b:1.2.3"


def test_missing_image_yields_no_provenance(monkeypatch, tmp_path):
    _fake_inspect(monkeypatch, _REAL_LABELS)
    assert C.container_build_tag(tmp_path / "nope.simg") == ""
    assert C.inspect_labels(tmp_path / "nope.simg") == {}


def test_no_apptainer_on_path_degrades_quietly(monkeypatch, tmp_path):
    img = tmp_path / "x.simg"
    img.write_text("img")
    C._inspect_labels_cached.cache_clear()
    monkeypatch.setattr(C.shutil, "which", lambda exe: None)
    assert C.container_build_tag(img) == ""


def test_inspect_failure_degrades_quietly(monkeypatch, tmp_path):
    img = tmp_path / "x.simg"
    img.write_text("img")
    _fake_inspect(monkeypatch, "", returncode=1)
    assert C.container_build_tag(img) == ""


def test_inspect_timeout_degrades_quietly(monkeypatch, tmp_path):
    img = tmp_path / "x.simg"
    img.write_text("img")
    C._inspect_labels_cached.cache_clear()
    monkeypatch.setattr(C.shutil, "which", lambda exe: "/usr/bin/apptainer")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 30)

    monkeypatch.setattr(C.subprocess, "run", boom)
    assert C.container_build_tag(img) == ""


def test_image_without_bootstrap_label_has_no_build_tag(monkeypatch, tmp_path):
    """Built from a local def file, not a registry — unknowable, not a mismatch."""
    img = tmp_path / "x.simg"
    img.write_text("img")
    _fake_inspect(monkeypatch, "org.label-schema.name: Custom\n")
    assert C.container_build_tag(img) == ""
    assert C.container_uri(img) == ""


def test_rebuilt_image_at_same_path_is_not_served_from_cache(monkeypatch, tmp_path):
    """The cache keys on (path, mtime, size) — an in-place rebuild must re-inspect,
    since that is exactly the drift build provenance exists to catch."""
    img = tmp_path / "x.simg"
    img.write_text("v1")
    _fake_inspect(monkeypatch, "org.label-schema.usage.singularity.deffile.from: t/x:1\n")
    assert C.container_build_tag(img) == "t/x:1"

    # Rebuild in place: same path, new contents (so new size/mtime), new labels.
    img.write_text("version two")
    monkeypatch.setattr(
        C.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(
            cmd, 0, stdout="org.label-schema.usage.singularity.deffile.from: t/x:2\n", stderr=""),
    )
    assert C.container_build_tag(img) == "t/x:2"
