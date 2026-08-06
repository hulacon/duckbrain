"""Reusable QC review panels, and the whole body of every QC page.

Lives here rather than in a page because a page is a Streamlit script that no
test imports — logic put there is logic nothing covers, which is the whole
reason ``core/qc.py`` was once the only untested module in ``core/``. A module
can be driven by ``AppTest.from_function``, exactly as
``tests/test_gui_components.py`` drives ``directory_picker``.

The QC pages are therefore *declarations*, not scripts: each one says which
domain it is and calls :func:`render_domain_page`. Splitting one page into five
would otherwise have multiplied untested statements fivefold, against a coverage
gate that is a ratchet.

What is here is the *rendering* of an already-decided thing. Which measures and
figures a domain covers is ``core.qc_domains``; where the figures are on disk is
``core.qc_evidence``; what a measure means is ``core.qc_guidance``. This decides
only how they are put on screen.

**Scope travels through session state, with query parameters as the bookmark
channel** — not the reverse. Treating the URL as the live store makes a widget
write back what it just read, and the app oscillates. So the URL seeds the
session once on arrival, session state is the truth thereafter, and the URL is
rewritten to match so a link to one run's alignment review can be sent to someone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import streamlit as st

from duckbrain.core import qc, qc_domains, qc_evidence, qc_guidance, qc_report
from duckbrain.core.qc_domains import ReviewDomain
from duckbrain.gui.components import flush_toasts, queue_toast

if TYPE_CHECKING:
    from ..config import Config


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


# ---------------------------------------------------------------------------
# Scope: what the reviewer is looking at, shared across the QC pages
# ---------------------------------------------------------------------------

#: Session keys holding the selection, and the URL parameter each maps to.
_SCOPE_PARAMS = {"qc_modality": "modality", "qc_run": "run"}
_SEEDED = "_qc_scope_seeded"

MODALITIES = ("bold", "T1w", "T2w")


@dataclass(frozen=True)
class Scope:
    """One reviewer's current selection, plus everything derived from it.

    Assembled once per page render by :func:`scope_bar` so the five QC pages
    agree about what is being looked at without each rebuilding it.

    The fields are spelled out because this used to be
    ``def __init__(self, **kwargs): self.__dict__.update(kwargs)``, and a bag
    that accepts anything documents nothing: the only way to learn what a
    ``Scope`` carries was to read all of ``scope_bar`` and every reader of it at
    once. Two things fell out of writing them down. ``run_key`` reached
    ``selected_key`` through ``getattr(self, ..., "")``, a default for an
    attribute that is in fact always assembled — so the fallback was dead and
    could only ever have masked a typo. And ``metrics_df`` was passed in and
    read by nobody: ``runs`` is what the table is built from, and the frame it
    came from has been dead weight since. Both are the kind of thing a declared
    field makes visible and a kwargs bag cannot.

    Frozen because it is one render's answer to "what is being looked at". A
    later panel that wanted to change the selection would be writing to a value
    the panels above it already rendered from.
    """

    config: Config
    modality: str
    iqm_cols: list[str]
    runs: list[dict]
    run: dict | None
    selected_key: str
    mriqc_dir: Path
    fmriprep_dir: Path
    decisions_dir: Path
    decisions_read_dirs: list[Path]
    settings: dict[str, float]
    iqr_multiplier: float
    motion_status: tuple[str, str]

    @property
    def run_key(self) -> str:
        """The selected run, whether or not MRIQC produced a row for it.

        Not read off ``run``: when MRIQC has not been run there are no rows, but
        there is still a run to look at fMRIPrep's figures for.
        """
        return self.selected_key or (self.run["run_key"] if self.run else "")

    def values_for(self, measure: str) -> list:
        """Every run's value for *measure* — the cohort this run is judged against."""
        return [r["iqms"].get(measure, (r.get("motion") or {}).get(measure)) for r in self.runs]


def _seed_scope_from_url() -> None:
    """Copy URL parameters into session state, once, on first arrival.

    Once only, and that matters: doing it every rerun would overwrite the
    reviewer's next click with the URL that click has not yet updated.
    """
    if st.session_state.get(_SEEDED):
        return
    for key, param in _SCOPE_PARAMS.items():
        value = st.query_params.get(param)
        if value:
            st.session_state[key] = value
    st.session_state[_SEEDED] = True


