import os
import math
import time
import numpy as np
import pandas as pd
import streamlit as st
import queue
import plotly.express as px
import plotly.graph_objects as go
from ui_theme import THEME_CSS, header_html, kpi_card_html

POLL_INTERVAL     = 1

STATIONS = [
    "station11", "station21", "station22", "station31",
    "station41", "station51", "station52", "station61", "station71",
]

STATION_NAMES = {
    "station11": "M1-1", "station21": "M2-1", "station22": "M2-2",
    "station31": "M3-1", "station41": "M4-1", "station51": "M5-1",
    "station52": "M5-2", "station61": "M6-1", "station71": "M7-1",
}

STATE_COLORS = {
    "BUSY":  "#3b82f6",
    "IDLE":  "#22c55e",
    "FAIL":  "#ef4444",
    "BLOCK": "#eab308",
}


REPAIR_END_ACTIVITIES = {"UNLOAD", "BLOCK"}

def _duration_s(t1, t2):
    return max((t2 - t1).total_seconds(), 0.0)

def fmt_s(s):
    if s is None or (isinstance(s, float) and math.isnan(s)):
        return "—"
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec:02d}s"


def _welford_update(n, mean, M2, new_value):
    n    += 1
    delta = new_value - mean
    mean += delta / n
    M2   += delta * (new_value - mean)
    return n, mean, M2

def _welford_finalize(n, mean, M2):
    if n == 0:
        return None, None
    std = (M2 / n) ** 0.5 if n > 1 else 0.0
    return round(mean, 2), round(std, 2)

def _welford_finalize_mttf(n, mean, M2, repair_end, fail_open, T_NOW):

    if fail_open is not None:
        return _welford_finalize(n, mean, M2)

    if repair_end is None or T_NOW is None:
        return _welford_finalize(n, mean, M2)
    current_uptime = max((T_NOW - repair_end).total_seconds(), 0.0)
    n_virt    = n + 1
    delta     = current_uptime - mean
    mean_virt = mean + delta / n_virt
    M2_virt   = M2 + delta * (current_uptime - mean_virt)
    return _welford_finalize(n_virt, mean_virt, M2_virt)


KEY_FAIL = "kpi_failures_inc"

def _fail_process_event(acc, activity, t, T_START):
    if activity == "FAIL":
        if acc["_fail_open"] is None:
            acc["n_failures"] += 1
            uptime_start = acc["_repair_end"] if acc["_repair_end"] is not None else T_START
            uptime_s = _duration_s(uptime_start, t)
            acc["n_mttf"], acc["mttf_mean"], acc["mttf_M2"] = _welford_update(
                acc["n_mttf"], acc["mttf_mean"], acc["mttf_M2"], uptime_s
            )
            acc["_fail_open"] = t
    elif activity in REPAIR_END_ACTIVITIES:
        if acc["_fail_open"] is not None:
            repair_s = _duration_s(acc["_fail_open"], t)
            acc["n_mttr"], acc["mttr_mean"], acc["mttr_M2"] = _welford_update(
                acc["n_mttr"], acc["mttr_mean"], acc["mttr_M2"], repair_s
            )
            acc["_repair_end"] = t
            acc["_fail_open"]  = None

def _fail_empty_acc():
    return {
        "n_failures": 0,
        "n_mttr": 0, "mttr_mean": 0.0, "mttr_M2": 0.0,
        "n_mttf": 0, "mttf_mean": 0.0, "mttf_M2": 0.0,
        "_fail_open": None, "_repair_end": None,
    }

