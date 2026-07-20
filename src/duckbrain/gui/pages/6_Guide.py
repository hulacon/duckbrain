"""Page 6: Guide — orientation for a new user.

This is the old app landing page. Top nav made a dedicated welcome screen a
detour on every launch, so the content moved here and Status became the default
landing (it degrades gracefully, pointing at Setup when no project is open).
"""

import streamlit as st

st.set_page_config(page_title="Guide — duckbrain", layout="wide")
st.title("duckbrain")

st.markdown(
    """
    A general-purpose neuroimaging toolbox for LCNI/Talapas HPC users at UO —
    raw DICOMs → BIDS → preprocessing → QC, without writing pipeline scripts.

    ### Where to work

    - **Status** — the cockpit, and where you land. What's done, half-done, or
      left per subject; launch the next step and inspect the exact SLURM job
      (id, live state, logs) in place. Start here day to day.
    - **Setup** — the project directory and its settings, plus the shared
      machine resources (containers, FreeSurfer license, NORDIC toolbox) that
      every project on this account reuses.
    - **Ingestion** — import DICOMs from an LCNI export, and write the BIDS
      root's `participants.tsv` / `dataset_description.json`.
    - **Conversion** — inspect a session's series, check fieldmap detection, fix
      the task/run mapping, and convert to BIDS via dcm2bids.
    - **Preprocessing** — fMRIPrep, NORDIC denoising, MRIQC.
    - **QC** — review quality metrics and record keep/exclude decisions.

    ### First time here?

    Go to **Setup** and point duckbrain at a project directory — it is the anchor
    everything else is derived from (`sourcedata/`, `derivatives/`, `code/`).
    Projects you open are remembered, so the **Switch** control at the top right
    gets you back to them without browsing.

    `QUICKSTART.md` in the repo covers install, container builds, and the layered
    config in more detail.
    """
)
