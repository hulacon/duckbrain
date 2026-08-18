"""Page 6: Guide — orientation for a new user.

This is the old app landing page. Top nav made a dedicated welcome screen a
detour on every launch, so the content moved here and the default landing is
computed instead (Status with a project open, Setup without — see ``app.py``).

The "New to Talapas?" signpost lives here too, merged in from its own page —
one orientation page, and the best lever on nav length (its label was the
bar's longest). The newcomer content itself stays in
``docs/new-to-talapas.md``, and that is deliberate: the people
who need it most are exactly the people who cannot launch this GUI yet, so the
canonical copy has to be readable on GitHub before any setup. This page only
points, so it never drifts.
"""

import streamlit as st

st.set_page_config(page_title="Guide — duckbrain", layout="wide")
st.title("duckbrain")

st.markdown(
    """
    A general-purpose neuroimaging toolbox for LCNI/Talapas HPC users at UO —
    raw DICOMs → BIDS → preprocessing → QC, without writing pipeline scripts.

    ### Where to work

    - **Status** — the cockpit, and where you land once a project is open.
      What's done, half-done, or left per subject; launch the next step and
      inspect the exact SLURM job (id, live state, logs) in place. Start here
      day to day.
    - **Setup** — the project directory and its settings, plus the shared
      machine resources (containers, FreeSurfer license, NORDIC toolbox) that
      every project on this account reuses.
    - **Preprocessing** — fMRIPrep, NORDIC denoising, MRIQC.
    - **BIDSification** — DICOMs in, a valid managed BIDS tree out:
      - **Ingestion** — import DICOMs from an LCNI export into sourcedata.
      - **Conversion** — inspect a session's series, check fieldmap detection,
        fix the task/run mapping, and convert to BIDS via dcm2bids.
      - **Project** — manage the dataset itself: `participants.tsv` /
        `dataset_description.json`, BIDS validation, and the study's declared
        expectations.
    - **QC** — review quality metrics and record keep/exclude decisions.

    ### First time here?

    Go to **Setup** and point duckbrain at a project directory — it is the anchor
    everything else is derived from (`sourcedata/`, `derivatives/`, `code/`).
    Projects you open are remembered, so the **Switch** control at the top right
    gets you back to them without browsing.

    `QUICKSTART.md` in the repo covers install, container builds, and the layered
    config in more detail.

    ### New to Talapas, the command line, or GitHub altogether?

    If words like *compute node*, *SLURM*, or *PIRG* are new to you, there is a
    guide for exactly that. It lives in the repository rather than in this GUI,
    so it can be read **before** any setup — by the people who can't launch
    this page yet:

    #### 📖 [New to Talapas? — the newcomer guide](https://github.com/hulacon/duckbrain/blob/main/docs/new-to-talapas.md)

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
