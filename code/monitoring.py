import common
import math
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import queue
from collections import defaultdict, deque
from ui_theme import (
    THEME_CSS, STATUS_COLORS, STATUS_EMOJI,
    header_html, kpi_card_html
)

CONFIG = common.load_json("config.json")
N_pallet = CONFIG["component_wips"]["station11"]

POLL_INTERVAL = 0.75

machines_conf = [
    {'name': 'M1-1', 'x': 2, 'id': 'station11'},
    {'name': 'M2-1', 'x': 6, 'id': 'station21'},
    {'name': 'M2-2', 'x': 8, 'id': 'station22'},
    {'name': 'M3-1', 'x': 12, 'id': 'station31'},
    {'name': 'M4-1', 'x': 16, 'id': 'station41'},
    {'name': 'M5-1', 'x': 18, 'id': 'station51'},
    {'name': 'M5-2', 'x': 20, 'id': 'station52'},
    {'name': 'M6-1', 'x': 24, 'id': 'station61'},
    {'name': 'M7-1', 'x': 28, 'id': 'station71'},
]

draw_mergers = [
    {'x': 4, 'y': 2, 'name': 'Merger 1'},
    {'x': 10, 'y': 0, 'name': 'Merger 2'},
    {'x': 14, 'y': 2, 'name': 'Merger 3'},
    {'x': 22, 'y': 0, 'name': 'Merger 4'},
    {'x': 26, 'y': 2, 'name': 'Merger 5'},
]

draw_splitters = [
    {'x': 10, 'y': 2, 'name': 'Splitter 1'},
    {'x': 4, 'y': 0, 'name': 'Splitter 2'},
    {'x': 22, 'y': 2, 'name': 'Splitter 3'},
    {'x': 14, 'y': 0, 'name': 'Splitter 4'},
    {'x': 26, 'y': 0, 'name': 'Splitter 5'},
]

gates_draw = [{'x': m['x'], 'name': m['name'].replace('M', 'Gate ')} for m in machines_conf]
gates_draw.insert(0, {'x': 0, 'name': 'Corner 2'})

