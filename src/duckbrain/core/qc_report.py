"""The QC report — one renderer, two delivery paths.

duckbrain is a control panel, and QC is the one surface that is mostly *read*.
Its output is a document: dense tables and charts, worth keeping and worth
sending to someone. MRIQC and fMRIPrep already work this way, emitting
self-contained HTML into ``derivatives/``; a duckbrain QC report belongs beside
them and opens the same way.

So this module renders **one** HTML string, delivered two ways: embedded in the
QC page via ``st.components.v1.html()``, and written to ``derivatives/`` as a
shareable export. The split that matters is read vs. write, not HTML vs.
Streamlit — recording a decision needs a server-side callback that static HTML
cannot do, so that half stays in Streamlit widgets outside the iframe. There is
only ever one renderer to maintain.

Everything here is deliberately free of Streamlit, which is what lets it be
tested at all: the logic used to live in the page, where no test could import it.

**Report links are relative, never ``file://``.** mmmdata's shipped dashboard
carries 837 absolute ``file:///gpfs/...`` links. Those work when the file is
opened from disk and are silently blocked by every browser when the same page is
served over HTTP — which is exactly how OnDemand serves it. The link does not
error; it does nothing at all. A relative path works in both places and survives
the directory being moved or copied off the cluster.
"""

from __future__ import annotations

import html as _html
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from . import qc_guidance

#: Where the report is written, relative to the derivatives directory. Its own
#: directory so the MRIQC-relative links below have a stable number of levels
#: to climb no matter what the report is named.
REPORT_SUBDIR = "duckbrain_qc"

#: Entities that make up a run key, in BIDS order. Kept identical to what
#: ``core.qc.save_decision`` has always written so existing decision files still
#: resolve — an absent entity is omitted rather than emitted empty, because
#: duckbrain supports sessionless projects.
_RUN_KEY_ENTITIES = ("sub", "ses", "task", "run")


def build_run_key(row: pd.Series | dict, modality: str) -> str:
    """Build the BIDS-style run key used to look up a decision.

    Omits entities the row does not carry, so a sessionless project yields
    ``sub-015_task-rest_run-1_bold`` rather than a key with an empty ``ses-``.
    """
    parts = [
        f"{k}-{row[k]}"
        for k in _RUN_KEY_ENTITIES
        if k in row and row[k] is not None and pd.notna(row[k])
    ]
    return "_".join(parts) + f"_{modality}"


def resolve_fmriprep_dir(config: dict) -> Path:
    """Return the fMRIPrep derivatives directory for this project.

    There is exactly one, ``<derivatives>/fmriprep``, whether or not
    ``use_nordic`` is set — ``core.fmriprep`` writes there unconditionally and
    duckbrain never produced the second ``fmriprep_nordic`` tree that mmmdata
    keeps. Which *input* a run used is recorded in the derivative's own
    provenance, not in its path; :func:`fmriprep_input_variant` reads that.

    This function exists so the path is derived in one place rather than
    hardcoded in the page, and so the above is written down where someone would
    otherwise go looking for a NORDIC branch that does not exist.
    """
    return Path(config["paths"]["derivatives_dir"]) / "fmriprep"


def fmriprep_input_variant(config: dict) -> str:
    """What the fMRIPrep derivative was actually built from.

    Returns ``"nordic"``, ``"raw"``, or ``"unknown"`` when there is no
    derivative or it carries no provenance link.

    The reviewer needs this stated. Mean FD off NORDIC-denoised data and mean FD
    off raw data are different numbers describing different images, and with one
    output directory serving both there is nothing in the path to tell them
    apart. Reading the config's ``use_nordic`` instead would report the intent
    rather than the artifact — and those disagreeing is a real, already-detected
    condition (``core.consistency``'s ``config-vs-provenance`` check).
    """
    from .consistency import _links_to_nordic, read_derivative_provenance

    prov = read_derivative_provenance(config, "fmriprep")
    if not prov.exists or not prov.raw_link:
        return "unknown"
    return "nordic" if _links_to_nordic(prov.raw_link) else "raw"


