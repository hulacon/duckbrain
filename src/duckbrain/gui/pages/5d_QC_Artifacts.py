"""QC — Artifacts & inhomogeneity, for one run.

Body lives in ``gui.qc_panels`` so a test can import it; this file only says
which domain it is. The domain's measures, figures and prose are declared in
``core.qc_domains``.
"""

import streamlit as st

st.set_page_config(page_title="Artifacts & inhomogeneity — duckbrain", layout="wide")

from duckbrain.gui import qc_panels

qc_panels.render_domain_page("artifact")
