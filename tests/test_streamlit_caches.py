"""One rule about Streamlit's caches, enforced over the whole package.

``st.cache_data`` and ``st.cache_resource`` build the cache key by iterating the
bound arguments and **skipping every one whose name starts with an underscore**
(``streamlit/runtime/caching/cache_utils.py``: "Underscore-prefixed args are
deliberately excluded from hashing"). The convention exists for the opposite
need — passing an unhashable object Streamlit must not try to hash, a database
connection or a loaded model — and it reads as "internal", which is how a *cache
key* ends up wearing one.

A key that is not hashed is not a key. ``qc_panels._load_metrics`` took a
``(count, newest mtime)`` fingerprint of the MRIQC derivative and named it
``_fingerprint``, so its real key was the directory and the modality — neither of
which changes when MRIQC re-runs into the same place. For as long as the QC pages
existed, a second run was served the first one's numbers until the server
restarted. Nothing noticed, because every test got its own ``tmp_path`` and so a
different key by accident rather than by the fingerprint.

Structural rather than behavioural on purpose. It is a claim about every cache in
the package, including the ones not written yet, and the pages under
``gui/pages/`` cannot be imported in order to be inspected — they are scripts
that call into Streamlit at import time. So the source is parsed, not run.

``EXEMPT`` is the escape hatch for the convention's real use. Adding to it asserts
that the value must *not* affect the key; a fingerprint, an mtime, a size or a
version never qualifies.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "duckbrain"

CACHE_DECORATORS = {"cache_data", "cache_resource"}

#: ``(module, function, parameter) -> why the value must not affect the key``.
EXEMPT: dict[tuple[str, str, str], str] = {}


def _decorator_name(node: ast.expr) -> str:
    """``st.cache_data``, ``st.cache_data(...)`` or ``cache_data`` -> a dotted name."""
    node = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _cached_functions():
    """Every ``st.cache_*`` function in the package, as (module, name, parameters)."""
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = {_decorator_name(d).split(".")[-1] for d in node.decorator_list}
            if not decorators & CACHE_DECORATORS:
                continue
            args = node.args
            params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            params += [a.arg for a in (args.vararg, args.kwarg) if a]
            yield path.relative_to(SRC.parent).as_posix(), node.name, params


def test_the_sweep_still_finds_the_caches_that_exist():
    """A finder that matched nothing would pass the rule below in silence."""
    found = {name for _, name, _ in _cached_functions()}
    assert {"_load_metrics", "_payload_bytes_cached", "_probe_cached"} <= found


def test_no_cache_key_wears_a_leading_underscore():
    offenders = [
        f"{module}::{func}({param})"
        for module, func, params in _cached_functions()
        for param in params
        if param.startswith("_") and (module, func, param) not in EXEMPT
    ]
    assert offenders == [], (
        "Streamlit drops underscore-prefixed arguments from the cache key, so these "
        "never invalidate. Rename, or add to EXEMPT with the reason the value must "
        f"not be hashed: {offenders}"
    )