def find_mriqc_reports(mriqc_dir: str | Path, modality: str = "bold") -> dict[str, str]:
    """Map run key → MRIQC HTML filename, for the ones that exist on disk.

    MRIQC writes its per-run reports flat at the top of its output directory.
    Only files that are really there get linked; a missing report yields no
    link rather than a dead one.
    """
    mriqc_dir = Path(mriqc_dir)
    if not mriqc_dir.is_dir():
        return {}

    reports = {}
    for path in sorted(mriqc_dir.glob(f"*_{modality}.html")):
        entities = {}
        for part in path.stem.split("_"):
            if "-" in part:
                key, val = part.split("-", 1)
                entities[key] = val
        if "sub" not in entities:
            continue
        reports[build_run_key(entities, modality)] = path.name
    return reports


def build_run_rows(
    metrics_df: pd.DataFrame,
    modality: str,
    iqm_cols: list[str],
    motion_df: pd.DataFrame | None = None,
    decisions: dict[str, dict] | None = None,
    reports: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Collapse the loaded tables into one row per run, ready to render.

    Takes already-loaded data and returns plain dicts: no filesystem access, no
    Streamlit, no rendering. This is the piece the QC page used to hold inline.
    """
    decisions = decisions or {}
    reports = reports or {}

    motion_by_key: dict[str, dict] = {}
    if motion_df is not None and not motion_df.empty:
        for _, m in motion_df.iterrows():
            motion_by_key[build_run_key(m, modality)] = {
                "mean_fd": _num(m.get("mean_fd")),
                "max_fd": _num(m.get("max_fd")),
                "pct_high_motion": _num(m.get("pct_high_motion")),
            }

    rows = []
    for _, row in metrics_df.iterrows():
        run_key = build_run_key(row, modality)
        iqms = {c: _num(row.get(c)) for c in iqm_cols if c in row}
        flagged = [c for c in iqm_cols if bool(row.get(f"{c}_outlier", False))]
        record = decisions.get(run_key) or {}
        latest = record.get("latest") or {}

        rows.append(
            {
                "run_key": run_key,
                "subject": _text(row.get("sub")),
                "session": _text(row.get("ses")),
                "task": _text(row.get("task")),
                "run": _text(row.get("run")),
                "iqms": iqms,
                "flagged_metrics": flagged,
                "is_outlier": bool(row.get("is_outlier", False)),
                "motion": motion_by_key.get(run_key),
                "decision": latest.get("decision") or "",
                "reviewer": latest.get("reviewer") or "",
                "reason": latest.get("reason") or "",
                "timestamp": latest.get("timestamp") or "",
                "automated": bool(latest.get("automated")),
                "recommendation": latest.get("recommendation") or "",
                "report": reports.get(run_key, ""),
            }
        )
    return rows


def _num(value: Any) -> float | None:
    """Coerce to float, or None. NaN is not a value a reader should be shown."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(out) else out


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value)


def _esc(text: Any) -> str:
    return _html.escape(str(text), quote=True)


