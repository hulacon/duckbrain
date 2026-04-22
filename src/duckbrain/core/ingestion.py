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


def _parse_session_folder(folder: Path) -> SessionInfo | None:
    """Extract subject, session, date from a folder name.

    Expected patterns (flexible):
    - <PROJECT>_<SUBID>_<SESLABEL>_<DATE>_<TIME>
    - <SUBID>_<SESLABEL>_<DATE>_<TIME>
    - Any folder with a parseable date component (YYYYMMDD)
    """
    name = folder.name

    # Try common LCNI pattern: PREFIX_SUBID_SESLABEL_YYYYMMDD_HHMMSS
    match = re.match(
        r"^(?:.*?_)?(\w+?)_(sess?\d+)_(\d{8})_(\d{6})$", name, re.IGNORECASE
    )
    if match:
        return SessionInfo(
            folder_name=name,
            parsed_subject=match.group(1),
            parsed_session=match.group(2),
            date=match.group(3),
            path=folder,
        )

    # Fallback: look for any YYYYMMDD in the name
    date_match = re.search(r"(\d{8})", name)
    if date_match:
        # Use the whole prefix as subject, no session parsed
        prefix = name[: date_match.start()].rstrip("_")
        return SessionInfo(
            folder_name=name,
            parsed_subject=prefix or name,
            parsed_session="",
            date=date_match.group(1),
            path=folder,
        )

    return None


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
    """Mapping from a scanner session to BIDS subject/session."""

    folder_name: str
    bids_subject: str  # e.g., "01"
    bids_session: str  # e.g., "01"


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
    sub = f"sub-{mapping.bids_subject}"
    ses = f"ses-{mapping.bids_session}"
    target = sourcedata_dir / sub / ses / "dicom"

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
        for ses_dir in sorted(sub_dir.iterdir()):
            if not ses_dir.is_dir() or not ses_dir.name.startswith("ses-"):
                continue
            session = ses_dir.name.replace("ses-", "")
            sessions.append(
                {
                    "subject": subject,
                    "session": session,
                    "path": ses_dir,
                    "has_dicom": (ses_dir / "dicom").exists(),
                }
            )

    return sessions
