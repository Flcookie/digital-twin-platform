# 原 `web_api` 能力 → Streamlit 位置（week5 · C1）

> 形态 **B**：`main_service.py` + `streamlit run streamlit_app/app.py` 两进程（见 README §2.13）。

| 原能力（概念） | Streamlit |
|----------------|-----------|
| `GET /api/health` | 非必须；可由主页 Neo4j/MQTT 状态侧面反映 |
| `GET /api/diagnostics` | 主页 **进程 / CONFIG_FILE**；Neo4j/MQTT 分段 |
| `GET /api/main_service/status` | 主页 `process_control.main_service_status()`；**06_Control** |
| `POST /api/main_service/start|stop` | **06_Control** |
| `GET /api/dashboard_status` | 拆成 MQTT KPI、Neo4j、`main_service`、录制状态（主页 + Control） |
| `GET/POST` replay、upload_log | **02_History**（子进程 `replay_events.py`）；原「单进程线程回放+自动切 config」未 1:1 复刻 |
| WebSocket `/ws/kpi` | **01_Realtime** `st.fragment` 轮询 `mqtt_backend.get_kpi_snapshot()` |
| `POST /api/control/*`（物理线、KPI、Neo4j、reset、录制、脚本） | **06_Control** + **01_Realtime** 顶栏 Start/Stop 物理线 |
| `GET /api/part_flow` | **03_Part_Trace** + `neo4j_backend.query_part_flow`（支持 Session 选择） |
| `GET /api/stations`、`/api/sessions`、`/api/graph` | Session：**03/04** 下拉；stations/graph 未独立页（可按需加） |
| 静态 `static/*` | **多页面** `streamlit_app/pages/*.py` |
