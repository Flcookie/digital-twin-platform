import pandas as pd
import streamlit as st
import queue
from ui_theme import THEME_CSS, header_html, kpi_card_html
import plotly.graph_objects as go

POLL_INTERVAL = 1

STATIONS = ["station11", "station21", "station22", "station31", "station41", "station51", "station52", "station61",
            "station71"]
STATIONS_NO_71 = [s for s in STATIONS if s != "station71"]

STATION_NAMES = {
    "station11": "M1-1", "station21": "M2-1", "station22": "M2-2",
    "station31": "M3-1", "station41": "M4-1", "station51": "M5-1",
    "station52": "M5-2", "station61": "M6-1", "station71": "M7-1",
}


def _last_process_station(event):
    TRACK_KEY = "kpi_scrap_part_tracking"
    if TRACK_KEY not in st.session_state:
        st.session_state[TRACK_KEY] = {}

    tracking = st.session_state[TRACK_KEY]
    part_id = event.get("part_id")

    if not part_id:
        return None

    if part_id not in tracking:
        tracking[part_id] = {"last_process": None, "culprit": None}

    comp = event.get("component_id")
    act = event.get("activity")

    if act == "PROCESS":
        if comp in STATIONS_NO_71:
            tracking[part_id]["last_process"] = comp
        elif comp == "station71":
            tracking[part_id]["culprit"] = tracking[part_id]["last_process"]

    return tracking[part_id]["culprit"]


def kpi_scrap(new_events):
    KEY = "kpi_scrap_state"
    if KEY not in st.session_state:
        st.session_state[KEY] = {
            "total": 0,
            "per_station": {s: 0 for s in STATIONS},
            "last_scrap_part": None,
            "last_scrap_station": None
        }

    state = st.session_state[KEY]

    for e in new_events:
        resp = _last_process_station(e)

        if e.get("component_id") == "splitter5" and e.get("activity") == "SCRAP":
            state["total"] += 1
            if resp:
                state["per_station"][resp] += 1
            state["last_scrap_part"] = e.get("part_id")
            state["last_scrap_station"] = resp

    return state


def kpi_scrap_rate(new_events):
    KEY = "kpi_scrap_rate_state"
    TREND_KEY = "kpi_scrap_rate_trend"

    if KEY not in st.session_state:
        st.session_state[KEY] = {"n_scrap": 0, "n_finish": 0}
        st.session_state[TREND_KEY] = []

    state = st.session_state[KEY]
    trend = st.session_state[TREND_KEY]

    for e in new_events:
        if e.get("component_id") == "splitter5":
            act = e.get("activity")
            if act == "SCRAP":
                state["n_scrap"] += 1
            elif act == "FINISH":
                state["n_finish"] += 1

            n_scrap = state["n_scrap"]
            n_total = n_scrap + state["n_finish"]
            if n_total > 0:
                rate_pct = round((n_scrap / n_total) * 100, 1)
                trend.append({"time": e.get("time"), "rate": rate_pct})

    n_scrap, n_finish = state["n_scrap"], state["n_finish"]
    n_total = n_scrap + n_finish

    if n_total == 0:
        return {"rate": None, "rate_pct": "0.0%", "n_scrap": 0, "n_finish": 0, "n_total": 0}

    rate = n_scrap / n_total
    return {
        "rate": round(rate, 4),
        "rate_pct": f"{rate * 100:.1f}%",
        "n_scrap": n_scrap,
        "n_finish": n_finish,
        "n_total": n_total
    }


FLOW_STEPS = [
    {"label": "S11", "stations": {"station11"}, "step_idx": 0},
    {"label": "S21/S22", "stations": {"station21", "station22"}, "step_idx": 1},
    {"label": "S31", "stations": {"station31"}, "step_idx": 2},
    {"label": "S41 (1st)", "stations": {"station41"}, "step_idx": 3},
    {"label": "S51/S52 (1st)", "stations": {"station51", "station52"}, "step_idx": 4},
    {"label": "S41 (2nd)", "stations": {"station41"}, "step_idx": 5},
    {"label": "S51/S52 (2nd)", "stations": {"station51", "station52"}, "step_idx": 6},
    {"label": "S61", "stations": {"station61"}, "step_idx": 7},
    {"label": "S71", "stations": {"station71"}, "step_idx": 8},
]

