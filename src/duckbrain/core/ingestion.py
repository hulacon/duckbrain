"""LCNI DICOM export → sourcedata organization."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SessionInfo:
    """Parsed info for one scanner session folder."""

    folder_name: str
    parsed_subject: str
    parsed_session: str
    date: str
    path: Path
    series_count: int = 0
    series_list: list[str] = field(default_factory=list)


def discover_sessions(dcm_source_dir: str | Path) -> list[SessionInfo]:
    """List available DICOM session folders from the LCNI export directory.

    Parameters
    ----------
    dcm_source_dir : path
        e.g., /projects/lcni/dcm/<group>/<project>/

    Returns
    -------
    list[SessionInfo]
        Parsed session info for each subfolder, sorted by date.
    """
    dcm_source_dir = Path(dcm_source_dir)
    if not dcm_source_dir.is_dir():
        raise FileNotFoundError(f"DICOM source directory not found: {dcm_source_dir}")

    sessions = []
    for entry in sorted(dcm_source_dir.iterdir()):
        if not entry.is_dir():
            continue
        info = _parse_session_folder(entry)
        if info is not None:
            # Count series subdirectories
            series = [
                d.name
                for d in sorted(entry.iterdir())
                if d.is_dir() and re.match(r"Series_\d+", d.name)
            ]
            info.series_count = len(series)
            info.series_list = series
            sessions.append(info)

    return sorted(sessions, key=lambda s: s.date)


# Trailing "_YYYYMMDD_HHMMSS" acquisition stamp on an LCNI export folder.
_DATE_TIME_RE = re.compile(r"_(\d{8})_(\d{6})$")
# A distinctly session-looking token, e.g. "ses01", "sess05", "ses-1".
# Requires the "ses" prefix so a bare subject id like "s01" isn't mistaken for one.
_SESSION_TOKEN_RE = re.compile(r"^ses{1,2}[-_]?\d+$", re.IGNORECASE)


def _sanitize_label(raw: str) -> str:
    """Reduce a token to a BIDS-valid entity label (alphanumeric only)."""
    return re.sub(r"[^A-Za-z0-9]", "", raw)


def _parse_session_folder(folder: Path) -> SessionInfo | None:
    """Extract subject, session, date from a folder name.

    Handles the common LCNI export forms:
    - ``<PROJECT>_<SUBID>_<SESLABEL>_<DATE>_<TIME>`` (e.g. ``MMM_003_sess05_...``)
    - ``<PROJECT>_<SUBID>_<DATE>_<TIME>``            (e.g. ``DIVATTEN_001_...``)

    The subject id is taken as the last token before the (optional session and)
    date stamp, and any leading project prefix is dropped — so ``DIVATTEN_001``
    yields subject ``001`` (a valid BIDS entity), not ``DIVATTEN_001``. Labels
    are sanitized to alphanumerics. These are suggestions; the ingestion mapping
    step lets the user override before conversion.
    """
    name = folder.name

    m = _DATE_TIME_RE.search(name)
    date = m.group(1) if m else None
    if date is None:
        # Fallback: any 8-digit date anywhere in the name.
        dm = re.search(r"(\d{8})", name)
        if dm is None:
            return None
        date = dm.group(1)
        head = name[: dm.start()].rstrip("_")
    else:
        head = name[: m.start()]

    tokens = [t for t in head.split("_") if t]

    session = ""
    if len(tokens) >= 2 and _SESSION_TOKEN_RE.match(tokens[-1]):
        session = tokens[-1]
        tokens = tokens[:-1]

    subject_raw = tokens[-1] if tokens else head or name

    return SessionInfo(
        folder_name=name,
        parsed_subject=_sanitize_label(subject_raw) or _sanitize_label(name),
        parsed_session=_sanitize_label(session),
        date=date,
        path=folder,
    )


def build_dcm_source_path(config: dict) -> Path:
    """Construct the LCNI DICOM source directory from config."""
    dcm = config.get("dcm_source", {})
    base = dcm.get("base_dir", "/projects/lcni/dcm")
    group = dcm.get("group", "")
    project = dcm.get("project", "")
    if not group or not project:
        raise ValueError("dcm_source.group and dcm_source.project must be set in config")
    return Path(base) / group / project


@dataclass
class BidsMapping:
    """Mapping from a scanner session to BIDS subject/session.

    ``bids_session`` of ``""`` means the study is treated as single-session and
    the ``ses-`` entity is omitted from paths and filenames entirely.
    """

    folder_name: str
    bids_subject: str  # e.g., "01"
    bids_session: str  # e.g., "01"; "" -> no ses- entity


def sub_ses_relpath(subject: str, session: str = "") -> Path:
    """Relative ``sub-XX[/ses-YY]`` path fragment; omits ses- when session is empty."""
    p = Path(f"sub-{subject}")
    if session:
        p = p / f"ses-{session}"
    return p


def ingest_session(
    session: SessionInfo,
    mapping: BidsMapping,
    sourcedata_dir: str | Path,
    method: str = "symlink",
) -> Path:
    """Organize a DICOM session into sourcedata.

    Creates: <sourcedata_dir>/sub-<subject>/ses-<session>/dicom/ → link/copy of DICOM session

    Parameters
    ----------
    session : SessionInfo
        Discovered session.
    mapping : BidsMapping
        BIDS subject/session assignment.
    sourcedata_dir : path
        Root sourcedata directory.
    method : str
        "symlink" or "copy"

    Returns
    -------
    Path
        The created sourcedata directory.
    """
    sourcedata_dir = Path(sourcedata_dir)
    target = sourcedata_dir / sub_ses_relpath(mapping.bids_subject, mapping.bids_session) / "dicom"

    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    if method == "symlink":
        os.symlink(session.path, target)
    elif method == "copy":
        import shutil

        shutil.copytree(session.path, target)
    else:
        raise ValueError(f"Unknown ingestion method: {method}")

    return target


def auto_number_sessions(
    sessions: list[SessionInfo], use_sessions: str | bool = "auto"
) -> list[BidsMapping]:
    """Auto-assign BIDS session numbers by date order, per subject.

    Groups sessions by parsed_subject, then numbers them sequentially
    (01, 02, ...) in chronological order. Inspired by mrpyconvert's
    set_autosession (Jolinda Smith, LCNI/UO).

    Parameters
    ----------
    sessions : list[SessionInfo]
        Discovered sessions (should already be sorted by date).
    use_sessions : {"auto", True, False}
        Whether to emit the ses- entity. ``"auto"`` (default) includes it only
        when some subject has more than one session; otherwise the study is
        single-session and ``bids_session`` is left ``""`` (no ses- entity).

    Returns
    -------
    list[BidsMapping]
        One mapping per session; ``bids_session`` is ``""`` when sessions are
        not used.
    """
    from collections import defaultdict

    by_subject: dict[str, list[SessionInfo]] = defaultdict(list)
    for s in sessions:
        by_subject[s.parsed_subject].append(s)

    if use_sessions == "auto":
        include = any(len(v) > 1 for v in by_subject.values())
    else:
        include = bool(use_sessions)

    mappings = []
    for subject, sess_list in by_subject.items():
        # Sort by date within each subject
        sess_list.sort(key=lambda s: s.date)
        for i, s in enumerate(sess_list, start=1):
            mappings.append(
                BidsMapping(
                    folder_name=s.folder_name,
                    bids_subject=subject,
                    bids_session=(f"{i:02d}" if include else ""),
                )
            )

    return mappings


def list_ingested_sessions(sourcedata_dir: str | Path) -> list[dict]:
    """List sessions already ingested into sourcedata.

    Returns
    -------
    list[dict]
        Each dict has keys: subject, session, path, has_dicom.
    """
    sourcedata_dir = Path(sourcedata_dir)
    sessions = []
    if not sourcedata_dir.is_dir():
        return sessions

    for sub_dir in sorted(sourcedata_dir.iterdir()):
        if not sub_dir.is_dir() or not sub_dir.name.startswith("sub-"):
            continue
        subject = sub_dir.name.replace("sub-", "")
        ses_dirs = [
            d for d in sorted(sub_dir.iterdir()) if d.is_dir() and d.name.startswith("ses-")
        ]
        if ses_dirs:
            for ses_dir in ses_dirs:
                sessions.append(
                    {
                        "subject": subject,
                        "session": ses_dir.name.replace("ses-", ""),
                        "path": ses_dir,
                        "has_dicom": (ses_dir / "dicom").exists(),
                    }
                )
        else:
            # Single-session layout: dicom/ lives directly under sub-XX/
            sessions.append(
                {
                    "subject": subject,
                    "session": "",
                    "path": sub_dir,
                    "has_dicom": (sub_dir / "dicom").exists(),
                }
            )

    return sessions
