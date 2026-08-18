"""The orientation page — Guide, carrying the New to Talapas? signpost.

One page since the newcomer page merged in (its label was the bar's longest,
and merging was the best lever on nav length). The newcomer content itself
lives in ``docs/new-to-talapas.md``, moved out of the GUI so it is readable on GitHub
*before* a user can launch anything — the people who need it most are exactly
the people who can't launch the GUI yet. The in-app section is a signpost. So
the failure modes worth pinning are: the doc losing a canonical link or the
PI-check list, either signpost (the Guide section, ``QUICKSTART.md``'s opening
section) ceasing to point at the doc, and the structural ones — the page not
rendering, or falling out of the nav.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from conftest import REPO_ROOT, page_path
from duckbrain.gui.app import _PAGES

GUIDE = page_path("src/duckbrain/gui/pages/6_Guide.py")
NEWCOMER_DOC = Path(REPO_ROOT) / "docs" / "new-to-talapas.md"

#: The canonical starting points the newcomer story promises — the topics Ben
#: named for #2 (command line, Talapas/RACS, GitHub, conda, BIDS, fMRIPrep,
#: MRIQC) plus SLURM as background. The doc is the single canonical copy.
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


def test_guide_renders_and_points_at_the_newcomer_doc():
    """The Guide is the in-app signpost now, and a signpost that loses
    its target is a dead end on exactly the audience least able to route
    around it."""
    at = AppTest.from_file(GUIDE, default_timeout=60).run()
    assert not at.exception
    assert "docs/new-to-talapas.md" in _page_text(at)


def test_newcomer_doc_carries_every_canonical_link():
    text = NEWCOMER_DOC.read_text()
    missing = [url for url in CANONICAL_LINKS if url not in text]
    assert missing == []


def test_newcomer_doc_carries_the_pi_check_list():
    """The PI flags are the part of #2 Ben asked for by name (2026-08-07):
    environment and pipeline choices are the lab's, and a newcomer's PI is not
    the maintainer — the doc must say whose question each one is."""
    text = NEWCOMER_DOC.read_text()
    assert "Check with your PI" in text
    for lab_decision in ("PIRG", "conda environment", "containers", "NORDIC"):
        assert lab_decision in text, lab_decision


def test_guide_is_in_the_nav_and_the_newcomer_page_is_gone():
    """A page file that exists but is not declared simply never appears —
    ``st.navigation`` replaced the pages-directory convention, so nothing
    auto-registers it and nothing else fails. And the merge is only a
    merge if the old page is actually gone: declared again, it would 404."""
    assert "6_Guide.py" in [f for f, _ in _PAGES]
    assert "7_New_to_Talapas.py" not in [f for f, _ in _PAGES]
    assert not (Path(REPO_ROOT) / "src/duckbrain/gui/pages/7_New_to_Talapas.py").exists()


def test_quickstart_points_at_the_doc():
    """QUICKSTART's opening section is the other signpost — it used to carry a
    full twin of the link list, held in sync by this file; now it must simply
    lead to the one canonical copy."""
    quickstart = (Path(REPO_ROOT) / "QUICKSTART.md").read_text()
    assert "docs/new-to-talapas.md" in quickstart
