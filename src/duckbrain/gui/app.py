"""Main Streamlit entrypoint for duckbrain (multipage app)."""

import streamlit as st
from pathlib import Path


def main():
    st.set_page_config(
        page_title="duckbrain",
        page_icon="\U0001f9e0",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.title("duckbrain")
    st.sidebar.caption("Neuroimaging toolbox for LCNI/Talapas HPC")

    # Check if config exists
    try:
        from ..config import load_config
        config = load_config()
        project_name = config.get("project", {}).get("name", "")
        if project_name:
            st.sidebar.success(f"Project: {project_name}")
        else:
            st.sidebar.warning("Project not configured — go to Project Setup")
    except (FileNotFoundError, Exception) as e:
        st.sidebar.error("Config not found — start with Project Setup")
        config = None

    st.title("duckbrain")
    st.markdown(
        """
        Welcome to **duckbrain** — a general-purpose neuroimaging toolbox for
        LCNI/Talapas HPC users at UO.

        ### Pipeline Steps
        - **Project Status** — What's done, half-done, or left per subject; launch
          the next step and track/inspect SLURM jobs (id, live state, logs) in place
        1. **Project Setup** — Configure paths, SLURM settings, containers
        2. **Data Ingestion** — Import DICOMs from LCNI export
        3. **BIDS Conversion** — Convert DICOMs to BIDS format via dcm2bids
        4. **Preprocessing** — fMRIPrep, NORDIC denoising, MRIQC
        5. **QC Dashboard** — Review quality metrics, make keep/exclude decisions

        Use the sidebar to navigate between pages.
        """
    )


if __name__ == "__main__":
    main()
