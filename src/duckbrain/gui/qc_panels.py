"""Reusable QC review panels, and the whole body of every QC page.

Lives here rather than in a page because a page is a Streamlit script that no
test imports — logic put there is logic nothing covers, which is the whole
reason ``core/qc.py`` was once the only untested module in ``core/``. A module
can be driven by ``AppTest.from_function``, exactly as
``tests/test_gui_components.py`` drives ``directory_picker``.

The QC pages are therefore *declarations*, not scripts: the Overview calls
:func:`render_overview`, the Inspect page :func:`render_inspection_page`.
Anything more in a page file is untested statements, against a coverage gate
that is a ratchet.

What is here is the *rendering* of an already-decided thing. Which measures and
figures a domain covers is ``core.qc_domains``; where the figures are on disk is
``core.qc_evidence``; what a measure means is ``core.qc_guidance``. This decides
only how they are put on screen.

**Scope travels through session state, with query parameters as the bookmark
channel** — not the reverse. Treating the URL as the live store makes a widget
write back what it just read, and the app oscillates. So the URL seeds the
session once on arrival, session state is the truth thereafter, and the URL is
rewritten to match so a link to one run's inspection can be sent to someone.
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
    from ..core.qc_report import RunRow


def _size_note(nbytes: int, n_files: int) -> str:
    """Name the cost before it is spent, in the unit a reader thinks in."""
    plural = "figure" if n_files == 1 else "figures"
    return f"{n_files} {plural} · {nbytes / 1e6:.1f} MB, loaded only when shown"


#: Inside a figure iframe: fill the frame's width and let the SVG keep the
#: aspect ratio its ``viewBox`` declares; ``st.iframe``'s default
#: ``height="content"`` then measures the result.
_SVG_FIGURE_STYLE = "<style>body{margin:0}svg{display:block;width:100%;height:auto}</style>"


def _show_figure(path: Path, label: str) -> None:
    """Render one figure the way its own stylesheet demands.

    fMRIPrep's before/after reportlets — SDC, BOLD-to-T1w and fieldmap
    coregistration, spatial normalization — ship with their flicker *paused*:
    the embedded CSS declares ``animation … paused`` and flips
    ``animation-play-state`` to ``running`` on ``:hover``. An SVG inside an
    ``<img>`` is rendered as a static image that can never be hovered, so behind
    ``st.image`` those figures sat frozen on the "before" frame and read as "no
    correction applied" — the exact misreading their ``look_for`` warns about.
    This is the same fact ``core.report_embed``'s docstring records about why
    fMRIPrep itself embeds these as ``<object>``, not ``<img>``.

    So a figure whose own CSS asks for ``:hover`` goes into an iframe, where it
    is a real document and the browser delivers the hover. Everything else stays
    ``st.image``, whose data URI has no URL for OnDemand's proxy to get wrong.
    Both halves are pinned by ``tests/test_qc_panels.py``
    (``test_a_hover_gated_figure_is_shipped_as_a_document`` and
    ``test_a_static_figure_stays_a_self_contained_image``).
    """
    if path.suffix.lower() == ".svg":
        svg = path.read_text(encoding="utf-8", errors="replace")
        if ":hover" in svg:
            st.iframe(_SVG_FIGURE_STYLE + svg)
            if label:
                st.caption(label)
            return
    st.image(str(path), caption=label or None, width="stretch")


def evidence_viewer(
    fmriprep_dir: Path | str,
    domain: ReviewDomain,
    run_key: str,
    *,
    modality: str = "bold",
    key_prefix: str = "",
    default_open: bool = False,
) -> int:
    """Show the fMRIPrep figures *domain* is reviewed through. Returns how many.

    Each figure sits behind its own toggle with its size named first, because
    these are megabyte-scale SVGs and the reviewer should choose knowingly which
    to load. That is the same courtesy the whole-report panel extended, at
    1.1 MB per figure instead of 80 MB per subject. ``default_open`` flips the
    toggles on to begin with — the inspector page wants the evidence visible on
    arrival, since looking at it *is* that page's purpose — while the toggle
    stays as the way to put a figure away.

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
        if not st.toggle(f"Show {fig.label}", key=widget_key, value=default_open):
            continue

        st.markdown(f"*Look for:* {fig.look_for}")
        for path in hit.paths:
            try:
                _show_figure(path, hit.label_for(path))
            except Exception as exc:
                st.warning(f"Could not render `{path.name}` — {exc}")
    return shown


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
    runs: list[RunRow]
    run: RunRow | None
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

    def values_for(self, measure: str) -> list[float | None]:
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
def _load_metrics(mriqc_dir: str, modality: str, fingerprint: tuple[int, float]) -> pd.DataFrame:
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