def _publish_scope_to_url(**values: str) -> None:
    """Rewrite the URL to match the selection, so the page can be linked to.

    Only on a real change: assigning unconditionally rewrites the URL on every
    rerun for no benefit.
    """
    for key, value in values.items():
        param = _SCOPE_PARAMS[key]
        if value and st.query_params.get(param) != value:
            st.query_params[param] = value


def _pick(label: str, options: list[str], session_key: str, **kwargs: Any) -> str:
    """A selectbox that remembers across pages, defaulting to a stale-proof index.

    A remembered value that no longer exists — the modality changed, or the
    derivative did — falls back to the first option rather than raising.

    Empty options give ``""``, not ``None``: every option here is a modality or
    a run key, so the empty string cannot collide with a real selection, and
    both callers already treated the no-selection case as the empty string.
    """
    if not options:
        return ""
    remembered = st.session_state.get(session_key)
    index = options.index(remembered) if remembered in options else 0
    chosen = st.selectbox(label, options, index=index, **kwargs)
    st.session_state[session_key] = chosen
    return str(chosen)


@st.cache_data(show_spinner="Reading MRIQC output…")
def _load_metrics(mriqc_dir: str, modality: str, fingerprint: tuple) -> pd.DataFrame:
    """Cached MRIQC load, keyed on the state of the derivative and not just its path.

    ``fingerprint`` carries no leading underscore, and that is the whole of it:
    Streamlit drops underscore-prefixed arguments from the cache key, so
    ``_fingerprint`` keyed this on ``(mriqc_dir, modality)`` — neither of which
    changes when MRIQC re-runs into the same output directory — and every QC page
    went on showing the previous run's numbers until the server restarted. Pinned
    by ``test_a_rerun_of_mriqc_is_not_served_the_previous_numbers``; the naming
    rule itself is enforced package-wide by ``tests/test_streamlit_caches.py``.
    """
    return qc.load_mriqc_metrics(mriqc_dir, modality)


def _fingerprint_of(root: Path, pattern: str) -> tuple:
    """(count, newest mtime) of matching files — enough to invalidate the cache.

    *pattern* is the loader's own glob, so this is taken over exactly the files
    the cached call reads. The walk is affordable here in a way it is not for
    ``conversion_panels.probe_fingerprint``, which refuses one for a good reason
    that does not apply: ~3 ms warm over `divatten_beta_v2`'s 639-file MRIQC
    tree, against a load of 10 ms warm and 1.4 s cold.
    """
    try:
        stats = [p.stat().st_mtime for p in root.rglob(pattern)]
    except OSError:
        return (0, 0.0)
    return (len(stats), max(stats, default=0.0))


