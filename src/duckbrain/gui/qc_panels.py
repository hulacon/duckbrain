"""Reusable QC review panels.

Lives here rather than in a page because a page is a Streamlit script that no
test imports — logic put there is logic nothing covers, which is the whole
reason ``core/qc.py`` was once the only untested module in ``core/``. A module
can be driven by ``AppTest.from_function``, exactly as
``tests/test_gui_components.py`` drives ``directory_picker``.

What is here is the *rendering* of an already-decided thing. Which figures a
domain is reviewed through is ``core.qc_domains``; where they are on disk is
``core.qc_evidence``; this decides only how they are put on screen.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from duckbrain.core import qc_evidence
from duckbrain.core.qc_domains import ReviewDomain


def _size_note(nbytes: int, n_files: int) -> str:
    """Name the cost before it is spent, in the unit a reader thinks in."""
    plural = "figure" if n_files == 1 else "figures"
    return f"{n_files} {plural} · {nbytes / 1e6:.1f} MB, loaded only when shown"


def evidence_viewer(
    fmriprep_dir: Path | str,
    domain: ReviewDomain,
    run_key: str,
    *,
    modality: str = "bold",
    key_prefix: str = "",
) -> int:
    """Show the fMRIPrep figures *domain* is reviewed through. Returns how many.

    Each figure sits behind its own toggle with its size named first, because
    these are megabyte-scale SVGs and the reviewer should choose knowingly which
    to load. That is the same courtesy the whole-report panel extended, at
    1.1 MB per figure instead of 80 MB per subject.

    An absent figure is **reported, not skipped**. For most that reads as "this
    run was not preprocessed"; for the distortion-correction figure it means the
    run was preprocessed with no correction at all, which is a finding a blank
    space would hide.
    """
    hits = qc_evidence.collect(fmriprep_dir, domain, run_key, modality=modality)
    if not hits:
        return 0

    shown = 0
    for hit in hits:
        fig = hit.figure
        widget_key = f"{key_prefix}fig_{domain.key}_{fig.key}"

        if not hit.found:
            st.caption(f"**{fig.label}** — not on disk. {hit.explain_absence()}")
            continue

        shown += 1
        st.caption(f"**{fig.label}** — {_size_note(hit.total_bytes, len(hit.paths))}")
        # Not lower-cased: these labels are full of acronyms, and "bold to t1w
        # coregistration" reads as a mistake rather than as a sentence.
        if not st.toggle(f"Show {fig.label}", key=widget_key):
            continue

        st.markdown(f"*Look for:* {fig.look_for}")
        for path in hit.paths:
            # Streamlit inlines a local SVG as a data URI inside an <img>, which
            # keeps the file's own <style> — and so the before/after flicker that
            # makes a distortion-correction figure readable. It also sidesteps
            # the OnDemand base-path problem entirely, since a data URI has no
            # URL to get wrong.
            label = hit.label_for(path)
            try:
                st.image(str(path), caption=label or None, width="stretch")
            except Exception as exc:
                st.warning(f"Could not render `{path.name}` — {exc}")
    return shown


def domain_intro(domain: ReviewDomain, modality: str, *, n_measures: int) -> None:
    """The domain's question, and — when it has no numbers here — why not.

    A section that renders blank is indistinguishable from one that failed to
    load, so the empty case gets a sentence rather than nothing.
    """
    st.markdown(f"**{domain.question}**")
    if not n_measures:
        st.info(domain.explain_absence(modality))
    if domain.caveat:
        st.caption(domain.caveat)
