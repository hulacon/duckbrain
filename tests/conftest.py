"""Suite-wide fixtures, and the one helper every page test needs.

The fixture exists to keep the network out of the test run: the GUI entrypoint
asks GitHub whether a newer release exists (``core.updates``), and several tests
execute that entrypoint under ``AppTest``. Left alone that would make the suite's
speed depend on GitHub being reachable and un-rate-limited, and would fail
differently on a build node with no route out. ``core.updates`` has a documented
opt-out; this is what it is for.

Autouse and unconditional on purpose. A test that wants to exercise the check
should call into ``core.updates`` directly with a stubbed fetch — never by letting
the real one through.
"""

from pathlib import Path

import pytest

from duckbrain.core.updates import OPT_OUT_ENV

REPO_ROOT = Path(__file__).resolve().parent.parent


def page_path(relpath: str) -> str:
    """Absolute path to a Streamlit page or app, for ``AppTest.from_file``.

    Absolute rather than repo-root-relative, and that is load-bearing rather than
    tidiness. Streamlit 1.61 changed how ``AppTest.from_file`` resolves a
    *relative* path: it used to be taken from the process working directory, and
    is now taken from the file that calls ``from_file``. So a literal
    ``"src/duckbrain/gui/pages/0_Project_Status.py"`` silently started resolving
    to ``tests/src/duckbrain/...``, and every page test in the suite — 162 of
    them — failed with ``FileNotFoundError`` on the day 1.61 was published, with
    nothing in this repo having changed.

    An absolute path is correct under both rules, which is why this is the fix
    rather than an upper bound on ``streamlit``: the dependency is a *runtime*
    one, users install whatever they install, and a ceiling here would only
    postpone the same break while making duckbrain harder to install alongside
    anything else.
    """
    return str(REPO_ROOT / relpath)


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    monkeypatch.setenv(OPT_OUT_ENV, "1")
