"""The Conversion page's dcm2niix probe: caching it, and reporting when it didn't run.

Lives here rather than in the page for the reason ``qc_panels`` does — a page is
a Streamlit script no test imports, so logic put there is logic nothing covers.

Two things the page needs and shouldn't have to know about:

**Caching.** The probe costs 0.15 s warm and 0.7 s cold per session. That is
fine once and not fine on every Streamlit rerun, and a rerun happens on every
widget touch. So it is keyed on what would change the answer.

**Honesty about absence.** ``probe_session`` returns ``{}`` for "ran and read
nothing" and for "couldn't look", and those must not render the same way. The
runtime is resolved *first* (:func:`~duckbrain.core.dcm2niix_probe.probe_runtime`)
so the page can say which happened.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# The module, not its members: tests patch ``dcm2niix_probe.probe_session`` to
# keep the suite off whatever dcm2niix happens to be on the developer's PATH,
# and a from-import would bind the real one here at import time.
from duckbrain.core import dcm2niix_probe
from duckbrain.core.dcm2niix_probe import ProbeRuntime, SeriesProbe

# Anything slower than a second is already pathological for a single session,
# and this runs inline in a page render. The module default (120 s) would stall
# the GUI for two minutes on a hung apptainer with no way to say why.
_TIMEOUT_S = 10


def probe_fingerprint(series_list: list, container: Path | None) -> tuple:
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
    image: tuple = ("", 0.0, 0)
    if container:
        try:
            stat = Path(container).stat()
            image = (str(container), stat.st_mtime, stat.st_size)
        except OSError:
            image = (str(container), 0.0, 0)
    return (series, image)


@st.cache_data(show_spinner="Asking dcm2niix what these series are…")
def _probe_cached(
    series_dirs: list[str], container: str, fingerprint: tuple
) -> dict[int, SeriesProbe]:
    """Probe one session, keyed as ``plan_warnings`` wants it.

    ``fingerprint`` has **no leading underscore, and that is load-bearing**.
    Streamlit deliberately excludes underscore-prefixed arguments from the cache
    key (``runtime/caching/cache_utils.py``: "Underscore-prefixed args are
    deliberately excluded from hashing"), so naming it ``_fingerprint`` — as
    ``qc_panels._load_metrics`` does — would key this on the paths alone and it
    would never invalidate. It is a cache key, so it has to be hashed.
    """
    return dcm2niix_probe.by_series_number(
        dcm2niix_probe.probe_session(series_dirs, container or None, timeout_s=_TIMEOUT_S)
    )


def session_probes(series_list: list, runtime: ProbeRuntime) -> dict[int, SeriesProbe]:
    """What dcm2niix says about this session, or ``{}`` when it couldn't be asked.

    An empty result is ambiguous by design — it is also what a timeout, an exec
    failure or a session of empty directories produces — so the caller must have
    *runtime* in hand and report from that, not from the emptiness of this.
    """
    if not runtime.available:
        return {}
    dirs = [str(s.path) for s in series_list if s.path]
    if not dirs:
        return {}
    return _probe_cached(
        dirs,
        str(runtime.container or ""),
        probe_fingerprint(series_list, runtime.container),
    )


def probe_note(runtime: ProbeRuntime, probes: dict) -> str:
    """One line for the preflight panel, or ``""`` when there is nothing to add.

    Prefixed with the severity marker the caption should carry. Gating on
    *probes* rather than ``runtime.available`` is the point: a runtime can be
    perfectly available and still return nothing, and a panel that says "checked"
    because the binary existed is the failure this whole item exists to prevent.
    """
    if not probes:
        reason = runtime.reason or "dcm2niix ran but read none of these series"
        return f"⚠️ Phase encoding was not checked: {reason}."
    if runtime.fallback:
        return (
            "ℹ️ Phase encoding was read with a host `dcm2niix` rather than the "
            f"pinned dcm2bids image ({runtime.fallback}), so it may not be the "
            "build that converts."
        )
    return ""
