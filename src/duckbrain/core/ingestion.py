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
    # Human-readable caveats about this row — an unreadable folder, or a parse
    # the heuristics don't trust. Surfaced in the ingestion table so a bad guess
    # is visible rather than silently accepted. This is the whole accommodation
    # messy source labeling gets — surface it and let the user override; don't
    # grow a parser branch per malformed folder (TODO #5).
    notes: str = ""
    # Name of the grouping folder this session was found under, for sources that
    # group sessions by protocol one level down (mmmdata's ``func_session_*/``).
    # Empty for the flat LCNI layout. A label only — the subject/session identity
    # comes from the leaf folder name in both layouts.
    source_group: str = ""


def discover_sessions(
    dcm_source_dir: str | Path, include_excluded: bool = False
) -> list[SessionInfo]:
    """List available DICOM session folders from the LCNI export directory.

    Session folders normally sit directly under *dcm_source_dir* — the flat LCNI
    layout, e.g. ``divatten/DIVATTEN_001_20220408_100353``. Some studies group
    them one level deeper by protocol instead: ``mmmdata`` has ``anat_session/``,
    ``func_session_localizers/``, ``func_session_free_recall/`` … each holding
    that study's ``MMM_003_sess02_<date>`` folders, with session numbers running
    across the whole set rather than restarting per protocol folder. So the
    subject/session identity lives in the leaf name either way, and the grouping
    folder is a *protocol* label, not part of the identity.

    Descent happens only when the top level yields nothing parseable, which
    leaves the flat layout untouched. The grouping folder is recorded on each
    result as ``source_group``.

    Parameters
    ----------
    dcm_source_dir : path
        e.g., /projects/lcni/dcm/<group>/<project>/
    include_excluded : bool
        When ``False`` (default), skip non-subject folders — phantoms, QA scans,
        test/demo runs, and any name containing whitespace (see
        ``_is_excluded_folder``). Set ``True`` to return everything.

    Returns
    -------
    list[SessionInfo]
        Parsed session info for each session folder, sorted by date.
    """
    dcm_source_dir = Path(dcm_source_dir)
    if not dcm_source_dir.is_dir():
        raise FileNotFoundError(f"DICOM source directory not found: {dcm_source_dir}")

    sessions = _scan_session_dir(dcm_source_dir, include_excluded)

    if not sessions:
        for entry in sorted(_safe_iterdir(dcm_source_dir)):
            if not entry.is_dir():
                continue
            for info in _scan_session_dir(entry, include_excluded):
                info.source_group = entry.name
                sessions.append(info)

    _flag_duplicate_labels(sessions)
    return sorted(sessions, key=lambda s: s.date)


def _flag_duplicate_labels(sessions: list[SessionInfo]) -> None:
    """Note any subject/session label claimed by more than one folder.

    Session numbering is not always unique across a grouped source: in mmmdata,
    subject 003 has a ``sess04`` under both ``func_session_localizers`` and
    ``func_session_cued_recall``. Ingesting both under the parsed labels would
    put two different scans in one ``sub-003/ses-sess04``, and ingestion is
    idempotent — the second would quietly resolve to the first rather than fail.
    Auto-numbering by date avoids this; a user reading the parsed labels off the
    table would not, so say so.
    """
    from collections import defaultdict

    seen: dict[tuple[str, str], list[SessionInfo]] = defaultdict(list)
    for s in sessions:
        if s.parsed_session:
            seen[(s.parsed_subject, s.parsed_session)].append(s)

    for (subject, session), group in seen.items():
        if len(group) < 2:
            continue
        for s in group:
            others = ", ".join(o.folder_name for o in group if o is not s)
            s.notes = "; ".join(
                filter(
                    None,
                    [
                        s.notes,
                        f"sub-{subject}/ses-{session} also claimed by {others} — "
                        "assign distinct BIDS sessions",
                    ],
                )
            )


def _safe_iterdir(directory: Path) -> list[Path]:
    """List *directory*, treating an unreadable one as empty rather than raising."""
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def _scan_session_dir(directory: Path, include_excluded: bool) -> list[SessionInfo]:
    """Parse the session folders sitting directly under *directory*."""
    sessions = []
    for entry in sorted(_safe_iterdir(directory)):
        if not entry.is_dir():
            continue
        info = _parse_session_folder(entry)
        if info is None:
            continue
        if not include_excluded and _is_excluded_folder(entry.name, info.parsed_subject):
            continue
        # Count series subdirectories. A shared LCNI export routinely holds
        # sessions owned by other users with no group read bit; listing one
        # raises PermissionError. Keep the row (dropping it would hide a real
        # subject — the failure this listing exists to prevent) and say why
        # it looks empty.
        try:
            series = [
                d.name
                for d in sorted(entry.iterdir())
                if d.is_dir() and re.match(r"Series_\d+", d.name)
            ]
        except OSError as exc:
            info.notes = "; ".join(
                filter(None, [info.notes, f"unreadable ({exc.strerror or exc})"])
            )
            series = []
        info.series_count = len(series)
        info.series_list = series
        sessions.append(info)
    return sessions


