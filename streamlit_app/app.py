"""
Streamlit 入口：**Main · Control**（week6 首页）+ 侧栏多页。
运行：`python -m streamlit run streamlit_app/app.py`
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

import ui_home  # noqa: E402
import ui_sidebar  # noqa: E402

st.set_page_config(
    page_title="LEGO Factory",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui_sidebar.render(page="Home")
ui_home.render()