def kpi_machine_failures(new_events, T_NOW):
    if KEY_FAIL not in st.session_state:
        st.session_state[KEY_FAIL] = {s: _fail_empty_acc() for s in STATIONS}

    acc_all = st.session_state[KEY_FAIL]
    T_START = st.session_state.get("T_GLOBAL_START", T_NOW)

    for e in new_events:
        comp = str(e.get("component_id", "")).strip()
        if comp not in acc_all:
            continue
        _fail_process_event(acc_all[comp], str(e.get("activity", "")),
                    pd.Timestamp(e["time"]), T_START)

    results = {}
    for s in STATIONS:
        acc = acc_all[s]
        mttf_s, _ = _welford_finalize_mttf(acc["n_mttf"], acc["mttf_mean"], acc["mttf_M2"],
            acc["_repair_end"], acc["_fail_open"], T_NOW)
        mttr_s, _ = _welford_finalize(acc["n_mttr"], acc["mttr_mean"], acc["mttr_M2"])
        if mttf_s and mttr_s and (mttf_s + mttr_s) > 0:
            availability = round(mttf_s / (mttf_s + mttr_s), 3)
        else:
            availability = None
        results[s] = {
            "failures":     acc["n_failures"],
            "mttf_s":       mttf_s,
            "mttr_s":       mttr_s,
            "availability": availability if availability is not None
                    else (1.0 if acc["n_failures"] == 0 else None),
        }
    return results


KEY_STATE = "kpi_state_inc"

STATE_MAP = {
    "LOAD": "BUSY", "PROCESS": "BUSY", "UNLOAD": "BUSY",
    "TRANSFER": "IDLE", "FAIL": "FAIL", "BLOCK": "BLOCK",
}

def _state_empty_acc():
    return {
        "busy_s": 0.0, "idle_s": 0.0, "fail_s": 0.0, "block_s": 0.0,
        "_current_part": None,
        "_last_activity": None,
        "_last_time":     None,
    }

def _state_process_event(acc, activity, part_id, t):
    if activity == "LOAD":
        if acc["_last_activity"] == "TRANSFER" and acc["_last_time"] is not None:
            acc["idle_s"] += _duration_s(acc["_last_time"], t)
        acc["_current_part"]  = part_id
        acc["_last_activity"] = "LOAD"
        acc["_last_time"]     = t
        return

    if acc["_current_part"] != part_id:
        return

    if acc["_last_time"] is not None and acc["_last_activity"] is not None:
        dt = _duration_s(acc["_last_time"], t)
        la = acc["_last_activity"]
        if   la in ("LOAD", "PROCESS", "UNLOAD"): acc["busy_s"]  += dt
        elif la == "FAIL":                         acc["fail_s"]  += dt
        elif la == "BLOCK":                        acc["block_s"] += dt

    acc["_last_activity"] = activity
    acc["_last_time"]     = t

    if activity == "TRANSFER":
        acc["_current_part"] = None

def _state_finalize(acc, T_GLOBAL_START, T_NOW):
    busy_s  = acc["busy_s"]
    idle_s  = acc["idle_s"]
    fail_s  = acc["fail_s"]
    block_s = acc["block_s"]

    if acc["_last_time"] is not None and acc["_last_activity"] is not None:
        dt = _duration_s(acc["_last_time"], T_NOW)
        la = acc["_last_activity"]
        if   la in ("LOAD", "PROCESS", "UNLOAD"): busy_s  += dt
        elif la == "FAIL":                         fail_s  += dt
        elif la == "BLOCK":                        block_s += dt
        elif la == "TRANSFER":                     idle_s  += dt

    total_avail = max(_duration_s(T_GLOBAL_START, T_NOW), 1.0)

    accounted = busy_s + idle_s + fail_s + block_s
    if accounted < total_avail:
        idle_s += total_avail - accounted

    current_state = STATE_MAP.get(acc["_last_activity"], "IDLE")
    return {
        "current_state": current_state,
        "busy_s":  round(busy_s,  1),
        "idle_s":  round(idle_s,  1),
        "fail_s":  round(fail_s,  1),
        "block_s": round(block_s, 1),
        "busy_pct":  round(busy_s  / total_avail * 100, 1),
        "idle_pct":  round(idle_s  / total_avail * 100, 1),
        "fail_pct":  round(fail_s  / total_avail * 100, 1),
        "block_pct": round(block_s / total_avail * 100, 1),
    }


