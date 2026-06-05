import os
import sys

_fp = os.path.abspath(__file__)
_d = os.path.dirname(_fp)
_APP = os.path.dirname(_d) if os.path.basename(_d) == "pages" else _d
if _APP not in sys.path:
    sys.path.insert(0, _APP)
from paths import ensure_paths  # noqa: E402

ensure_paths()

import streamlit as st

import ui_sidebar
import ui_what_if_panel

st.set_page_config(
    page_title="What-if Analysis",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui_sidebar.render(page="What-if Analysis")

st.title("What-if Analysis")
st.page_link("app.py", label="← DASHBOARD", icon="🏠")

ui_what_if_panel.render_what_if_panel()