def _fmt(value: float | None, spec: str = ".4g") -> str:
    return "" if value is None else format(value, spec)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_report(
    runs: list[dict[str, Any]],
    modality: str,
    iqm_cols: list[str],
    *,
    fd_threshold: float = 0.5,
    iqr_multiplier: float = 1.5,
    subject: str | None = None,
    project_name: str = "",
    fmriprep_variant: str = "unknown",
    report_base: str = "../mriqc",
    generated: datetime | None = None,
) -> str:
    """Render the whole report as one self-contained HTML string.

    Parameters
    ----------
    runs : list of dict
        From :func:`build_run_rows`.
    report_base : str
        Path prefix for MRIQC report links, relative to where this HTML will be
        written. The default assumes ``<derivatives>/duckbrain_qc/``. Never pass
        an absolute path — see the module docstring.
    generated : datetime, optional
        Injected so tests can pin the output; defaults to now.
    """
    stamp = (generated or datetime.now()).strftime("%Y-%m-%d %H:%M")
    scope = f"sub-{subject}" if subject else "All subjects"
    n_total = len(runs)
    n_outliers = sum(1 for r in runs if r["is_outlier"])
    n_signed = sum(1 for r in runs if _is_signed_off(r))
    n_unattributed = sum(1 for r in runs if r["decision"] and not _is_signed_off(r))

    has_motion = modality == "bold" and any(r.get("motion") for r in runs)
    guidance_keys = list(iqm_cols) + (["mean_fd", "pct_high_motion"] if has_motion else [])

    title = f"QC report — {scope} ({modality})"
    meta_bits = [scope, modality, f"Generated {stamp}"]
    if project_name:
        meta_bits.insert(0, project_name)

    motion_section = ""
    if has_motion:
        motion_section = _section(
            "motion-overview", "Motion overview", _render_motion_chart(runs, fd_threshold)
        )
    outlier_section = ""
    if n_outliers:
        outlier_section = _section(
            "outlier-detail", "Outlier detail", _render_outlier_detail(runs, report_base)
        )

    return f"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<script>{_plotly_js()}</script>
{_CSS}
<header>
  <h1>QC report</h1>
  <p class="meta">{" &middot; ".join(_esc(b) for b in meta_bits)}</p>
  <div class="cards">
    <div class="card">{n_total}<span>Runs</span></div>
    <div class="card card-warn">{n_outliers}<span>Outliers</span></div>
    <div class="card card-ok">{n_signed}<span>Signed off</span></div>
    <div class="card">{n_total - n_signed}<span>Pending</span></div>
  </div>
  {_provenance_note(fmriprep_variant, has_motion, iqr_multiplier, n_unattributed)}
</header>

<section id="how-to-review">
  <h2>How to review</h2>
  <p class="section-intro">Read this before making a call. It states what the
  report decides on its own and what it is asking you to judge.</p>
  {qc_guidance.render_process_section()}
</section>

<section id="run-table">
  <h2>Run table</h2>
  {_render_table(runs, iqm_cols, has_motion, report_base)}
</section>

<section id="iqm-distributions">
  <h2>IQM distributions</h2>
  {_render_iqm_charts(runs, iqm_cols, modality, subject)}
</section>

{motion_section}

{outlier_section}

<section id="measure-guidance">
  <h2>Measure guidance</h2>
  <p class="section-intro">One entry per column above: why it is measured, what
  to check by eye, what is flagged without you, and the source of the guidance.
  Most of these measures have no defensible absolute cutoff, and the entry says
  so where that is the case.</p>
  {qc_guidance.render_guidance_section(guidance_keys)}
</section>