def kpi_machine_state_all(new_events, T_GLOBAL_START, T_NOW):
    if KEY_STATE not in st.session_state:
        st.session_state[KEY_STATE] = {s: _state_empty_acc() for s in STATIONS}

    acc_all = st.session_state[KEY_STATE]

    for e in new_events:
        comp = str(e.get("component_id", "")).strip()
        if comp not in acc_all:
            continue
        _state_process_event(
            acc_all[comp],
            str(e.get("activity", "")),
            e.get("part_id"),
            pd.Timestamp(e["time"]),
        )

    return {s: _state_finalize(acc_all[s], T_GLOBAL_START, T_NOW) for s in STATIONS}


KEY_UTIL = "kpi_util_inc"

def kpi_utilization_all(state_results, T_GLOBAL_START, T_NOW):
    total_avail = max(_duration_s(T_GLOBAL_START, T_NOW), 1.0)
    results = {}
    for s in STATIONS:
        st_kpi = state_results.get(s, {})
        busy_s = st_kpi.get("busy_s", 0.0)
        results[s] = {
            "util": round(min(busy_s / total_avail, 1.0), 4),
            "busy_s": busy_s,
        }
    return results


def kpi_downtime_all(T_NOW):
    if KEY_STATE not in st.session_state:
        return {}

    acc_all = st.session_state[KEY_STATE]
    result  = {}

    for s in STATIONS:
        acc = acc_all[s]
        if acc["_last_activity"] == "FAIL" and acc["_last_time"] is not None:
            result[s] = {
                "in_downtime": True,
                "downtime_s":  round(_duration_s(acc["_last_time"], T_NOW), 1),
                "since":       acc["_last_time"],
            }

    return result


KEY_TIMELINE = "kpi_timeline_inc"


def _timeline_process_event(acc, station, activity, t):
    if activity == "FAIL":
        if acc["_open_fail"].get(station) is None:
            acc["_open_fail"][station] = t
    elif activity in REPAIR_END_ACTIVITIES:
        t_fail = acc["_open_fail"].get(station)
        if t_fail is not None:
            duration_s = max((t - t_fail).total_seconds(), 0.0)
            acc["rows"].append({
                "machine": STATION_NAMES.get(station, station),
                "start": t_fail,
                "end": t,
                "duration_s": round(duration_s, 1),
                "duration_fmt": f"{int(duration_s // 60)}m {int(duration_s % 60):02d}s"
                if duration_s >= 60 else f"{int(duration_s)}s",
            })
            acc["_open_fail"][station] = None


def kpi_timeline(new_events):
    if KEY_TIMELINE not in st.session_state:
        st.session_state[KEY_TIMELINE] = {
            "rows": [],
            "_open_fail": {s: None for s in STATIONS},
        }
    acc = st.session_state[KEY_TIMELINE]
    for e in new_events:
        comp = str(e.get("component_id", "")).strip()
        if comp not in STATIONS:
            continue
        _timeline_process_event(acc, comp, str(e.get("activity", "")), pd.Timestamp(e["time"]))
    return acc["rows"]


