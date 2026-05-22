import pandas as pd
import streamlit as st
import queue
from ui_theme import THEME_CSS, header_html

RUN_INTERVAL = 1

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
                "is_finished": False,
                "in_qc": False,
                "after_QC": False,
                "next_expected": 0,
                "previous_step": 0,
                "pre_qc_expected_step": 0,
                "pre_qc_previous_step": 0,
                "N_rework": [1] * N_STEPS
            }
    if "recent_anomalies" not in st.session_state:
        st.session_state.recent_anomalies = {}

    if "total_events_count" not in st.session_state:
        st.session_state.total_events_count = 0


def process_incremental_events(new_events):
    for row in new_events:
        part = row.get("part_id")
        if part not in st.session_state.flow_state:
            continue

        state = st.session_state.flow_state[part]

        was_reworked_before = list(state["reworked"])

        comp = str(row.get("component_id")).strip()
        act = str(row.get("activity")).strip()

        if comp == "corner2" and act == "START":
            st.session_state.flow_state[part] = {
                "reached": [False] * N_STEPS,
                "reworked": [False] * N_STEPS,
                "anomaly": False,
                "is_scrapped": False,
                "is_finished": False,
                "in_qc": False,
                "after_QC": False,
                "next_expected": 0,
                "previous_step": 0,
                "pre_qc_expected_step": 0,
                "pre_qc_previous_step": 0,
                "N_rework": [1] * N_STEPS
            }
            continue

        if comp == "splitter5" and act == "SCRAP":
            state["is_scrapped"] = True
            continue

        if comp == "splitter5" and act == "FINISH":
            state["is_finished"] = True
            continue

        if comp == "station71" and act == "UNLOAD":
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
            if state["reached"][matched_step]:
                if was_reworked_before[matched_step]:
                    state["N_rework"][matched_step] += 1
                state["reworked"][matched_step] = True
            else:
                state["reached"][matched_step] = True

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


