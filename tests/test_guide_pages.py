"""The two orientation pages — Guide, and New to Talapas? (`TODO.md` #2).

Both are static markdown, so the failure modes worth pinning are structural:
the page not rendering at all, the newcomer page falling out of the nav, and
the two copies of the resource-link list (the page and ``QUICKSTART.md``'s
"Completely new to Talapas?" section — a deliberate twin, since one audience
reads the repo before it can launch the GUI) drifting apart.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from conftest import REPO_ROOT, page_path
from duckbrain.gui.app import _PAGES

GUIDE = page_path("src/duckbrain/gui/pages/6_Guide.py")
NEWCOMER = page_path("src/duckbrain/gui/pages/7_New_to_Talapas.py")

#: The canonical starting points the newcomer story promises — the topics Ben
#: named for #2 (command line, Talapas/RACS, GitHub, conda, BIDS, fMRIPrep,
#: MRIQC) plus SLURM as background. Both copies of the list carry all of them.
CANONICAL_LINKS = [
    "swcarpentry.github.io/shell-novice",
    "hpcf.uoregon.edu",
    "docs.github.com/en/get-started",
    "swcarpentry.github.io/git-novice",
    "docs.conda.io",
    "slurm.schedmd.com/quickstart",
    "bids.neuroimaging.io",
    "bids-standard.github.io/bids-starter-kit",
    "fmriprep.org",
    "mriqc.readthedocs.io",
]


def _page_text(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_guide_renders_and_points_at_the_newcomer_page():
    at = AppTest.from_file(GUIDE, default_timeout=60).run()
    assert not at.exception
    # Normalize the triple-quoted block's newlines/indentation before matching.
    assert "New to Talapas?" in " ".join(_page_text(at).split())


def test_newcomer_page_renders_with_every_canonical_link():
    at = AppTest.from_file(NEWCOMER, default_timeout=60).run()
    assert not at.exception
    text = _page_text(at)
    missing = [url for url in CANONICAL_LINKS if url not in text]
    assert missing == []


def test_newcomer_page_carries_the_pi_check_list():
    """The PI flags are the part of #2 Ben asked for by name (2026-08-07):
    environment and pipeline choices are the lab's, and a newcomer's PI is not
    the maintainer — the page must say whose question each one is."""
    at = AppTest.from_file(NEWCOMER, default_timeout=60).run()
    text = _page_text(at)
    assert "Check with your PI" in text
    for lab_decision in ("PIRG", "conda environment", "containers", "NORDIC"):
        assert lab_decision in text, lab_decision


def test_newcomer_page_is_in_the_nav():
    """A page file that exists but is not declared simply never appears —
    ``st.navigation`` replaced the pages-directory convention, so nothing
    auto-registers it and nothing else fails."""
    assert "7_New_to_Talapas.py" in [f for f, _ in _PAGES]


def test_quickstart_twin_carries_the_same_links():
    """QUICKSTART's newcomer section and the page promise to stay in sync —
    each says "if you edit the links here, edit them there too". Hold both to
    the same canonical set so the promise is a test, not a comment."""
    quickstart = (Path(REPO_ROOT) / "QUICKSTART.md").read_text()
    missing = [url for url in CANONICAL_LINKS if url not in quickstart]
    assert missing == []
