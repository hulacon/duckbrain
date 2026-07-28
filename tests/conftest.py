"""Suite-wide fixtures.

Only one so far, and it exists to keep the network out of the test run: the GUI
entrypoint asks GitHub whether a newer release exists (``core.updates``), and
several tests execute that entrypoint under ``AppTest``. Left alone that would
make the suite's speed depend on GitHub being reachable and un-rate-limited, and
would fail differently on a build node with no route out. ``core.updates`` has a
documented opt-out; this is what it is for.

Autouse and unconditional on purpose. A test that wants to exercise the check
should call into ``core.updates`` directly with a stubbed fetch — never by letting
the real one through.
"""

import pytest

from duckbrain.core.updates import OPT_OUT_ENV


@pytest.fixture(autouse=True)
def _no_update_check(monkeypatch):
    monkeypatch.setenv(OPT_OUT_ENV, "1")