N_STEPS = len(FLOW_STEPS)
ALL_PARTS = [f"p{i}" for i in range(1, 17)]
ACTIVE_ACTIVITIES = "PROCESS"


def init_flow_state():
    if "flow_state" not in st.session_state:
        st.session_state.flow_state = {}
        for part in ALL_PARTS:
            st.session_state.flow_state[part] = {
                "reached": [False] * N_STEPS,
                "reworked": [False] * N_STEPS,
                "anomaly": False,
                "is_scrapped": False,
                "in_qc": False,
                "after_QC": False,
                "next_expected": 0,
                "previous_step": 0,
                "pre_qc_expected_step": 0,
                "pre_qc_previous_step": 0
            }
    if "recent_anomalies" not in st.session_state:
        st.session_state.recent_anomalies = {}

    if "total_events_count" not in st.session_state:
        st.session_state.total_events_count = 0

    if "kpi_state" not in st.session_state:
        st.session_state.kpi_state = {
            "nominal_flow": 0,
            "nominal_good": 0,
            "nominal_scrap": 0,
            "rework": 0,
            "n_of_rework": 0,
            "falsely_bad": 0,
            "rework_to_good": 0,
            "rework_to_scrap": 0,
            "scrap_before_end": 0,
            "sent_to_qc": 0,
            "part_with_anomaly": 0
        }