# Trailing "_YYYYMMDD_HHMMSS" acquisition stamp on an LCNI export folder.
_DATE_TIME_RE = re.compile(r"_(\d{8})_(\d{6})$")
# A distinctly session-looking token, e.g. "ses01", "sess05", "ses-1".
# Requires the "ses" prefix so a bare subject id like "s01" isn't mistaken for one.
# The trailing group allows the qualifiers real exports carry after the number —
# "sess04CR" (a condition tag) and "sess3.2" (a rescan). Without it those tokens
# failed to match and were adopted as the *subject*, so MMM03_sess04CR parsed as
# subject "sess04CR": the real subject vanished and two of its sessions became
# phantom subjects. Verified against /projects/lcni/dcm/hulacon/mmmdata.
_SESSION_TOKEN_RE = re.compile(r"^ses{1,2}[-_]?\d+[A-Za-z0-9.]*$", re.IGNORECASE)
# The mmmdata/LCNI "G##_S##" style: the last token is a session like "S02" only
# when the preceding token is a subject like "G01". Requiring the paired G-token
# keeps a bare "s01" subject id from being misread as a session — the same reason
# _SESSION_TOKEN_RE demands the "ses" prefix.
_GS_SUBJECT_RE = re.compile(r"^G\d+$", re.IGNORECASE)
_GS_SESSION_RE = re.compile(r"^S\d+$", re.IGNORECASE)

# Folders that aren't real subject sessions: QA scans, phantoms, test/demo runs.
# Marker words are matched as whole underscore/space/hyphen tokens (so a project
# like "Detest" won't trip on the "test" substring). Names containing whitespace
# are also skipped — real LCNI exports never have spaces, but scratch/test
# folders do.
_EXCLUDE_TOKENS = frozenset({"test", "phantom", "demo", "qa"})
_TOKEN_SPLIT_RE = re.compile(r"[_\s-]+")


def _is_excluded_folder(name: str, subject_label: str) -> bool:
    """True for non-subject folders (phantoms, QA, test/demo runs, spaced names).

    A marker word alone isn't decisive: a real study may *use* one as its project
    prefix (e.g. ``TEST_01_...``). Such a folder still resolves to a numeric
    subject id, so it's kept; a marker paired with a non-numeric identity
    (``phantom``, ``QA_daily``, ``DEMO``) is treated as a non-subject folder.
    ``subject_label`` is the already-parsed subject (see ``_parse_session_folder``).
    """
    if any(ch.isspace() for ch in name):
        return True
    tokens = {t.lower() for t in _TOKEN_SPLIT_RE.split(name) if t}
    if tokens & _EXCLUDE_TOKENS:
        return not any(ch.isdigit() for ch in subject_label)
    return False


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
    elif len(tokens) >= 2 and _GS_SESSION_RE.match(tokens[-1]) and _GS_SUBJECT_RE.match(tokens[-2]):
        # "G##_S##" style: last token is the session, the paired G-token is the subject.
        session = tokens[-1]
        tokens = tokens[:-1]

    subject_raw = tokens[-1] if tokens else head or name

    # Flag the guesses that are probably wrong rather than accepting them
    # silently. A subject that still reads as a session label, or as the export's
    # own date stamp, means the folder didn't follow any form we know — the user
    # needs to override it in the mapping table.
    notes = ""
    if _SESSION_TOKEN_RE.match(subject_raw):
        notes = "subject looks like a session label — check the mapping"
    elif re.fullmatch(r"\d{6,8}", subject_raw):
        notes = "subject looks like a date — check the mapping"

    return SessionInfo(
        folder_name=name,
        parsed_subject=_sanitize_label(subject_raw) or _sanitize_label(name),
        parsed_session=_sanitize_label(session),
        date=date,
        path=folder,
        notes=notes,
    )