SEQ_MAP = {
    # 与 streamlit_app/factory_floor_plotly.SEQ_MAP 保持同一组键，便于与 Digital Twin / event_log 对齐
    ('corner2', 'RETURN'): (0.0, 0.0, 'dx'),
    ('corner2', 'START'): (0.0, 0.0, 'dx'),
    ('corner2', 'TRANSFER'): (0.0, 2.0, 'down'),
    ('station11', 'LOAD'): (2.0, 2.5, 'sx'),
    ('station11', 'PASS'): (2.0, 2.0, 'sx'),
    ('station11', 'PROCESS'): (2.0, 3.5, 'down'),
    ('station11', 'FAIL'): (2.0, 3.5, 'down'),
    ('station11', 'BLOCK'): (2.0, 3.5, 'down'),
    ('station11', 'UNLOAD'): (2.0, 2.5, 'sx'),
    ('station11', 'TRANSFER'): (4.0, 2.0, 'sx'),
    ('station21', 'LOAD'): (6.0, 2.5, 'sx'),
    ('station21', 'PASS'): (6.0, 2.0, 'sx'),
    ('station21', 'PROCESS'): (6.0, 3.5, 'down'),
    ('station21', 'FAIL'): (6.0, 3.5, 'down'),
    ('station21', 'BLOCK'): (6.0, 3.5, 'down'),
    ('station21', 'UNLOAD'): (6.0, 2.5, 'sx'),
    ('station21', 'TRANSFER'): (7.0, 2.0, 'sx'),
    ('station22', 'LOAD'): (8.0, 2.5, 'sx'),
    ('station22', 'PASS'): (8.0, 2.0, 'sx'),
    ('station22', 'PROCESS'): (8.0, 3.5, 'down'),
    ('station22', 'FAIL'): (8.0, 3.5, 'down'),
    ('station22', 'BLOCK'): (8.0, 3.5, 'down'),
    ('station22', 'UNLOAD'): (8.0, 2.5, 'sx'),
    ('station22', 'TRANSFER'): (10.0, 2.0, 'sx'),
    ('splitter1', 'FORWARD'): (11.0, 2.0, 'sx'),
    ('splitter1', 'RETURN'): (10.0, 0.5, 'up'),
    ('station31', 'LOAD'): (12.0, 2.5, 'sx'),
    ('station31', 'PASS'): (12.0, 2.0, 'sx'),
    ('station31', 'PROCESS'): (12.0, 3.5, 'down'),
    ('station31', 'FAIL'): (12.0, 3.5, 'down'),
    ('station31', 'BLOCK'): (12.0, 3.5, 'down'),
    ('station31', 'UNLOAD'): (12.0, 2.5, 'sx'),
    ('station31', 'TRANSFER'): (14.0, 2.0, 'sx'),
    ('station41', 'LOAD'): (16.0, 2.5, 'sx'),
    ('station41', 'PASS'): (16.0, 2.0, 'sx'),
    ('station41', 'PROCESS'): (16.0, 3.5, 'down'),
    ('station41', 'FAIL'): (16.0, 3.5, 'down'),
    ('station41', 'BLOCK'): (16.0, 3.5, 'down'),
    ('station41', 'UNLOAD'): (16.0, 2.5, 'sx'),
    ('station41', 'TRANSFER'): (17.0, 2.0, 'sx'),
    ('station51', 'LOAD'): (18.0, 2.5, 'sx'),
    ('station51', 'PASS'): (18.0, 2.0, 'sx'),
    ('station51', 'PROCESS'): (18.0, 3.5, 'down'),
    ('station51', 'FAIL'): (18.0, 3.5, 'down'),
    ('station51', 'BLOCK'): (18.0, 3.5, 'down'),
    ('station51', 'UNLOAD'): (18.0, 2.5, 'sx'),
    ('station51', 'TRANSFER'): (19.0, 2.0, 'sx'),
    ('station52', 'LOAD'): (20.0, 2.5, 'sx'),
    ('station52', 'PASS'): (20.0, 2.0, 'sx'),
    ('station52', 'PROCESS'): (20.0, 3.5, 'down'),
    ('station52', 'FAIL'): (20.0, 3.5, 'down'),
    ('station52', 'BLOCK'): (20.0, 3.5, 'down'),
    ('station52', 'UNLOAD'): (20.0, 2.5, 'sx'),
    ('station52', 'TRANSFER'): (22.0, 2.0, 'sx'),
    ('splitter3', 'FORWARD'): (23.0, 2.0, 'sx'),
    ('splitter3', 'RETURN'): (22.0, 0.5, 'up'),
    ('station61', 'LOAD'): (24.0, 2.5, 'sx'),
    ('station61', 'PASS'): (24.0, 2.0, 'sx'),
    ('station61', 'PROCESS'): (24.0, 3.5, 'down'),
    ('station61', 'FAIL'): (24.0, 3.5, 'down'),
    ('station61', 'BLOCK'): (24.0, 3.5, 'down'),
    ('station61', 'UNLOAD'): (24.0, 2.5, 'sx'),
    ('station61', 'TRANSFER'): (26.0, 2.0, 'sx'),
    ('station71', 'LOAD'): (28.0, 2.5, 'sx'),
    ('station71', 'PASS'): (28.0, 2.0, 'sx'),
    ('station71', 'PROCESS'): (28.0, 3.5, 'down'),
    ('station71', 'FAIL'): (28.0, 3.5, 'down'),
    ('station71', 'BLOCK'): (28.0, 3.5, 'down'),
    ('station71', 'UNLOAD'): (28.0, 2.5, 'sx'),
    ('station71', 'TRANSFER'): (29.0, 2.0, 'sx'),
    ('corner1', 'RETURN'): (30.0, 2.0, 'sx'),
    ('corner1', 'TRANSFER'): (26.0, 0.0, 'dx'),
    ('splitter5', 'FORWARD'): (22.0, 0.0, 'dx'),
    ('splitter5', 'RETURN'): (26.0, 1.5, 'down'),
    ('splitter5', 'CHECKOUT'): (22.0, 0.0, 'dx'),
    ('splitter5', 'FINISH'): (22.0, 0.0, 'dx'),
    ('splitter5', 'SCRAP'): (22.0, 0.0, 'dx'),
    ('splitter4', 'FORWARD'): (10.0, 0.0, 'dx'),
    ('splitter4', 'RETURN'): (14.0, 1.5, 'down'),
    ('splitter2', 'FORWARD'): (0.0, 0.0, 'dx'),
    ('splitter2', 'RETURN'): (4.0, 1.5, 'down'),
}

