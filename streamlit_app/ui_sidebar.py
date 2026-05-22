"""Per-page hook: MQTT ready + Neo4j index check."""
from __future__ import annotations

import streamlit as st

import mqtt_backend
import neo4j_backend

# 全站略放大字号（各页在 set_page_config 后调用 ui_sidebar.render 即生效）
_GLOBAL_APP_FONT_CSS = """
<style>
    html {
        font-size: 17px;
    }
    div[data-testid="stMainBlockContainer"] {
        max-width: 1440px !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
        padding-top: 1rem !important;
    }
    div[data-testid="stMainBlockContainer"] h1 {
        font-size: 2.05rem !important;
    }
    div[data-testid="stMainBlockContainer"] h2 {
        font-size: 1.7rem !important;
    }
    div[data-testid="stMainBlockContainer"] h3 {
        font-size: 1.4rem !important;
    }
    div[data-testid="stSidebarContent"] {
        font-size: 1rem !important;
    }
</style>
"""


def render(*, page: str = "") -> None:
    """Call right after `st.set_page_config`."""
    _ = page
    st.markdown(_GLOBAL_APP_FONT_CSS, unsafe_allow_html=True)
    mqtt_backend.ensure_started()
    if "_neo4j_index_report" not in st.session_state:
        st.session_state["_neo4j_index_report"] = neo4j_backend.ensure_indexes()
    _idx = st.session_state["_neo4j_index_report"]
    if not _idx.get("ok"):
        st.warning(
            "Neo4j indexes not fully ready: **{}**".format(
                "; ".join(_idx.get("errors", [])[:2]) or "unknown error"
            )
        )