def scope_bar(config: Config, *, with_run: bool = True) -> Scope | None:
    """Render the shared selection controls and return what was selected.

    ``None`` means there is nothing to review and the reason has already been
    said on screen — the caller should stop rather than render an empty page.
    """
    _seed_scope_from_url()

    paths = config.get("paths", {})
    derivatives_dir = paths.get("derivatives_dir", "")
    if not derivatives_dir:
        st.error("Derivatives directory not set. Check **Project Setup**.")
        return None

    mriqc_dir = Path(derivatives_dir) / "mriqc"
    # Two names, and they are not the same thing: decisions are *written* to one
    # place and *read* from everywhere they have ever been written, so a project
    # reviewed before duckbrain gathered its output under one directory — or by
    # mmmdata, which still writes the old location — does not lose its history.
    decisions_read_dirs = qc.decision_search_dirs(config)
    fmriprep_dir = qc_report.resolve_fmriprep_dir(config)
    decisions_dir = qc.decisions_dir(config)
    settings = qc.qc_settings()

    cols = st.columns([1, 2, 1] if with_run else [1, 3])
    with cols[0]:
        modality = _pick("Modality", list(MODALITIES), "qc_modality")

    metrics_df = _load_metrics(
        str(mriqc_dir), modality, _fingerprint_of(mriqc_dir, f"*_{modality}.json")
    )
    iqm_cols = qc.BOLD_IQMS if modality == "bold" else qc.ANAT_IQMS
    iqr_multiplier = float(st.session_state.get("qc_iqr", settings["iqr_multiplier"]))
    runs: list[dict] = []

    if metrics_df.empty:
        # MRIQC has not run, but fMRIPrep may well have. Falling back to the run
        # list in fMRIPrep's own figures keeps the visual review reachable, which
        # stopping here would not: a present derivative would become invisible
        # and the page would say only that MRIQC has not run. That failure has
        # shipped twice, and the old single page guarded against it by ordering
        # the fMRIPrep panel above its own stop.
        st.warning(f"No MRIQC metrics found for **{modality}** in `{mriqc_dir}`.")
        keys = qc_evidence.all_runs_with_figures(fmriprep_dir, modality)
        if not keys:
            st.info("Run MRIQC first from the **Preprocessing** page.")
            return None
        st.caption(
            "Runs below are read from fMRIPrep's own figures instead, so the "
            "visual review still works. The measures need MRIQC — run it from "
            "**Preprocessing** for those."
        )
        flagged: set[str] = set()
    else:
        metrics_df = qc.detect_outliers(
            metrics_df, iqm_columns=iqm_cols, iqr_multiplier=iqr_multiplier
        )
        motion_df = None
        if modality == "bold" and fmriprep_dir.is_dir():
            motion_df = qc.summarize_motion(fmriprep_dir, fd_threshold=settings["fd_threshold"])
        runs = qc_report.build_run_rows(
            metrics_df,
            modality,
            iqm_cols,
            motion_df=motion_df,
            decisions=qc.load_decisions(decisions_read_dirs),
            reports=qc_report.find_mriqc_reports(mriqc_dir, modality),
        )
        keys = [r["run_key"] for r in runs]
        flagged = {r["run_key"] for r in runs if r["is_outlier"]}

    run = None
    run_key = ""
    if with_run:
        with cols[1]:
            chosen = _pick(
                "Run",
                keys,
                "qc_run",
                format_func=lambda k: f"{k}  ⚠️" if k in flagged else k,
                help="The run every section on this page describes.",
            )
        run_key = chosen
        run = next((r for r in runs if r["run_key"] == run_key), None)
        with cols[2]:
            st.metric("Runs", len(keys), f"{len(flagged)} flagged" if flagged else None)
        _publish_scope_to_url(qc_modality=modality, qc_run=run_key)
    else:
        _publish_scope_to_url(qc_modality=modality)

    return Scope(
        config=config,
        modality=modality,
        iqm_cols=iqm_cols,
        runs=runs,
        run=run,
        selected_key=run_key,
        mriqc_dir=mriqc_dir,
        fmriprep_dir=fmriprep_dir,
        decisions_dir=decisions_dir,
        decisions_read_dirs=decisions_read_dirs,
        settings=settings,
        iqr_multiplier=iqr_multiplier,
        motion_status=qc_report.describe_motion_source(fmriprep_dir, runs, modality),
    )


def load_config_or_stop() -> dict:
    """The config every QC page needs, or a message and a stop."""
    from duckbrain.config import load_config

    try:
        return load_config()
    except FileNotFoundError:
        st.error("Configuration not found. Please complete **Project Setup** first.")
        st.stop()


# ---------------------------------------------------------------------------
# A domain, for one run
# ---------------------------------------------------------------------------


def measure_table(scope: Scope, measures: list[str]) -> None:
    """This run's numbers for *measures*, each against the cohort it sits in.

    The position column is the point. Every measure here carries site, scanner
    and protocol batch effects, so a bare value cannot be read on its own — what
    a reviewer needs to know is whether this run is unusual *for this dataset*,
    which is the same comparison the outlier fence makes and the same one the
    guidance says to make by eye.
    """
    run = scope.run
    if not run:
        return
    rows = []
    for key in measures:
        value = run["iqms"].get(key, (run.get("motion") or {}).get(key))
        guidance = qc_guidance.get_guidance(key)
        cohort = scope.values_for(key)
        series = pd.Series(cohort, dtype="float64").dropna()
        rows.append(
            {
                "Measure": guidance.label if guidance else key,
                "Value": value,
                "Cohort median": float(series.median()) if len(series) else None,
                "Position in cohort": qc.cohort_position(cohort, value),
                "Better": guidance.direction_label if guidance else "",
                "Flagged": "⚠️" if key in run["flagged_metrics"] else "",
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Position in cohort": st.column_config.ProgressColumn(
                "Position in cohort",
                help=(
                    "Where this run sits among the runs shown, 0 = lowest value, "
                    "1 = highest. A position, not a verdict — every dataset has a "
                    "lowest run."
                ),
                min_value=0.0,
                max_value=1.0,
                format="%.2f",
            ),
            "Value": st.column_config.NumberColumn(format="%.4f"),
            "Cohort median": st.column_config.NumberColumn(format="%.4f"),
        },
    )


