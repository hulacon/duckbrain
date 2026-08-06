"""A type alias is evaluated at import time. `TYPE_CHECKING` names are not there.

``from __future__ import annotations`` defers **annotations** — a parameter's
type, a return type, a dataclass field — so those may freely name something
imported only under ``if TYPE_CHECKING:``. A type *alias* is not an annotation.
It is an ordinary assignment, evaluated when the module loads, and a name that
exists only for the checker is simply absent::

    if TYPE_CHECKING:
        from ..config import Config

    StageBuilder = Callable[[Config, ...], ...]   # NameError on import

**mypy cannot catch this**, and that is not an oversight to file: to mypy the
``TYPE_CHECKING`` branch is always taken, so the name *is* in scope and the
module typechecks clean. The gate went green on exactly the revision where six
test files could not be collected. That is what makes this a test rather than a
comment — the checker is blind here by construction, and the blindness is
permanent.

So: import every module in the package and let a bad alias raise. It is a
weaker claim than the AST sweep in ``test_streamlit_caches.py`` — that one reads
source and so reaches the Streamlit pages, which cannot be imported at all
(they run Streamlit calls at module scope) — but it is the claim that catches
this, because the failure is an import failure and nothing short of importing
sees it.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import duckbrain

#: Modules that legitimately cannot be imported in a bare process. The Streamlit
#: pages call ``st.set_page_config`` at module scope; importing one outside a
#: script run is not a thing they support, and their aliases are covered by the
#: panel modules they import from.
SKIP_PREFIXES = ("duckbrain.gui.pages.",)


def _importable_modules() -> list[str]:
    return [
        m.name
        for m in pkgutil.walk_packages(duckbrain.__path__, prefix="duckbrain.")
        if not m.name.startswith(SKIP_PREFIXES)
    ]


@pytest.mark.parametrize("name", _importable_modules())
def test_every_module_imports(name: str) -> None:
    """A module-scope alias naming a `TYPE_CHECKING`-only import fails here."""
    importlib.import_module(name)


def test_the_sweep_actually_reaches_the_package() -> None:
    """Guards the guard: an empty parametrize list passes vacuously.

    ``walk_packages`` returns nothing if ``__path__`` is wrong or the package is
    installed as a zip, and a test that ran zero times looks exactly like a test
    that found nothing wrong.
    """
    found = _importable_modules()
    assert len(found) > 30, found
    assert "duckbrain.core.pipeline" in found
    assert "duckbrain.gui.qc_panels" in found
