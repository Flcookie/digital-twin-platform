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

import factory_floor_plotly
import mqtt_backend
import neo4j_backend
import part_track_conformance
import ui_live_refresh
import ui_nav
import ui_part_trace_panel
import ui_sidebar

st.set_page_config(
    page_title="Digital Twin",
    layout="wide",
    initial_sidebar_state="expanded",
)
mqtt_backend.ensure_started()
ui_sidebar.render(page="05 Digital Twin")

if "dt_q_injected" not in st.session_state:
    st.session_state.dt_q_injected = True
    _qp0 = st.query_params.get("part_id")
    if _qp0 and str(_qp0).strip():
        st.session_state.part_trace_part_id = str(_qp0).strip()

if ui_nav.UI_NAV_PART_ID in st.session_state:
    _v = st.session_state.pop(ui_nav.UI_NAV_PART_ID)
    if _v:
        st.session_state.part_trace_part_id = _v.strip()

st.title("Digital Twin")
st.page_link("app.py", label="← DASHBOARD", icon="🏠")

st.subheader("Factory Layout")


@st.fragment(run_every=ui_live_refresh.live_ui_refresh_delta())
def _digital_twin_synced():
    """单 fragment：地图与 Part Tracking 同一拍拉 Neo4j / session，避免两区错开刷新。"""
    # 与 01 Realtime 同一套 session 解析（KPI、回放侧写、断线时 Neo4j），地图与 Part Tracking 用同一 `sess`。
    sess = mqtt_backend.resolve_digital_twin_neo4j_session_id()
    neo = neo4j_backend.neo4j_status()
    kpi, _tupd = mqtt_backend.get_kpi_snapshot()
    is_replay = isinstance(kpi, dict) and (kpi.get("run_mode") or "") == "replay"

    part_markers: list[dict] | None = None
    status: str | None = None
    twin_preload_parts: list[dict] | None = None
    twin_preload_sid: str | None = None

    # 回放：地图与 Part Tracking 共用「按 chart_time_unix 截断后的 parts」；取每 part **最后工步** 做
    # (component_id, activity) → SEQ_MAP（与 code/monitoring 事件流一致）。仅用 station_live 会漏运输途中的 part。
    if is_replay and neo.get("connected"):
        _pd = neo4j_backend.query_part_flow(None, sess)
        if not _pd.get("error"):
            twin_preload_parts = part_track_conformance.filter_parts_to_replay_kpi_progress(
                _pd.get("parts") or [], kpi
            )
            twin_preload_sid = _pd.get("session_id")
            _m = factory_floor_plotly.part_markers_from_parts_last_step(
                twin_preload_parts
            )
            part_markers = _m if _m else None
        if not part_markers:
            part_markers = factory_floor_plotly.part_markers_from_kpi_station_live(
                kpi
            ) or None
    elif is_replay:
        part_markers = factory_floor_plotly.part_markers_from_kpi_station_live(
            kpi
        ) or None
    elif not neo.get("connected"):
        status = "Neo4j not connected — cannot load part positions."
    else:
        markers, meta = neo4j_backend.get_session_parts_latest_locations(
            sess, limit=120
        )
        err = meta.get("error")
        if err and err != "No session in graph.":
            status = "Neo4j: **{}**".format(err)
        elif not err and markers:
            part_markers = markers

    if status:
        st.markdown(status)

    with st.container(key="digital_twin_factory_map"):
        _fig = factory_floor_plotly.build_factory_floor_figure(part_markers=part_markers)
        st.plotly_chart(
            _fig,
            use_container_width=True,
            key="digital_twin_factory_floor",
            config={"displayModeBar": False},
        )

    st.divider()
    st.subheader("Part Trace")
    with st.container(border=True):
        ui_part_trace_panel.render_part_trace_panel(
            from_query_params=False,
            use_page_session=True,
            use_coordinated_twin_session=True,
            coordinated_twin_session_id=sess,
            kpi_for_replay=kpi,
            twin_preloaded_parts=twin_preload_parts,
            twin_preloaded_session_id=twin_preload_sid,
        )


_digital_twin_synced()
ui_part_trace_panel.render_pending_complete_trace_dialog()