def process_incremental_events(new_events):
    for row in new_events:
        part = row.get("part_id")
        if part not in st.session_state.flow_state:
            continue

        state = st.session_state.flow_state[part]

        comp = str(row.get("component_id")).strip()
        act = str(row.get("activity")).strip()

        if comp == "corner2" and act == "START":
            st.session_state.flow_state[part] = {
                "reached": [False] * N_STEPS,
                "reworked": [False] * N_STEPS,
                "anomaly": False,
                "is_scrapped": False,
                "in_qc": False,
                "after_QC": False,
                "next_expected": 0,
                "previous_step": 0,
                "pre_qc_expected_step": 0,
                "pre_qc_previous_step": 0
            }
            continue

        if comp == "splitter5":
            if act == "SCRAP":
                state["is_scrapped"] = True
                if not all(state["reached"]):
                    st.session_state.kpi_state["sent_to_qc"] += 1
                    st.session_state.kpi_state["scrap_before_end"] += 1
                elif not any(state["reworked"]) and all(state["reached"]):
                    st.session_state.kpi_state["nominal_scrap"] += 1

                if any(state["reworked"]):
                    st.session_state.kpi_state["rework_to_scrap"] += 1

            elif act == "FINISH":
                if all(state["reached"]):
                    if any(state["reworked"]):
                        st.session_state.kpi_state["rework_to_good"] += 1
                    else:
                        st.session_state.kpi_state["nominal_good"] += 1
                else:
                    st.session_state.kpi_state["part_with_anomaly"] += 1

            elif act == "CHECKOUT":
                if all(state["reached"]):
                    if any(state["reworked"]):
                        st.session_state.kpi_state["rework"] += 1
                    else:
                        st.session_state.kpi_state["nominal_flow"] += 1

        if comp == "station71" and act == "UNLOAD":
            state["in_qc"] = False
            state["after_QC"] = True

        if state["is_scrapped"] or act not in ACTIVE_ACTIVITIES:
            continue

        matched_step = -1

        if comp == "station11" and act in ACTIVE_ACTIVITIES:
            matched_step = 0
        elif comp in ["station21", "station22"] and act in ACTIVE_ACTIVITIES:
            matched_step = 1
        elif comp == "station31" and act in ACTIVE_ACTIVITIES:
            matched_step = 2
        elif comp == "station41" and act in ACTIVE_ACTIVITIES:
            exp = state["pre_qc_expected_step"] if state["after_QC"] else state["next_expected"]
            prev = state["pre_qc_previous_step"] if state["after_QC"] else state["previous_step"]

            if exp == 5 or prev == 4:
                matched_step = 5
            elif exp == 3 or prev == 2:
                matched_step = 3
            else:
                matched_step = 5 if state["reached"][5] else 3
        elif comp in ["station51", "station52"] and act in ACTIVE_ACTIVITIES:
            exp = state["pre_qc_expected_step"] if state["after_QC"] else state["next_expected"]
            prev = state["pre_qc_previous_step"] if state["after_QC"] else state["previous_step"]

            if exp == 6 or prev == 5:
                matched_step = 6
            elif exp == 4 or prev == 3:
                matched_step = 4
            else:
                matched_step = 6 if state["reached"][6] else 4
        elif comp == "station61" and act in ACTIVE_ACTIVITIES:
            matched_step = 7
        elif comp == "station71" and act in ACTIVE_ACTIVITIES:
            matched_step = 8

        if matched_step == -1:
            continue

        if state["after_QC"] == True and act in ACTIVE_ACTIVITIES:
            st.session_state.kpi_state["sent_to_qc"] += 1
            if state["reached"][matched_step]:
                state["reworked"][matched_step] = True
                st.session_state.kpi_state["n_of_rework"] += 1
            else:
                state["reached"][matched_step] = True
                st.session_state.kpi_state["falsely_bad"] += 1

            state["after_QC"] = False
            state["previous_step"] = matched_step
            state["next_expected"] = matched_step + 1

        elif matched_step == state["next_expected"]:
            state["reached"][matched_step] = True
            state["previous_step"] = matched_step
            state["next_expected"] = matched_step + 1

        else:
            is_forward_jump = matched_step > state["next_expected"]
            is_backward_jump = matched_step < state["previous_step"]
            is_repetition = matched_step == state["previous_step"]

            if matched_step == 8 and (is_forward_jump or is_backward_jump):
                if not state["in_qc"]:
                    state["pre_qc_expected_step"] = state["next_expected"]
                    state["pre_qc_previous_step"] = state["previous_step"]
                pass
            else:
                state["anomaly"] = True
                time_val = row.get("time", pd.Timestamp.now())
                time_str = pd.to_datetime(time_val).strftime("%H:%M:%S")
                exp_label = FLOW_STEPS[state["next_expected"]]["label"] if state[
                                                                               "next_expected"] < N_STEPS else "End of flow"

                match_label = FLOW_STEPS[matched_step]["label"]

                if is_forward_jump:
                    detail = f"Station skipped: expected {exp_label}, detected {match_label}."
                elif is_backward_jump:
                    detail = f"Unauthorized return: expected {exp_label}, detected {match_label}."
                elif is_repetition:
                    detail = f"Unauthorized repetition: expected {exp_label}, detected {match_label}."
                else:
                    detail = f"Anomaly: expected {exp_label}, detected {match_label}."

                st.session_state.recent_anomalies[part] = {
                    "time_str": time_str,
                    "detail": detail
                }

            state["reached"][matched_step] = True
            state["previous_step"] = matched_step
            state["next_expected"] = matched_step + 1

        if comp == "station71" and act in ACTIVE_ACTIVITIES:
            state["in_qc"] = True