def plot_failure_timeline(new_events):
    rows = kpi_timeline(new_events)
    if not rows:
        return None
    rows_df = pd.DataFrame(rows)

    machine_order = [STATION_NAMES[s] for s in STATIONS]

    fig = px.timeline(rows_df, x_start="start", x_end="end", y="machine",
                      title="Machine Failure Timeline", color_discrete_sequence=["#ef4444"],
                      custom_data=["duration_fmt", "duration_s"],
                      category_orders={"machine": machine_order})
    fig.update_traces(
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Start: %{base|%H:%M:%S.%L}<br>"
            "End:   %{x|%H:%M:%S.%L}<br>"
            "Duration: %{customdata[0]} (%{customdata[1]:.1f}s)"
            "<extra></extra>"
        )
    )
    fig.update_yaxes(autorange=True)
    fig.update_layout(
        height=280, paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(color="#334155", size=10),
        margin=dict(t=30, b=10, l=60, r=10),
        title_font=dict(size=11, color="#334155"),
    )
    return fig


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

    if new_rows and "T_GLOBAL_START" not in st.session_state:
        st.session_state["T_GLOBAL_START"] = pd.Timestamp(new_rows[0]["time"])

    T_GLOBAL_START = st.session_state.get("T_GLOBAL_START", pd.Timestamp.now())

    if new_rows:
        T_NOW = pd.Timestamp(new_rows[-1]["time"])
        st.session_state["T_LAST_EVENT"] = T_NOW
    else:
        T_NOW = st.session_state.get("T_LAST_EVENT", pd.Timestamp.now())

    fail_kpi = kpi_machine_failures(new_rows, T_NOW)
    state_all = kpi_machine_state_all(new_rows, T_GLOBAL_START, T_NOW)
    util_all = kpi_utilization_all(state_all, T_GLOBAL_START, T_NOW)
    down_all = kpi_downtime_all(T_NOW)

    BG       = "#ffffff"
    status   = st.session_state.mqtt_manager.status

    station_labels = [STATION_NAMES.get(s, s) for s in STATIONS]

    st.markdown(header_html(
        title="Machine Health & Performance 📋",
        subtitle= "", #f"OEE, State, Failures, Downtime and Buffer · {n_events} events",
        mqtt_status=status,
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)

    st.markdown('<div class="section-title">📊 Overview</div>', unsafe_allow_html=True)
    total_fails = sum(v["failures"] for v in fail_kpi.values())
    busy_count  = sum(1 for s in STATIONS if state_all[s]["current_state"] == "BUSY")
    fail_count  = sum(1 for s in STATIONS if state_all[s]["current_state"] == "FAIL")
    block_count = sum(1 for s in STATIONS if state_all[s]["current_state"] == "BLOCK")
    avg_util    = round(np.mean([util_all[s]["util"] for s in STATIONS]) * 100, 1)

    k = st.columns(5)
    with k[0]: st.markdown(kpi_card_html(f"{avg_util}%", "Average OEE", " ", "var(--accent)"), unsafe_allow_html=True)
    with k[1]: st.markdown(kpi_card_html(str(busy_count), "Machines BUSY", "", "var(--green)"), unsafe_allow_html=True)
    with k[2]: st.markdown(kpi_card_html(str(fail_count), "Machines in FAIL", "", "var(--red)"), unsafe_allow_html=True)
    with k[3]: st.markdown(kpi_card_html(str(block_count), "Machines in BLOCK", "", "var(--gold)"), unsafe_allow_html=True)
    with k[4]: st.markdown(kpi_card_html(str(total_fails), "Total FAIL events", " ", "var(--red)"), unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🔢 OEE & Machine State</div>', unsafe_allow_html=True)
    col_util, col_state = st.columns(2)

    with col_util:
        util_vals = [util_all[s]["util"] * 100 for s in STATIONS]
        fig_util = go.Figure()
        fig_util.add_hline(y=85, line_dash="dot", line_color="#0284c7",
                           annotation_text="85%", annotation_font_color="#0284c7")
        text_positions = ["inside" if v >= 15 else "outside" for v in util_vals]
        text_colors = ["white" if v >= 15 else "#334155" for v in util_vals]
        fig_util.add_trace(go.Bar(
            x=station_labels, y=util_vals,
            marker_color=["#2ca02c" if v >= 85 else ("#ff7f0e" if v >= 65 else "#d62728") for v in util_vals],
            text=[f"{v:.1f}%" for v in util_vals],
            textposition=text_positions,
            insidetextanchor="middle",
            textfont=dict(size=11, family="Arial", color=text_colors),
            showlegend=False,
        ))
        for label, color in [
            ("≥ 85%  Good", "#2ca02c"),
            ("65 ÷ 85%  Medium", "#ff7f0e"),
            ("< 65%  Low", "#d62728"),
        ]:
            fig_util.add_trace(go.Scatter(
                x=[None], y=[None],
                mode="markers",
                marker=dict(symbol="square", size=10, color=color),
                name=label,
                showlegend=True,
            ))
        fig_util.update_layout(
            title=dict(text="OEE per Machine", font=dict(size=11, color="#334155")),
            height=260, paper_bgcolor=BG, plot_bgcolor=BG,
            margin=dict(t=30, b=10, l=40, r=10),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom", y=1.02,
                xanchor="right", x=1.0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(color="#1e293b", size=10),
            ),
            yaxis=dict(range=[0, 110], tickvals=[0, 20, 40, 60, 80, 100], gridcolor="#e2e8f0"),
        )
        st.plotly_chart(fig_util, use_container_width=True)

    with col_state:
        fig_state = go.Figure()
        for label, key, color in [
            ("BUSY",  "busy_pct",  "#3b82f6"),
            ("IDLE",  "idle_pct",  "#22c55e"),
            ("FAIL",  "fail_pct",  "#ef4444"),
            ("BLOCK", "block_pct", "#eab308"),
        ]:
            vals = [state_all[s][key] for s in STATIONS]
            fig_state.add_trace(go.Bar(
                name=label, x=station_labels,
                y=vals, marker_color=color,
                text=[f"{v:.1f}%" if v >= 3 else "" for v in vals],
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(size=10, family="Arial", color="white"),
            ))
        fig_state.update_layout(
            barmode="stack",
            title=dict(text="Machine State Breakdown (%)", font=dict(size=11, color="#334155"), x=0.0, xanchor="left"),
            height=260, paper_bgcolor=BG, plot_bgcolor=BG,
            margin=dict(t=30, b=10, l=40, r=10),
            legend=dict(orientation="h", yanchor="top", y=1.15, xanchor="right", x=1.0,
                        bgcolor="rgba(0,0,0,0)", font=dict(color="#1e293b")),
            xaxis=dict(gridcolor="#e2e8f0"),
            yaxis=dict(gridcolor="#e2e8f0", title="%", range=[0, 100]),
        )
        st.plotly_chart(fig_state, use_container_width=True)


    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">⚠️ Machine Failures</div>', unsafe_allow_html=True)
    col_tbl, col_tl = st.columns([1, 2])

    with col_tbl:
        rows = [{
            "Machine":      STATION_NAMES.get(s, s),
            "Failures":     fail_kpi[s]["failures"],
            "MTTF":         fmt_s(fail_kpi[s]["mttf_s"]),
            "MTTR":         fmt_s(fail_kpi[s]["mttr_s"]),
            "Availability": f"{fail_kpi[s]['availability']*100:.1f}%" if fail_kpi[s]["availability"] else "—",
        } for s in STATIONS]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with col_tl:
        fig_tl = plot_failure_timeline(new_rows)
        if fig_tl:
            st.plotly_chart(fig_tl, use_container_width=True)
        else:
            fig_empty = go.Figure()
            fig_empty.update_layout(
                title=dict(text="Machine Failure Timeline", font=dict(size=11, color="#334155")),
                height=350, paper_bgcolor=BG, plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=60, r=10),
                yaxis=dict(tickvals=list(range(len(STATIONS))),
                           ticktext=[STATION_NAMES.get(s, s) for s in STATIONS]),
            )
            st.plotly_chart(fig_empty, use_container_width=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🔴 Current Downtime</div>', unsafe_allow_html=True)
    if not down_all:
        st.markdown(
            "<div style='padding:14px 18px;background:#f0fdf4;border-radius:10px;"
            "border:1px solid #bbf7d0;color:#16a34a;font-weight:600;font-size:14px;'>"
            "✅ All stations operational — no active downtime</div>",
            unsafe_allow_html=True,
        )
    else:
        d_cols = st.columns(min(len(down_all), 4))
        for col, (s, info) in zip(d_cols, down_all.items()):
            with col:
                st.markdown(kpi_card_html(
                    fmt_s(info["downtime_s"]),
                    f"⚠ {STATION_NAMES.get(s, s)}",
                    f"since {info['since'].strftime('%H:%M:%S.%f')[:-5]}",
                    "var(--red)",
                ), unsafe_allow_html=True)


    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)


def render():
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.set_page_config(layout="wide", page_title="Machine Health & Performance")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    render_live_dashboard()