{_TABLE_SORT_JS}
"""


def _section(anchor: str, heading: str, body: str) -> str:
    return f'<section id="{anchor}"><h2>{_esc(heading)}</h2>{body}</section>'


def _is_signed_off(run: dict) -> bool:
    """Whether this row is a call a named person made.

    Defers to :func:`core.qc.is_signed_off` so the report and the writer cannot
    drift apart on what counts as a sign-off — there is one rule, and the store
    owns it.
    """
    from .qc import is_signed_off

    return is_signed_off(
        {
            "decision": run.get("decision"),
            "reviewer": run.get("reviewer"),
            "automated": run.get("automated"),
        }
    )


def _provenance_note(
    variant: str, has_motion: bool, iqr_multiplier: float, n_unattributed: int
) -> str:
    """State what produced these numbers and what the counts above mean."""
    bits = [
        f"Outliers are values outside a {iqr_multiplier}&times; IQR fence computed "
        f"across the runs shown — a within-dataset comparison, not an absolute "
        f"threshold. Most IQMs have no defensible absolute cutoff.",
        "&quot;Signed off&quot; counts only decisions carrying a named reviewer.",
    ]
    if n_unattributed:
        bits.append(
            f"<strong>{n_unattributed}</strong> record(s) carry a verdict but no "
            f"reviewer; they are shown as unattributed and counted as pending."
        )
    if has_motion:
        label = {
            "nordic": "NORDIC-denoised data",
            "raw": "raw (non-NORDIC) data",
            "unknown": "data of an unrecorded variant",
        }[variant]
        bits.append(f"Motion columns come from fMRIPrep confounds computed on {label}.")
    return '<p class="meta signoff-note">' + " ".join(bits) + "</p>"


def _render_header_cells(headers: list[str]) -> str:
    """Render ``<th>`` cells, linking any documented measure to its glossary entry.

    The reason a column exists is never more than one click from the number.
    """
    cells = []
    for h in headers:
        g = qc_guidance.get_guidance(h)
        if g is None:
            cells.append(f'<th data-col="{_esc(h)}">{_esc(h)}</th>')
        else:
            cells.append(
                f'<th data-col="{_esc(h)}" class="th-documented" title="{_esc(g.tooltip())}">'
                f'{_esc(h)}<a class="g-marker" href="#guidance-{_esc(h)}" '
                f'aria-label="Guidance for {_esc(h)}">&#9432;</a></th>'
            )
    return "".join(cells)


def _render_table(runs: list[dict], iqm_cols: list[str], has_motion: bool, report_base: str) -> str:
    if not runs:
        return "<p>No runs.</p>"

    headers = ["Subject", "Session", "Task", "Run", "Decision", "Outlier"]
    headers += iqm_cols
    if has_motion:
        headers += ["mean_fd", "pct_high_motion"]
    headers.append("Report")

    body = []
    for r in runs:
        signed = _is_signed_off(r)
        label = r["decision"] if signed else "pending"
        badge = {
            "keep": "badge-keep",
            "exclude": "badge-exclude",
            "investigate": "badge-warn",
            "pending": "badge-pending",
        }.get(label, "badge-pending")

        note = ""
        suffix = ""
        if signed:
            note = f"{r['reviewer']} — {r['reason']} ({r['timestamp']})"
        elif r.get("automated"):
            note = f"Written by automation ({r['reviewer'] or 'unnamed'}) — {r['reason']}"
            if r.get("recommendation") and r["recommendation"] != "pending":
                suffix = f'<span class="auto-suggest">suggests: {_esc(r["recommendation"])}</span>'
        elif r["decision"]:
            note = f"Recorded as '{r['decision']}' with no reviewer — cannot be attributed."
            suffix = f'<span class="auto-suggest">unattributed: {_esc(r["decision"])}</span>'

        cells = [
            f"<td>{_esc(r['subject'])}</td>",
            f"<td>{_esc(r['session'])}</td>",
            f"<td>{_esc(r['task'])}</td>",
            f"<td>{_esc(r['run'])}</td>",
            f'<td><span class="badge {badge}" title="{_esc(note)}">'
            f"{label.upper()}</span>{suffix}</td>",
            f"<td>{'YES' if r['is_outlier'] else ''}</td>",
        ]
        for m in iqm_cols:
            klass = "cell-flagged" if m in r["flagged_metrics"] else ""
            cells.append(f'<td class="{klass}">{_fmt(r["iqms"].get(m))}</td>')
        if has_motion:
            motion = r.get("motion") or {}
            cells.append(f"<td>{_fmt(motion.get('mean_fd'), '.3f')}</td>")
            phm = motion.get("pct_high_motion")
            cells.append(f"<td>{'' if phm is None else f'{phm:.1f}%'}</td>")
        if r["report"]:
            href = f"{report_base}/{r['report']}"
            cells.append(f'<td><a href="{_esc(href)}" target="_blank">View</a></td>')
        else:
            cells.append("<td></td>")

        klass = ("row-outlier " if r["is_outlier"] else "") + f"border-{label}"
        body.append(f'<tr class="{klass}">{"".join(cells)}</tr>')

    return (
        '<table class="qc-table">'
        f"<thead><tr>{_render_header_cells(headers)}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table>"
    )


def _render_iqm_charts(
    runs: list[dict], iqm_cols: list[str], modality: str, subject: str | None
) -> str:
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:  # pragma: no cover - plotly is a hard dependency
        return "<p>Plotly not available — charts skipped.</p>"

    present = [m for m in iqm_cols if any(r["iqms"].get(m) is not None for r in runs)]
    if not present or not runs:
        return "<p>No data for charts.</p>"

    cols = min(len(present), 3)
    n_rows = (len(present) + cols - 1) // cols
    fig = make_subplots(rows=n_rows, cols=cols, subplot_titles=present, vertical_spacing=0.10)

    for i, metric in enumerate(present):
        having = [r for r in runs if r["iqms"].get(metric) is not None]
        values = [r["iqms"][metric] for r in having]
        groups = [(r["session"] if subject else r["subject"]) or "" for r in having]
        fig.add_trace(
            go.Box(
                y=values,
                x=groups,
                name=metric,
                boxpoints="all",
                jitter=0.3,
                marker={"size": 4, "opacity": 0.5},
                text=[_run_label(r) for r in having],
                showlegend=False,
            ),
            row=i // cols + 1,
            col=i % cols + 1,
        )

        flagged = [r for r in having if metric in r["flagged_metrics"]]
        if flagged:
            fig.add_trace(
                go.Scatter(
                    y=[r["iqms"][metric] for r in flagged],
                    x=[(r["session"] if subject else r["subject"]) or "" for r in flagged],
                    mode="markers",
                    marker={"color": "red", "size": 10, "symbol": "x"},
                    text=[_run_label(r) for r in flagged],
                    hoverinfo="text+y",
                    name="outlier",
                    showlegend=(i == 0),
                ),
                row=i // cols + 1,
                col=i % cols + 1,
            )

    fig.update_layout(height=300 * n_rows, title_text=f"IQM distributions ({modality})")
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _render_motion_chart(runs: list[dict], fd_threshold: float) -> str:
    try:
        import plotly.graph_objects as go
    except ImportError:  # pragma: no cover - plotly is a hard dependency
        return "<p>Plotly not available — chart skipped.</p>"

    having = [r for r in runs if (r.get("motion") or {}).get("mean_fd") is not None]
    if not having:
        return "<p>No motion data available.</p>"
    having.sort(key=lambda r: (r["subject"], r["session"], r["task"], r["run"]))

    fig = go.Figure(
        go.Scatter(
            x=list(range(len(having))),
            y=[r["motion"]["mean_fd"] for r in having],
            mode="markers",
            marker={
                "color": ["red" if r["is_outlier"] else "#3b82f6" for r in having],
                "size": 8,
            },
            text=[_run_label(r) for r in having],
            hoverinfo="text+y",
        )
    )
    fig.add_hline(
        y=fd_threshold,
        line_dash="dash",
        line_color="red",
        annotation_text=f"{fd_threshold} mm",
    )
    fig.update_layout(
        title="Mean framewise displacement per run",
        xaxis_title="Run",
        yaxis_title="Mean FD (mm)",
        height=350,
        showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _render_outlier_detail(runs: list[dict], report_base: str) -> str:
    items = []
    for r in (x for x in runs if x["is_outlier"]):
        bullets = []
        for m in r["flagged_metrics"]:
            g = qc_guidance.get_guidance(m)
            hint = ""
            if g is not None:
                hint = (
                    f'<div class="flag-hint"><em>Check:</em> {_esc(g.look_for)} '
                    f'<a href="#guidance-{_esc(m)}">guidance</a></div>'
                )
            bullets.append(f"<li><strong>{_esc(m)}</strong>: {_fmt(r['iqms'].get(m))}{hint}</li>")
        detail = f"<ul>{''.join(bullets)}</ul>" if bullets else "<p>No flagged measures.</p>"
        link = ""
        if r["report"]:
            href = f"{report_base}/{r['report']}"
            link = f' <a href="{_esc(href)}" target="_blank">[MRIQC report]</a>'
        items.append(f"<details><summary>{_esc(_run_label(r))}{link}</summary>{detail}</details>")
    return "\n".join(items)


def _run_label(run: dict) -> str:
    bits = [f"sub-{run['subject']}"]
    for entity, value in (("ses", run["session"]), ("run", run["run"])):
        if value:
            bits.append(f"{entity}-{value}")
    if run["task"]:
        bits.insert(1, run["task"])
    return " ".join(bits)


def _plotly_js() -> str:
    """Inline the Plotly source so the report works with no network.

    Deliberate: these reports are read on HPC nodes and mailed around as single
    files. It costs a fixed ~4.9 MB and the run table adds under a kilobyte per
    run, so the payload is effectively constant in dataset size.
    """
    try:
        from plotly.offline import get_plotlyjs

        return get_plotlyjs()
    except ImportError:  # pragma: no cover - plotly is a hard dependency
        return "/* plotly not installed */"


def write_report(html: str, derivatives_dir: str | Path, filename: str) -> Path:
    """Write the report into ``<derivatives>/duckbrain_qc/`` and return its path.

    Beside MRIQC's and fMRIPrep's own reports, which is where someone looking for
    a report will look, and at the depth ``report_base``'s default assumes.
    """
    out_dir = Path(derivatives_dir) / REPORT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(html, encoding="utf-8")
    return path


def report_filename(modality: str, subject: str | None = None) -> str:
    scope = f"sub-{subject}" if subject else "all"
    return f"qc_report_{scope}_{modality}.html"


_CSS = """<style>
:root {
  --bg: #ffffff; --fg: #1a1a2e;
  --ok: #22c55e; --warn: #f59e0b; --error: #ef4444;
  --pending: #94a3b8; --blue: #3b82f6;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       color: var(--fg); background: var(--bg); padding: 1.5rem; line-height: 1.5; }
header { margin-bottom: 2rem; }
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { font-size: 1.2rem; margin: 1.5rem 0 0.75rem;
     border-bottom: 1px solid #e2e8f0; padding-bottom: 0.25rem; }
.meta { color: #64748b; font-size: 0.85rem; margin-bottom: 1rem; }
.cards { display: flex; gap: 1rem; flex-wrap: wrap; }
.card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
        padding: 0.75rem 1.25rem; font-size: 1.5rem; font-weight: 600;
        text-align: center; min-width: 100px; }
.card span { display: block; font-size: 0.75rem; font-weight: 400; color: #64748b; }
.card-warn { border-color: var(--warn); }
.card-ok { border-color: var(--ok); }

/* Table */
.qc-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-top: 0.5rem; }
.qc-table th { background: #f1f5f9; padding: 0.5rem 0.4rem; text-align: left;
               cursor: pointer; user-select: none; position: sticky; top: 0; white-space: nowrap; }
.qc-table th:hover { background: #e2e8f0; }
.qc-table td { padding: 0.35rem 0.4rem; border-bottom: 1px solid #e2e8f0; white-space: nowrap; }
.qc-table tbody tr:hover { background: #f8fafc; }

/* Row borders by decision */
.border-keep { border-left: 3px solid var(--ok); }
.border-exclude { border-left: 3px solid var(--error); }
.border-investigate { border-left: 3px solid var(--warn); }
.border-pending { border-left: 3px solid var(--pending); }
.row-outlier { background: #fef2f2; }

.cell-flagged { background: #fee2e2; font-weight: 600; }
.signoff-note { margin-top: 0.6rem; font-size: 0.78rem; max-width: 90ch; }
.auto-suggest { margin-left: 0.4rem; font-size: 0.65rem; color: #94a3b8;
                font-style: italic; white-space: nowrap; }

/* Badges */
.badge { padding: 0.15rem 0.5rem; border-radius: 9999px; font-size: 0.65rem;
         font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.badge-keep { background: #dcfce7; color: #166534; }
.badge-exclude { background: #fee2e2; color: #991b1b; }
.badge-warn { background: #fef3c7; color: #92400e; }
.badge-pending { background: #f1f5f9; color: #64748b; }

a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

details { margin: 0.5rem 0; padding: 0.5rem; background: #f8fafc; border-radius: 4px; }
summary { cursor: pointer; font-weight: 500; }
details ul { margin: 0.5rem 0 0 1.5rem; }
details li { margin: 0.25rem 0; font-size: 0.85rem; }

section { margin-bottom: 2rem; }
.section-intro { color: #475569; font-size: 0.85rem; margin-bottom: 0.75rem; max-width: 70ch; }

/* Guidance: documented column headers */
.th-documented { border-bottom: 2px solid var(--blue); }
.g-marker { font-size: 0.7rem; margin-left: 0.2rem; opacity: 0.55; }
.g-marker:hover { opacity: 1; }

/* Guidance cards */
.guidance-card { border: 1px solid #e2e8f0; background: #fff; margin: 0.35rem 0; }
.guidance-card summary { font-size: 0.9rem; padding: 0.15rem 0; }
.guidance-card summary code { background: #f1f5f9; padding: 0.05rem 0.3rem;
                              border-radius: 3px; font-size: 0.85rem; }
.process-card { background: #f8fafc; }
.guidance-body { margin-top: 0.6rem; padding-left: 0.25rem; }
.g-units { color: #64748b; font-weight: 400; font-size: 0.8rem; }
.g-dir { float: right; font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
         letter-spacing: 0.04em; padding: 0.1rem 0.45rem; border-radius: 9999px;
         background: #f1f5f9; color: #475569; }
.g-dir-lower_better { background: #e0f2fe; color: #075985; }
.g-dir-higher_better { background: #dcfce7; color: #166534; }
.g-dir-target_range { background: #fef3c7; color: #92400e; }
.g-dir-context { background: #f1f5f9; color: #475569; }
.g-row { display: flex; gap: 0.75rem; margin: 0.4rem 0; font-size: 0.85rem;
         align-items: baseline; }
.g-label { flex: 0 0 11rem; font-weight: 600; color: #334155; font-size: 0.75rem;
           text-transform: uppercase; letter-spacing: 0.03em; }
.g-text { flex: 1; max-width: 80ch; }

/* References */
.ref-list { margin: 0.75rem 0 0.25rem 1.1rem; padding: 0; }
.ref { font-size: 0.8rem; margin: 0.25rem 0; }
.ref-detail { color: #64748b; }
.ref-note { color: #475569; font-style: italic; }
.ref-docs a { color: #7c3aed; }
.ref-forum a { color: #ea580c; }

.flag-hint { font-size: 0.8rem; color: #475569; margin: 0.25rem 0 0.5rem 0; max-width: 80ch; }
</style>"""


_TABLE_SORT_JS = """<script>
document.querySelectorAll('.qc-table th').forEach(th => {
  th.addEventListener('click', () => {
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const idx = Array.from(th.parentNode.children).indexOf(th);
    const dir = th.dataset.sortDir === 'asc' ? 'desc' : 'asc';
    th.parentNode.querySelectorAll('th').forEach(h => delete h.dataset.sortDir);
    th.dataset.sortDir = dir;
    rows.sort((a, b) => {
      let av = a.children[idx]?.textContent.trim() ?? '';
      let bv = b.children[idx]?.textContent.trim() ?? '';
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return dir === 'asc' ? an - bn : bn - an;
      return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    });
    rows.forEach(r => tbody.appendChild(r));
  });
});
</script>"""
