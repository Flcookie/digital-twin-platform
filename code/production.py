import math
import pandas as pd
import streamlit as st
import queue
import plotly.graph_objects as go
from ui_theme import THEME_CSS, header_html, kpi_card_html

POLL_INTERVAL = 1

STATIONS = [
    "station11", "station21", "station22", "station31",
    "station41", "station51", "station52", "station61", "station71",
]

STATION_NAMES = {
    "station11": "M1-1", "station21": "M2-1", "station22": "M2-2",
    "station31": "M3-1", "station41": "M4-1", "station51": "M5-1",
    "station52": "M5-2", "station61": "M6-1", "station71": "M7-1",
}

STAGE_GROUPS = [
    ("op1", ["station11"]),
    ("op2", ["station21", "station22"]),
    ("op3", ["station31"]),
    ("op4", ["station41"]),
    ("op5", ["station51", "station52"]),
    ("op6", ["station61"]),
    ("op7", ["station71"]),
]

STAGE_LABELS = {
    "op1": "Op. 1 (M1-1)",
    "op2": "Op. 2 (M2-1/M2-2)",
    "op3": "Op. 3 (M3-1)",
    "op4": "Op. 4 (M4-1)",
    "op5": "Op. 5 (M5-1/M5-2)",
    "op6": "Op. 6 (M6-1)",
    "op7": "Op. 7 (M7-1)",
}

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


KEY_ST     = "kpi_sysTime_inc"
WINDOW_CYCLES = 100

def _st_empty_acc():
    from collections import deque
    return {
        "n": 0, "mean": 0.0, "M2": 0.0,
        "_open_start": {},
        "series_window": deque(maxlen=WINDOW_CYCLES),
    }

def _st_process_event(acc, component_id, activity, part_id, t):
    if component_id == "corner2" and activity == "START":
        acc["_open_start"][part_id] = t
    elif component_id == "splitter5" and activity == "CHECKOUT":
        t_start = acc["_open_start"].pop(part_id, None)
        if t_start is not None:
            val = round(_duration_s(t_start, t), 2)
            acc["n"], acc["mean"], acc["M2"] = _welford_update(
                acc["n"], acc["mean"], acc["M2"], val
            )
            acc["series_window"].append(val)

def kpi_system_time(new_events):
    if KEY_ST not in st.session_state:
        st.session_state[KEY_ST] = _st_empty_acc()

    acc = st.session_state[KEY_ST]
    for e in new_events:
        _st_process_event(
            acc,
            str(e.get("component_id", "")),
            str(e.get("activity", "")),
            e.get("part_id"),
            pd.Timestamp(e["time"]),
        )

    series = pd.Series(list(acc["series_window"]), dtype=float)
    mean_s = round(series.mean(), 2) if not series.empty else None
    std_s = round(series.std(), 2) if len(series) >= 2 else None
    return {
        "global_mean_s": mean_s,
        "global_std_s":  std_s,
        "series":        pd.Series(list(acc["series_window"]), dtype=float),
    }


KEY_TH = "kpi_throughput_inc"

def kpi_throughput(new_events, T_NOW):
    if KEY_TH not in st.session_state:
        st.session_state[KEY_TH] = {"n": 0, "t_run_start": None}

    acc = st.session_state[KEY_TH]
    for e in new_events:
        t = pd.Timestamp(e["time"])
        if acc["t_run_start"] is None:
            acc["t_run_start"] = t
        if str(e.get("component_id", "")) == "splitter5" and str(e.get("activity", "")) == "CHECKOUT":
            acc["n"] += 1

    n = acc["n"]
    if n >= 1 and acc["t_run_start"]:
        duration_min = max(_duration_s(acc["t_run_start"], T_NOW) / 60.0, 1e-6)
        thr = round(n / duration_min, 2)
    else:
        thr = 0.0

    return {"throughput_per_min": thr, "n_parts": n}


KEY_TH_GOOD = "kpi_throughput_good_inc"