def guidance_expanders(measures: list[str]) -> None:
    """Each measure's guidance, next to the number rather than in a glossary.

    This is the "tethered, not floating" half of the redesign: the reason a
    measure earns a column used to live in one glossary at the bottom of a long
    report, which is far enough away that nobody read it.
    """
    for g in qc_guidance.guidance_for_keys(measures):
        with st.expander(f"{g.label} — {g.direction_label}"):
            if g.units:
                st.caption(f"Units: {g.units}")
            st.markdown(f"**Why it is here.** {g.why}")
            st.markdown(f"**Look for.** {g.look_for}")
            st.markdown(f"**Flagged when.** {g.auto_flag}")
            if g.literature_threshold:
                st.markdown(f"**A priori thresholds.** {g.literature_threshold}")
            if g.caveats:
                st.markdown(f"**Caveats.** {g.caveats}")
            for ref in g.references:
                st.caption(f"[{ref.label}]({ref.url}) — {ref.detail}. {ref.note}")


def render_domain_page(domain_key: str) -> None:
    """The whole body of one domain page.

    The pages are five near-identical declarations of which domain they are, so
    that everything here is exercised by ``AppTest.from_function`` instead of
    living five times over in scripts no test imports.
    """
    # A sign-off recorded on the previous run confirms itself here; see
    # `components.queue_toast` for why it cannot confirm itself at the call site.
    flush_toasts()
    domain = qc_domains.get_domain(domain_key)
    st.title(domain.label)

    config = load_config_or_stop()
    scope = scope_bar(config)
    if scope is None:
        return

    measures = domain.measures_for(scope.modality)
    domain_intro(domain, scope.modality, n_measures=len(measures))

    if not scope.run_key:
        st.info("Pick a run above to review it.")
        return

    # The guidance stands on its own even with no numbers to attach it to, and
    # the figures do not need MRIQC at all — so neither is gated on ``scope.run``,
    # which is absent whenever MRIQC has not run.
    if measures and scope.run:
        measure_table(scope, measures)
    if measures:
        guidance_expanders(measures)

    if domain.evidence_for(scope.modality):
        st.subheader("Evidence")
        evidence_viewer(scope.fmriprep_dir, domain, scope.run_key, modality=scope.modality)

    st.divider()
    domain_signoff(scope, domain)
    _page_link(
        "pages/5_QC_Overview.py",
        "Record a keep/exclude verdict for this run on the Overview",
        icon="⬅️",
    )


def domain_signoff(scope: Scope, domain: ReviewDomain) -> None:
    """Record that this aspect of this run was reviewed.

    Optional, and it gates nothing. Four domains across sixty-five runs is a lot
    of clicking if it were required, and the run's verdict is a separate act that
    must stay reachable without touring four pages first — a reviewer looking at a
    wrecked run should be able to exclude it immediately.

    The note is carried into whichever state is clicked rather than saved on its
    own, for the reason the run-level panel does the same: a typed note that
    records itself becomes a judgement nobody made.
    """
    import getpass

    run_key = scope.run_key
    if not run_key:
        return

    record = qc.load_decisions(scope.decisions_read_dirs).get(run_key, {})
    current = (record.get("domains") or {}).get(domain.key, {})
    latest = current.get("latest") or {}

    st.subheader("Review this aspect")
    if current.get("signed_off"):
        st.caption(
            f"**{latest.get('decision')}** — {latest.get('reviewer')} "
            f"{('· ' + latest['reason']) if latest.get('reason') else ''}"
            f" ({latest.get('timestamp', '')[:10]})"
        )
    else:
        st.caption("Not yet reviewed.")

    reviewer = getpass.getuser()
    note_key = f"note_{domain.key}_{run_key}"
    st.text_input(
        "Note",
        key=note_key,
        value=latest.get("reason", ""),
        help="Saved with whichever state you pick — a note on its own is not a review.",
    )

    def _record(state: str) -> None:
        qc.save_decision(
            scope.decisions_dir,
            run_key,
            state,
            reason=st.session_state.get(note_key, ""),
            reviewer=reviewer,
            domain=domain.key,
        )
        queue_toast(f"{run_key} · {domain.label}: {state}")

    left, right = st.columns(2)
    with left:
        if st.button("Reviewed — no concerns", key=f"rev_{domain.key}_{run_key}", width="stretch"):
            _record("reviewed")
            st.rerun()
    with right:
        if st.button("Reviewed — concerns", key=f"con_{domain.key}_{run_key}", width="stretch"):
            _record("concerns")
            st.rerun()
    st.caption(
        f"Recorded as **{reviewer}**, against this aspect only. It does not give "
        f"the run a keep/exclude verdict — that stays a separate call on the Overview."
    )