def _fingerprint_of(root: Path, pattern: str) -> tuple[int, float]:
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
    iqm_cols = qc.iqm_columns(modality)
    iqr_multiplier = float(st.session_state.get("qc_iqr", settings["iqr_multiplier"]))
    runs: list[RunRow] = []

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


def load_config_or_stop() -> Config:
    """The config every QC page needs, or a message and a stop."""
    from duckbrain.config import load_config

    try:
        return load_config()
    except FileNotFoundError:
        st.error("Configuration not found. Please complete **Project Setup** first.")
        st.stop()


# ---------------------------------------------------------------------------
# The numbers, for one run
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


# ---------------------------------------------------------------------------
# The inspector: one run, every domain at once
# ---------------------------------------------------------------------------


def measure_glossary(measures: list[str]) -> None:
    """Every shown measure's guidance, as one glossary at the foot of the page.

    The inspector puts all domains' numbers in one table, so per-measure
    expanders beside it would be thirty click targets each hiding one
    paragraph — reviewer feedback (2026-08-17) called that detached and
    awkward. Per-cell mouseover is not something ``st.dataframe`` offers, so
    the definitions live here instead, label leading in bold so the eye can
    index this list the way it indexes the table above.
    """
    for g in qc_guidance.guidance_for_keys(measures):
        head = f"**{g.label}** ({g.direction_label}"
        if g.units:
            head += f", {g.units}"
        body = f"{head}) — {g.why} *Look for:* {g.look_for} *Flagged when:* {g.auto_flag}"
        if g.literature_threshold:
            body += f" *A priori thresholds:* {g.literature_threshold}"
        if g.caveats:
            body += f" *Caveats:* {g.caveats}"
        st.markdown(body)
        for ref in g.references:
            st.caption(f"[{ref.label}]({ref.url}) — {ref.detail}. {ref.note}")


def _legacy_aspect_note(record: qc.DecisionRecord | None) -> None:
    """Aspect reviews recorded under the five-page layout, shown read-only.

    The decision files are append-only, so per-domain entries written before
    the inspector replaced the domain pages are still on disk and still load.
    They are shown rather than hidden — a reviewer's recorded look at a run
    does not stop having happened because the interface moved on — but nothing
    writes new ones.
    """
    domains = record["domains"] if record else {}
    parts = []
    for key, dom in domains.items():
        if not dom.get("signed_off"):
            continue
        latest = dom.get("latest") or {}
        try:
            label = qc_domains.get_domain(key).label
        except KeyError:
            label = key
        parts.append(
            f"{label}: **{latest.get('decision')}** "
            f"({latest.get('reviewer')}, {latest.get('timestamp', '')[:10]})"
        )
    if parts:
        st.caption(
            "Aspect reviews recorded under the previous per-aspect layout, "
            "kept for the record — " + " · ".join(parts)
        )


def run_signoff(scope: Scope) -> None:
    """Who is signing, what has been signed before, and the verdict buttons.

    The one review interface a run has: recording a keep/exclude/investigate
    verdict *is* the sign-off. The per-aspect reviewed/concerns states that
    used to sit under each domain page are gone from the UI — four states per
    run across a 65-run project was the clicking the feedback objected to —
    though everything previously recorded stays readable via
    :func:`_legacy_aspect_note`.
    """
    import getpass

    if not scope.run:
        return
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