@st.fragment(run_every=RUN_INTERVAL)
def render_live_dashboard():
    new_rows = []
    while not st.session_state.event_queue.empty():
        try:
            event = st.session_state.event_queue.get_nowait()
            st.session_state.last_message = event
            new_rows.append(event)
        except queue.Empty:
            break

    if new_rows:
        process_incremental_events(new_rows)
        st.session_state.total_events_count += len(new_rows)

    last = st.session_state.get("last_message") or {}
    first = st.session_state.get("first_message_time")

    if new_rows and "first_message_time" not in st.session_state:
        st.session_state["first_message_time"] = pd.to_datetime(new_rows[0]["time"])

    last_time = pd.to_datetime(last.get("time")) if last.get("time") else None
    first_time = st.session_state.get("first_message_time")

    if last_time and first_time:
        duration_s = int((last_time - first_time).total_seconds())
        tnow_str = f"{duration_s // 60}m {duration_s % 60:02d}s"
    else:
        tnow_str = "—"

    status = st.session_state.mqtt_manager.status
    # n_events = st.session_state.total_events_count

    state = st.session_state.flow_state
    recent_anomalies = st.session_state.recent_anomalies

    st.markdown(header_html(
        title="FLOW CONFORMANCE CHECKING 🎯",
        subtitle=f"",
        # subtitle=f"Part Routing, Rework and Anomalies · {n_events} events",
        mqtt_status=status,
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)

    col_table, col_alerts = st.columns([4, 1])

    with col_table:
        CLR_STEP_DONE = "#1a6b3c"
        CLR_STEP_REWORK = "#e67e22"
        CLR_STEP_EMPTY = "#e8e8e8"
        CLR_QC = "#8e44ad"
        CLR_COL_ANOMALY = "#fff0f0"
        CLR_COL_SCRAP = "#d1d5db"
        CLR_COL_FINISHED = "rgba(26, 107, 60, 0.15)"
        CLR_COL_NORMAL = "#ffffff"

        header_cells = "<th style='padding:10px 6px; background:#2c3e50; color:white; font-size:0.8rem; min-width:60px;'>Step</th>"
        for part in ALL_PARTS:
            s = state[part]
            if s["is_scrapped"]:
                anomaly_icon = "🗑️ "
                col_bg = "#4b5563"
            elif s["is_finished"]:
                anomaly_icon = "✅ " if not s["anomaly"] else "⚠️ "
                col_bg = CLR_STEP_DONE
            else:
                anomaly_icon = "⚠️ " if s["anomaly"] else ""
                col_bg = CLR_COL_ANOMALY if s["anomaly"] else "#2c3e50"

            header_cells += (
                f"<th style='padding:10px 4px; background:{col_bg}; color:white; "
                f"font-size:0.8rem; min-width:52px; text-align:center;'>"
                f"{anomaly_icon}{part}</th>"
            )

        rows_html = ""
        for step_i, step in enumerate(FLOW_STEPS):
            row_cells = (
                f"<td style='padding:8px 10px; background:#34495e; color:white; "
                f"font-weight:600; font-size:0.8rem; white-space:nowrap;'>{step['label']}</td>"
            )
            for part in ALL_PARTS:
                s = state[part]
                reached = s["reached"][step_i]
                reworked = s["reworked"][step_i]

                if s["is_scrapped"]:
                    col_bg = CLR_COL_SCRAP
                elif s["is_finished"]:
                    col_bg = CLR_COL_FINISHED
                else:
                    col_bg = CLR_COL_ANOMALY if s["anomaly"] else CLR_COL_NORMAL

                if s["is_scrapped"] and step_i == 8:
                    cell_content = "<div style='width:28px; height:28px; margin:auto; display:flex; align-items:center; justify-content:center; font-size:1.1rem;'>❌</div>"
                elif s["is_scrapped"]:
                    cell_content = "<div style='width:28px; height:28px; margin:auto;'></div>"
                elif s["in_qc"] and step_i == 8:
                    cell_content = f"<div style='width:28px; height:28px; border-radius:4px; background:{CLR_QC}; margin:auto; display:flex; align-items:center; justify-content:center; font-size:0.75rem; color:white;'>🔍</div>"
                elif reworked:
                    n_rew = s["N_rework"][step_i]
                    cell_content = (
                        f"<div style='position:relative; width:28px; height:28px; border-radius:4px; background:{CLR_STEP_REWORK}; "
                        f"margin:auto; display:flex; align-items:center; justify-content:center; color:white;'>"
                        f"<span style='font-size:1.8rem; line-height:1;'>↺</span>"
                        f"<span style='position:absolute; font-size:0.6rem; font-weight:bold; margin-top:2px;'>{n_rew}</span>"
                        f"</div>"
                    )
                elif reached:
                    cell_content = f"<div style='width:28px; height:28px; border-radius:4px; background:{CLR_STEP_DONE}; margin:auto;'></div>"
                else:
                    cell_content = f"<div style='width:28px; height:28px; border-radius:4px; background:{CLR_STEP_EMPTY}; margin:auto; border:1px solid #ccc;'></div>"

                row_cells += f"<td style='padding:6px 4px; background:{col_bg}; text-align:center;'>{cell_content}</td>"

            rows_html += f"<tr>{row_cells}</tr>"

        table_html = f"""
        <div style='overflow-x:auto; border-radius:10px; border:1px solid #ddd; margin-bottom: 20px;'>
          <table style='border-collapse:collapse; width:100%; font-family:sans-serif;'>
            <thead><tr>{header_cells}</tr></thead>
            <tbody>{rows_html}</tbody>
          </table>
        </div>
        """

        legend_html = f"""
        <div style='display:flex; gap:16px; margin-bottom:12px; font-size:0.82rem; align-items:center; flex-wrap: wrap;'>
          <div style='display:flex; align-items:center; gap:6px;'><div style='width:18px;height:18px;border-radius:3px;background:{CLR_STEP_DONE};'></div> Processed </div>
          <div style='display:flex; align-items:center; gap:6px;'><div style='position:relative; width:18px;height:18px;border-radius:3px;background:#e67e22; display:flex; align-items:center; justify-content:center; color:white;'><span style='font-size:1.1rem; line-height:1;'>↺</span><span style='position:absolute; font-size:0.4rem; font-weight:bold; margin-top:1.5px;'>n</span></div> Rework </div>
          <div style='display:flex; align-items:center; gap:6px;'><div style='width:18px;height:18px;border-radius:3px;background:{CLR_QC}; display:flex; align-items:center; justify-content:center; color:white; font-size:0.6rem;'>🔍</div> Quality Check </div>
          <div style='display:flex; align-items:center; gap:6px;'><div style='width:18px;height:18px;border-radius:3px;background:{CLR_COL_FINISHED};border:1px solid {CLR_STEP_DONE}; display:flex; align-items:center; justify-content:center; font-size:0.6rem;'>✅</div> Finished </div>
          <div style='display:flex; align-items:center; gap:6px;'><div style='width:18px;height:18px;border-radius:3px;background:#4b5563; display:flex; align-items:center; justify-content:center; color:white; font-size:0.6rem;'>🗑️</div> Scrapped </div>
          <div style='display:flex; align-items:center; gap:6px;'><div style='width:18px;height:18px;border-radius:3px;background:{CLR_COL_ANOMALY};border:1px solid #f99;'></div> ⚠️ Flow anomaly</div>
        </div>
        """
        st.markdown(legend_html, unsafe_allow_html=True)
        st.markdown(table_html, unsafe_allow_html=True)

        # ── Last event bar ────────────────────────────────────────
        last = st.session_state.get("last_message") or {}
        t = str(last.get("time", "—"))
        c = str(last.get("component_id", "—"))
        a = str(last.get("activity", "—"))
        p = str(last.get("part_id", "—"))
        ac = {"FAIL": "#ef4444", "BLOCK": "#eab308", "PROCESS": "#3b82f6"}.get(a, "#94a3b8")

        st.markdown(f"""
            <div class="last-event-bar">
              <span style="color:var(--text-dim)">🕒 {t}</span>
              <span style="color:var(--accent)">📍 {c}</span>
              <span style="color:{ac}">⚡ {a}</span>
              <span style="color:#c9955a">📦 {p}</span>
              <span style="color:#9333ea">⏱ Run time: {tnow_str}</span>
            </div>""", unsafe_allow_html=True)
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    with col_alerts:
        st.markdown("<h4 style='margin-top:0;'>Anomalies ⚠️</h4>", unsafe_allow_html=True)

        if not recent_anomalies:
            st.success("No anomalies recorded.")
        else:
            for part, data in recent_anomalies.items():
                part_num = part.replace("p", "")
                st.error(
                    f"**Part {part_num}** at {data['time_str']}\n\n"
                    f"{data['detail']}\n\n"
                )


def render():
    st.set_page_config(layout="wide", page_title="Flow Conformance Checking")
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    init_flow_state()

    render_live_dashboard()