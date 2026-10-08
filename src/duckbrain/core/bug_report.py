"""Assemble a bug report a user can read, then send themselves.

Support is paste-mediated: the maintainer cannot read the reporting lab's PIRG,
so the report *is* the visibility. A report protocol of four manual steps
(version, full error, log tail, what was clicked) fails by incompleteness rather
than unwillingness: the version goes missing, the wrong log gets pasted, the
error gets paraphrased. This module gathers all four at click time into one
plain-text file.

**Nothing is sent.** The bundle scrapes log tails and config values from a tree
whose paths and subject labels belong to the lab, so the GUI shows the whole
text before offering the download, and the user decides what leaves their PIRG.
Email delivery is deliberately absent. SMTP from a compute node is unproven,
a recipient baked into a public tool would route every adopter's bugs to one
person, and sending automatically takes the user's eyes off the content.

**Built from what exists, never cached.** The traceback is the last one
``show_error`` displayed this session, the logs are whatever ``log_dir`` holds
now, and the config is re-read. A cache of report material would be a second
state store with a staleness story.

Every section degrades to a line saying what could not be read. A report
builder that raises while the user is already stuck is the worst failure this
module could have.
"""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from duckbrain.config import Config

# Config keys whose values are never copied into a report, matched as a
# substring of the lower-cased key. Today's config carries no credentials (the
# GUI's access token lives in the environment, not the config), so this is a
# guard for keys a future version or a hand-edited project config might add.
_REDACT = ("token", "password", "secret", "api_key", "apikey", "credential")

# Log files worth tailing: SLURM stdout/stderr and tool logs. The submission
# log and the per-job BIDS filter JSONs share the directory and are not logs.
_LOG_SUFFIXES = {".out", ".err", ".log"}


def _section(title: str, body: str) -> str:
    return f"== {title} ==\n{body.rstrip()}\n"


def _header(page: str | None, now: datetime) -> str:
    from duckbrain.core.bids_metadata import duckbrain_version

    try:
        import streamlit

        st_version = streamlit.__version__
    except Exception:  # a report must not fail on an import
        st_version = "unknown"
    lines = [
        f"duckbrain: {duckbrain_version() or 'unknown'}",
        f"python: {platform.python_version()} ({sys.executable})",
        f"streamlit: {st_version}",
        f"host: {platform.node() or 'unknown'}",
        f"gui slurm job: {os.environ.get('SLURM_JOB_ID', 'none (not under SLURM)')}",
        f"page: {page or 'unknown'}",
        f"assembled: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    return _section("Environment", "\n".join(lines))


def _redacted(value: Any, key: str = "") -> Any:
    if any(word in key.lower() for word in _REDACT):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: _redacted(v, str(k)) for k, v in value.items()}
    return value


def _flatten(d: dict[str, Any], prefix: str = "") -> list[str]:
    lines: list[str] = []
    for key in sorted(d):
        value = d[key]
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            lines.extend(_flatten(value, name))
        else:
            lines.append(f"{name} = {value!r}")
    return lines


def _config_section(config: Config | None) -> str:
    if not config:
        return _section("Config", "no project open, so no project config was loaded")
    return _section("Config (effective, merged)", "\n".join(_flatten(_redacted(config))))


def _error_section(last_error: dict[str, str] | None) -> str:
    if not last_error:
        return _section("Last error shown", "none shown in this browser session")
    body = (
        f"page: {last_error.get('page', 'unknown')}\n"
        f"at: {last_error.get('at', 'unknown')}\n"
        f"message: {last_error.get('message', '')}\n\n"
        f"{last_error.get('trace', '').rstrip()}"
    )
    return _section("Last error shown", body)


def _submissions_section(config: Config | None, limit: int) -> str:
    if not config:
        return _section("Recent submissions", "no project open")
    try:
        from duckbrain.core.pipeline import read_submissions

        df = read_submissions(config)
    except Exception as exc:
        return _section("Recent submissions", f"could not read the submission log: {exc}")
    if df.empty:
        return _section("Recent submissions", "none recorded")
    cols = [c for c in ("timestamp", "stage", "subject", "session", "job_id") if c in df]
    return _section(
        f"Recent submissions (last {min(limit, len(df))} of {len(df)})",
        df[cols].tail(limit).to_string(index=False),
    )


def newest_logs(log_dir: str | Path, n: int) -> list[Path]:
    """The *n* most recently modified log files in *log_dir*, newest first."""
    root = Path(log_dir)
    try:
        files = [p for p in root.iterdir() if p.is_file() and p.suffix in _LOG_SUFFIXES]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[:n]


def _logs_section(config: Config | None, n: int, max_bytes: int) -> str:
    if not config:
        return _section("Newest logs", "no project open")
    from duckbrain.core.pipeline import _resolve_log_dir
    from duckbrain.slurm.monitor import tail_text

    log_dir = _resolve_log_dir(config)
    logs = newest_logs(log_dir, n)
    if not logs:
        return _section("Newest logs", f"no .out/.err/.log files in {log_dir}")
    parts = []
    for path in logs:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        parts.append(f"--- {path} (modified {stamp}) ---\n{tail_text(path, max_bytes).rstrip()}")
    return _section(f"Newest logs (tails, from {log_dir})", "\n\n".join(parts))


def build_bug_report(
    config: Config | None,
    *,
    what_happened: str,
    last_error: dict[str, str] | None = None,
    page: str | None = None,
    n_logs: int = 3,
    log_bytes: int = 6_000,
    n_submissions: int = 10,
    now: datetime | None = None,
) -> str:
    """The whole report as one string, in the order a reader needs it.

    The user's own words come first, then the environment (``git describe`` of
    the running checkout is the provenance rule's "what ran"), the last error,
    recent submissions, log tails, and finally the effective config, which is
    the longest and the least often needed.
    """
    now = now or datetime.now(UTC).astimezone()
    sections = [
        "duckbrain bug report. Read it before sending: it contains paths and log\n"
        "text from your project. Delete anything you'd rather not share.\n",
        _section("What happened", what_happened.strip() or "(not filled in)"),
        _header(page, now),
        _error_section(last_error),
    ]
    builders: list[Callable[[], str]] = [
        lambda: _submissions_section(config, n_submissions),
        lambda: _logs_section(config, n_logs, log_bytes),
        lambda: _config_section(config),
    ]
    for build in builders:
        try:
            sections.append(build())
        except Exception as exc:  # degrade, never raise
            sections.append(_section("Section failed", f"{type(exc).__name__}: {exc}"))
    return "\n".join(sections)


def report_filename(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"duckbrain-report-{now.strftime('%Y%m%d-%H%M%S')}.txt"