NODE_FIXED_DIR = {}
for (comp, act), (x, y, d) in SEQ_MAP.items():
    key = (x, y)
    if key not in NODE_FIXED_DIR:
        NODE_FIXED_DIR[key] = d
    else:
        priority = {'down': 0, 'up': 1, 'sx': 2, 'dx': 3}
        if priority.get(d, 9) < priority.get(NODE_FIXED_DIR[key], 9):
            NODE_FIXED_DIR[key] = d

FWD_TRA_COMPONENTS = {"splitter1", "splitter2", "splitter3", "splitter4", "splitter5"}
AVG_BUFFER_WINDOW_MIN = 30

BUFFER_RULES = {
    "stage1": [("corner2", "START", +1, "corner2_start"), ("splitter2", "TRANSFER", +1, "fwd_tra"),
               ("station11", "TRANSFER", -1, "direct")],
    "stage2": [("station11", "TRANSFER", +1, "direct"), ("splitter4", "TRANSFER", +1, "fwd_tra"),
               ("splitter1", "TRANSFER", -1, "fwd_tra"), ("splitter2", "TRANSFER", -1, "fwd_tra")],
    "stage3": [("splitter1", "TRANSFER", +1, "fwd_tra"), ("station31", "TRANSFER", -1, "direct")],
    "stage4": [("station31", "TRANSFER", +1, "direct"), ("splitter5", "TRANSFER", +1, "fwd_tra"),
               ("splitter4", "TRANSFER", -1, "fwd_tra"), ("splitter3", "TRANSFER", -1, "fwd_tra")],
    "stage5": [("splitter3", "TRANSFER", +1, "fwd_tra"), ("station61", "TRANSFER", -1, "direct")],
    "stage6": [("station61", "TRANSFER", +1, "direct"), ("splitter5", "TRANSFER", -1, "fwd_tra")],
}


def get_sequence_info(component_id, activity):
    return SEQ_MAP.get(
        (str(component_id or "").strip(), str(activity or "").strip()),
        (None, None, None),
    )