# ---------------------------------------------------------------------------
# The overview: the cohort, and where the verdict is recorded
# ---------------------------------------------------------------------------

#: Where each domain's own page lives, for deep links out of the worklist.
DOMAIN_PAGES = {
    "signal": "pages/5a_QC_Signal.py",
    "temporal": "pages/5b_QC_Temporal.py",
    "alignment": "pages/5c_QC_Alignment.py",
    "artifact": "pages/5d_QC_Artifacts.py",
}


def _page_link(path: str, label: str, **kwargs: Any) -> None:
    """A cross-page link that degrades instead of raising outside the app.

    ``st.page_link`` resolves a page path against the set registered by
    ``st.navigation``, so it raises when a page is rendered on its own — which
    is how every page test runs it, and how anyone debugging one page runs it.
    Same best-effort treatment as ``0_Project_Status._deep_links``; a missing
    link is a smaller failure than a page that will not render.
    """
    try:
        st.page_link(path, label=label, **kwargs)
    except Exception:
        st.caption(label)


def domain_links(run_key: str, modality: str) -> None:
    """One link per domain, carrying the selection into that domain's page.

    ``st.page_link`` takes query parameters directly, so this needs no
    ``switch_page`` dance and no pre-navigation session write — and the
    resulting URL is one a reviewer can send to someone else.
    """
    cols = st.columns(len(qc_domains.DOMAINS))
    for col, domain in zip(cols, qc_domains.DOMAINS, strict=True):
        with col:
            _page_link(
                DOMAIN_PAGES[domain.key],
                domain.label,
                query_params={"run": run_key, "modality": modality},
            )


def _fmriprep_report_keys(run_key: str) -> list[str]:
    """The stems an fMRIPrep report for *run_key* could carry, most specific first.

    fMRIPrep keys its reports by subject, or by subject and session when a run
    was preprocessed session-aggregated. A run key names both, so try the longer
    stem first and fall back — matching on ``sub-01`` when ``sub-01_ses-02.html``
    is what exists would hand a reviewer another session's report.
    """
    entities = dict(part.split("-", 1) for part in run_key.split("_") if "-" in part)
    subject = entities.get("sub")
    if not subject:
        return []
    session = entities.get("ses")
    keys = [f"sub-{subject}_ses-{session}"] if session else []
    keys.append(f"sub-{subject}")
    return keys


@st.cache_data(show_spinner=False)
def _payload_bytes_cached(report_path: str, fingerprint: tuple) -> int:
    """What embedding *report_path* would pull in, cached against *fingerprint*.

    The answer costs a read of the report plus a ``stat`` of every figure it
    names, and it is wanted on *every* rerun to label a toggle nobody may click.
    Measured on `divatten_beta_v2`'s fMRIPrep reports (~95 figures each, GPFS):
    55 ms cold, 22 ms warm, per report. Small, but Streamlit reruns the page on
    every click, and two reports are offered — so it is paid over and over for
    a number that only changes when the derivative does.

    ``fingerprint`` has **no leading underscore, and that is load-bearing**:
    Streamlit excludes underscore-prefixed arguments from the cache key, so this
    would key on the path alone and never invalidate. Enforced for every cache in
    the package by ``tests/test_streamlit_caches.py``.
    """
    from duckbrain.core import report_embed

    return report_embed.payload_bytes(Path(report_path))


