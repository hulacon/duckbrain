"""Page 6: Job Monitor — live SLURM job tracking and log viewing."""

import streamlit as st
import pandas as pd


st.set_page_config(page_title="Job Monitor — duckbrain", layout="wide")
st.title("Job Monitor")

from duckbrain.slurm.monitor import list_jobs, job_history, job_status, job_log

# ---- Auto-refresh ----
auto_refresh = st.sidebar.checkbox("Auto-refresh (30s)", value=False)
if auto_refresh:
    import time
    st.sidebar.info("Refreshing every 30 seconds...")

# ---- Active Jobs ----
st.subheader("Active Jobs")

jobs = list_jobs()
if jobs:
    jobs_data = [
        {
            "Job ID": j.job_id,
            "Name": j.name,
            "State": j.state,
            "Partition": j.partition,
            "Time Used": j.time_used,
            "Time Limit": j.time_limit,
            "Nodes": j.nodes,
            "Reason": j.reason,
        }
        for j in jobs
    ]
    df = pd.DataFrame(jobs_data)

    # Color-code state column
    st.dataframe(
        df.style.apply(
            lambda row: [
                "background-color: #cce5ff"
                if row["State"] == "RUNNING"
                else "background-color: #fff3cd"
                if row["State"] == "PENDING"
                else ""
                for _ in row
            ],
            axis=1,
        ),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No active jobs.")

# ---- Job History ----
st.subheader("Job History")
history_days = st.slider("Days to look back", 1, 30, 7)

history = job_history(days=history_days)
if history:
    history_data = [
        {
            "Job ID": j.job_id,
            "Name": j.name,
            "State": j.state,
            "Partition": j.partition,
            "Elapsed": j.time_used,
            "Submit": j.submit_time,
            "Start": j.start_time,
            "End": j.end_time,
            "Exit Code": j.exit_code,
        }
        for j in history
    ]
    hist_df = pd.DataFrame(history_data)

    # Filter by state
    states = sorted(hist_df["State"].unique())
    selected_states = st.multiselect("Filter by state", states, default=states)
    filtered = hist_df[hist_df["State"].isin(selected_states)]

    st.dataframe(
        filtered.style.apply(
            lambda row: [
                "background-color: #d4edda"
                if row["State"] == "COMPLETED"
                else "background-color: #f8d7da"
                if row["State"] in ("FAILED", "TIMEOUT", "OUT_OF_MEMORY")
                else ""
                for _ in row
            ],
            axis=1,
        ),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No job history found.")

# ---- Log Viewer ----
st.subheader("Log Viewer")

col1, col2 = st.columns(2)
with col1:
    log_job_id = st.text_input("Job ID", placeholder="Enter a job ID to view logs")
with col2:
    try:
        from duckbrain.config import load_config
        config = load_config()
        log_dir = config.get("paths", {}).get("work_dir", "")
        if log_dir:
            log_dir = f"{log_dir}/logs"
    except Exception:
        log_dir = ""
    log_dir = st.text_input("Log directory", value=log_dir)

if log_job_id and log_dir:
    logs = job_log(log_job_id, log_dir)

    if logs["stdout"]:
        with st.expander("stdout", expanded=True):
            st.code(logs["stdout"][-5000:], language="text")  # Last 5000 chars
            if len(logs["stdout"]) > 5000:
                st.caption(f"(Showing last 5000 of {len(logs['stdout'])} characters)")
    else:
        st.info("No stdout log found.")

    if logs["stderr"]:
        with st.expander("stderr"):
            st.code(logs["stderr"][-5000:], language="text")
    else:
        st.info("No stderr log found.")

    # Also show sacct details
    details = job_status(log_job_id)
    if details:
        st.markdown(f"**State:** {details.state} | **Exit code:** {details.exit_code} | **Elapsed:** {details.time_used}")

# ---- Auto-refresh implementation ----
if auto_refresh:
    time.sleep(30)
    st.rerun()