def kpi_throughput_good(new_events, T_NOW):
    if KEY_TH_GOOD not in st.session_state:
        st.session_state[KEY_TH_GOOD] = {"n_good": 0, "t_run_start": None}

    acc = st.session_state[KEY_TH_GOOD]
    for e in new_events:
        t = pd.Timestamp(e["time"])
        if acc["t_run_start"] is None:
            acc["t_run_start"] = t
        if str(e.get("component_id", "")) == "splitter5" and str(e.get("activity", "")) == "FINISH":
            acc["n_good"] += 1

    duration_min = (
        max(_duration_s(acc["t_run_start"], T_NOW) / 60.0, 1e-6)
        if acc["t_run_start"] else 1e-6
    )

    return {
        "throughput_good_per_min": round(acc["n_good"] / duration_min, 2) if acc["n_good"] >= 1 else 0.0,
        "n_good": acc["n_good"],
    }


KEY_IAT = "kpi_iat_inc"

def _iat_empty_acc():
    from collections import deque
    return {
        "n": 0, "mean": 0.0, "M2": 0.0,
        "_last_start": None,
        "last_s": 0.0,
        "series_window": deque(maxlen=WINDOW_CYCLES),
    }

def _iat_process_event(acc, component_id, activity, t):
    if component_id == "corner2" and activity == "START":
        if acc["_last_start"] is not None:
            gap = round(_duration_s(acc["_last_start"], t), 2)
            acc["n"], acc["mean"], acc["M2"] = _welford_update(
                acc["n"], acc["mean"], acc["M2"], gap
            )
            acc["last_s"] = gap
            acc["series_window"].append((t, gap))
        acc["_last_start"] = t

def kpi_interarrival_time(new_events):
    if KEY_IAT not in st.session_state:
        st.session_state[KEY_IAT] = _iat_empty_acc()

    acc = st.session_state[KEY_IAT]
    for e in new_events:
        _iat_process_event(
            acc,
            str(e.get("component_id", "")),
            str(e.get("activity", "")),
            pd.Timestamp(e["time"]),
        )

    _vals = [v for _, v in acc["series_window"]]
    series_std = pd.Series(_vals, dtype=float)
    mean_s = round(series_std.mean(), 2) if not series_std.empty else None
    std_s = round(series_std.std(), 2) if len(series_std) >= 2 else None
    times, vals   = zip(*acc["series_window"]) if acc["series_window"] else ([], [])
    series        = pd.Series(list(vals), index=list(times), dtype=float)

    return {
        "last_s": acc["last_s"],
        "mean_s": mean_s or 0.0,
        "std_s":  std_s  or 0.0,
        "cv":     round((std_s / mean_s), 3) if mean_s and std_s else 0.0,
        "n":      acc["n"],
        "series": series,
    }


KEY_BN = "kpi_bottleneck_inc"

def _bn_empty_station_acc():
    return {
        "effective_s": 0.0,
        "process_s":   0.0,
        "block_s":     0.0,
        "fail_s":      0.0,
        "block_count": 0,
        "_state":      "IDLE",
        "_current_part": None,
        "_load_t":     None,
        "_state_t":    None,
        "_fail_acc":   0.0,
        "_block_acc":  0.0,
    }

