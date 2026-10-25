from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from veritas.pipeline.runner import run_pipeline  # noqa: E402
from veritas.settings import get_settings  # noqa: E402
from veritas.storage.db import SQLiteRecordStore, get_record_store  # noqa: E402
from veritas.storage.object_store import get_object_store  # noqa: E402
from veritas.storage.progress import ProgressTracker  # noqa: E402

st.set_page_config(page_title="Veritas Claims Ops", layout="wide", page_icon="🩺")

st.markdown(
    """
    <style>
      .stApp { background: linear-gradient(160deg, #f7fafc 0%, #e8f1f5 45%, #dfe9f2 100%); }
      h1 { font-family: "Segoe UI", Georgia, serif !important; color: #0f2c3e !important; }
      .metric-card { background: rgba(255,255,255,0.7); padding: 0.75rem 1rem; border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Veritas Claims — Ops Console")
st.caption("Pipeline health · flagged queue · clinic quality · record inspector")

settings = get_settings()
db = get_record_store(settings)
db.ensure_schema()
obj = get_object_store(settings)
progress = ProgressTracker(obj)

with st.sidebar:
    st.header("Controls")
    st.write(f"Backend: **{settings.storage_backend}**")
    if st.button("Run pipeline now", type="primary"):
        with st.spinner("Running pipeline…"):
            stats = run_pipeline()
        st.success(
            f"OK={stats['files_ok']} Failed={stats['files_failed']} "
            f"Dup={stats['files_dup']} Rows={stats['rows_written']}"
        )
        st.json(stats)
    st.divider()
    st.markdown("Sample data lives under `sample-data/{clinic}/{date}/`.")

# --- Dashboard ---
tab_dash, tab_flagged, tab_clinic, tab_inspect = st.tabs(
    ["Pipeline dashboard", "Flagged queue", "Clinic quality", "Record inspector"]
)

with tab_dash:
    summary = progress.summary()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Files tracked", summary.get("total", 0))
    c2.metric("Completed", summary.get("completed", 0))
    c3.metric("Failed", summary.get("failed", 0))
    c4.metric("Duplicates", summary.get("skipped_duplicate", 0))
    c5.metric("In progress", summary.get("in_progress", 0))

    rows = db.fetch_all(limit=5000)
    df = pd.DataFrame(rows)
    if not df.empty:
        st.subheader("Recent standardised rows")
        show_cols = [
            c
            for c in [
                "processed_at",
                "clinic_id",
                "document_id",
                "record_type",
                "test_name_original",
                "test_name_canonical",
                "result_value",
                "unit_canonical",
                "test_analytics",
                "normalization_method",
                "pending_ai",
                "medicine",
                "medicine_generic",
            ]
            if c in df.columns
        ]
        st.dataframe(df[show_cols], use_container_width=True, height=360)

        if "test_analytics" in df.columns:
            st.subheader("Analytics distribution")
            st.bar_chart(df["test_analytics"].fillna("n/a").value_counts())
    else:
        st.info("No rows yet — click **Run pipeline now** in the sidebar.")

    if isinstance(db, SQLiteRecordStore):
        runs = db.recent_runs()
        if runs:
            st.subheader("Pipeline runs")
            st.dataframe(pd.DataFrame(runs), use_container_width=True)

with tab_flagged:
    flagged = db.fetch_flagged(limit=500)
    fdf = pd.DataFrame(flagged)
    if fdf.empty:
        st.success("No flagged records.")
    else:
        st.write(f"{len(fdf)} flagged / pending-AI rows")
        st.dataframe(fdf, use_container_width=True, height=480)

with tab_clinic:
    stats = db.clinic_stats()
    cdf = pd.DataFrame(stats)
    if cdf.empty:
        st.info("No clinic stats yet.")
    else:
        cdf["flag_rate"] = (cdf["flagged"] / cdf["total_rows"].clip(lower=1)).round(3)
        st.dataframe(cdf, use_container_width=True)
        st.bar_chart(cdf.set_index("clinic_id")["flag_rate"])

with tab_inspect:
    all_rows = db.fetch_all(limit=2000)
    adf = pd.DataFrame(all_rows)
    if adf.empty:
        st.info("Nothing to inspect.")
    else:
        docs = sorted(adf["document_id"].dropna().unique().tolist())
        doc = st.selectbox("Document", docs)
        subset = adf[adf["document_id"] == doc]
        st.write(f"{len(subset)} rows for `{doc}`")
        st.dataframe(subset, use_container_width=True, height=300)

        file_path = subset.iloc[0].get("file_gcs_path") if len(subset) else None
        if file_path:
            st.subheader("Raw JSON (source)")
            try:
                raw = obj.read_json(file_path)
                st.json(raw)
            except Exception as exc:
                st.warning(f"Could not load raw file: {exc}")
                if "raw_json" in subset.columns:
                    st.code(subset.iloc[0]["raw_json"])