def full_report_panel(
    mriqc_dir: Path | str,
    fmriprep_dir: Path | str,
    run_key: str,
    *,
    modality: str = "bold",
) -> int:
    """Offer the tools' own reports for this run, whole. Returns how many.

    Everything else on these pages is duckbrain's *reading* of the derivatives:
    the figures a domain is reviewed through, and the numbers beside what they
    mean. This is the document MRIQC and fMRIPrep wrote, and it carries what no
    per-figure view reconstructs — the methods boilerplate a paper has to cite,
    fMRIPrep's About section and its error list, and the report in the order
    nireports chose to argue it. Between the pages replacing the old embedded
    view and now, nothing in duckbrain could reach any of that.

    Behind a toggle that names the cost first, because the cost is *why* it
    stopped being the default view. Streamlit's media manager reads every figure
    into the server's RAM as the page is built, so the spend is real and it is
    not lazy: ~15 MB for an MRIQC T1w report, ~80 MB for an fMRIPrep subject,
    against ~1.1 MB for the single figure the evidence viewer shows. The
    evidence viewer stays the way to review a run; this is the way to read what
    the tool said.
    """
    from duckbrain.gui.components import embed_tool_report

    mriqc_dir, fmriprep_dir = Path(mriqc_dir), Path(fmriprep_dir)
    offered: list[tuple[str, Path]] = []

    name = qc_report.find_mriqc_reports(mriqc_dir, modality).get(run_key)
    if name:
        offered.append(("MRIQC — this run", mriqc_dir / name))

    fmriprep_reports = qc_report.find_fmriprep_reports(fmriprep_dir)
    for key in _fmriprep_report_keys(run_key):
        if key in fmriprep_reports:
            offered.append((f"fMRIPrep — {key}", fmriprep_dir / fmriprep_reports[key]))
            break

    if not offered:
        st.caption(
            "Neither tool has written a report covering this run. MRIQC writes "
            "one per run and fMRIPrep one per subject — run them from "
            "**Preprocessing**."
        )
        return 0

    for label, path in offered:
        try:
            stat = path.stat()
            fingerprint = (stat.st_mtime, stat.st_size)
        except OSError:
            fingerprint = (0.0, 0)
        payload = _payload_bytes_cached(str(path), fingerprint)
        st.caption(f"**{label}** — `{path.name}` · {payload / 1e6:.1f} MB, loaded only when shown")
        if st.toggle(f"Open {label}", key=f"fullreport_{run_key}_{path.name}"):
            embed_tool_report(path)
    return len(offered)


def verdict_panel(scope: Scope, reviewer: str) -> None:
    """Record keep / exclude / investigate for the selected run.

    The reason is carried into whichever verdict is clicked rather than saved on
    its own. Typing a note used to write a decision by itself, defaulting to
    "investigate", so a run the reviewer had only jotted a reminder against
    acquired a verdict they never made.
    """
    run = scope.run
    if not run:
        return
    run_key = run["run_key"]
    st.text_input(
        "Reason",
        key=f"reason_{run_key}",
        value=run["reason"],
        help="Saved with the decision you pick — a note on its own is not a verdict.",
    )

    def _record(verdict: str) -> None:
        qc.save_decision(
            scope.decisions_dir,
            run_key,
            verdict,
            reason=st.session_state.get(f"reason_{run_key}", ""),
            reviewer=reviewer,
        )
        queue_toast(f"{run_key}: {verdict}")

    col1, col2, col3 = st.columns(3)
    for col, verdict, label in (
        (col1, "keep", "Keep"),
        (col2, "exclude", "Exclude"),
        (col3, "investigate", "Investigate"),
    ):
        with col:
            if st.button(label, key=f"{verdict}_{run_key}", width="stretch"):
                _record(verdict)
                st.rerun()


