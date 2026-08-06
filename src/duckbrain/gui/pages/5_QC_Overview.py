"""QC Overview — the cohort, and where a run's verdict is recorded.

Body lives in ``gui.qc_panels`` so a test can import it; this file only says
which page it is. See that module's docstring for why the split is shaped this
way.
"""

import streamlit as st

st.set_page_config(page_title="QC Overview — duckbrain", layout="wide")

from duckbrain.gui import qc_panels

qc_panels.render_overview()
