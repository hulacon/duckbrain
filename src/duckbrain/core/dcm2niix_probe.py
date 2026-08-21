"""Ask dcm2niix what a series is, before converting it.

``dicom_header`` reads the DICOM directly and normalises across the two Siemens
dialects by hand. That works for what it does, but two fields duckbrain wants at
plan time are simply not in the tags it can reach:

* **Signed phase-encoding direction.** ``InPlanePhaseEncodingDirection`` is
  ``ROW``/``COL`` — an *axis*, with no polarity — and on XA30 it is absent
  entirely. AP and PA are indistinguishable there, so every ``dir-`` label
  duckbrain writes today comes from the ``_ap``/``_pa`` token in the operator's
  series name. That guess is right for all 32 name-tokened fieldmaps in the LCNI
  repository, which is reassuring and is exactly why it should be *checked*: the
  inverted ``B0FieldIdentifier`` also validated cleanly for months.
* **``ShimSetting``.** Siemens keeps it in the CSA blob's ASCCONV protocol, and
  XA30 has no CSA at all — yet dcm2niix reports it for 383 of the corpus's 385
  readable series, XA30 included, because it reconstructs it from the enhanced
  structures. Reimplementing that is turning a wheel dcm2niix already turns.

So run dcm2niix. The cost objection is real but applies to the wrong invocation:
``dcm2niix -b o`` over a session *directory* reads every file — 90 s for a
2.5 GB session on GPFS, essentially all I/O. One file per series is enough for
everything above, so stage a directory of symlinks (one per series, named after
the series directory) and make a single call over that: **0.15 s for a whole
session**, or 0.35 s through the container.

Validated one-file-vs-whole-series on REV055: 259 of 272 key/value pairs
identical, every difference confined to multi-echo gradient-echo fieldmaps
(``SliceTiming`` and ``MultibandAccelerationFactor`` need several files, and
``EchoTime`` reports whichever echo sorted first) plus sub-second
``AcquisitionTime`` jitter. BOLD series matched exactly. So: read the
single-file-safe fields here, and leave volume counts and second echoes to
``dicom_header``, which reads three files per series precisely to see them.

**Prefer the container.** The pinned ``dcm2bids`` image holds the same dcm2niix
build that will do the conversion, so a preview taken through it cannot disagree
with the result for a reason duckbrain can't see. A host dcm2niix is the
fallback, and *no* dcm2niix is not an error — it means the probe returns nothing
and every caller keeps the behaviour it had before. That degradation is
reportable rather than silent, per ``CLAUDE.md``: a check that can't run must
say so, not pass.

**Which is why the probe returns a** :class:`ProbeResult` **and not a map.**
:func:`probe_unavailable_reason` answers "is there a dcm2niix" and cannot answer
"does it work" — it looks for the binary rather than trying it. So availability
was reportable and *usability* was not: dcm2niix on ``PATH`` here is a pip
console-script shim that a test run with user site-packages disabled makes
unimportable (``memory/pythonnousersite-for-test-runs``), the process exited 1,
and the probe returned the same empty map as a session whose series
all legitimately yield nothing. The trigger was environmental; the failure mode
was not, since **any** non-zero exit read as "nothing to probe here" and the plan
then quietly lost the two fields only the probe supplies. A run that did not
complete now says so in :attr:`ProbeResult.failure`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_TIMEOUT_S = 120

# The BIDS phase-encoding direction a ``dir-`` label implies. **Assumes an axial
# acquisition**, where the anterior-posterior axis is the second voxel axis; it
# is not a general mapping from anatomy to voxel space, and an oblique or
# coronal pepolar pair would need ``ImageOrientationPatient`` to place it. Both
# consumers import it from here rather than keeping a copy: the plan-time check
# and the post-conversion one have to agree, or a conversion passes one and
# fails the other. See ``TODO`` ``#19.2`` for the general case.
#
# **RL/LR are measured, not derived, and that is a weaker footing than AP/PA.**
# ``AP``→``j-`` is a naming convention that happens to agree with anatomy. R→L
# phase encoding is −x, which would imply ``i-``; both the ABCD-protocol tree at
# /projects/hulacon/shared/mmmsourcedata and the LCNI corpus's ``Round_Robin``
# diffusion nonetheless read ``rl``→``i`` and ``lr``→``i-``, at two different
# sites. Two agreeing studies is what these rows rest on, so they are the rows
# most likely to invert somewhere else — which costs a false *warning* and never
# deformed data, since the only consumers compare and report. The message already
# offers "or it isn't an axial acquisition" as the alternative reading.
PE_FOR_DIR = {"AP": "j-", "PA": "j", "RL": "i", "LR": "i-"}

# dcm2niix appends these to the ``%b`` basename when one input yields more than
# one output — a second echo, or the phase image of a gradient-echo pair. The
# staged name is therefore a *prefix* of the sidecar name, not an equality.
_SUFFIX_HINT = "_e"


@dataclass(frozen=True)
class SeriesProbe:
    """What dcm2niix says about one series, read from a single file.

    Every field is optional: dcm2niix omits what the acquisition doesn't have
    (an anat has no phase-encoding direction) and callers must treat absence as
    "unknown", never as a value.
    """

    series_number: int | None = None
    series_description: str = ""
    # BIDS-space phase encoding: 'i', 'i-', 'j', 'j-', 'k', 'k-'. Signed, which
    # is the whole point — the raw tag gives the axis only.
    phase_encoding_direction: str = ""
    shim_setting: tuple[float, ...] = ()
    total_readout_time: float | None = None
    effective_echo_spacing: float | None = None
    multiband_factor: int | None = None
    echo_time: float | None = None
    image_type: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def pe_axis(self) -> str:
        """The unsigned axis, or ``""``. ``'j-'`` and ``'j'`` share axis ``'j'``."""
        return self.phase_encoding_direction.rstrip("-")


def by_series_number(probes: dict[str, SeriesProbe]) -> dict[int, SeriesProbe]:
    """Re-key a session's probes on ``SeriesNumber``.

    :func:`probe_session` keys on the directory name because that is what the
    caller passed in and what can't collide. Consumers that hold a plan rather
    than a directory listing want the series number, which is what every other
    duckbrain structure is indexed by. Series with no readable number are
    dropped — the alternative is a ``None`` key nothing can look up.
    """
    return {p.series_number: p for p in probes.values() if p.series_number is not None}


@dataclass(frozen=True)
class ProbeResult:
    """What a session probe read, and whether the run behind it can be believed.

    The two empty cases are different answers and must not render the same way:

    * ``probes`` empty, ``failure`` empty — dcm2niix ran and declined every
      series. A legitimate miss: empty directories, a Phoenix report, anything
      it doesn't recognise.
    * ``failure`` set — the run did not complete (a non-zero exit, a timeout, no
      runnable dcm2niix at all). Whatever is in ``probes`` is what survived, and
      may be partial: dcm2niix can write sidecars and *then* fail.

    Conflating them is the silently-degrading-option rule (``CLAUDE.md``) inside
    ``core/``, and it is what this class exists to stop.
    """

    probes: dict[str, SeriesProbe] = field(default_factory=dict)
    failure: str = ""

    @property
    def ok(self) -> bool:
        """Whether the run completed. ``ok`` and empty is a real "nothing here"."""
        return not self.failure

    @property
    def by_number(self) -> dict[int, SeriesProbe]:
        """:func:`by_series_number` over :attr:`probes`, for plan-shaped callers."""
        return by_series_number(self.probes)


def probe_unavailable_reason(container: str | Path | None = None) -> str:
    """Why the probe can't run, or ``""`` when it can.

    Exists so a caller can *say* the check was skipped. Returning an empty probe
    map and letting the panel look clean is the failure mode ``CLAUDE.md``
    forbids.
    """
    if container:
        if not Path(container).exists():
            return f"container image not found: {container}"
        if not (shutil.which("apptainer") or shutil.which("singularity")):
            return "neither apptainer nor singularity is on PATH"
        return ""
    if not shutil.which("dcm2niix"):
        return "dcm2niix is not on PATH and no container was given"
    return ""


@dataclass(frozen=True)
class ProbeRuntime:
    """What the probe would run through, and what it cost to decide.

    Three states, and a caller has to tell them apart to report honestly:

    * ``reason`` empty and ``fallback`` empty — the pinned image will be used.
    * ``reason`` empty, ``fallback`` set — the image was unusable and a host
      ``dcm2niix`` is standing in. The probe works, but it may not be the build
      that converts, which is a weaker claim than the pinned image supports.
    * ``reason`` set — nothing can run, and the caller must say so rather than
      render an unchecked panel as a clean one.
    """

    container: Path | None = None
    reason: str = ""
    fallback: str = ""

    @property
    def available(self) -> bool:
        return not self.reason


def probe_runtime(container: str | Path | None = None) -> ProbeRuntime:
    """Resolve what to probe through, preferring *container* over a host dcm2niix.

    :func:`probe_unavailable_reason` answers this for one candidate at a time and
    cannot express the preference: given a container it never looks at the host,
    and given none it never looks at the image. The preference is the point —
    the pinned image holds the same dcm2niix build that will do the conversion,
    so a preview taken through it cannot disagree with the result for a reason
    duckbrain can't see (validated identical on REV055). A host binary is worth
    falling back to and worth *saying* you fell back to.
    """
    container_reason = probe_unavailable_reason(container) if container else ""
    if container and not container_reason:
        return ProbeRuntime(container=Path(container))

    host_reason = probe_unavailable_reason(None)
    if not host_reason:
        return ProbeRuntime(fallback=container_reason)
    if container_reason:
        return ProbeRuntime(reason=f"{container_reason}; {host_reason}")
    return ProbeRuntime(reason=host_reason)


def _first_file(series_dir: Path) -> Path | None:
    try:
        for name in sorted(os.listdir(series_dir)):
            candidate = series_dir / name
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def _command(
    stage: Path, out: Path, container: str | Path | None, sources: list[Path]
) -> list[str]:
    # -b o: sidecar only, no NIfTI. -w 1: overwrite rather than add a suffix on
    # a name clash, so a collision can't silently produce a second file we then
    # fail to map back. -f %b: name the output after the staged symlink.
    dcm2niix = ["dcm2niix", "-b", "o", "-w", "1", "-f", "%b", "-o", str(out), str(stage)]
    if not container:
        return dcm2niix
    exe = shutil.which("apptainer") or shutil.which("singularity") or "apptainer"
    # The staging dir holds symlinks pointing *out* of itself, and apptainer
    # resolves them inside the container — so binding the staging dir alone
    # gives 17 dangling links and an empty result. Every filesystem the links
    # reach into has to be bound too.
    binds = []
    for path in [stage, out, *sources]:
        bind = str(path)
        if bind not in binds:
            binds.append(bind)
    flags = [arg for bind in binds for arg in ("-B", f"{bind}:{bind}")]
    return [exe, "exec", *flags, str(container), *dcm2niix]


def _as_floats(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    try:
        return tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return ()


def _exit_failure(completed: subprocess.CompletedProcess[str]) -> str:
    """Why a *finished* dcm2niix run can't be believed, or ``""`` when it can.

    dcm2niix is chatty on both streams and says the useful thing last, so the
    last non-empty line is the one worth carrying up — the whole log would not
    fit in the caption that renders it.
    """
    if completed.returncode == 0:
        return ""
    detail = ""
    for stream in (completed.stderr, completed.stdout):
        lines = [line.strip() for line in (stream or "").splitlines() if line.strip()]
        if lines:
            detail = lines[-1][:200]
            break
    return f"dcm2niix exited {completed.returncode}" + (f": {detail}" if detail else "")


def _to_probe(sidecar: dict[str, Any]) -> SeriesProbe:
    number = sidecar.get("SeriesNumber")
    multiband = sidecar.get("MultibandAccelerationFactor")
    return SeriesProbe(
        series_number=int(number) if isinstance(number, (int, float)) else None,
        series_description=str(sidecar.get("SeriesDescription") or ""),
        phase_encoding_direction=str(sidecar.get("PhaseEncodingDirection") or ""),
        shim_setting=_as_floats(sidecar.get("ShimSetting")),
        total_readout_time=sidecar.get("TotalReadoutTime"),
        effective_echo_spacing=sidecar.get("EffectiveEchoSpacing"),
        multiband_factor=int(multiband) if isinstance(multiband, (int, float)) else None,
        echo_time=sidecar.get("EchoTime"),
        image_type=tuple(str(t) for t in sidecar.get("ImageType", ()) or ()),
        raw=sidecar,
    )


def probe_session(
    # Sequence, not list: this only ever iterates the argument, and `list` is
    # invariant — so a caller holding a plain `list[str]` could not pass it
    # without building a second list to satisfy the annotation.
    series_dirs: Sequence[str | Path],
    container: str | Path | None = None,
    timeout_s: int = _TIMEOUT_S,
) -> ProbeResult:
    """Probe every series in one session with a single dcm2niix call.

    :attr:`ProbeResult.probes` is keyed on each series directory's **name**
    (``Series_7_fieldmap1``) and holds only the series that produced a sidecar. A
    series that yields nothing is absent rather than empty — an empty directory,
    a Phoenix report, or anything else dcm2niix declines is a legitimate miss and
    not a failure.

    Never raises: a missing dcm2niix, a non-zero exit, a timeout or a malformed
    sidecar all return what was read so far. But they are no longer *silent* —
    everything except the malformed sidecar sets :attr:`ProbeResult.failure`, so
    the caller can tell "nothing to say" from "couldn't look" without having to
    know to ask something else first. It used to have to, and in the case that
    found this it would have been told the wrong thing anyway.
    """
    paths = [Path(d) for d in series_dirs]
    if not paths:
        return ProbeResult()
    unavailable = probe_unavailable_reason(container)
    if unavailable:
        return ProbeResult(failure=unavailable)

    probes: dict[str, SeriesProbe] = {}
    with tempfile.TemporaryDirectory(prefix="duckbrain-probe-") as tmp:
        stage, out = Path(tmp) / "stage", Path(tmp) / "out"
        stage.mkdir()
        out.mkdir()

        staged: set[str] = set()
        sources: list[Path] = []
        for series_dir in paths:
            first = _first_file(series_dir)
            if first is None:
                continue
            link = stage / series_dir.name
            try:
                link.symlink_to(first)
            except OSError:
                continue
            staged.add(series_dir.name)
            parent = series_dir.resolve().parent
            if parent not in sources:
                sources.append(parent)
        if not staged:
            return ProbeResult()

        try:
            completed = subprocess.run(
                _command(stage, out, container, sources),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(failure=f"dcm2niix did not finish within {timeout_s}s")
        except (OSError, subprocess.SubprocessError) as exc:
            return ProbeResult(failure=f"dcm2niix could not be run: {exc}")

        # Map each sidecar back by longest matching staged name: dcm2niix may
        # have appended '_e2_ph' or similar, and a plain equality test would
        # then drop exactly the gradient-echo fieldmaps this exists to check.
        for sidecar_path in sorted(out.glob("*.json")):
            stem = sidecar_path.stem
            match = max(
                (name for name in staged if stem == name or stem.startswith(name + _SUFFIX_HINT)),
                key=len,
                default="",
            )
            if not match or match in probes:
                continue
            try:
                probes[match] = _to_probe(json.loads(sidecar_path.read_text()))
            except (OSError, ValueError):
                continue

    # Outside the `with`, and deliberately after the parse: a non-zero exit does
    # not mean nothing was read, so report both rather than discarding whichever
    # is inconvenient.
    return ProbeResult(probes=probes, failure=_exit_failure(completed))