@st.fragment(run_every=POLL_INTERVAL)
def render_live_dashboard():
    new_rows = []
    while not st.session_state.event_queue.empty():
        try:
            event = st.session_state.event_queue.get_nowait()
            st.session_state.last_message = event
            new_rows.append(event)
        except queue.Empty:
            break

    if "total_events_processed" not in st.session_state:
        st.session_state.total_events_processed = 0
    st.session_state.total_events_processed += len(new_rows)

    status = st.session_state.mqtt_manager.status
    #n_events = st.session_state.total_events_processed

    st.markdown(header_html(
        title="QUALITY MONITORING 🌟",
        subtitle=f"",
        # subtitle=f"Scraps, Flow Check and Rework · {n_events} events",
        mqtt_status=status,
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)

    scrap = kpi_scrap(new_rows)
    sr = kpi_scrap_rate(new_rows)

    if new_rows:
        process_incremental_events(new_rows)

    BG = "#ffffff"

    kpi_state = st.session_state.get("kpi_state", {})
    good_disp = kpi_state.get("nominal_good", 0) + kpi_state.get("rework", 0)
    # Row n1
    st.markdown('<div class="section-title">📊 Overview</div>', unsafe_allow_html=True)
    k = st.columns(5)
    with k[0]:
        st.markdown(kpi_card_html(str(sr["n_total"]), "Total Parts Completed", "", "var(--blue)"),
                    unsafe_allow_html=True)
    with k[1]:
        st.markdown(
            kpi_card_html(str(good_disp), "Total Number of Good Parts without detected anomalies", "", "var(--green)"),
            unsafe_allow_html=True)
    with k[2]:
        st.markdown(kpi_card_html(str(kpi_state.get("part_with_anomaly", 0)),
                                  "Total Number of Good Parts with detected anomalies", "", "#808080"),
                    unsafe_allow_html=True)
    with k[3]:
        st.markdown(kpi_card_html(str(scrap["total"]), "Total Number of Scrap Parts", "", "var(--red)"),
                    unsafe_allow_html=True)
    with k[4]:
        st.markdown(kpi_card_html(sr["rate_pct"], "Scrap Rate", "", "var(--red)"),
                    unsafe_allow_html=True)

    # Row n2
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🗑 Scrap & Trends</div>', unsafe_allow_html=True)

    col_scr_tbl, col_scr_chart = st.columns([1, 3])

    with col_scr_tbl:
        sorted_stations = sorted(scrap["per_station"].items(), key=lambda x: x[1], reverse=True)
        rows_html = "".join([
            f"<tr><td style='padding:3px 14px;color:{'#1a1a1a' if count > 0 else '#ccc'};'>{STATION_NAMES.get(station, station)}</td>"
            f"<td style='padding:3px 14px;font-weight:700;color:{'#1a1a1a' if count > 0 else '#ccc'};text-align:center;'>{count}</td></tr>"
            for station, count in sorted_stations if station != "station71"
        ])
        st.markdown(
            f"<table style='font-size:0.88rem; width:100%;'><thead><tr>"
            f"<th style='padding:3px 14px;color:#888;font-weight:400;text-align:left;'>Station</th>"
            f"<th style='padding:3px 14px;color:#888;font-weight:400;text-align:center;'>Attributed Scraps</th>"
            f"</tr></thead><tbody>{rows_html}</tbody></table>",
            unsafe_allow_html=True,
        )

    with col_scr_chart:
        col_trend, col_bar = st.columns(2)
        with col_trend:
            trend_data = st.session_state.get("kpi_scrap_rate_trend", [])
            fig_trend = go.Figure()

            if len(trend_data) >= 2:
                times = [d["time"] for d in trend_data]
                rates = [d["rate"] for d in trend_data]

                fig_trend.add_trace(go.Scatter(
                    x=times, y=rates, mode="lines",
                    line=dict(color="#ef4444", width=2), fill="tozeroy",
                    fillcolor="rgba(239,68,68,0.08)"
                ))

            fig_trend.update_layout(title=dict(text="Scrap Rate Over Time (%)", font=dict(size=11, color="#334155")),
                                    height=270, paper_bgcolor=BG, plot_bgcolor=BG, margin=dict(t=30, b=10, l=40, r=10),
                                    showlegend=False, xaxis=dict(tickformat="%H:%M"))
            st.plotly_chart(fig_trend, use_container_width=True)

        with col_bar:
            bar_stations = [STATION_NAMES.get(s, s) for s in STATIONS_NO_71]
            bar_values = [scrap["per_station"].get(s, 0) for s in STATIONS_NO_71]

            max_val = max(bar_values) if bar_values else 0

            y_upper = max(2, max_val * 1.1)

            fig_bar = go.Figure(
                go.Bar(
                    x=bar_stations,
                    y=bar_values,
                    marker_color="#ef4444",
                    text=bar_values,
                    insidetextanchor="middle",
                    textfont=dict(color="white")
                )
            )

            fig_bar.update_layout(
                title=dict(text="Scrap per Station", font=dict(size=11, color="#334155")),
                height=270,
                paper_bgcolor=BG,
                plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=20, r=10),
                showlegend=False,
                yaxis=dict(
                    showgrid=True,
                    gridcolor="#f0f0f0",
                    range=[0, y_upper + 0.2],
                    dtick=1
                )
            )

            st.plotly_chart(fig_bar, use_container_width=True)

    # Row n3
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🔍 Flow & Rework Quality</div>', unsafe_allow_html=True)

    v_nominal_flow = kpi_state.get("nominal_flow", 0)
    v_nominal_good = kpi_state.get("nominal_good", 0)
    v_nominal_scrap = kpi_state.get("nominal_scrap", 0)

    v_rework = kpi_state.get("rework", 0)
    v_rework_to_good = kpi_state.get("rework_to_good", 0)
    v_rework_to_scrap = kpi_state.get("rework_to_scrap", 0)

    v_sent_to_qc = kpi_state.get("sent_to_qc", 0)
    v_falsely_bad = kpi_state.get("falsely_bad", 0)
    v_scrap_before_end = kpi_state.get("scrap_before_end", 0)
    v_n_of_rework = kpi_state.get("n_of_rework", 0)

    def calc_qc_pct(value, total):
        if total > 0:
            return f"{(value / total * 100):.1f} %"
        return "0.0 %"

    main_cols = st.columns([1.25, 1, 1.8])

    with main_cols[0]:
        with st.container(border=True):
            st.markdown(kpi_card_html(str(v_nominal_flow), "Nominal cycle parts", "", "var(--blue)"),
                        unsafe_allow_html=True)

            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            sub_cols_1 = st.columns(2)
            with sub_cols_1[0]:
                st.markdown(kpi_card_html(str(v_nominal_good), "Good nominal cycle parts",
                                          calc_qc_pct(v_nominal_good, v_nominal_flow), "var(--green)"),
                            unsafe_allow_html=True)
            with sub_cols_1[1]:
                st.markdown(kpi_card_html(str(v_nominal_scrap), "Scrap nominal cycle parts",
                                          calc_qc_pct(v_nominal_scrap, v_nominal_flow), "var(--red)"),
                            unsafe_allow_html=True)

            st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)

    with main_cols[1]:
        with st.container(border=True):
            st.markdown(kpi_card_html(str(v_rework), "NUMBER of PARTS REWORKED", "", "#e67e22"), unsafe_allow_html=True)

            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            sub_cols_2 = st.columns(2)
            with sub_cols_2[0]:
                st.markdown(
                    kpi_card_html(str(v_rework_to_good), "GOOD after REWORK", calc_qc_pct(v_rework_to_good, v_rework),
                                  "var(--green)"),
                    unsafe_allow_html=True)
            with sub_cols_2[1]:
                st.markdown(kpi_card_html(str(v_rework_to_scrap), "SCRAP after REWORK",
                                          calc_qc_pct(v_rework_to_scrap, v_rework), "var(--red)"),
                            unsafe_allow_html=True)

            st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)

    with main_cols[2]:
        with st.container(border=True):
            st.markdown(kpi_card_html(str(v_sent_to_qc),
                                      "Number of quality checks performed on parts that have not completed the nominal cycle",
                                      "", "var(--blue)"), unsafe_allow_html=True)
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

            sub_cols_3 = st.columns(3)

            with sub_cols_3[0]:
                st.markdown(f"""
                <div class="kpi-card" style="--accent-line: linear-gradient(to right, #808080 50%, var(--red) 50%);">
                    <div class="kpi-value" style="color: #808080;">{v_falsely_bad}</div>
                    <div class="kpi-label">FALSELY BAD</div>
                    <div class="kpi-sub">{calc_qc_pct(v_falsely_bad, v_sent_to_qc)}</div>
                </div>
                """, unsafe_allow_html=True)

            with sub_cols_3[1]:
                st.markdown(kpi_card_html(str(v_scrap_before_end), "Scrapped mid-cycle",
                                          calc_qc_pct(v_scrap_before_end, v_sent_to_qc), "var(--red)"),
                            unsafe_allow_html=True)

            with sub_cols_3[2]:
                st.markdown(kpi_card_html(str(v_n_of_rework), "Reworks after inspection",
                                          calc_qc_pct(v_n_of_rework, v_sent_to_qc),
                                          "#e67e22"), unsafe_allow_html=True)

            st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)


def render():
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.set_page_config(layout="wide", page_title="Quality monitoring")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    init_flow_state()
    render_live_dashboard()