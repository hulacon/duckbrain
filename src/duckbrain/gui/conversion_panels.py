"""The Conversion page's dcm2niix probe: caching it, and reporting when it didn't run.

Lives here rather than in the page for the reason ``qc_panels`` does — a page is
a Streamlit script no test imports, so logic put there is logic nothing covers.

Two things the page needs and shouldn't have to know about:

**Caching.** The probe costs 0.15 s warm and 0.7 s cold per session. That is
fine once and not fine on every Streamlit rerun, and a rerun happens on every
widget touch. So it is keyed on what would change the answer.

**Honesty about absence.** "Ran and read nothing" and "couldn't look" must not
render the same way. Two things separate them, because there are two ways to be
unable to look: the runtime is resolved *first*
(:func:`~duckbrain.core.dcm2niix_probe.probe_runtime`), which answers whether
there was anything to run, and the probe reports its own exit
(:class:`~duckbrain.core.dcm2niix_probe.ProbeResult`), which answers whether
running it worked. Only the first of those existed at first, and a dcm2niix
that ran and exited 1 came back as an empty map and read as a clean session;
``tests/test_conversion_panels.py`` pins both halves of the caption.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import streamlit as st

# The module, not its members: tests patch ``dcm2niix_probe.probe_session`` to
# keep the suite off whatever dcm2niix happens to be on the developer's PATH,
# and a from-import would bind the real one here at import time.
from duckbrain.core import dcm2niix_probe
from duckbrain.core.dcm2niix_probe import ProbeResult, ProbeRuntime

if TYPE_CHECKING:
    from duckbrain.core.dicom_inspect import SeriesInfo

#: What ``probe_fingerprint`` returns and ``_probe_cached`` keys on: the series
#: names and file counts, plus the image's ``(path, mtime, size)``. Written out
#: rather than left a bare ``tuple`` because Streamlit hashes it as the cache
#: key — a shape that quietly changed here is a cache that quietly never
#: invalidates, which is the failure `#29` was.
ProbeFingerprint = tuple[tuple[tuple[str, int], ...], tuple[str, float, int]]

# Anything slower than a second is already pathological for a single session,
# and this runs inline in a page render. The module default (120 s) would stall
# the GUI for two minutes on a hung apptainer with no way to say why.
_TIMEOUT_S = 10


def probe_fingerprint(series_list: list[SeriesInfo], container: Path | None) -> ProbeFingerprint:
    """What has to change before the cached probe is stale.

    Deliberately *not* an rglob of the session directory: that stats ~2000 files
    on GPFS and costs more than the 0.15 s probe it would be protecting.
    ``list_series`` already counted every series, so the series names and their
    file counts are free and move whenever the input does.

    The image joins the key for the reason ``core.containers`` keys on
    ``(path, mtime, size)``: a rebuilt image at the same path is a different
    dcm2niix, and must re-probe rather than serve the previous build's answer.
    """
    series = tuple(sorted((Path(s.path).name if s.path else "", s.file_count) for s in series_list))
    image: tuple[str, float, int] = ("", 0.0, 0)
    if container:
        try:
            stat = Path(container).stat()
            image = (str(container), stat.st_mtime, stat.st_size)
        except OSError:
            image = (str(container), 0.0, 0)
    return (series, image)


@st.cache_data(show_spinner="Asking dcm2niix what these series are…")
def _probe_cached(
    series_dirs: list[str], container: str, fingerprint: ProbeFingerprint
) -> ProbeResult:
    """Probe one session, cached on what would change the answer.

    ``fingerprint`` has **no leading underscore, and that is load-bearing**:
    Streamlit excludes underscore-prefixed arguments from the cache key, so this
    would key on the paths alone and never invalidate. The rule, why the
    convention exists, and its one escape hatch are in
    ``tests/test_streamlit_caches.py``, which enforces it over every cache here.

    Caches the whole :class:`ProbeResult` rather than the numbered map, so a
    rerun that hits the cache re-renders the *same* honesty about what happened,
    not a clean panel over a remembered empty map.
    """
    return dcm2niix_probe.probe_session(series_dirs, container or None, timeout_s=_TIMEOUT_S)


def session_probes(series_list: list[SeriesInfo], runtime: ProbeRuntime) -> ProbeResult:
    """What dcm2niix says about this session, and whether it got to say it.

    Emptiness alone stays ambiguous — a session of empty directories reads the
    same as a probe that never ran — so this returns the result object rather
    than its map, and carries ``runtime.reason`` into it when there was nothing
    runnable to begin with. That is the one failure the probe itself cannot
    report, because it is never called.
    """
    if not runtime.available:
        return ProbeResult(failure=runtime.reason)
    dirs = [str(s.path) for s in series_list if s.path]
    if not dirs:
        return ProbeResult()
    return _probe_cached(
        dirs,
        str(runtime.container or ""),
        probe_fingerprint(series_list, runtime.container),
    )


def probe_note(runtime: ProbeRuntime, result: ProbeResult) -> str:
    """One line for the preflight panel, or ``""`` when there is nothing to add.

    Prefixed with the severity marker the caption should carry. Gating on the
    *result* rather than ``runtime.available`` is the point: a runtime can be
    perfectly available and the probe still fail or read nothing, and a panel
    that says "checked" because the binary existed is the failure this whole
    feature exists to prevent.
    """
    if result.failure:
        return f"⚠️ Phase encoding was not checked: {result.failure}."
    if not result.probes:
        return "⚠️ Phase encoding was not checked: dcm2niix ran but read none of these series."
    if runtime.fallback:
        return (
            "ℹ️ Phase encoding was read with a host `dcm2niix` rather than the "
            f"pinned dcm2bids image ({runtime.fallback}), so it may not be the "
            "build that converts."
        )
    return ""