def _bn_process_event(acc, activity, part_id, t):
    if activity == "LOAD":
        acc["_state"] = "BUSY"
        acc["_current_part"] = part_id
        acc["_load_t"] = t
        acc["_state_t"] = t
        acc["_fail_acc"] = 0.0
        acc["_block_acc"] = 0.0
        return

    if acc["_current_part"] != part_id:
        return

    if activity == "PROCESS":
        acc["_state"] = "BUSY"
        acc["_state_t"] = t

    elif activity == "UNLOAD":
        if acc["_state"] == "FAIL":
            acc["_fail_acc"] += _duration_s(acc["_state_t"], t)
        elif acc["_state"] == "BLOCK":
            acc["_block_acc"] += _duration_s(acc["_state_t"], t)
        acc["_state"] = "BUSY"
        acc["_state_t"] = t

    elif activity == "BLOCK":
        if acc["_state"] == "FAIL":
            acc["_fail_acc"] += _duration_s(acc["_state_t"], t)
        acc["_state"] = "BLOCK"
        acc["_state_t"] = t
        acc["block_count"] += 1

    elif "FAIL" in activity:
        acc["_state"] = "FAIL"
        acc["_state_t"] = t

    elif activity == "TRANSFER":
        if acc["_load_t"] is None:
            return
        if acc["_state"] == "FAIL":
            acc["_fail_acc"] += _duration_s(acc["_state_t"], t)
        elif acc["_state"] == "BLOCK":
            acc["_block_acc"] += _duration_s(acc["_state_t"], t)

        window_s = _duration_s(acc["_load_t"], t)
        acc["effective_s"] += window_s
        acc["fail_s"] += acc["_fail_acc"]
        acc["block_s"] += acc["_block_acc"]
        acc["process_s"] += max(window_s - acc["_fail_acc"] - acc["_block_acc"], 0.0)

        acc["_state"] = "IDLE"
        acc["_current_part"] = None
        acc["_load_t"] = None
        acc["_state_t"] = t
        acc["_fail_acc"] = 0.0
        acc["_block_acc"] = 0.0

def _bn_build_result(state, T_NOW):
    t0_global   = state["_t0_global"]
    total_avail = max(_duration_s(t0_global, T_NOW), 1.0) if t0_global else 1.0

    station_to_stage = {
        s: stage
        for stage, stations in STAGE_GROUPS
        for s in stations
    }

    stage_detail = {}
    ranking = []

    for station in STATIONS:
        acc = state["stations"].get(station)
        if acc is None:
            continue

        effective_s = acc["effective_s"]
        process_s   = acc["process_s"]
        fail_s      = acc["fail_s"]
        block_s     = acc["block_s"]

        if acc["_load_t"] is not None:
            window_s    = _duration_s(acc["_load_t"], T_NOW)
            fail_acc    = acc["_fail_acc"]
            block_acc   = acc["_block_acc"]

            if acc["_state"] == "FAIL":
                fail_acc  += _duration_s(acc["_state_t"], T_NOW)
            elif acc["_state"] == "BLOCK":
                block_acc += _duration_s(acc["_state_t"], T_NOW)

            effective_s += window_s
            fail_s      += fail_acc
            block_s     += block_acc
            process_s   += max(window_s - fail_acc - block_acc, 0.0)

        elif acc["_state"] == "FAIL" and acc["_state_t"] is not None:
            fail_s += _duration_s(acc["_state_t"], T_NOW)

        eff_pct   = effective_s / total_avail
        proc_pct  = process_s   / total_avail
        fail_pct  = fail_s      / total_avail
        block_pct = block_s     / total_avail
        stage     = station_to_stage.get(station, station)

        stage_detail[station] = {
            "effective_pct": round(eff_pct   * 100, 1),
            "process_pct":   round(proc_pct  * 100, 1),
            "fail_pct":      round(fail_pct  * 100, 1),
            "block_pct":     round(block_pct * 100, 1),
            "availability":  round((1 - fail_pct) * 100, 1),
            "occupied_pct":  round(eff_pct   * 100, 1),
            "busy_pct":      round(proc_pct  * 100, 1),
            "stage":         stage,
            "block_count":   acc["block_count"],
        }

        ranking.append({
            "stage":    station,
            "label":    STATION_NAMES.get(station, station),
            "util":     round(eff_pct, 4),
            "util_pct": round(eff_pct * 100, 1),
        })

    ranking.sort(key=lambda x: x["util"], reverse=True)

    bottleneck = ranking[0]["stage"] if ranking else "—"

    process_ranking_local = sorted(
        ranking, key=lambda x: stage_detail[x["stage"]]["busy_pct"], reverse=True
    )
    process_top = process_ranking_local[0]["stage"] if process_ranking_local else None

    return {
        "bottleneck":      bottleneck,
        "bottleneck_util": ranking[0]["util_pct"] if ranking else 0.0,
        "ranking":         ranking,
        "stage_detail":    stage_detail,
        "process_top": process_top,
    }

