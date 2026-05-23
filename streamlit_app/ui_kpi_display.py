"""KPI 展示：System / Stage / Station，与 `kpi_calculator.get_snapshot()` 对齐。"""
from __future__ import annotations

import datetime
import html
import time
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Stage KPI 表：行文案与 Looping 行底色
_STAGE_TABLE_LABELS: dict[int, str] = {
    1: "Stage 1 · Non-Looping",
    2: "Stage 2 · Looping",
    3: "Stage 3 · Non-Looping",
    4: "Stage 4 · Looping",
    5: "Stage 5 · Non-Looping",
    6: "Stage 6 · Looping",
}
_STAGE_LOOPING_INDEX = frozenset({1, 3, 5})  # 0-based row index → stage 2,4,6

# 与 code/ui_theme.py STATUS_COLORS / :root 对齐（仅 UI 展示）
_UI_THEME: dict[str, str] = {
    "bg": "#f8fafc",
    "surface": "#ffffff",
    "surface2": "#f1f5f9",
    "border": "#e2e8f0",
    "border2": "#cbd5e1",
    "text": "#1e293b",
    "text_dim": "#64748b",
    "accent": "#0284c7",
    "blue": "#3b82f6",
    "green": "#22c55e",
    "orange": "#f97316",
    "red": "#ef4444",
    "gold": "#eab308",
    "indigo": "#6366f1",
}

# Plotly 与 Streamlit 共用：Barlow Condensed（与 ui_sidebar 一致）
_PLOT_FONT = '"Barlow Condensed", "Segoe UI", sans-serif'

# 字号层级（优化2 版式定稿 · B；本轮只统一字号，不改布局/颜色）
_FONT_L1_PX = 24   # section：System KPI
_FONT_L2_PX = 20   # section：Trends / Stage / Station；图表标题
_FONT_L3_PX = 14   # 指标名、工站名、柱图轴
_FONT_L4_SYSTEM_PX = 30  # System 双行卡主数值
_FONT_L4_STAGE_PX = 28   # Stage 卡主数值
_FONT_L4_STAGE_THR_PX = 30  # Stage Throughput 略强调
_FONT_L5_PX = 12   # caption、hover、副标题
_FONT_CHART_TITLE_PX = 18  # Plotly 图标题（与 L2 section 区分）
_FONT_CHART_AXIS_PX = 14
_FONT_STAGE_NAME_PX = 18  # Stage 卡内阶段名

# Trends 双图：等高、同 margin；仅使用 KPI 内 trend_* 序列（不用 MQTT 缓冲假滚动）
_WIP_TREND_MAX_POINTS = 20
_TREND_CHART_HEIGHT = 250
_TREND_PAIR_MARGIN = dict(t=42, b=36, l=60, r=20)
_CHART_TITLE_WIP = "WIP (pcs)"
_CHART_TITLE_RATES = "Completion & Scrap (%)"

# System / Stage 指标数值色（同一语义同一色）
_KPI_COLOR_WIP = "#1565c0"
_KPI_COLOR_COMPLETION = "#2e7d32"
_KPI_COLOR_SCRAP = "#c62828"
_KPI_COLOR_LEAD = "#e65100"
_KPI_COLOR_DEFAULT = "#1a2332"
_STAGE_TITLE_COLOR = "#1e293b"
_STAGE_BADGE_BG = "#f1f5f9"
_STAGE_BADGE_TEXT = "#64748b"
_STAGE_CARD_ACCENT = "#e2e8f0"

