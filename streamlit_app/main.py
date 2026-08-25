"""
与 `app.py` 相同：**Main · Control** 首页（兼容 `streamlit run streamlit_app/main.py`）。

运行任一并可：
  python -m streamlit run streamlit_app/main.py
  python -m streamlit run streamlit_app/app.py
"""
import os
import sys

_fp = os.path.abspath(__file__)
_d = os.path.dirname(_fp)
if _d not in sys.path:
    sys.path.insert(0, _d)

from paths import ensure_paths  # noqa: E402

ensure_paths()

import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="LEGO Factory",
    layout="wide",
    initial_sidebar_state="expanded",
)

import ui_home  # noqa: E402
import ui_sidebar  # noqa: E402

ui_sidebar.render_shell(page="Home")
ui_home.render()
ui_sidebar.finalize_neo4j_indexes()