def render_inspection_page() -> None:
    """The whole body of the inspection page: one run, every domain at once.

    This page replaces the four per-domain pages. Reviewer feedback
    (2026-08-17): four sign-offs per run slowed review to no benefit, and two
    of the domain pages carried only a few numbers each. The domain taxonomy
    still structures the page — it orders the table, sections the evidence and
    groups the glossary — it just no longer costs a navigation to cross.
    """
    # A verdict recorded on the previous run confirms itself here; see
    # `components.queue_toast` for why it cannot confirm itself at the call site.
    flush_toasts()
    st.title("Inspect a run")

    config = load_config_or_stop()
    scope = scope_bar(config)
    if scope is None:
        return
    if not scope.run_key:
        st.info("Pick a run above to review it.")
        return

    all_measures = [m for d in qc_domains.DOMAINS for m in d.measures_for(scope.modality)]

    st.subheader("Numbers at a glance")
    if scope.run and all_measures:
        measure_table(scope, all_measures)
        # A domain-wide caveat is about reading its numbers, so it belongs with
        # the table rather than down in the glossary a reader may not reach.
        for domain in qc_domains.DOMAINS:
            if domain.caveat and domain.measures_for(scope.modality):
                st.caption(f"**{domain.label}:** {domain.caveat}")
    # A domain with neither numbers nor figures for this modality still says
    # why — a silently absent section reads as a section that failed to load.
    for domain in qc_domains.DOMAINS:
        if not domain.measures_for(scope.modality) and not domain.evidence_for(scope.modality):
            st.caption(f"**{domain.label}:** {domain.explain_absence(scope.modality)}")
    else:
        st.caption(
            "The measures need MRIQC — run it from **Preprocessing**. The figures below do not."
        )

    st.subheader("Evidence")
    for domain in qc_domains.DOMAINS:
        if not domain.evidence_for(scope.modality):
            continue
        st.markdown(f"**{domain.label}** — {domain.question}")
        evidence_viewer(
            scope.fmriprep_dir,
            domain,
            scope.run_key,
            modality=scope.modality,
            default_open=True,
        )

    with st.expander("Open the tool's own report"):
        full_report_panel(
            scope.mriqc_dir, scope.fmriprep_dir, scope.run_key, modality=scope.modality
        )

    if scope.run:
        st.divider()
        st.subheader(f"Review {scope.run_key}")
        record = qc.load_decisions(scope.decisions_read_dirs).get(scope.run_key)
        verdict = (record.get("latest") or {}).get("decision") if record else None
        st.caption(f"verdict: **{verdict}**" if verdict else "no verdict recorded")
        _legacy_aspect_note(record)
        run_signoff(scope)

    st.divider()
    st.subheader("Glossary")
    measure_glossary(all_measures)
    _page_link("pages/5_QC_Overview.py", "Back to the Overview", icon="⬅️")


# ---------------------------------------------------------------------------
# The overview: the cohort, and where the verdict is recorded
# ---------------------------------------------------------------------------


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


def _switch_page(path: str, label: str) -> None:
    """Best-effort ``st.switch_page``, degrading like :func:`_page_link` does.

    ``st.switch_page`` needs the ``st.navigation`` registry too, so outside the
    app — every page test, every standalone debug run — it raises rather than
    navigates. The caption names where the click would have gone.
    """
    try:
        st.switch_page(path)
    except Exception:
        st.caption(label)


def _selection_rows(event: Any) -> list[int]:
    """The selected row indices out of a ``st.dataframe`` selection event.

    Defensive because the return shape is Streamlit's, not ours: outside a
    session (``AppTest``) the call returns the element rather than a selection
    state, and a missing attribute must read as "nothing selected", not crash
    the overview.
    """
    try:
        return list(event.selection.rows)
    except Exception:
        return []


def clicked_run_key(runs: list[RunRow], rows: list[int]) -> str:
    """The run key behind a table row selection, or ``""`` when there is none.

    Pure on purpose: ``AppTest`` models a dataframe as an element with no
    ``select_row``, so the click itself can only be eyeballed (``TODO.md``
    ``#30``) — this mapping is the part a test can hold.
    """
    if not rows:
        return ""
    index = rows[0]
    if 0 <= index < len(runs):
        return str(runs[index]["run_key"])
    return ""


def _selection_points(event: Any) -> list[dict[str, Any]]:
    """The selected points out of a ``st.plotly_chart`` selection event.

    Defensive for the same reason :func:`_selection_rows` is: the return shape
    is Streamlit's, and outside a session the call returns the element rather
    than a selection state.
    """
    try:
        return [dict(p) for p in event.selection.points]
    except Exception:
        return []