def _export_panel(scope: Scope) -> None:
    """The standalone HTML report, kept working but not developed further.

    The pages are the QC surface now, and the plan to reorganise this document
    by domain was dropped (``TODO.md`` ``#24``, slice B). It still renders and
    still exports, because deleting a working capability is not what punting on
    one means — but it is organised the way it always was, so it and the pages
    disagree about how QC is grouped until someone revisits it.
    """
    with st.expander("Export a standalone HTML report"):
        st.caption(
            "The report as it has always been: one flat table with the glossary "
            "at the end. It is not grouped into the domains these pages use."
        )
        # Built only when asked for. An expander's body runs even while collapsed,
        # and rendering this inlines a ~4.9 MB Plotly bundle — which took the
        # overview from about a second to ten on a 65-run project, on every visit,
        # for a file almost nobody exports.
        if not st.toggle("Prepare the report", key="qc_prepare_export"):
            st.caption("Roughly 5 MB of charts, built on request.")
            return
        html = qc_report.render_report(
            scope.runs,
            scope.modality,
            scope.iqm_cols,
            fd_threshold=scope.settings["fd_threshold"],
            iqr_multiplier=scope.iqr_multiplier,
            project_name=scope.config.get("project", {}).get("name", ""),
            fmriprep_variant=qc_report.fmriprep_input_variant(scope.config),
            motion_status=scope.motion_status,
        )
        filename = qc_report.report_filename(scope.modality)
        left, right = st.columns(2)
        with left:
            st.download_button(
                "Download report", data=html, file_name=filename, mime="text/html", width="stretch"
            )
        with right:
            if st.button("Save to derivatives", width="stretch"):
                derivatives = scope.config.get("paths", {}).get("derivatives_dir", "")
                st.success(f"Wrote `{qc_report.write_report(html, derivatives, filename)}`")


def render_overview() -> None:
    """The whole body of the QC overview page."""
    import getpass

    flush_toasts()  # as in render_domain_page
    st.title("QC Overview")

    config = load_config_or_stop()
    scope = scope_bar(config)
    if scope is None:
        return

    st.slider(
        "IQR multiplier for outlier detection",
        1.0,
        3.0,
        scope.iqr_multiplier,
        0.1,
        key="qc_iqr",
        help=(
            "Flags runs outside a Tukey fence computed across the runs shown — a "
            "comparison within this dataset, not an absolute cutoff. The starting "
            "value comes from [qc].iqr_multiplier."
        ),
    )

    state, sentence = scope.motion_status
    if sentence and state != "complete":
        st.info(sentence)

    st.subheader("Runs")
    st.caption(
        "Every measure is compared within this dataset, never against a fixed "
        "cutoff — a flag means unusual here, not bad."
    )
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Run": r["run_key"],
                    "Decision": r["decision"] or "pending",
                    "Reviewer": r["reviewer"],
                    "Flagged": ", ".join(r["flagged_metrics"]) or "",
                }
                for r in scope.runs
            ]
        ),
        hide_index=True,
        width="stretch",
    )

    if scope.runs:
        _export_panel(scope)

    if not scope.run_key:
        return

    st.subheader(f"Review {scope.run_key}")

    # Shown, never recorded. Reviewing all four domains is not a verdict: the
    # domains do not partition the question a verdict answers — none covers task
    # timing, stimulus delivery, or a participant asleep with their eyes open.
    # So this prompts, and the reviewer still has to make the call.
    record = qc.load_decisions(scope.decisions_read_dirs).get(scope.run_key, {})
    done, total = qc.domain_progress(record, [d.key for d in qc_domains.DOMAINS])
    verdict = (record.get("latest") or {}).get("decision")
    st.caption(
        f"{done}/{total} aspects reviewed · "
        + (f"verdict: **{verdict}**" if verdict else "no verdict recorded")
    )
    domain_links(scope.run_key, scope.modality)

    with st.expander("Open the tool's own report"):
        full_report_panel(
            scope.mriqc_dir, scope.fmriprep_dir, scope.run_key, modality=scope.modality
        )

    if not scope.run:
        return

    st.divider()
    reviewer = getpass.getuser()
    st.caption(f"Signing off as **{reviewer}**, recorded with each decision.")
    counts = qc.decision_counts(qc.load_decisions(scope.decisions_read_dirs))
    if counts["unattributed"]:
        st.warning(
            f"{counts['unattributed']} decision(s) were recorded before duckbrain "
            f"captured a reviewer, so no one can be identified as having made them. "
            f"They are shown as unattributed and do not count as signed off — "
            f"re-record any you still stand behind."
        )
    verdict_panel(scope, reviewer)