def kpi_bottleneck(new_events, T_NOW):
    if KEY_BN not in st.session_state:
        st.session_state[KEY_BN] = {
            "stations":   {s: _bn_empty_station_acc() for s in STATIONS},
            "_t0_global": None,
            "eff_top_history": {},
            "proc_top_history": {},
            "_last_eff_top": None,
            "_last_proc_top": None,
            "eff_top_sequence":  [],
            "proc_top_sequence": [],
        }

    state = st.session_state[KEY_BN]

    if "eff_top_sequence" not in state:
        state["eff_top_sequence"] = []
    if "proc_top_sequence" not in state:
        state["proc_top_sequence"] = []
    if "_last_eff_top" not in state:
        state["_last_eff_top"] = None
    if "_last_proc_top" not in state:
        state["_last_proc_top"] = None

    for e in new_events:
        comp    = str(e.get("component_id", "")).strip()
        act     = str(e.get("activity",     "")).strip()
        part_id = e.get("part_id")
        t       = pd.Timestamp(e["time"])

        if state["_t0_global"] is None:
            state["_t0_global"] = t

        if comp in state["stations"]:
            _bn_process_event(state["stations"][comp], act, part_id, t)

    result = _bn_build_result(state, T_NOW)

    eff_top = result["bottleneck"]
    proc_top = result.get("process_top")

    if eff_top and eff_top != "—" and eff_top != state["_last_eff_top"]:
        h = state["eff_top_history"].setdefault(eff_top, {"count": 0, "last": None})
        h["count"] += 1
        h["last"] = T_NOW
        state["_last_eff_top"] = eff_top
        state["eff_top_sequence"].append(STATION_NAMES.get(eff_top, eff_top))

    if proc_top and proc_top != state["_last_proc_top"]:
        h = state["proc_top_history"].setdefault(proc_top, {"count": 0, "last": None})
        h["count"] += 1
        h["last"] = T_NOW
        state["_last_proc_top"] = proc_top
        state["proc_top_sequence"].append(STATION_NAMES.get(proc_top, proc_top))

    result["eff_top_history"] = state["eff_top_history"]
    result["proc_top_history"] = state["proc_top_history"]
    result["eff_top_sequence"]  = state["eff_top_sequence"]
    result["proc_top_sequence"] = state["proc_top_sequence"]

    return result

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

    BG       = "#ffffff"
    status   = st.session_state.mqtt_manager.status

    st.markdown(header_html(
        title="Production Control Board ⏳",
        subtitle="",
        mqtt_status=status,
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)

    if new_rows:
        T_NOW = pd.Timestamp(new_rows[-1]["time"])
        st.session_state["T_LAST_EVENT"] = T_NOW
    else:
        T_NOW = st.session_state.get("T_LAST_EVENT", pd.Timestamp.now())

    st_kpi  = kpi_system_time(new_rows)
    th_kpi  = kpi_throughput(new_rows, T_NOW)
    th_good_kpi = kpi_throughput_good(new_rows, T_NOW)
    iat_kpi = kpi_interarrival_time(new_rows)
    bn_kpi  = kpi_bottleneck(new_rows, T_NOW)
    bn_name = STATION_NAMES.get(bn_kpi["bottleneck"], bn_kpi["bottleneck"])

    st.markdown('<div class="section-title">📊 Overview</div>', unsafe_allow_html=True)
    k = st.columns(5)
    with k[0]:
        st.markdown(kpi_card_html(
            fmt_s(st_kpi["global_mean_s"]), "Average System Time",
            f"σ = {fmt_s(st_kpi['global_std_s'])}", "var(--accent)",
        ), unsafe_allow_html=True)
    with k[1]:
        st.markdown(kpi_card_html(
            f"{th_kpi['throughput_per_min']} p/min", "Gross Throughput",
            f"{th_kpi['n_parts']} finished parts", "var(--green)",
        ), unsafe_allow_html=True)
    with k[2]:
        st.markdown(kpi_card_html(
            f"{th_good_kpi['throughput_good_per_min']} p/min", "Good Throughput",
            f"{th_good_kpi['n_good']} good parts", "var(--green)",
        ), unsafe_allow_html=True)
    with k[3]:
        st.markdown(kpi_card_html(
            fmt_s(iat_kpi["mean_s"]), "Average Interarrival Time",
            f"σ = {fmt_s(iat_kpi['std_s'])}", "var(--gold)",
        ), unsafe_allow_html=True)
    with k[4]:
        st.markdown(kpi_card_html(
            bn_name, "Highest Effective Utilization",
            f"{bn_kpi['bottleneck_util']:.1f}% ", "var(--red)",
        ), unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    st.markdown('<div class="section-title">⏱ System Time and Interarrival Time</div>', unsafe_allow_html=True)
    col_st, col_iat = st.columns(2)

    with col_st:
        if not st_kpi["series"].empty and len(st_kpi["series"]) >= 2:
            fig_st = go.Figure()
            series_min = (st_kpi["series"] / 60).tolist()
            fig_st.add_trace(go.Scatter(
                y=series_min, mode="lines+markers",
                line=dict(color="#38bdf8", width=2), marker=dict(size=4), name="System Time",
            ))
            if st_kpi["global_mean_s"]:
                fig_st.add_hline(y=st_kpi["global_mean_s"]/ 60, line_dash="dash", line_color="#22c55e",
                                 annotation_text=fmt_s(st_kpi["global_mean_s"]),
                                 annotation_position="top right", annotation=dict(font=dict(color="#22c55e", size=11),
                                 bgcolor="white", borderpad=3),
    )
            fig_st.update_layout(
                title=dict(text=f"System Time — last {WINDOW_CYCLES} cycles (min)", font=dict(size=11, color="#334155")),
                height=220, paper_bgcolor=BG, plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=40, r=10), showlegend=False,
                xaxis=dict(showticklabels=False),
            )
        else:
            fig_st = go.Figure()
            fig_st.update_layout(
                title=dict(text=f"System Time — last {WINDOW_CYCLES} cycles (min)", font=dict(size=11, color="#334155")),
                height=220, paper_bgcolor=BG, plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=40, r=10),
                xaxis=dict(showticklabels=False),
            )
        st.plotly_chart(fig_st, use_container_width=True)

    with col_iat:
        if not iat_kpi["series"].empty and len(iat_kpi["series"]) >= 3:
            fig_iat = go.Figure()
            fig_iat.add_trace(go.Scatter(
                x=list(iat_kpi["series"].index), y=[v / 60 for v in iat_kpi["series"].values],
                mode="lines+markers", line=dict(color="#a78bfa", width=2), marker=dict(size=4),
            ))
            if iat_kpi["mean_s"]:
                fig_iat.add_hline(y=iat_kpi["mean_s"]/60, line_dash="dash", line_color="#22c55e",
                                  annotation_text=fmt_s(iat_kpi["mean_s"]),
                                  annotation_position="top right",
                                  annotation=dict(font=dict(color="#22c55e", size=11), bgcolor="white", borderpad=3),)
            fig_iat.update_layout(
                title=dict(text=f"Interarrival Time — last {WINDOW_CYCLES} cycles (min)", font=dict(size=11, color="#334155")),
                height=220, paper_bgcolor=BG, plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=40, r=10), showlegend=False,
                xaxis=dict(showticklabels=False),
            )
        else:
            fig_iat = go.Figure()
            fig_iat.update_layout(
                title=dict(text=f"Interarrival Time — last {WINDOW_CYCLES} cycles (min)", font=dict(size=11, color="#334155")),
                height=220, paper_bgcolor=BG, plot_bgcolor=BG,
                margin=dict(t=30, b=10, l=40, r=10),
                xaxis=dict(showticklabels=False),
            )
        st.plotly_chart(fig_iat, use_container_width=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    st.markdown('<div class="section-title">🚧 Utilization Analysis</div>', unsafe_allow_html=True)
    col_bn, col_rank = st.columns([1, 3.5])

    with col_bn:
        st.markdown(
            "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
            "🔴 Effective Utilization (busy time + fail time + block time)</div>",
            unsafe_allow_html=True,
        )
        st.markdown(kpi_card_html(
            bn_name, "Current Highest Effective Utilization",
            f"{bn_kpi['bottleneck_util']:.1f}%", "var(--red)",
        ), unsafe_allow_html=True)

        detail = bn_kpi["stage_detail"].get(bn_kpi["bottleneck"], {}) if bn_kpi["bottleneck"] != "—" else {}
        if detail:
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(
                f"<div style='font-size:12px;color:#334155;padding:10px 14px;background:#f8fafc;"
                f"border-radius:8px;border:1px solid #e2e8f0;line-height:2'>"
                f"🔵 Busy: <b>{detail['busy_pct']}%</b><br>"
                f"🔴 Fail: <b>{detail['fail_pct']}%</b><br>"
                f"🟡 Block: <b>{detail['block_pct']}%</b></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        seq_eff = bn_kpi.get("eff_top_sequence", [])
        seq_eff_html = " → ".join(
            f"<span style='background:#fee2e2;color:#b91c1c;"
            f"padding:1px 6px;border-radius:4px;font-size:10px;white-space:nowrap'>{s}</span>"
            for s in seq_eff[-20:]
        ) if seq_eff else "<span style='color:#94a3b8;font-size:10px'>No data yet</span>"
        st.markdown(
            f"<div style='background:#f8fafc;border-radius:8px;padding:8px 10px;border:1px solid #e2e8f0'>"
            f"<div style='font-size:10px;color:#64748b;margin-bottom:6px'>⏱ Highest Effective Utilization Sequence</div>"
            f"<div style='line-height:2'>{seq_eff_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        process_ranking = sorted(
            bn_kpi["ranking"],
            key=lambda r: bn_kpi["stage_detail"][r["stage"]]["busy_pct"],
            reverse=True,
        ) if bn_kpi["ranking"] else []

        proc_bn_stage = process_ranking[0]["stage"] if process_ranking else "—"
        proc_bn_name = STATION_NAMES.get(proc_bn_stage, proc_bn_stage)
        proc_bn_detail = bn_kpi["stage_detail"].get(proc_bn_stage, {}) if proc_bn_stage != "—" else {}
        proc_bn_pct = proc_bn_detail.get("busy_pct", 0.0)

        st.markdown(
            "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
            "🟠 Process Utilization (busy time)</div>",
            unsafe_allow_html=True,
        )
        st.markdown(kpi_card_html(
            proc_bn_name, "Current Highest Process Utilization",
            f"{proc_bn_pct:.1f}% ", "var(--orange)",
        ), unsafe_allow_html=True)

        st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
        seq_proc = bn_kpi.get("proc_top_sequence", [])
        seq_proc_html = " → ".join(
            f"<span style='background:#ffedd5;color:#c2410c;"
            f"padding:1px 6px;border-radius:4px;font-size:10px;white-space:nowrap'>{s}</span>"
            for s in seq_proc[-20:]
        ) if seq_proc else "<span style='color:#94a3b8;font-size:10px'>No data yet</span>"
        st.markdown(
            f"<div style='background:#f8fafc;border-radius:8px;padding:8px 10px;border:1px solid #e2e8f0'>"
            f"<div style='font-size:10px;color:#64748b;margin-bottom:6px'>⏱ Highest Process Utilization Sequence</div>"
            f"<div style='line-height:2'>{seq_proc_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if proc_bn_detail:
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            same = proc_bn_stage == bn_kpi["bottleneck"]
            badge = "✅ Same As Effective" if same else "⚠️ Different From Effective"
            badge_color = "#16a34a" if same else "#b45309"
            badge_bg = "#f0fdf4" if same else "#fffbea"
            badge_bd = "#bbf7d0" if same else "#fde68a"
            st.markdown(
                f"<div style='font-size:11px;padding:6px 12px;border-radius:8px;"
                f"border:1px solid {badge_bd};background:{badge_bg};color:{badge_color};'>"
                f"{badge}</div>",
                unsafe_allow_html=True,
            )


    with col_rank:
        if bn_kpi["ranking"]:
            stage_labels_rank = [r["label"] for r in bn_kpi["ranking"]]
            busy_vals = [bn_kpi["stage_detail"][r["stage"]]["busy_pct"] for r in bn_kpi["ranking"]]
            fail_vals = [bn_kpi["stage_detail"][r["stage"]]["fail_pct"] for r in bn_kpi["ranking"]]

            proc_labels = [r["label"] for r in process_ranking]
            proc_vals   = [bn_kpi["stage_detail"][r["stage"]]["busy_pct"] for r in process_ranking]

            col_eff, col_proc = st.columns(2)

            with col_eff:
                st.markdown(
                    "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
                    "🔴 Effective Utilization (busy time + fail time + block time)</div>",
                    unsafe_allow_html=True,
                )
                fig_eff = go.Figure()
                block_vals = [bn_kpi["stage_detail"][r["stage"]].get("block_pct", 0.0) for r in bn_kpi["ranking"]]
                fig_eff.add_trace(go.Bar(
                    name="Busy", x=busy_vals, y=stage_labels_rank, orientation="h",
                    marker_color="#3b82f6",
                    text=[f"{v:.1f}%" if v > 0 else "" for v in busy_vals],
                    textposition="inside",
                    textfont=dict(color="white", size=11, family="Arial"),
                ))
                fig_eff.add_trace(go.Bar(
                    name="Fail", x=fail_vals, y=stage_labels_rank, orientation="h",
                    marker_color="#ef4444",
                    text=[f"{v:.1f}%" if v > 0 else "" for v in fail_vals],
                    textposition="inside",
                    textfont=dict(color="white", size=11, family="Arial"),
                ))
                fig_eff.add_trace(go.Bar(
                    name="Block", x=block_vals, y=stage_labels_rank, orientation="h",
                    marker_color="#eab308",
                    text=[f"{v:.1f}%" if v > 0 else "" for v in block_vals],
                    textposition="inside",
                    textfont=dict(color="white", size=11, family="Arial"),
                ))
                fig_eff.update_layout(
                    barmode="stack", height=320, paper_bgcolor=BG, plot_bgcolor=BG,
                    margin=dict(t=10, b=10, l=120, r=20),
                    xaxis=dict(range=[0, 115]), yaxis=dict(autorange="reversed"),
                    showlegend=False,
                )
                st.plotly_chart(fig_eff, use_container_width=True)
                if bn_kpi.get("eff_top_history"):
                    hist = sorted(
                        bn_kpi["eff_top_history"].items(),
                        key=lambda x: -x[1]["count"]
                    )
                    rows = "".join(
                        f"<tr style='border-bottom:1px solid #f1f5f9'>"
                        f"<td style='padding:3px 6px'>{STATION_NAMES.get(s, s)}</td>"
                        f"<td style='padding:3px 6px;text-align:center'>{v['count']}</td>"
                        f"</tr>"
                        for s, v in hist
                    )
                    st.markdown(
                        f"<div style='font-size:11px;color:#334155;margin-top:6px;"
                        f"background:#f8fafc;border-radius:8px;padding:8px 10px;"
                        f"border:1px solid #ef4444'>"
                        f"<div style='font-size:10px;color:#64748b;margin-bottom:4px'>⏱ History — Highest Effective Utilization</div>"
                        f"<table style='width:100%;border-collapse:collapse'>"
                        f"<thead><tr style='color:#94a3b8;font-size:10px'>"
                        f"<th style='text-align:left;padding:2px 6px'>Machine</th>"
                        f"<th style='text-align:center;padding:2px 6px'>Times</th>"
                        f"</tr></thead>"
                        f"<tbody>{rows}</tbody>"
                        f"</table></div>",
                        unsafe_allow_html=True,
                    )

            with col_proc:
                st.markdown(
                    "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
                    "🟠 Process Utilization (busy time)</div>",
                    unsafe_allow_html=True,
                )
                fig_proc = go.Figure()
                fig_proc.add_trace(go.Bar(
                    x=proc_vals, y=proc_labels, orientation="h",
                    marker_color="#f97316",
                    text=[f"{v:.1f}%" for v in proc_vals],
                    textposition="inside",
                    textfont=dict(color="white", size=11, family="Arial"),
                ))
                fig_proc.update_layout(
                    height=320, paper_bgcolor=BG, plot_bgcolor=BG,
                    margin=dict(t=10, b=10, l=120, r=40),
                    xaxis=dict(range=[0, 115]), yaxis=dict(autorange="reversed"),
                )
                st.plotly_chart(fig_proc, use_container_width=True)
                if bn_kpi.get("proc_top_history"):
                    hist = sorted(
                        bn_kpi["proc_top_history"].items(),
                        key=lambda x: -x[1]["count"]
                    )
                    rows = "".join(
                        f"<tr style='border-bottom:1px solid #f1f5f9'>"
                        f"<td style='padding:3px 6px'>{STATION_NAMES.get(s, s)}</td>"
                        f"<td style='padding:3px 6px;text-align:center'>{v['count']}</td>"
                        f"</tr>"
                        for s, v in hist
                    )
                    st.markdown(
                        f"<div style='font-size:11px;color:#334155;margin-top:6px;"
                        f"background:#f8fafc;border-radius:8px;padding:8px 10px;"
                        f"border:1px solid #f97316'>"
                        f"<div style='font-size:10px;color:#64748b;margin-bottom:4px'>⏱ History — Highest Process Utilization</div>"
                        f"<table style='width:100%;border-collapse:collapse'>"
                        f"<thead><tr style='color:#94a3b8;font-size:10px'>"
                        f"<th style='text-align:left;padding:2px 6px'>Machine</th>"
                        f"<th style='text-align:center;padding:2px 6px'>Times</th>"
                        f"</tr></thead>"
                        f"<tbody>{rows}</tbody>"
                        f"</table></div>",
                        unsafe_allow_html=True,
                    )

        else:
            col_eff, col_proc = st.columns(2)
            with col_eff:
                st.markdown(
                    "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
                    "🔴 Effective Utilization (busy time + fail time + block time)</div>",
                    unsafe_allow_html=True,
                )
                fig_e1 = go.Figure()
                fig_e1.update_layout(height=320, paper_bgcolor=BG, plot_bgcolor=BG)
                st.plotly_chart(fig_e1, use_container_width=True, key="empty_eff_bottleneck")
            with col_proc:
                st.markdown(
                    "<div style='font-size:11px;color:#64748b;margin-bottom:4px;'>"
                    "🟠 Process Utilization (busy time)</div>",
                    unsafe_allow_html=True,
                )
                fig_e2 = go.Figure()
                fig_e2.update_layout(height=320, paper_bgcolor=BG, plot_bgcolor=BG)
                st.plotly_chart(fig_e2, use_container_width=True, key="empty_proc_bottleneck")

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

def render():
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.set_page_config(layout="wide", page_title="Production Control Board")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    render_live_dashboard()