def clicked_point_run_key(points: list[dict[str, Any]]) -> str:
    """The run key a clicked chart point carries, or ``""`` when there is none.

    The strips' scatter points carry their run key in ``customdata`` (see
    ``core.qc_report.build_iqm_figure``); Streamlit hands it back either bare or
    wrapped in a one-element list depending on how the trace declared it, so
    both shapes are read. A point without one — the box trace, a stray
    selection — reads as no click, exactly as :func:`clicked_run_key` treats a
    stale row index.
    """
    for point in points:
        data = point.get("customdata")
        if isinstance(data, str) and data:
            return data
        if isinstance(data, (list, tuple)) and data and isinstance(data[0], str) and data[0]:
            return str(data[0])
    return ""


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
def _payload_bytes_cached(report_path: str, fingerprint: tuple[float, int]) -> int:
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
    """The whole body of the QC overview page: the cohort, scanned at a glance.

    Cohort-level only, since the rework that gave each run its own inspection
    page: no run dropdown, no verdict buttons, no per-run report. The table is
    the worklist — a click on a row opens that run on the Inspect page, which is
    where everything per-run now lives.
    """
    flush_toasts()  # as in render_inspection_page
    st.title("QC Overview")

    config = load_config_or_stop()
    scope = scope_bar(config, with_run=False)
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
        "cutoff — a flag means unusual here, not bad. Click a row to open that "
        "run on the Inspect page."
    )
    rows: list[dict[str, Any]] = []
    for r in scope.runs:
        row: dict[str, Any] = {
            "Run": r["run_key"],
            "Decision": r["decision"] or "pending",
        }
        # At-a-glance columns for a group-level scan (reviewer request,
        # 2026-08-17). The motion pair and tSNR are BOLD-only facts, so anat
        # tables carry just the flag count rather than three empty columns.
        if scope.modality == "bold":
            row["Mean FD"] = (r.get("motion") or {}).get("mean_fd")
            row["% high motion"] = r["iqms"].get("fd_perc")
            row["tSNR"] = r["iqms"].get("tsnr")
        row["Flags"] = len(r["flagged_metrics"])
        row["Reviewer"] = r["reviewer"]
        rows.append(row)
    event = st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        key="qc_overview_runs",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Mean FD": st.column_config.NumberColumn(
                format="%.3f",
                help="Mean framewise displacement (mm) — the standard motion summary.",
            ),
            "% high motion": st.column_config.NumberColumn(
                format="%.1f%%",
                help="Share of frames moving more than MRIQC's 0.2 mm FD threshold.",
            ),
            "tSNR": st.column_config.NumberColumn(
                format="%.1f", help="Temporal signal-to-noise ratio."
            ),
            "Flags": st.column_config.NumberColumn(
                help=(
                    "How many of this run's measures sit outside the IQR fence "
                    "for this dataset. Which ones, and why they matter, is on "
                    "the Inspect page."
                ),
            ),
        },
    )
    clicked = clicked_run_key(scope.runs, _selection_rows(event))
    if clicked:
        _open_in_inspector(clicked, scope.modality)

    if scope.runs:
        _iqm_strips(scope)
        _export_panel(scope)


def _open_in_inspector(run_key: str, modality: str) -> None:
    """Hand *run_key* to the Inspect page through session state.

    The same channel the inspector's Run selectbox reads, so however a run is
    arrived at — a table row, a chart point, the dropdown itself — the ways
    cannot disagree about what is selected.
    """
    st.session_state["qc_run"] = run_key
    st.session_state["qc_modality"] = modality
    _switch_page("pages/5a_QC_Inspect.py", f"Open **{run_key}** on the Inspect page.")


def _iqm_strips(scope: Scope) -> None:
    """The exported dashboard's IQR strip plots, live under the run table.

    Same figure the export ships (``core.qc_report.build_iqm_figure`` — one
    builder, two delivery paths), rendered natively so a reviewer scanning the
    cohort sees the distributions without exporting anything. Cheap where the
    export panel is not: ``st.plotly_chart`` ships figure data against
    Streamlit's own plotly bundle, not the ~5 MB inline copy the export inlines.

    A clicked point opens its run on the Inspect page through the same channel
    as the table's row-click; the widget's selection state is dropped whenever
    a page render omits the chart, which is what keeps the click from re-firing
    on the way back — the mechanism the row-click already proved live.
    """
    fig = qc_report.build_iqm_figure(scope.runs, scope.iqm_cols, scope.modality)
    if fig is None:
        return
    st.subheader("Distributions")
    st.caption(
        "Every measure across the runs shown, grouped by subject — the boxes "
        "are the IQR the outlier fence is computed from, and ✗ marks a flagged "
        "run. Click a point to open that run on the Inspect page."
    )
    event = st.plotly_chart(
        fig,
        width="stretch",
        key="qc_overview_strips",
        on_select="rerun",
        selection_mode="points",
    )
    clicked = clicked_point_run_key(_selection_points(event))
    if clicked:
        _open_in_inspector(clicked, scope.modality)
