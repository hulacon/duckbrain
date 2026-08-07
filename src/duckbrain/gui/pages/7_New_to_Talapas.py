"""Page 7: New to Talapas? — signpost to the newcomer guide in the repo.

The hand-holding for first-time cluster users (`TODO.md` #2) lives in
``docs/new-to-talapas.md``, and that is deliberate: the people who need it
most are exactly the people who cannot launch this GUI yet, so the canonical
copy has to be readable on GitHub before any setup. Keeping one copy there
(rather than a full in-app twin held in sync by a test) is what this page
buys — it only points, it never drifts.
"""

import streamlit as st

st.set_page_config(page_title="New to Talapas — duckbrain", layout="wide")
st.title("First time using Talapas?")

st.markdown(
    """
    If words like *compute node*, *SLURM*, or *PIRG* are new to you, there is
    a guide for exactly that. It lives in the repository rather than in this
    GUI, so it can be read **before** any setup — by the people who can't
    launch this page yet:

    ### 📖 [New to Talapas? — the newcomer guide](https://github.com/hulacon/duckbrain/blob/main/docs/new-to-talapas.md)

    It covers, in plain words:

    - **The five-minute picture** — what a cluster, a compute node, SLURM,
      and a PIRG are, and what duckbrain does with them.
    - **The canonical tutorials** — the command line, Talapas/RACS,
      Git/GitHub, conda, SLURM, and the neuroimaging side (BIDS, fMRIPrep,
      MRIQC).
    - **Check with your PI first** — the setup steps that encode a *lab*
      decision (PIRG and SLURM account, the shared conda environment, the
      containers, tool versions, NORDIC, where projects live) and so should
      be asked about, not defaulted.
    - **What you do *not* need to learn** — duckbrain writes, submits, and
      monitors your SLURM jobs for you.

    The checkout serving this GUI carries the same file at
    `docs/new-to-talapas.md`, so it is also readable straight from the clone.
    """
)
