import common
import queue
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st

from ui_theme import THEME_CSS, STATUS_COLORS, header_html, mqtt_pill_html

CONFIG           = common.load_json("config.json")
MQTT_BROKER_HOST = CONFIG["server_hostname"]
MQTT_BROKER_PORT = CONFIG["server_mqtt_port"]
RUN_INTERVAL     = 1

class MQTTManager:
    def __init__(self, host, port, event_queue):
        self._host        = host
        self._port        = port
        self._event_queue = event_queue
        self._status_lock = threading.Lock()
        self._status      = "disconnected"
        self._client = mqtt.Client()
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def status(self):
        with self._status_lock:
            return self._status

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            with self._status_lock:
                self._status = "connected"
            topic = common.render_topic("component_event", "+", "all")
            client.subscribe(topic, qos=2)
        else:
            with self._status_lock:
                self._status = "error"

    def _on_disconnect(self, client, userdata, rc):
        with self._status_lock:
            self._status = "disconnected"

    def _on_message(self, client, userdata, msg):
        context, source_id, target_id = common.parse_topic(msg.topic)
        payload = msg.payload.decode("utf-8")
        if context == "component_event":
            event = common.deserialize_object(payload)
            self._event_queue.put(event)

    def _run(self):
        while True:
            try:
                self._client.connect(self._host, port=self._port)
                self._client.loop_forever()
            except Exception as e:
                print(f"[MQTT] Connection error: {e}")
                with self._status_lock:
                    self._status = "error"
            time.sleep(5)


if "event_queue" not in st.session_state:
    st.session_state.event_queue = queue.Queue()

if "mqtt_manager" not in st.session_state:
    st.session_state.mqtt_manager = MQTTManager(
        MQTT_BROKER_HOST, MQTT_BROKER_PORT, st.session_state.event_queue
    )

if "last_message" not in st.session_state:
    st.session_state.last_message = None

if "page" in st.query_params:
    st.session_state.page = st.query_params["page"]
elif "page" not in st.session_state:
    st.session_state.page = "main"


if st.session_state.page == "monitoring":
    import monitoring
    monitoring.render()
    st.stop()

elif st.session_state.page == "flow":
    import flow
    flow.render()
    st.stop()

elif st.session_state.page == "production":
    import production
    production.render()
    st.stop()

elif st.session_state.page == "quality":
    import quality
    quality.render()
    st.stop()

elif st.session_state.page == "health_performance":
    import health_performance
    health_performance.render()
    st.stop()

elif st.session_state.page == "combined":
    import combined_view
    combined_view.render()
    st.stop()

else:
    st.set_page_config(layout="wide", page_title="KDA-01 — Dashboard")
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    @st.fragment(run_every=RUN_INTERVAL)
    def render_live_hub():
        while not st.session_state.event_queue.empty():
            try:
                st.session_state.event_queue.get_nowait()
            except queue.Empty:
                break

        status = st.session_state.mqtt_manager.status

        st.markdown(header_html(
            title="DASHBOARD",
            subtitle=f"{MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}",
            mqtt_status=status,
        ), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        DASHBOARDS = [
            {
                "key": "monitoring",
                "icon": "🏭",
                "label": "Shop Floor Monitoring",
                "desc": "",
                "ready": True,
            },
            {
                "key": "flow",
                "icon": "🎯",
                "label": "Flow Conformance Checking",
                "desc": "",
                "ready": True,
            },
            {
                "key": "production",
                "icon": "⏳",
                "label": "Production Control Board",
                "desc": "",
                "ready": True,
            },
            {
                "key": "quality",
                "icon": "🌟",
                "label": "Quality Monitoring",
                "desc": "",
                "ready": True,
            },
            {
                "key": "health_performance",
                "icon": "📋",
                "label": "Machine Health & Performance",
                "desc": "",
                "ready": True,
            },
            {
                "key": "combined",
                "icon": "🧩",
                "label": "Unified Monitoring + Flow",
                "desc": "",
                "ready": True,
            },
        ]

        cols = st.columns(len(DASHBOARDS), gap="large")
        for col, dash in zip(cols, DASHBOARDS):
            with col:
                if dash["ready"]:
                    st.markdown(f"""
                    <a href="/?page={dash['key']}" target="_blank" style="text-decoration: none; color: inherit;">
                      <div class="dash-card">
                        <div class="dash-card-icon">{dash['icon']}</div>
                        <div class="dash-card-title">{dash['label']}</div>
                        <div class="dash-card-desc">{dash['desc']}</div>
                      </div>
                    </a>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="dash-card disabled">
                      <div class="dash-card-icon">{dash['icon']}</div>
                      <div class="dash-card-title">{dash['label']}</div>
                      <div class="dash-card-desc">{dash['desc']}</div>
                    </div>
                    """, unsafe_allow_html=True)

    render_live_hub()