def build_dcm_source_path(config: dict) -> Path:
    """Resolve the LCNI DICOM source directory from config.

    Prefers an explicit ``dcm_source.dir`` (the full path to the study's DICOM
    export). Falls back to the legacy ``base_dir / group / project`` composition
    for older configs. A single directory is unambiguous across LCNI's varied
    layouts (e.g. ``hulacon/mmmdata`` vs ``hulacon/Hutchinson/divatten``).
    """
    dcm = config.get("dcm_source", {})
    explicit = dcm.get("dir", "")
    if explicit:
        return Path(explicit)

    base = dcm.get("base_dir", "/projects/lcni/dcm")
    group = dcm.get("group", "")
    project = dcm.get("project", "")
    if not group or not project:
        raise ValueError(
            "Set dcm_source.dir (full path to the DICOM export), "
            "or the legacy dcm_source.group + dcm_source.project."
        )
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


class InvalidLabel(ValueError):
    """A subject/session label that BIDS does not allow, caught before it's a path.

    ``_sanitize_label`` only ever ran on the heuristic's guesses; the mapping
    table's subject and session columns are free text, and the sole gate was
    emptiness. A label of ``../../x`` or ``01/junk`` therefore went straight into
    ``sub_ses_relpath`` and built a directory outside the tree it named.
    """


def validate_label(raw: str, what: str) -> str:
    """Return *raw* if it is a legal BIDS entity label, else raise.

    BIDS entity labels are alphanumeric — no separators, no dots, no spaces —
    which rules out traversal (``..``) and absolute paths as a side effect rather
    than by blocklisting them.
    """
    if not raw or not raw.isalnum():
        raise InvalidLabel(
            f"{what} label {raw!r} is not a valid BIDS entity: labels must be "
            "alphanumeric (letters and digits only, no /, .., spaces or dashes)."
        )
    return raw


def sub_ses_relpath(subject: str, session: str = "") -> Path:
    """Relative ``sub-XX[/ses-YY]`` path fragment; omits ses- when session is empty."""
    p = Path(f"sub-{subject}")
    if session:
        p = p / f"ses-{session}"
    return p


def plan_ingest(mappings: list[BidsMapping], sourcedata_dir: str | Path) -> dict[str, list[str]]:
    """Destinations claimed by more than one folder: ``{relpath: [folder, ...]}``.

    Preflight, because the collision check inside :func:`ingest_session` is
    reactive — it fires only once the first of a colliding pair is already on
    disk, and iteration order silently decides which folder wins. Empty dict
    means the whole selection can be written.
    """
    by_dest: dict[str, list[str]] = {}
    for m in mappings:
        dest = str(sub_ses_relpath(m.bids_subject, m.bids_session))
        by_dest.setdefault(dest, []).append(m.folder_name)
    return {d: folders for d, folders in by_dest.items() if len(folders) > 1}


class IngestCollision(Exception):
    """Two source folders map onto one subject/session, so one was not ingested.

    Its own type because the caller must not report this as a success and must not
    report it as an ordinary failure either: the *first* folder is ingested fine,
    and what needs fixing is the mapping rather than the ingest.
    """


#: Written inside a *copied* target to record which source folder it came from.
#: A symlink carries that provenance in the link itself; a copy carries none, and
#: without it the collision check below cannot tell "you ingested this same folder
#: yesterday" from "a different folder already claimed this subject/session".
_SOURCE_MARKER = ".duckbrain-source"


def _describe_target(target: Path) -> str:
    """What an existing ingested target points at, for a collision message."""
    try:
        if target.is_symlink():
            return str(target.readlink())
        recorded = _ingested_source(target)
        return recorded if recorded else str(target)
    except OSError:
        return str(target)


def _ingested_source(target: Path) -> str | None:
    """The source folder a copied *target* was ingested from, or None if unrecorded.

    None means either an unmarked copy — one ingested before the marker existed —
    or an unreadable target. Callers must not read None as "different source";
    see :func:`ingest_session`.
    """
    try:
        return (target / _SOURCE_MARKER).read_text().strip() or None
    except OSError:
        return None