_KPI_SECTION_TITLE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&display=swap');
    div[data-testid="stMainBlockContainer"] .kpi-sec-title {
        margin: 0 0 0.75rem 0 !important;
        padding: 0 0 0 12px !important;
        font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
        font-weight: 700 !important;
        line-height: 1.3 !important;
        letter-spacing: 0.02em !important;
        border-left-style: solid !important;
        border-left-width: 4px !important;
        color: #1e293b !important;
    }
    div[data-testid="stMainBlockContainer"] .kpi-sec-title--system {
        font-size: """ + str(_FONT_L1_PX) + """px !important;
        border-left-color: #0284c7 !important;
    }
    div[data-testid="stMainBlockContainer"] .kpi-sec-title--stage {
        font-size: """ + str(_FONT_L2_PX) + """px !important;
        border-left-color: #64748b !important;
    }
    div[data-testid="stMainBlockContainer"] .kpi-sec-title--station {
        font-size: """ + str(_FONT_L2_PX) + """px !important;
        border-left-color: #cbd5e1 !important;
    }
    div[data-testid="stMainBlockContainer"] .kpi-sec-title--trends {
        font-size: """ + str(_FONT_L2_PX) + """px !important;
        border-left-color: #0284c7 !important;
    }
    /* Stage | Station 并列：行高随右列拉伸，左列 flex + 底部 spacer 填满 */
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_stage_station_panel [data-testid="stHorizontalBlock"] {
        align-items: stretch !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_stage_station_panel div.st-key-kpi_stage_col {
        flex: 1 1 auto !important;
        display: flex !important;
        flex-direction: column !important;
        min-height: 0 !important;
        height: 100% !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_stage_station_panel div.st-key-kpi_stage_col [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        flex: 1 1 auto !important;
        min-height: 0 !important;
        height: 100% !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_stage_station_panel .kpi-stage-spacer {
        flex: 1 1 auto !important;
        min-height: 0 !important;
        width: 100% !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_trends_wrap,
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_trends_wrap [data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(165deg, #f8fafc 0%, #ffffff 55%) !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 12px !important;
        padding: 16px 20px !important;
        margin-bottom: 20px !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_trends_wrap [data-testid="stPlotlyChart"] {
        min-height: """ + str(_TREND_CHART_HEIGHT + 28) + """px !important;
    }
    div[data-testid="stMainBlockContainer"] div.st-key-kpi_trends_wrap [data-testid="stPlotlyChart"] > div {
        height: """ + str(_TREND_CHART_HEIGHT + 28) + """px !important;
    }
</style>
"""


def _kpi_section_title_html(title: str, variant: str) -> str:
    v = html.escape(variant.strip().lower())
    t = html.escape(title)
    return '<p class="kpi-sec-title kpi-sec-title--{}">{}</p>'.format(v, t)


def _stage_kpi_row_style(row: pd.Series) -> list[str]:
    idx = int(cast(int, row.name))
    bg = _UI_THEME["surface2"] if idx in _STAGE_LOOPING_INDEX else _UI_THEME["surface"]
    return [f"background-color: {bg};"] * len(row)


# Station KPI 卡片标题（与 Digital Twin / part_track_conformance.SLOT_HEADERS_M 风格一致：M1-1 …）
STATION_KPI_DISPLAY_NAME: dict[str, str] = {
    "station11": "M1-1",
    "station21": "M2-1",
    "station22": "M2-2",
    "station31": "M3-1",
    "station41": "M4-1",
    "station51": "M5-1",
    "station52": "M5-2",
    "station61": "M6-1",
    "station71": "M7-1",
}

_STATE_LABEL_EN = {
    "busy": "Busy",
    "fail": "Failed",
    "blocked": "Blocked",
    "idle": "Idle",
}

# Station state semantics（优化2 定稿：Busy 绿 / Idle 灰 / Blocked 黄 / Fail 红）
_STATION_BUSY_COLOR = "#22c55e"
_STATION_FAIL_COLOR = "#ef4444"
_STATION_BLOCKED_COLOR = "#eab308"
_STATION_IDLE_COLOR = "#94a3b8"

def station_kpi_display_name(sid: str) -> str:
    """工站 KPI 卡片标题：M1-1 …（与 Twin 一致；未知 id 则回退为原 id）。"""
    key = str(sid or "").strip().lower()
    return STATION_KPI_DISPLAY_NAME.get(key, sid or key or "—")


def _dominant_state_key(pn: dict[str, float]) -> str:
    """busy / fail / blocked / idle 中占比最大者（并列时按元组顺序先者优先）。"""
    keys = ("busy", "fail", "blocked", "idle")
    return max(keys, key=lambda s: float(pn.get(s, 0.0) or 0.0))


def _state_key_dot_and_color(state_key: str) -> tuple[str, str]:
    """Busy=绿 / Fail=红 / Blocked=黄 / Idle=灰。"""
    k = (state_key or "idle").strip().lower()
    if k == "busy":
        return "\u25cf", _STATION_BUSY_COLOR
    if k == "fail":
        return "\u25cf", _STATION_FAIL_COLOR
    if k == "blocked":
        return "\u25cf", _STATION_BLOCKED_COLOR
    return "\u25cf", _STATION_IDLE_COLOR


@st.cache_data(ttl=60.0, show_spinner=False)
def default_station_ids() -> tuple[str, ...]:
    from paths import ensure_paths

    ensure_paths()
    import common  # noqa: E402

    cfg = common.load_config("config.json")
    hosts = list(cfg.get("controller_hostnames") or [])
    stations = [str(h) for h in hosts if str(h).startswith("station")]
    if stations:
        return tuple(sorted(stations))
    w = cfg.get("component_wips") or {}
    stations = [str(k) for k in w if str(k).startswith("station")]
    return tuple(sorted(stations)) if stations else tuple()


def _format_runtime_hms(seconds: float) -> str:
    sec = max(0, int(seconds))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "{:d}:{:02d}:{:02d}".format(h, m, s)
    if m and s:
        return "{:d} min {:d} s".format(m, s)
    if m:
        return "{:d} min".format(m)
    return "{:d} s".format(s)


def _four_state_percent_ints(b: float, f: float, bl: float, i: float) -> tuple[int, int, int, int]:
    """整数百分比 busy/fail/blocked/idle，总和恒为 100（最大余数法）。全 Idle 时 (0,0,0,100)，条为整段灰。"""
    b = max(0.0, min(1.0, float(b)))
    f = max(0.0, min(1.0, float(f)))
    bl = max(0.0, min(1.0, float(bl)))
    i = max(0.0, min(1.0, float(i)))
    sm = b + f + bl + i
    if sm > 1e-9:
        b, f, bl, i = b / sm, f / sm, bl / sm, i / sm
    else:
        b, f, bl, i = 0.0, 0.0, 0.0, 1.0
    if b + f + bl < 1e-9:
        return 0, 0, 0, 100
    raw = [100.0 * b, 100.0 * f, 100.0 * bl, 100.0 * i]
    base = [int(x) for x in raw]
    rem = 100 - sum(base)
    frac_order = sorted(
        range(4), key=lambda j: raw[j] - base[j], reverse=True
    )
    for k in range(max(0, rem)):
        base[frac_order[k % 4]] += 1
    return base[0], base[1], base[2], base[3]


def _station_stacked_bar_html(pn: dict[str, float]) -> str:
    """单行四色堆叠条（无图例；全 Idle 时整段为 Idle 灰）。"""
    b = max(0.0, min(1.0, float(pn.get("busy", 0.0) or 0.0)))
    f = max(0.0, min(1.0, float(pn.get("fail", 0.0) or 0.0)))
    bl = max(0.0, min(1.0, float(pn.get("blocked", 0.0) or 0.0)))
    i = max(0.0, min(1.0, float(pn.get("idle", 0.0) or 0.0)))
    sm = b + f + bl + i
    if sm > 1e-9:
        b, f, bl, i = b / sm, f / sm, bl / sm, i / sm
    else:
        b, f, bl, i = 0.0, 0.0, 0.0, 1.0
    pb, pf, pbl, pi = _four_state_percent_ints(b, f, bl, i)
    wb = float(pb)
    wf = float(pf)
    wbl = float(pbl)
    wi = float(pi)
    return (
        '<div style="display:flex;height:7px;border-radius:4px;overflow:hidden;'
        'width:100%;margin:4px 0 0 0;">'
        '<div style="width:{:.4f}%;min-width:0;background:{};"></div>'
        '<div style="width:{:.4f}%;min-width:0;background:{};"></div>'
        '<div style="width:{:.4f}%;min-width:0;background:{};"></div>'
        '<div style="width:{:.4f}%;min-width:0;background:{};"></div>'
        "</div>"
    ).format(
        wb,
        _STATION_BUSY_COLOR,
        wf,
        _STATION_FAIL_COLOR,
        wbl,
        _STATION_BLOCKED_COLOR,
        wi,
        _STATION_IDLE_COLOR,
    )


def _station_probs_normalize(probs: dict) -> dict[str, float]:
    if not probs:
        return {"busy": 0.0, "fail": 0.0, "blocked": 0.0, "idle": 1.0}
    pl = {str(k).lower(): max(0.0, float(v or 0)) for k, v in probs.items()}
    b = pl.get("busy", pl.get("loading", 0.0))
    f = pl.get("fail", 0.0)
    bl = pl.get("blocked", 0.0)
    i = pl.get("idle", 0.0)
    sm = b + f + bl + i
    if sm > 1e-9:
        b, f, bl, i = b / sm, f / sm, bl / sm, i / sm
    else:
        b, f, bl, i = 0.0, 0.0, 0.0, 1.0
    return {"busy": b, "fail": f, "blocked": bl, "idle": i}


def _station_compact_card_html(
    sid: str,
    util_raw,
    probs: dict,
    *,
    live: dict | None = None,
) -> str:
    _ = util_raw, live
    pn = _station_probs_normalize(probs)
    body = _station_stacked_bar_html(pn)

    dom = _dominant_state_key(pn)
    dot, dot_color = _state_key_dot_and_color(dom)
    line_lbl = html.escape(_STATE_LABEL_EN.get(dom, dom.title()))
    title_esc = html.escape(station_kpi_display_name(sid))
    top_bar = (
        f"<div style='font-size:{_FONT_L5_PX}px;font-family:\"Barlow Condensed\",\"Segoe UI\",sans-serif;"
        "color:{};margin:0 0 2px 0;line-height:1.35;letter-spacing:0.01em;"
        "display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;'>"
        "<span style='font-weight:700;color:{};'>{}</span>"
        "<span style='color:{};font-size:1.02em;line-height:1;'>{}</span>"
        "<b style='font-weight:600;'>{}</b>"
        "</div>"
    ).format(
        _UI_THEME["text_dim"],
        _UI_THEME["text"],
        title_esc,
        dot_color,
        html.escape(dot),
        line_lbl,
    )

    return (
        "<div style='padding:10px 12px;border-radius:10px;box-sizing:border-box;"
        "background:linear-gradient(165deg,{} 0%,{} 52%);"
        "border:1px solid {};box-shadow:0 1px 2px rgba(15,23,42,0.06);"
        "margin-bottom:10px;position:relative;overflow:hidden;'>"
        "<div style='position:absolute;top:0;left:0;right:0;height:2px;"
        "background:{};'></div>{}{}</div>"
    ).format(
        _UI_THEME["bg"],
        _UI_THEME["surface"],
        _UI_THEME["border"],
        _UI_THEME["accent"],
        top_bar,
        body,
    )


def render_station_card_grid(
    kpi: dict | None,
    *,
    cols_per_row: int = 4,
    age_sec: float | None = None,
    compact: bool = True,
    station_ids: tuple[str, ...] | None = None,
) -> None:
    _ = age_sec
    k = dict(kpi or {})
    probs = dict(k.get("state_probability") or {})
    live_all = dict(k.get("station_live") or {})
    defaults = station_ids if station_ids is not None else default_station_ids()
    stations = sorted(set(defaults) | set(probs.keys()))
    if not stations:
        st.markdown(
            _kpi_section_title_html("Station KPI", "station"),
            unsafe_allow_html=True,
        )
        st.text("No station* list in config.")
        return
    st.markdown(
        _kpi_section_title_html("Station KPI", "station"),
        unsafe_allow_html=True,
    )
    station_order = [
        "station11",
        "station21",
        "station22",
        "station31",
        "station41",
        "station51",
        "station52",
        "station61",
        "station71",
    ]
    state_color = {
        "BUSY": _STATION_BUSY_COLOR,
        "FAIL": _STATION_FAIL_COLOR,
        "BLOCKED": _STATION_BLOCKED_COLOR,
        "IDLE": _STATION_IDLE_COLOR,
    }
    state_dot = {"BUSY": "●", "FAIL": "●", "BLOCKED": "●", "IDLE": "●"}
    pills = ""
    for sid in station_order:
        live = live_all.get(sid) or {}
        state = str(live.get("current_state") or "IDLE").upper()
        color = state_color.get(state, "#9e9e9e")
        dot = state_dot.get(state, "○")
        name = station_kpi_display_name(sid)
        pills += (
            '<span style="display:inline-flex;align-items:center;justify-content:center;gap:6px;'
            'background:#f5f5f5;border-radius:18px;padding:7px 12px;'
            f'margin:0;font-size:{_FONT_L3_PX}px;width:100%;box-sizing:border-box;">'
            f'<span style="color:{color};font-size:{_FONT_L3_PX}px">{dot}</span>'
            f'<span style="color:#333;font-weight:700;font-size:{_FONT_L3_PX}px">{html.escape(name)}</span>'
            f'<span style="color:{color};font-size:{_FONT_L3_PX}px">{html.escape(state.capitalize())}</span>'
            "</span>"
        )
    st.markdown(
        (
            '<div style="margin-bottom:12px;">'
            f'<div style="font-size:{_FONT_L3_PX}px;color:#9e9e9e;margin-bottom:4px;">'
            "State"
            "</div>"
            '<div style="display:grid;grid-template-columns:repeat(9,minmax(0,1fr));gap:10px;align-items:center;">'
            f"{pills}"
            "</div>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    # 2x2 station comparison bars (Busy / Fail / Blocked / Idle)
    state_probs = dict(k.get("state_probability") or {})
    labels = [station_kpi_display_name(s) for s in station_order]
    busy_vals = [float((state_probs.get(s) or {}).get("busy", 0) or 0) * 100 for s in station_order]
    fail_vals = [float((state_probs.get(s) or {}).get("fail", 0) or 0) * 100 for s in station_order]
    blocked_vals = [float((state_probs.get(s) or {}).get("blocked", 0) or 0) * 100 for s in station_order]
    idle_vals = [float((state_probs.get(s) or {}).get("idle", 0) or 0) * 100 for s in station_order]

    _STATION_HOVER = dict(
        bgcolor="#1e2a3a",
        font_size=_FONT_L5_PX,
        font_family=_PLOT_FONT,
        font_color="#e0e6f0",
        bordercolor="#444c56",
    )

    def _make_station_bar(
        title: str,
        values: list[float],
        color: str,
        metric_name: str,
        *,
        annotate_values: bool = False,
    ) -> go.Figure:
        n = len(labels)
        bar_kwargs: dict[str, Any] = dict(
            x=labels,
            y=values,
            marker_color=color,
            customdata=[metric_name] * n,
            hovertemplate="<b>%{x}</b><br>%{customdata}: %{y:.1f}<extra></extra>",
        )
        if not annotate_values:
            bar_kwargs["text"] = ["{:.0f}".format(v) if v > 0.5 else "" for v in values]
            bar_kwargs["textposition"] = [
                "inside" if v >= 92.0 else "outside" for v in values
            ]
            bar_kwargs["cliponaxis"] = False
        fig = go.Figure(go.Bar(**bar_kwargs))
        y_max = 105.0
        if annotate_values:
            y_max = max(105.0, max(values, default=0) + 8.0)
            for lb, val in zip(labels, values):
                if val > 0:
                    fig.add_annotation(
                        x=lb,
                        y=val + 1.0,
                        text="{:.0f}".format(val),
                        showarrow=False,
                        font=dict(size=_FONT_L5_PX, color=color, family=_PLOT_FONT),
                        yanchor="bottom",
                    )
        fig.update_layout(
            title=dict(text=title, font=dict(size=_FONT_CHART_TITLE_PX, family=_PLOT_FONT)),
            height=200,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="#f8f9fa",
            margin=dict(t=36, b=40, l=40, r=10),
            yaxis=dict(
                range=[0, y_max],
                dtick=25,
                title=dict(text=""),
                tickfont=dict(size=_FONT_CHART_AXIS_PX),
            ),
            xaxis=dict(tickfont=dict(size=_FONT_CHART_AXIS_PX)),
            font=dict(size=_FONT_CHART_AXIS_PX, color="#546e7a", family=_PLOT_FONT),
            showlegend=False,
            hoverlabel=_STATION_HOVER,
        )
        return fig

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    row1_col1, row1_col2 = st.columns(2)
    row2_col1, row2_col2 = st.columns(2)
    with row1_col1:
        st.plotly_chart(
            _make_station_bar("Busy (%)", busy_vals, _STATION_BUSY_COLOR, "Busy"),
            use_container_width=True,
            config={"displayModeBar": False},
            key="kpi_station_busy_bar",
        )
    with row1_col2:
        st.plotly_chart(
            _make_station_bar(
                "Failed (%)",
                fail_vals,
                _STATION_FAIL_COLOR,
                "Failed",
                annotate_values=True,
            ),
            use_container_width=True,
            config={"displayModeBar": False},
            key="kpi_station_fail_bar",
        )
    with row2_col1:
        st.plotly_chart(
            _make_station_bar("Blocked (%)", blocked_vals, _STATION_BLOCKED_COLOR, "Blocked"),
            use_container_width=True,
            config={"displayModeBar": False},
            key="kpi_station_blocked_bar",
        )
    with row2_col2:
        st.plotly_chart(
            _make_station_bar("Idle (%)", idle_vals, _STATION_IDLE_COLOR, "Idle"),
            use_container_width=True,
            config={"displayModeBar": False},
            key="kpi_station_idle_bar",
        )


def _system_values(kpi: dict) -> dict[str, float | int]:
    """Normalize snapshot `system` + legacy top-level keys."""
    k = dict(kpi or {})
    sysb = dict(k.get("system") or {})
    n_comp = int(sysb.get("num_completions", k.get("finished_count", 0)) or 0)
    n_scrap = int(sysb.get("num_scraps", k.get("scrap_count", 0)) or 0)
    wip = int(sysb.get("wip_instantaneous", k.get("current_wip", 0)) or 0)
    awip = float(sysb.get("wip_average", k.get("avg_wip", 0)) or 0)
    cr = float(sysb.get("complete_rate", k.get("throughput", 0)) or 0)
    sr = float(sysb.get("scrap_rate", k.get("scrap_rate", 0)) or 0)
    ct_fin = float(sysb.get("avg_cycle_time_fin", k.get("avg_flow_time_sec", 0)) or 0)
    ct_all = float(sysb.get("avg_cycle_time_all", k.get("avg_cycle_time_all_sec", 0)) or 0)
    ftc = int(k.get("flow_time_count", 0) or 0)
    ftca = int(k.get("avg_cycle_all_sample_count", 0) or 0)
    departed = n_comp + n_scrap
    yield_rate = float(k.get("yield_rate", 0) or 0)
    if departed > 0 and yield_rate <= 0:
        yield_rate = n_comp / departed
    return {
        "n_comp": n_comp,
        "n_scrap": n_scrap,
        "wip": wip,
        "awip": awip,
        "cr": cr,
        "sr": sr,
        "yield_rate": yield_rate,
        "ct_fin": ct_fin,
        "ct_all": ct_all,
        "ftc": ftc,
        "ftca": ftca,
        "obs": float(k.get("observation_time_sec", 0) or 0),
    }


def render_system_kpi_group(
    kpi: dict | None,
    *,
    age_sec: float | None = None,
) -> None:
    _ = age_sec
    v = _system_values(dict(kpi or {}))
    st.markdown(
        _kpi_section_title_html("System KPI", "system"),
        unsafe_allow_html=True,
    )
    def _pair_card_html(
        top_label: str,
        top_value: str,
        top_color: str,
        bottom_label: str,
        bottom_value: str,
        bottom_color: str,
        *,
        top_sub: str = "",
        bottom_sub: str = "",
        top_sub_inline: bool = False,
        bottom_sub_inline: bool = False,
    ) -> str:
        top_label_e = html.escape(str(top_label))
        top_value_e = html.escape(str(top_value))
        bottom_label_e = html.escape(str(bottom_label))
        bottom_value_e = html.escape(str(bottom_value))
        top_sub_html = ""
        l3, l4, l5 = _FONT_L3_PX, _FONT_L4_SYSTEM_PX, _FONT_L5_PX
        if top_sub:
            if top_sub_inline:
                top_sub_html = (
                    f'<span style="font-size:{l5}px;color:#9aa4af;line-height:1.2;">{html.escape(str(top_sub))}</span>'
                )
            else:
                top_sub_html = (
                    f'<div style="font-size:{l3}px;color:#9aa4af;line-height:1.2;">{html.escape(str(top_sub))}</div>'
                )
        bottom_sub_html = ""
        if bottom_sub:
            if bottom_sub_inline:
                bottom_sub_html = (
                    f'<span style="font-size:{l5}px;color:#9aa4af;line-height:1.2;">{html.escape(str(bottom_sub))}</span>'
                )
            else:
                bottom_sub_html = (
                    f'<div style="font-size:{l3}px;color:#9aa4af;line-height:1.2;">{html.escape(str(bottom_sub))}</div>'
                )
        top_title_html = (
            f'<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:nowrap;">'
            f'<span style="font-size:{l3}px;color:#546e7a;font-weight:600;white-space:nowrap;">{top_label_e}</span>'
            f'{top_sub_html}'
            "</div>"
            if top_sub_inline
            else f'<div style="font-size:{l3}px;color:#546e7a;font-weight:600;">{top_label_e}</div>{top_sub_html}'
        )
        bottom_title_html = (
            f'<div style="display:flex;align-items:baseline;gap:8px;flex-wrap:nowrap;">'
            f'<span style="font-size:{l3}px;color:#546e7a;font-weight:600;white-space:nowrap;">{bottom_label_e}</span>'
            f'{bottom_sub_html}'
            "</div>"
            if bottom_sub_inline
            else f'<div style="font-size:{l3}px;color:#546e7a;font-weight:600;">{bottom_label_e}</div>{bottom_sub_html}'
        )
        return (
            '<div style="background:white;border:1px solid #e0e0e0;border-radius:8px;'
            'padding:14px 16px;height:162px;display:flex;flex-direction:column;justify-content:space-between;'
            'margin-bottom:6px;">'
            '<div style="min-height:68px;display:flex;flex-direction:column;justify-content:flex-start;">'
            f"{top_title_html}"
            f'<div style="font-size:{l4}px;font-weight:700;color:{top_color};line-height:1.15;">{top_value_e}</div>'
            '</div>'
            '<div style="border-top:1px solid #f0f0f0;padding-top:10px;min-height:64px;'
            'display:flex;flex-direction:column;justify-content:flex-start;">'
            f"{bottom_title_html}"
            f'<div style="font-size:{l4}px;font-weight:700;color:{bottom_color};line-height:1.15;">{bottom_value_e}</div>'
            '</div>'
            '</div>'
        )

    completion_pct = "{:.1f}".format(float(v["yield_rate"]) * 100.0)
    scrap_pct = "{:.1f}".format(float(v["sr"]) * 100.0)
    lead_fin_text = "{:.1f}".format(float(v["ct_fin"]))
    lead_all_text = "{:.1f}".format(float(v["ct_all"]))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            _pair_card_html(
                "WIP (pcs)",
                str(v["wip"]),
                _KPI_COLOR_WIP,
                "AVG WIP (pcs)",
                "{:.3f}".format(v["awip"]),
                _KPI_COLOR_WIP,
            ),
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            _pair_card_html(
                "Completions",
                str(v["n_comp"]),
                _KPI_COLOR_COMPLETION,
                "Completion Rate (%)",
                completion_pct,
                _KPI_COLOR_COMPLETION,
            ),
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            _pair_card_html(
                "Scraps",
                str(v["n_scrap"]),
                _KPI_COLOR_SCRAP,
                "Scrap Rate (%)",
                scrap_pct,
                _KPI_COLOR_SCRAP,
            ),
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            _pair_card_html(
                "Lead Time (s)",
                lead_fin_text,
                _KPI_COLOR_LEAD,
                "Lead Time all (s)",
                lead_all_text,
                _KPI_COLOR_LEAD,
            ),
            unsafe_allow_html=True,
        )


def render_stage_kpi_group(kpi: dict | None) -> None:
    k = dict(kpi or {})
    stg = k.get("stages") or {}
    st.markdown(
        _kpi_section_title_html("Stage KPI", "stage"),
        unsafe_allow_html=True,
    )
    stage_cfg = {
        1: {"name": "Stage 1", "type": "Non-Looping"},
        2: {"name": "Stage 2", "type": "Looping"},
        3: {"name": "Stage 3", "type": "Non-Looping"},
        4: {"name": "Stage 4", "type": "Looping"},
        5: {"name": "Stage 5", "type": "Non-Looping"},
        6: {"name": "Stage 6", "type": "Looping"},
    }
    def _stage_card_html(s: int) -> str:
        data = stg.get("stage{}".format(s)) or stg.get(str(s)) or {}
        cfg = stage_cfg[s]
        thr_v = float(data.get("throughput", data.get("throughput_per_sec", 0)) or 0)
        ft_v = float(data.get("avg_flow_time", data.get("avg_flow_time_sec", 0)) or 0)
        awip_v = float(data.get("wip_average", data.get("avg_wip", 0)) or 0)
        wip_v = int(data.get("wip_instantaneous", data.get("instantaneous_wip", 0)) or 0)
        dep_v = int(data.get("num_departures", data.get("departures", 0)) or 0)

        thr = "{:.4f}".format(thr_v)
        ft = "{:.1f}".format(ft_v)
        awip = "{:.3f}".format(awip_v)
        wip = str(wip_v)
        dep = str(dep_v)
        l3, l4, l4t, l5n = _FONT_L3_PX, _FONT_L4_STAGE_PX, _FONT_L4_STAGE_THR_PX, _FONT_STAGE_NAME_PX
        c_wip, c_lead, c_def = _KPI_COLOR_WIP, _KPI_COLOR_LEAD, _KPI_COLOR_DEFAULT
        c_title, c_badge_bg, c_badge_txt = _STAGE_TITLE_COLOR, _STAGE_BADGE_BG, _STAGE_BADGE_TEXT
        c_accent = _STAGE_CARD_ACCENT
        return f"""
<div style="background:white;border:0.5px solid #e0e0e0;
            border-radius:12px;border-left:3px solid {c_accent};
            padding:14px 18px;margin-bottom:8px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">
    <span style="font-size:{l5n}px;font-weight:700;color:{c_title};">{cfg['name']}</span>
    <span style="background:{c_badge_bg};color:{c_badge_txt};font-size:{l3}px;
                 font-weight:500;padding:2px 8px;border-radius:20px;">
      {cfg['type']}
    </span>
  </div>
  <div style="display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;">
    <div>
      <div style="font-size:{l3}px;color:#64748b;margin-bottom:3px;font-weight:600;">WIP (pcs)</div>
      <div style="font-size:{l4}px;font-weight:700;color:{c_wip};">{wip}</div>
    </div>
    <div>
      <div style="font-size:{l3}px;color:#64748b;margin-bottom:3px;font-weight:600;">AVG WIP (pcs)</div>
      <div style="font-size:{l4}px;font-weight:700;color:{c_wip};">{awip}</div>
    </div>
    <div>
      <div style="font-size:{l3}px;color:#64748b;margin-bottom:3px;font-weight:600;">Avg Flow Time (s)</div>
      <div style="font-size:{l4}px;font-weight:700;color:{c_lead};">{ft}</div>
    </div>
    <div>
      <div style="font-size:{l3}px;color:#64748b;margin-bottom:3px;font-weight:600;">Throughput (/s)</div>
      <div style="font-size:{l4t}px;font-weight:700;color:{c_def};">{thr}</div>
    </div>
    <div>
      <div style="font-size:{l3}px;color:#64748b;margin-bottom:3px;font-weight:600;">Departures</div>
      <div style="font-size:{l4}px;font-weight:700;color:{c_def};">{dep}</div>
    </div>
  </div>
</div>
"""

    col_l, col_r = st.columns(2, gap="small")
    with col_l:
        for s in (1, 2, 3):
            st.markdown(_stage_card_html(s), unsafe_allow_html=True)
    with col_r:
        for s in (4, 5, 6):
            st.markdown(_stage_card_html(s), unsafe_allow_html=True)


def replay_age_seconds(last_update_unix: float) -> float | None:
    if not last_update_unix:
        return None
    return max(0.0, time.time() - last_update_unix)


def _trend_chart_title(text: str) -> dict[str, Any]:
    return dict(
        text=text,
        font=dict(family=_PLOT_FONT, size=_FONT_CHART_TITLE_PX, color=_UI_THEME["text"]),
    )


_TREND_HOVERLABEL: dict[str, Any] = dict(
    bgcolor="#1e2a3a",
    font_size=_FONT_L5_PX,
    font_family=_PLOT_FONT,
    font_color="#e0e6f0",
    bordercolor="#444c56",
)


def _trend_layout_common(*, showlegend: bool) -> dict[str, Any]:
    d: dict[str, Any] = {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "#f8f9fa",
        "margin": dict(t=36, b=30, l=50, r=20),
        "height": 260,
        "font": dict(family=_PLOT_FONT, size=_FONT_CHART_AXIS_PX, color="#546e7a"),
        "showlegend": showlegend,
        "hovermode": "x unified",
        "hoverlabel": _TREND_HOVERLABEL,
    }
    if showlegend:
        d["legend"] = dict(
            x=0.01,
            y=0.99,
            xanchor="left",
            yanchor="top",
            bgcolor="rgba(255,255,255,0.8)",
            borderwidth=0,
            font=dict(size=_FONT_CHART_AXIS_PX, color="#546e7a", family=_PLOT_FONT),
        )
    return d


def _trend_apply_grid(fig: go.Figure) -> None:
    g = _UI_THEME["border"]
    z = _UI_THEME["border2"]
    ax_font = dict(size=_FONT_CHART_AXIS_PX, color=_UI_THEME["text_dim"])
    title_font = dict(size=_FONT_CHART_AXIS_PX, color=_UI_THEME["text_dim"], family=_PLOT_FONT)
    fig.update_xaxes(
        showgrid=False,
        gridcolor=g,
        gridwidth=1,
        zeroline=False,
        zerolinecolor=z,
        zerolinewidth=1,
        tickfont=ax_font,
        title_font=title_font,
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=g,
        gridwidth=1,
        zeroline=True,
        zerolinecolor=z,
        zerolinewidth=1,
        tickfont=ax_font,
        title_font=title_font,
    )


def _trend_pair_layout_extras() -> dict[str, Any]:
    """Trends 双图共用：等高、margin 对齐、图例右上。"""
    base = _trend_layout_common(showlegend=True)
    base["height"] = _TREND_CHART_HEIGHT
    base["margin"] = dict(_TREND_PAIR_MARGIN)
    base["legend"] = dict(
        orientation="h",
        x=1.0,
        y=1.02,
        xanchor="right",
        yanchor="bottom",
        bgcolor="rgba(255,255,255,0)",
        borderwidth=0,
        font=dict(size=_FONT_CHART_AXIS_PX, color="#546e7a", family=_PLOT_FONT),
    )
    return base


def _trend_pair_apply_xaxis(fig: go.Figure, *, empty: bool) -> None:
    fig.update_xaxes(
        title=dict(text=""),
        showticklabels=not empty,
        tickformat="%H:%M:%S",
        nticks=4,
        tickangle=0,
    )


def _wip_trend_series_average(hist: list[tuple[float, int]]) -> float:
    """Time-weighted mean over the points actually drawn (not full-run system avg)."""
    if not hist:
        return 0.0
    if len(hist) == 1:
        return float(hist[0][1])
    total = 0.0
    for i in range(len(hist) - 1):
        t0, w = hist[i]
        t1, _ = hist[i + 1]
        total += float(w) * max(0.0, t1 - t0)
    tail = max(0.0, hist[-1][0] - hist[-2][0])
    last_t, last_w = hist[-1]
    total += float(last_w) * tail
    span = max(0.001, (hist[-1][0] - hist[0][0]) + tail)
    return total / span


def _wip_trend_y_range(ys: list[int], avg_w: float, *, pad: float = 2.0) -> list[float]:
    """dataMin - pad .. dataMax + pad (WIP 不强制从 0 起）。"""
    vals = [float(v) for v in ys] + [float(avg_w)]
    if not vals:
        return [0.0, 4.0]
    lo = min(vals) - pad
    hi = max(vals) + pad
    if hi <= lo:
        hi = lo + 4.0
    return [lo, hi]


def _wip_trend_apply_axes(
    fig: go.Figure, *, empty: bool, y_range: list[float] | None = None
) -> None:
    _trend_apply_grid(fig)
    if empty:
        fig.update_yaxes(
            title=dict(text=""),
            range=[0, 4],
            autorange=False,
            nticks=5,
            tickformat="d",
        )
        _trend_pair_apply_xaxis(fig, empty=True)
        return
    fig.update_yaxes(
        title=dict(text=""),
        range=y_range,
        autorange=False,
        nticks=5,
        tickformat="d",
    )
    _trend_pair_apply_xaxis(fig, empty=False)


def _fig_wip_over_time(kpi: dict) -> go.Figure:
    hist = _parse_wip_trend_hist(kpi)
    avg_w = _wip_trend_series_average(hist)
    fig = go.Figure()
    if not hist:
        fig.update_layout(
            **_trend_pair_layout_extras(),
            title=_trend_chart_title(_CHART_TITLE_WIP),
        )
        _wip_trend_apply_axes(fig, empty=True)
        return fig
    n = len(hist)
    ys = [w for _, w in hist]
    x_dt = [
        datetime.datetime.fromtimestamp(max(0.0, min(1e12, float(ts))))
        for ts, _ in hist
    ]
    sample_idx = list(range(1, n + 1))
    mk = dict(
        size=3,
        color="#1976d2",
        symbol="circle",
        line=dict(width=1, color="#ffffff"),
    )
    fig.add_trace(
        go.Scatter(
            x=x_dt,
            y=ys,
            mode="lines+markers",
            name="WIP",
            line=dict(color="#1976d2", width=2.5),
            marker=mk,
            selected=dict(marker=dict(size=10, color="#1976d2")),
            unselected=dict(marker=dict(size=3, opacity=1.0)),
            customdata=sample_idx,
            hovertemplate=(
                "<b>Sample %{customdata}</b><br>Time: %{x|%H:%M:%S}<br>WIP: %{y}<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_dt,
            y=[avg_w] * n,
            mode="lines",
            name="AVG WIP",
            line=dict(color="#ff9800", width=2, dash="6px,3px"),
            hovertemplate=(
                "AVG WIP (this window): %{y:.2f}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_trend_pair_layout_extras(),
        title=_trend_chart_title(_CHART_TITLE_WIP),
    )
    _wip_trend_apply_axes(
        fig, empty=False, y_range=_wip_trend_y_range(ys, avg_w)
    )
    return fig


def _parse_wip_trend_hist(kpi: dict) -> list[tuple[float, int]]:
    raw = kpi.get("trend_sys_wip_history")
    hist: list[tuple[float, int]] = []
    if isinstance(raw, list):
        for row in raw:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                try:
                    hist.append((float(row[0]), int(row[1])))
                except (TypeError, ValueError):
                    pass
    if len(hist) > _WIP_TREND_MAX_POINTS:
        hist = hist[-_WIP_TREND_MAX_POINTS:]
    return hist


def _trend_rate_points(kpi: dict) -> list[tuple[float, float, float]]:
    """(unix_ts, completion_rate_pct, scrap_rate_pct) — 仅 trend_rate_history，与 WIP 同源采样。"""
    rows: list[tuple[float, float, float]] = []
    raw = kpi.get("trend_rate_history")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                try:
                    rows.append((float(item[0]), float(item[1]), float(item[2])))
                except (TypeError, ValueError):
                    pass
    if len(rows) > _WIP_TREND_MAX_POINTS:
        rows = rows[-_WIP_TREND_MAX_POINTS:]
    return rows


def _rate_trend_apply_axes(fig: go.Figure, *, empty: bool) -> None:
    _trend_apply_grid(fig)
    fig.update_yaxes(
        title=dict(text=""),
        range=[0, 100],
        autorange=False,
        tickmode="array",
        tickvals=[0, 25, 50, 75, 100],
    )
    _trend_pair_apply_xaxis(fig, empty=empty)


def _fig_completion_scrap_over_time(kpi: dict) -> go.Figure:
    hist = _trend_rate_points(kpi)
    fig = go.Figure()
    if not hist:
        fig.update_layout(
            **_trend_pair_layout_extras(),
            title=_trend_chart_title(_CHART_TITLE_RATES),
        )
        _rate_trend_apply_axes(fig, empty=True)
        return fig
    x_dt = [
        datetime.datetime.fromtimestamp(max(0.0, min(1e12, float(ts))))
        for ts, _, _ in hist
    ]
    comp_y = [c for _, c, _ in hist]
    scrap_y = [s for _, _, s in hist]
    n = len(hist)
    sample_idx = list(range(1, n + 1))
    fig.add_trace(
        go.Scatter(
            x=x_dt,
            y=comp_y,
            mode="lines",
            name="Completion (recent)",
            line=dict(color="#16A34A", width=2),
            customdata=sample_idx,
            hovertemplate=(
                "<b>Sample %{customdata}</b><br>Time: %{x|%H:%M:%S}<br>"
                "Completion: %{y:.1f}% (recent window)<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_dt,
            y=scrap_y,
            mode="lines",
            name="Scrap (recent)",
            line=dict(color="#DC2626", width=2),
            customdata=sample_idx,
            hovertemplate=(
                "<b>Sample %{customdata}</b><br>Time: %{x|%H:%M:%S}<br>"
                "Scrap: %{y:.1f}% (recent window)<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        **_trend_pair_layout_extras(),
        title=_trend_chart_title(_CHART_TITLE_RATES),
    )
    _rate_trend_apply_axes(fig, empty=False)
    return fig


def render_kpi_trends_block(kpi: dict | None) -> None:
    """Trends：WIP 时序 / Completion & Scrap（两图并排、等高）。"""
    k = dict(kpi or {})
    st.markdown(
        _kpi_section_title_html("Trends", "trends"),
        unsafe_allow_html=True,
    )
    with st.container(key="kpi_trends_wrap"):
        c1, c2 = st.columns(2, gap="small")
        with c1:
            st.plotly_chart(
                _fig_wip_over_time(k),
                use_container_width=True,
                config={"displayModeBar": False},
                key="kpi_trend_wip_over_time",
            )
        with c2:
            st.plotly_chart(
                _fig_completion_scrap_over_time(k),
                use_container_width=True,
                config={"displayModeBar": False},
                key="kpi_trend_completion_scrap",
            )
    


def render_kpi_metrics(
    kpi: dict | None,
    *,
    age_sec: float | None = None,
) -> None:
    """Deprecated name: same as **System KPI** block only (for older callers/tests)."""
    render_system_kpi_group(kpi, age_sec=age_sec)


def render_kpi_dashboard(
    kpi: dict | None,
    *,
    age_sec: float | None = None,
    cols_per_row: int = 4,
    compact_stations: bool = True,
) -> None:
    st.markdown(_KPI_SECTION_TITLE_CSS, unsafe_allow_html=True)
    with st.container(border=True, key="kpi_all_panel"):
        render_system_kpi_group(kpi, age_sec=age_sec)
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.markdown(
            "<hr style='border:none;border-top:1px solid #e2e8f0;margin:6px 0 10px 0;'>",
            unsafe_allow_html=True,
        )
        render_kpi_trends_block(kpi)
        st.markdown(
            "<hr style='border:none;border-top:1px solid #e2e8f0;margin:10px 0 10px 0;'>",
            unsafe_allow_html=True,
        )
        with st.container(key="kpi_stage_station_panel"):
            with st.container(key="kpi_stage_col"):
                render_stage_kpi_group(kpi)
                st.markdown(
                    '<div class="kpi-stage-spacer" aria-hidden="true"></div>',
                    unsafe_allow_html=True,
                )
            render_station_card_grid(
                kpi,
                cols_per_row=cols_per_row,
                age_sec=age_sec,
                compact=compact_stations,
            )
