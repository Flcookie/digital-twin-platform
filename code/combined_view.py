import streamlit as st
import streamlit.components.v1 as components

from ui_theme import THEME_CSS, header_html


def _iframe_block(title: str, page_key: str, height: int):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    components.html(
        f"""
        <iframe
            src="/?page={page_key}"
            style="width: 100%; height: {height}px; border: 1px solid #e2e8f0; border-radius: 10px; background: #ffffff;"
        ></iframe>
        """,
        height=height + 8,
    )


def render():
    st.set_page_config(layout="wide", page_title="Monitoring + Flow")
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    status = st.session_state.mqtt_manager.status if "mqtt_manager" in st.session_state else "disconnected"
    st.markdown(
        header_html(
            title="UNIFIED VIEW 🧩",
            subtitle="Shop Floor Monitoring + Flow Conformance",
            mqtt_status=status,
        ),
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    _iframe_block("🏭 Shop Floor Monitoring", "monitoring", 520)
    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
    _iframe_block("🎯 Flow Conformance Checking", "flow", 520)