def _same_source(target: Path, source: Path) -> bool | None:
    """Was *target* ingested from *source*? None when it cannot be determined.

    Symlinks answer this themselves. Copies answer it from the marker file, and
    a copy predating the marker answers None — which is not the same as False,
    because reporting a collision against a target the user very likely created
    from this exact folder would block a re-ingest that has always been a no-op.
    """
    try:
        if target.is_symlink():
            return target.resolve() == Path(source).resolve()
    except OSError:  # broken link, unreadable mount
        return False

    # A real directory resolves to itself, so a resolved-path comparison here is
    # always False and would flag every copy-mode re-ingest as a collision.
    recorded = _ingested_source(target)
    if recorded is None:
        return None
    try:
        return Path(recorded).resolve() == Path(source).resolve()
    except OSError:
        return recorded == str(source)


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

    Raises
    ------
    IngestCollision
        The target is already ingested *from a different source folder* — two
        scanner folders mapped onto one subject/session. See below.
    """
    sourcedata_dir = Path(sourcedata_dir)
    validate_label(mapping.bids_subject, "subject")
    if mapping.bids_session:
        validate_label(mapping.bids_session, "session")
    target = sourcedata_dir / sub_ses_relpath(mapping.bids_subject, mapping.bids_session) / "dicom"

    # Belt and braces on top of the label check: whatever the labels were, the
    # path we are about to build has to land inside sourcedata. Normalized, not
    # resolved — an already-ingested target is a symlink *to* the DICOM source,
    # so resolving it would follow the link straight out of the tree and fail
    # every legitimate re-ingest.
    if not Path(os.path.normpath(target.absolute())).is_relative_to(
        Path(os.path.normpath(sourcedata_dir.absolute()))
    ):
        raise InvalidLabel(
            f"sub-{mapping.bids_subject} builds the path {target}, which is "
            f"outside {sourcedata_dir}."
        )

    if target.exists():
        # Ingestion is idempotent, and re-ingesting the same folder is a genuine
        # no-op. But an existing target pointing at a *different* source is the
        # duplicate-label collision `_flag_duplicate_labels` warns about, and
        # returning quietly let the caller report it as a success: two folders,
        # two green rows, one of them not on disk anywhere (TODO #17.9). Silence
        # here is the same class of bug as a silently-degrading option.
        #
        # Only a *definite* different-source answer is a collision. An unmarked
        # copy answers None, and treating that as a collision made every re-ingest
        # of a copied session fail against its own output.
        if _same_source(target, session.path) is False:
            raise IngestCollision(
                f"sub-{mapping.bids_subject}"
                + (f"/ses-{mapping.bids_session}" if mapping.bids_session else "")
                + f" is already ingested from '{_describe_target(target)}', so "
                f"'{session.folder_name}' was NOT ingested. Two source folders are "
                "mapped to one subject/session — fix the mapping, or remove the "
                "existing link if this one supersedes it."
            )
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    if method == "symlink":
        os.symlink(session.path, target)
    elif method == "copy":
        import shutil

        shutil.copytree(session.path, target)
        # The copy's only record of where it came from; see `_same_source`.
        (target / _SOURCE_MARKER).write_text(f"{Path(session.path).resolve()}\n")
    else:
        raise ValueError(f"Unknown ingestion method: {method}")

    return target


USE_SESSIONS_CHOICES = ("auto", "true", "false")

_TRUTHY = frozenset({"true", "yes", "on", "1"})
_FALSY = frozenset({"false", "no", "off", "0"})


def normalize_use_sessions(value: str | bool | None) -> str:
    """Reduce a ``use_sessions`` config value to ``"auto"``/``"true"``/``"false"``.

    The setting arrives in two shapes and both are legitimate, which is what made
    it fragile. TOML's ``use_sessions = true`` loads as a Python ``True``, while
    the Setup page's selectbox writes the *string* ``"true"``/``"false"`` — so
    every consumer had to handle both, and none of them did:

    - ``["auto", "true", "false"].index(True)`` raised ``ValueError`` and took
      down the Setup page for any project whose config used a real TOML boolean.
    - Worse, ``bool("false")`` is ``True``. A project that turned sessions *off*
      through the GUI got ``ses-`` entities anyway — the option quietly did the
      opposite of what it said, which is the failure mode ``CLAUDE.md`` singles
      out as worse than an error.

    Normalizing in one place, in core, is what keeps the GUI's option list and
    the ingestion behaviour from disagreeing again. Anything unrecognized falls
    back to ``"auto"``, the safe default that inspects the data rather than
    asserting an answer; callers that can show it (the Setup page) surface that
    fallback rather than swallowing it.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value or "").strip().lower()
    if text in _TRUTHY:
        return "true"
    if text in _FALSY:
        return "false"
    return "auto"


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
    use_sessions : {"auto", True, False, "true", "false"}
        Whether to emit the ses- entity. ``"auto"`` (default) includes it only
        when some subject has more than one session; otherwise the study is
        single-session and ``bids_session`` is left ``""`` (no ses- entity).
        Accepts either the TOML boolean or the GUI's string form — see
        :func:`normalize_use_sessions`, which is why this must not test the raw
        value for truthiness.

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

    mode = normalize_use_sessions(use_sessions)
    if mode == "auto":
        include = any(len(v) > 1 for v in by_subject.values())
    else:
        include = mode == "true"

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
