"""QC — one run inspected whole: all numbers, all evidence, one sign-off.

Body lives in ``gui.qc_panels`` so a test can import it; this file only exists
to be a page. Which measures and figures each section covers is declared in
``core.qc_domains``.
"""

import streamlit as st

st.set_page_config(page_title="Inspect a run — duckbrain", layout="wide")

from duckbrain.gui import qc_panels

qc_panels.render_inspection_page()