def _build_static_traces():
    traces = []
    RAIL = '#334155'
    N_BG = '#e2e8f0'
    N_BR = '#0284c7'
    RAIL_TOP = 2.0
    RAIL_BOT = 0.0
    CONN_START = 2.0
    CONN_END = 3.5

    for xs, ys in [
        ([-0.04, 30.04], [RAIL_TOP, RAIL_TOP]),
        ([30.04, 0.0], [RAIL_BOT, RAIL_BOT]),
        ([0.0, 0.0], [RAIL_BOT, RAIL_TOP]),
        ([30.0, 30.0], [RAIL_TOP, RAIL_BOT]),
    ]:
        traces.append(go.Scatter(x=xs, y=ys, mode='lines',
                                 line=dict(color=RAIL, width=3),
                                 showlegend=False, hoverinfo='skip'))
    for vx in [4, 10, 14, 22, 26]:
        traces.append(go.Scatter(x=[vx, vx], y=[RAIL_BOT, RAIL_TOP], mode='lines',
                                 line=dict(color=RAIL, width=3),
                                 showlegend=False, hoverinfo='skip'))

    for m in machines_conf:
        traces.append(go.Scatter(
            x=[m['x'], m['x']], y=[CONN_START, CONN_END], mode='lines',
            line=dict(color='#94a3b8', width=1.75),
            showlegend=False, hoverinfo='skip'
        ))

    def _arrow(x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0
        angle = math.degrees(math.atan2(dy, dx))
        return go.Scatter(
            x=[x0, x1], y=[y0, y1],
            mode='lines+markers',
            line=dict(color=RAIL, width=1.75),
            marker=dict(symbol='arrow', size=10, angle=angle - 90,
                        color=RAIL, line=dict(color=RAIL, width=1)),
            showlegend=False, hoverinfo='skip'
        )

    top_nodes_x = sorted(set(
        [0] +
        [m['x'] for m in machines_conf] +
        [n['x'] for n in draw_mergers if n['y'] == RAIL_TOP] +
        [n['x'] for n in draw_splitters if n['y'] == RAIL_TOP] +
        [30]
    ))
    for i in range(len(top_nodes_x) - 1):
        mid = (top_nodes_x[i] + top_nodes_x[i + 1]) / 2.0
        traces.append(_arrow(mid + 0.01, RAIL_TOP, mid - 0.01, RAIL_TOP))

    bot_nodes_x = sorted(set(
        [0] +
        [n['x'] for n in draw_mergers if n['y'] == RAIL_BOT] +
        [n['x'] for n in draw_splitters if n['y'] == RAIL_BOT] +
        [30]
    ))
    for i in range(len(bot_nodes_x) - 1):
        mid = (bot_nodes_x[i] + bot_nodes_x[i + 1]) / 2.0
        traces.append(_arrow(mid - 0.01, RAIL_BOT, mid + 0.01, RAIL_BOT))

    for vx in [10, 22, 30]:
        traces.append(_arrow(vx, 1.0 + 0.01, vx, 1.0 - 0.01))
    for vx in [0, 4, 14, 26]:
        traces.append(_arrow(vx, 1.0 - 0.01, vx, 1.0 + 0.01))

    ms_data = pd.DataFrame(draw_mergers + draw_splitters)
    top_list = ['Merger 1', 'Merger 3', 'Merger 5', 'Splitter 1', 'Splitter 3']
    ms_pos = ['top center' if n in top_list else 'bottom center' for n in ms_data['name']]
    traces.append(go.Scatter(
        x=ms_data['x'], y=ms_data['y'], mode='markers+text',
        marker=dict(size=22, color=N_BG, line=dict(color=N_BR, width=2)),
        text=ms_data['name'], textposition=ms_pos,
        textfont=dict(size=8, color='#334155'),
        showlegend=False,
        hovertemplate='<b>%{text}</b><extra></extra>'
    ))

    df_gates = pd.DataFrame(gates_draw)
    gate_ys = [RAIL_TOP if x > 0 else RAIL_BOT for x in df_gates['x']]
    traces.append(go.Scatter(
        x=df_gates['x'], y=gate_ys,
        mode='markers+text',
        marker=dict(size=20, color=N_BG, line=dict(color=N_BR, width=2)),
        text=df_gates['name'], textposition="bottom center",
        textfont=dict(size=8, color='#334155'),
        showlegend=False,
        hovertemplate='<b>%{text}</b><extra></extra>'
    ))

    return traces


def kpi_buffer_levels(new_events):
    KEY = "kpi_buffer_state"

    if KEY not in st.session_state:
        st.session_state[KEY] = {
            "levels": {f"stage{i}": 0 for i in range(1, 7)},
            "last_act": {c: {} for c in FWD_TRA_COMPONENTS},
            "averages": {f"stage{i}": None for i in range(1, 7)},
            "corner2_starts_used": 0,
            "cum_area": {f"stage{i}": 0.0 for i in range(1, 7)},
            "start_time": {f"stage{i}": None for i in range(1, 7)},
            "last_time": {f"stage{i}": None for i in range(1, 7)},
            "last_level": {f"stage{i}": 0 for i in range(1, 7)}
        }

    state = st.session_state[KEY]
    levels = state["levels"]
    last_act = state["last_act"]
    averages = state["averages"]

    cum_area = state["cum_area"]
    start_time = state["start_time"]
    last_time = state["last_time"]
    last_level = state["last_level"]

    for e in new_events:
        comp = str(e.get("component_id")).strip()
        act = str(e.get("activity")).strip()
        part_id = e.get("part_id")
        t = pd.Timestamp(e["time"])

        for stage, rules in BUFFER_RULES.items():
            for rule_comp, rule_act, delta, mode in rules:
                if comp != rule_comp or act != rule_act:
                    continue

                if mode == "corner2_start":
                    if state["corner2_starts_used"] < N_pallet:
                        levels[stage] += delta
                        state["corner2_starts_used"] += 1
                elif mode == "direct":
                    levels[stage] += delta
                elif mode == "fwd_tra":
                    prev_act = last_act.get(comp, {}).get(part_id)
                    if prev_act == "FORWARD":
                        levels[stage] += delta

        if comp in FWD_TRA_COMPONENTS:
            last_act.setdefault(comp, {})[part_id] = act

        for stage in levels:
            current_level = levels[stage]

            if start_time[stage] is None:
                start_time[stage] = t
                last_time[stage] = t
                last_level[stage] = current_level
                averages[stage] = round(float(current_level), 1)
                continue

            dt_seconds = (t - last_time[stage]).total_seconds()

            if dt_seconds > 0:
                cum_area[stage] += last_level[stage] * dt_seconds

            last_time[stage] = t
            last_level[stage] = current_level

            total_time = (t - start_time[stage]).total_seconds()
            if total_time > 0:
                averages[stage] = round(cum_area[stage] / total_time, 1)
            else:
                averages[stage] = round(float(current_level), 1)

    return state


def process_event_state(queues, part_locations, part_states, machines, machine_parts, kpi, event):
    part_id = event['part_id']
    comp_id = str(event['component_id']).strip()
    act = str(event['activity']).strip()

    if 'time' in event:
        t_val = pd.Timestamp(event['time'])
        kpi['last_event_time'] = t_val
        if comp_id == 'corner2' and act == 'START':
            if kpi.get('first_start_time') is None:
                kpi['first_start_time'] = t_val

    if comp_id == 'splitter5' and act == 'CHECKOUT':
        kpi['total_checkouts'] = kpi.get('total_checkouts', 0) + 1

    target_x, target_y, target_dir = get_sequence_info(comp_id, act)

    if target_x is not None:
        nk = (target_x, target_y)
        fixed_dir = NODE_FIXED_DIR.get(nk, target_dir)
        old_nk = part_locations.get(part_id)

        if old_nk is not None and old_nk != nk:
            if old_nk in queues and part_id in queues[old_nk]['parts']:
                queues[old_nk]['parts'].remove(part_id)

        queues.setdefault(nk, {'parts': [], 'dir': fixed_dir})
        queues[nk]['dir'] = fixed_dir

        if part_id not in queues[nk]['parts']:
            queues[nk]['parts'].append(part_id)

        part_locations[part_id] = nk

    if act == 'LOAD':
        machines[comp_id] = 'BUSY'
        machine_parts[comp_id] = part_id
    elif machine_parts.get(comp_id) == part_id:
        if act in ['PROCESS', 'UNLOAD']:
            machines[comp_id] = 'BUSY'
        elif act in ['BLOCK']:
            machines[comp_id] = 'BLOCK'
            kpi['block_events'][comp_id] = kpi['block_events'].get(comp_id, 0) + 1
            machine_parts[comp_id] = part_id
        elif 'FAIL' in act:
            machines[comp_id] = 'FAIL'
            kpi['fail_events'][comp_id] = kpi['fail_events'].get(comp_id, 0) + 1
            machine_parts[comp_id] = part_id
        elif act in ['TRANSFER']:
            machines[comp_id] = 'IDLE'
            machine_parts.pop(comp_id, None)

    part_states.setdefault(part_id, False)
    if comp_id == 'splitter5' and act in ['FINISH', 'SCRAP']:
        part_states[part_id] = True
        if act == 'FINISH':
            kpi['completed'] = kpi.get('completed', 0) + 1
        else:
            kpi['scrapped'] = kpi.get('scrapped', 0) + 1
    elif act == 'START':
        part_states[part_id] = False

    return queues, part_locations, part_states, machines, machine_parts, kpi


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

    sim = st.session_state.sim_state
    kpi = st.session_state.dt_kpi

    for event in new_rows:
        sim['queues'], sim['part_locs'], sim['part_states'], sim['machines'], sim['machine_parts'], kpi = \
            process_event_state(sim['queues'], sim['part_locs'], sim['part_states'],
                                sim['machines'], sim['machine_parts'], kpi, event)
        st.session_state.dt_event_log.appendleft(event)

    st.session_state.sim_state = sim
    st.session_state.dt_kpi = kpi

    current_machines = sim['machines']
    current_queues = sim['queues']
    current_part_states = sim['part_states']
    status = st.session_state.mqtt_manager.status

    buf = kpi_buffer_levels(new_rows)

    st.markdown(header_html(
        title="Shop Floor Monitoring 🏭",
        subtitle="",
        mqtt_status=status,
    ), unsafe_allow_html=True)

    st.markdown("<div style='height:15px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📊 Overview</div>', unsafe_allow_html=True)

    active_parts = len(sim['part_locs'])
    # busy_count = sum(1 for s in current_machines.values() if s in 'BUSY')
    # fail_count = sum(1 for s in current_machines.values() if s == 'FAIL')
    total_fails = sum(kpi['fail_events'].values())
    total_blocks = sum(kpi['block_events'].values())

    t_start = kpi.get('first_start_time')
    t_last = kpi.get('last_event_time')
    n_parts = kpi.get('total_checkouts', 0)

    if t_start and t_last and t_last > t_start:
        duration_min = (t_last - t_start).total_seconds() / 60.0
        _s = int(duration_min * 60)
        st.session_state._tnow_str = f"{_s // 60}m {_s % 60:02d}s"

        if n_parts >= 1:
            throughput_val = f"{round(n_parts / duration_min, 2)} p/min"
        else:
            throughput_val = "0.0 p/min"
    else:
        st.session_state._tnow_str = "—"
        throughput_val = "0.0 p/min"

    k = st.columns(6)
    for col, val, color, label, sub in [
        (k[0], f"{active_parts}", "var(--accent)", "Active Parts", ""),
        (k[1], f"{kpi.get('completed', 0)}", "var(--green)", "Total Number of Good Parts", ""),
        (k[2], f"{kpi.get('scrapped', 0)}", "var(--red)", "Total Number of Scraps", ""),
        (k[3], throughput_val.replace("pcs/min", "p/min"), "var(--accent)", "Gross Throughput", ""),
        (k[4], f"{total_fails}", "var(--red)", "Total FAIL events", ""),
        (k[5], f"{total_blocks}", "var(--gold)", "Total BLOCK events", ""),
    ]:
        with col:
            st.markdown(kpi_card_html(val, label, sub, color), unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    col_map, col_side = st.columns([3, 1])

    with col_map:
        st.markdown('<div class="section-title">🔧 Factory Floor</div>', unsafe_allow_html=True)

        display_pallets, SPACING = [], 0.35
        for (qx, qy), q_data in current_queues.items():
            for i, pid in enumerate(q_data['parts']):
                vx, vy = qx, qy
                d = q_data['dir']
                if d == 'dx':
                    vx = qx + i * SPACING
                elif d == 'sx':
                    vx = qx - i * SPACING
                elif d == 'up':
                    vy = qy + i * SPACING
                elif d == 'down':
                    vy = qy - i * SPACING
                is_empty = current_part_states.get(pid, False)
                color = '#b8956a' if is_empty else '#7a4f2a'
                display_pallets.append({'x': vx, 'y': vy, 'id': pid, 'color': color})

        BG = '#ffffff'
        MACH_Y = 3.5
        fig = go.Figure(data=list(st.session_state._static_traces))

        for m in machines_conf:
            mid = m['id']
            status_m = current_machines.get(mid, 'IDLE')
            mc = STATUS_COLORS.get(status_m, '#22c55e')
            fails = kpi['fail_events'].get(mid, 0)
            blocks = kpi['block_events'].get(mid, 0)
            fig.add_trace(go.Scatter(
                x=[m['x']], y=[MACH_Y], mode='markers+text',
                marker=dict(symbol='square', size=46, color=mc,
                            line=dict(color='#000000', width=2)),
                text=[f"<b>{m['name']}</b><br><span style='font-size:9px'>{status_m}</span>"],
                textposition="top center", textfont=dict(size=9, color='#1e293b'),
                showlegend=False,
                hovertemplate=(
                    f"<b>{m['name']}</b><br>Status: <b>{status_m}</b><br>"
                    f"FAILs: {fails}  BLOCKs: {blocks}<extra></extra>"
                ),
            ))

        if display_pallets:
            df_p = pd.DataFrame(display_pallets)
            fig.add_trace(go.Scatter(
                x=df_p['x'], y=df_p['y'], mode='markers+text',
                marker=dict(symbol='circle', size=20, color=df_p['color'],
                            line=dict(color='#ffffff', width=1)),
                text=df_p['id'], textposition="middle center",
                textfont=dict(size=7, color='white'),
                hovertemplate='Part: <b>%{text}</b><extra></extra>',
                showlegend=False,
            ))

        fig.update_layout(
            xaxis=dict(visible=False, range=[-1, 31]),
            yaxis=dict(visible=False, range=[-0.9, 5.0]),
            height=440, plot_bgcolor=BG, paper_bgcolor=BG,
            margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
        )

        st.plotly_chart(fig, use_container_width=True)

    with col_side:
        st.markdown('<div class="section-title">🛠️ Machine Status</div>', unsafe_allow_html=True)
        for m in machines_conf:
            s = current_machines.get(m['id'], 'IDLE')
            color = STATUS_COLORS.get(s, '#22c55e')
            emoji = STATUS_EMOJI.get(s, '✅')
            fails = kpi['fail_events'].get(m['id'], 0)
            blocks = kpi['block_events'].get(m['id'], 0)
            st.markdown(f"""
            <div class="machine-row">
              <span class="machine-name" style="color:{color}">{emoji} {m['name']}</span>
              <span class="machine-stats">🔴{fails}&nbsp;⚠️{blocks}</span>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:5px'></div>", unsafe_allow_html=True)

        last = st.session_state.get("last_message") or {}
        t = str(last.get('time', '—'))
        c = str(last.get('component_id', '—'))
        a = str(last.get('activity', '—'))
        p = str(last.get('part_id', '—'))
        tnow = st.session_state.get("_tnow_str", "—")
        ac = {'FAIL': '#ef4444', 'BLOCK': '#eab308', 'PROCESS': '#3b82f6'}.get(a, '#94a3b8')
        st.markdown(f"""
        <div class="last-event-bar">
          <span style="color:var(--text-dim)">🕒 {t}</span>
          <span style="color:var(--accent)">📍 {c}</span>
          <span style="color:{ac}">⚡ {a}</span>
          <span style="color:#c9955a">📦 {p}</span>
          <span style="color:#9333ea">⏱ Run Time:{tnow}</span>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📦 Stage Buffer Levels</div>', unsafe_allow_html=True)
    levels = buf["levels"]
    b_cols = st.columns(6)
    for col, stage in zip(b_cols, [f"stage{i}" for i in range(1, 7)]):
        with col:
            st.markdown(kpi_card_html(
                str(levels[stage]), stage.replace("stage", "Stage "), "pallets", "var(--accent)"
            ), unsafe_allow_html=True)

    st.markdown(
        f"<div style='height:8px'></div>"
        f"<small style='color:var(--text-dim);'>Average Stage Buffer Level </small>",
        unsafe_allow_html=True,
    )
    a_cols = st.columns(6)
    for col, stage in zip(a_cols, [f"stage{i}" for i in range(1, 7)]):
        avg = buf["averages"][stage]
        with col:
            st.markdown(kpi_card_html(
                str(avg) if avg is not None else "—",
                stage.replace("stage", "Avg Stage "), "pallets", "var(--text-dim)",
            ), unsafe_allow_html=True)

    total_buf = sum(levels.values())
    warns = []
    for stage, val in levels.items():
        if val < 0:
            warns.append(("error", f"Stage {stage.replace('stage', '')} negative ({val}) — Missing Events"))
    if total_buf != N_pallet:
        warns.append(("warning", f"Pallet = {total_buf}, Expected {N_pallet}"))

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    if not warns:
        st.markdown(
            "<div style='border:1px solid #c3e6cb;border-radius:8px;padding:10px 16px;"
            "background:#f0fff4;color:#276749;font-size:0.85rem;'>"
            "✔ Buffer consistency OK — total pallets = 16</div>",
            unsafe_allow_html=True,
        )
    else:
        for level, msg in warns:
            color_bg, color_bd, color_txt, icon = (
                ("#fff5f5", "#feb2b2", "#9b2c2c", "✖") if level == "error"
                else ("#fffbea", "#fbd38d", "#7b4f12", "⚠")
            )
            st.markdown(
                f"<div style='border:1px solid {color_bd};border-radius:8px;padding:10px 16px;"
                f"background:{color_bg};color:{color_txt};font-size:0.85rem;margin-bottom:6px;'>"
                f"{icon} {msg}</div>",
                unsafe_allow_html=True,
            )
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)


def render():
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    st.set_page_config(layout="wide", page_title="Shop Floor Monitoring")
    st.markdown(THEME_CSS, unsafe_allow_html=True)

    if 'sim_state' not in st.session_state:
        st.session_state.sim_state = {
            'queues': {}, 'part_locs': {}, 'part_states': {},
            'machines': {m['id']: 'IDLE' for m in machines_conf},
            'machine_parts': {},
        }
    if 'dt_kpi' not in st.session_state:
        st.session_state.dt_kpi = {
            'fail_events': {}, 'block_events': {}, 'completed': 0, 'scrapped': 0,
            'total_checkouts': 0,
            'first_start_time': None,
            'last_event_time': None
        }
    if 'dt_event_log' not in st.session_state:
        st.session_state.dt_event_log = deque(maxlen=200)
    if '_static_traces' not in st.session_state:
        st.session_state._static_traces = _build_static_traces()
    if "last_mh_snapshot_t" not in st.session_state:
        st.session_state["last_mh_snapshot_t"] = 0.0

    render_live_dashboard()