"""QC — Signal & contrast, for one run.

Body lives in ``gui.qc_panels`` so a test can import it; this file only says
which domain it is. The domain's measures, figures and prose are declared in
``core.qc_domains``.
"""

import streamlit as st

st.set_page_config(page_title="Signal & contrast — duckbrain", layout="wide")

from duckbrain.gui import qc_panels  # noqa: E402

qc_panels.render_domain_page("signal")
