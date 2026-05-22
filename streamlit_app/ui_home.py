"""
Main page: global control + dashboard entry links (week6 §六阶段 A).
"""
from __future__ import annotations

import html
import json
import os
import time

import streamlit as st

from paths import PROJECT_ROOT

import mqtt_backend
import physical_workflow
import process_control
import recording
import ui_history_panel
import ui_replay_panel


@st.dialog("Service logs", width="large")
def _service_logs_unified_dialog() -> None:
    """Control run history + service/deployment logs."""
    t1, t2, t3 = st.tabs(["Control Runs", "main_service", "Deployment(raw)"])
    with t1:
        _h_r1, _h_r2 = st.columns([4, 1])
        with _h_r1:
            st.caption("完整控制动作记录（Start/Stop/Shutdown/System）")
        with _h_r2:
            if st.button("Refresh", key="home_dlg_log_refresh_hist", type="secondary"):
                st.rerun()

        hist = process_control.read_control_action_history(80)
        if not hist:
            st.info("暂无控制动作记录。")
        else:
            for i, row in enumerate(hist):
                cmd = str(row.get("cmd") or "—")
                tm = str(row.get("time_full") or row.get("time") or "")
                ok = row.get("success")
                icon = "✓" if ok is True else ("✗" if ok is False else "—")
                status = "successful" if ok is True else ("failed" if ok is False else "unknown")
                title = "{} {} · {} · {}".format(icon, cmd, tm, status)
                with st.expander(title, expanded=(i == 0)):
                    msg = (row.get("message") or "").strip()
                    if msg:
                        st.caption(msg)
                    prog = row.get("progress") if isinstance(row.get("progress"), dict) else {}
                    comps = prog.get("components") if isinstance(prog, dict) else {}
                    if isinstance(comps, dict) and comps:
                        st.caption(
                            "{} · {} · {}".format(
                                prog.get("operation", "—"),
                                prog.get("updated_at", "—"),
                                prog.get("status", "—"),
                            )
                        )
                        for k in sorted(comps.keys()):
                            if k == "_error":
                                continue
                            info = comps.get(k) or {}
                            c_ok = bool(info.get("ok"))
                            c_icon = "✓" if c_ok else "✗"
                            c_msg = (
                                (info.get("message") or "")
                                .replace("\r\n", "\n")
                                .replace("\r", "\n")
                                .strip()
                            )
                            st.markdown("**{}** — {}".format(k, c_icon))
                            if c_msg:
                                if c_ok:
                                    disp = (
                                        " ".join(c_msg.split())
                                        if "\n" in c_msg
                                        else c_msg
                                    )
                                    st.caption(disp)
                                else:
                                    st.code(c_msg, language=None)
                            elif not c_ok:
                                st.caption("Failed (no message)")
                            else:
                                st.caption("OK")
                    elif not msg:
                        st.caption("(no extra details)")

    with t2:
        _t_r1, _t_r2 = st.columns([4, 1])
        with _t_r1:
            _lt, _lp = process_control.tail_latest_main_service_log(100)
            st.caption(
                "**File:** `{}`".format(os.path.basename(_lp) if _lp else "—")
            )
        with _t_r2:
            if st.button("Refresh", key="home_dlg_log_refresh_main", type="secondary"):
                st.rerun()
        st.markdown(_service_log_html_block(_lt), unsafe_allow_html=True)
    with t3:
        _d_r1, _d_r2 = st.columns([4, 1])
        with _d_r1:
            _dt, _dp = process_control.tail_deployment_actions_log(200)
            st.caption(
                "**File:** `{}`".format(os.path.basename(_dp) if _dp else "—")
            )
        with _d_r2:
            if st.button("Refresh", key="home_dlg_log_refresh_dep", type="secondary"):
                st.rerun()
        st.markdown(_service_log_html_block(_dt), unsafe_allow_html=True)


def _render_live_header_status(*, logs_disabled: bool) -> None:
    """LIVE 标题行右侧：Programs / System + View Logs。

    Last command stays in ``session_state.last_cmd`` and View Logs; not shown in the bar.

    ``logs_disabled``：仅在未选择 Data Source 时禁用日志（回放/本地仍可查日志）。
    """
    prog_raw = process_control.get_programs_status()
    sys_raw = process_control.get_system_status()
    last = process_control.read_last_control_action()

    st.session_state["programs_status"] = prog_raw
    st.session_state["system_status"] = sys_raw
    if last:
        _succ = last.get("success")
        st.session_state["last_cmd"] = {
            "name": str(last.get("cmd") or "—"),
            "result": "successful" if _succ is True else "failed",
            "time": str(last.get("time") or ""),
        }
    else:
        st.session_state["last_cmd"] = {}

    prog_color = {
        "activated": "#2e7d32",
        "partial": "#b45309",
        "deactivated": "#64748b",
    }.get(prog_raw, "#64748b")
    prog_bg = {
        "activated": "#dcfce7",
        "partial": "#fef3c7",
        "deactivated": "#f1f5f9",
    }.get(prog_raw, "#f1f5f9")
    prog_label = {
        "activated": "Activated",
        "partial": "Partial",
        "deactivated": "Deactivated",
    }.get(prog_raw, prog_raw.replace("_", " ").title())

    sys_color = "#2e7d32" if sys_raw == "start" else "#64748b"
    sys_bg = "#dcfce7" if sys_raw == "start" else "#f1f5f9"
    sys_label = "Running" if sys_raw == "start" else "Stopped"

    status_html = (
        '<div class="cp-live-status-line cp-live-status-line--inline cp-live-status-bar">'
        '<span class="cp-live-status-core">'
        '<span class="cp-stat-pill" style="background:{pb};border:1.5px solid {pc};">'
        '<span class="cp-stat-dot" style="background:{pc};"></span>'
        '<span class="cp-stat-key">Programs</span>'
        '<span class="cp-stat-val" style="color:{pc};">{pl}</span>'
        '</span>'
        '<span class="cp-stat-pill" style="background:{sb};border:1.5px solid {sc};">'
        '<span class="cp-stat-dot" style="background:{sc};"></span>'
        '<span class="cp-stat-key">System</span>'
        '<span class="cp-stat-val" style="color:{sc};">{sl}</span>'
        '</span>'
        '</span>'
        '</div>'
    ).format(
        pb=prog_bg,
        pc=prog_color,
        pl=prog_label,
        sb=sys_bg,
        sc=sys_color,
        sl=sys_label,
    )

    _sl, _sr = st.columns([1, 0.42], gap="small", vertical_alignment="center")
    with _sl:
        st.markdown(status_html, unsafe_allow_html=True)
    with _sr:
        if st.button(
            "View Logs",
            key="home_view_logs",
            type="secondary",
            use_container_width=True,
            help="main_service 日志与 deployment_actions（含 Upload）",
            disabled=logs_disabled,
        ):
            _service_logs_unified_dialog()


def _service_log_html_block(text: str) -> str:
    """Colored log body for ``st.markdown(..., unsafe_allow_html=True)``."""
    raw = text or ""
    if not raw.strip():
        inner = '<span style="color:#6b7280;">(empty)</span>'
    else:
        parts: list[str] = []
        for line in raw.splitlines():
            u = line.upper()
            if "ERROR" in u or "FAIL" in u:
                color = "#b91c1c"
            elif "WARNING" in u or "WARN" in u:
                color = "#c2410c"
            else:
                color = "#1f2937"
            parts.append(
                '<span style="color:{};">{}</span>'.format(color, html.escape(line))
            )
        inner = "\n".join(parts)
    return (
        '<pre style="margin:0.35rem 0 0 0;font-family:Consolas,Monaco,monospace;'
        "font-size:13px;background-color:#f5f5f5;padding:14px;border-radius:8px;"
        "white-space:pre-wrap;word-break:break-word;max-height:420px;overflow-y:auto;"
        'line-height:1.55;border:1px solid #e5e7eb;">{}</pre>'
    ).format(inner)


# Control Panel（ui优化：可读性优先、徽章状态条、触控目标与危险操作分隔）
_HOME_MAIN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow+Condensed:wght@300;400;500;600;700;900&display=swap');

:root {
  --bg: #f8fafc;
  --surface: #ffffff;
  --surface2: #f1f5f9;
  --border: #e2e8f0;
  --border2: #cbd5e1;
  --text: #1e293b;
  --text-dim: #64748b;
  --accent: #0284c7;
  --sans: 'Barlow Condensed', sans-serif;
  --mono: 'Share Tech Mono', monospace;
  --cp-blue: #1565c0;
  --cp-blue-soft: #e3f2fd;
  --cp-orange: #c2570a;
  --cp-orange-soft: #fff7ed;
  --cp-red: #b91c1c;
  --cp-red-soft: #fef2f2;
  --cp-stop-bg: #f1f5f9;
  --cp-stop-border: #94a3b8;
  --cp-green-dot: #22c55e;
  --cp-btn-h: 46px;
  --cp-card-shadow: 0 1px 4px rgba(15, 23, 42, 0.07);
  --cp-radius: 10px;
  --cp-radius-btn: 8px;
}

div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"]:has(.home-module-head-live) > div > [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"]:first-of-type {
    justify-content: space-between !important;
    width: 100% !important;
    align-items: center !important;
}

div[data-testid="stAppViewContainer"] .stMainBlockContainer {
    background-color: var(--bg) !important;
}
div[data-testid="stMainBlockContainer"] {
    padding-top: 1rem !important;
    font-family: var(--sans) !important;
    font-size: 15px !important;
    color: var(--text) !important;
}
div[data-testid="stMainBlockContainer"] h1 {
    font-family: var(--sans) !important;
    font-size: 2rem !important;
    font-weight: 900 !important;
    letter-spacing: 0.04em !important;
    color: var(--text) !important;
    margin-bottom: 1.25rem !important;
}

div[data-testid="stMainBlockContainer"] .home-module-head-live {
    font-family: var(--sans) !important;
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    letter-spacing: 1.5px !important;
    color: var(--cp-blue) !important;
    border-left: 4px solid var(--cp-blue) !important;
    border-top: none !important;
    padding: 10px 0 10px 14px !important;
    margin: 0 !important;
    text-transform: uppercase !important;
    background: transparent !important;
    border-radius: 0 !important;
}
div[data-testid="stMainBlockContainer"] .home-module-head-live.cp-live-head-inline {
    margin: 0 !important;
}

div[data-testid="stMainBlockContainer"] .home-module-head-history {
    font-family: var(--sans) !important;
    font-size: 1.15rem !important;
    font-weight: 700 !important;
    letter-spacing: 1.5px !important;
    color: var(--cp-orange) !important;
    border-left: 4px solid var(--cp-orange) !important;
    border-top: none !important;
    padding: 10px 0 10px 14px !important;
    margin: 0 0 1rem 0 !important;
    text-transform: uppercase !important;
    background: transparent !important;
    border-radius: 0 !important;
}

div[data-testid="stMainBlockContainer"] .cp-live-subsection-label {
    font-family: var(--sans) !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    color: #374151 !important;
    margin: 12px 0 10px 0 !important;
    line-height: 1.2 !important;
    text-transform: uppercase !important;
    letter-spacing: 1px !important;
    border-bottom: 1px solid var(--border) !important;
    padding-bottom: 6px !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-subsection-label--deployment {
    margin-top: 18px !important;
}

div[data-testid="stMainBlockContainer"] .cp-live-status-line {
    font-family: var(--sans) !important;
    font-size: 15px !important;
    color: var(--text-dim) !important;
    line-height: 1.35 !important;
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    flex-wrap: wrap !important;
    margin: 0 !important;
    min-height: var(--cp-btn-h) !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-line--inline {
    min-height: var(--cp-btn-h) !important;
    justify-content: flex-end !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-line.cp-live-status-bar {
    justify-content: flex-start !important;
    flex-wrap: nowrap !important;
    text-align: left !important;
    width: 100% !important;
    max-width: 100% !important;
    box-sizing: border-box !important;
    column-gap: 10px !important;
    row-gap: 0 !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-core {
    flex: 0 0 auto !important;
    display: inline-flex !important;
    align-items: center !important;
    gap: 8px !important;
    white-space: nowrap !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-last {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    max-width: 100% !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-last-inner {
    display: block !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
    font-size: 14px !important;
    color: var(--text-dim) !important;
}

div[data-testid="stMainBlockContainer"] .cp-stat-pill {
    display: inline-flex !important;
    align-items: center !important;
    gap: 6px !important;
    padding: 4px 10px 4px 8px !important;
    border-radius: 20px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    white-space: nowrap !important;
}
div[data-testid="stMainBlockContainer"] .cp-stat-dot {
    width: 8px !important;
    height: 8px !important;
    border-radius: 50% !important;
    flex-shrink: 0 !important;
}
div[data-testid="stMainBlockContainer"] .cp-stat-key {
    color: var(--text-dim) !important;
}
div[data-testid="stMainBlockContainer"] .cp-stat-val {
    font-weight: 700 !important;
}

div[data-testid="stMainBlockContainer"] .cp-live-run-stop {
    display: inline-flex !important;
    align-items: center !important;
    gap: 8px !important;
    color: var(--text) !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-sep {
    color: var(--border2) !important;
    user-select: none !important;
    font-size: 16px !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-fail-hint {
    color: var(--cp-red) !important;
    font-size: 13px !important;
}

div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"]:has(.home-module-head-live),
div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"]:has(.home-module-head-history) {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--cp-radius) !important;
    box-shadow: var(--cp-card-shadow) !important;
    padding: 1.25rem 1.5rem 1.4rem !important;
    margin-bottom: 1.25rem !important;
}

div[data-testid="stMainBlockContainer"] .home-section-title {
    font-family: var(--sans) !important;
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 1.5px !important;
    color: var(--text-dim) !important;
    border-bottom: 1px solid var(--border) !important;
    padding-bottom: 7px !important;
    margin: 0.5rem 0 0.75rem 0 !important;
}

div[data-testid="stMainBlockContainer"] .cp-ds-title {
    font-family: var(--sans) !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    letter-spacing: 1px !important;
    color: var(--cp-blue) !important;
    margin: 0 0 0.75rem 0 !important;
    text-transform: uppercase !important;
}
div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"]:has(.cp-ds-title) {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--cp-radius) !important;
    border-top: 3px solid var(--accent) !important;
    box-shadow: var(--cp-card-shadow) !important;
    margin-bottom: 1.25rem !important;
    padding: 1.25rem 1.5rem !important;
}

div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local {
    max-width: 220px !important;
    filter: drop-shadow(0 1px 2px rgba(15, 23, 42, 0.04)) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_ds_row [data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    justify-content: flex-start !important;
    align-items: stretch !important;
    gap: 0.5rem !important;
    width: 100% !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_ds_row [data-testid="stHorizontalBlock"] > div:nth-of-type(1),
div[data-testid="stMainBlockContainer"] div.st-key-cp_ds_row [data-testid="stHorizontalBlock"] > div:nth-of-type(2) {
    flex: 0 0 220px !important;
    min-width: 220px !important;
    max-width: 220px !important;
    width: 220px !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    box-sizing: border-box !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_ds_row [data-testid="stHorizontalBlock"] > div:nth-of-type(3) {
    flex: 1 1 auto !important;
    min-width: 0 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button {
    width: 220px !important;
    max-width: 220px !important;
    min-height: 74px !important;
    height: auto !important;
    border-radius: var(--cp-radius-btn) !important;
    padding: 16px 16px 16px 40px !important;
    font-family: var(--sans) !important;
    font-size: 18px !important;
    font-weight: 600 !important;
    line-height: 1.45 !important;
    color: var(--text) !important;
    text-align: left !important;
    justify-content: flex-start !important;
    white-space: normal !important;
    position: relative !important;
    box-sizing: border-box !important;
    box-shadow: var(--cp-card-shadow) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button p,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button p {
    font-family: var(--sans) !important;
    font-size: 18px !important;
    font-weight: 600 !important;
}

div[data-testid="stMainBlockContainer"] div.st-key-home_start_progs button,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_stop button,
div[data-testid="stMainBlockContainer"] div.st-key-home_stop_progs button,
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown button,
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_code button,
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_cfg button {
    min-height: var(--cp-btn-h) !important;
    max-height: var(--cp-btn-h) !important;
    height: var(--cp-btn-h) !important;
    font-family: var(--sans) !important;
    font-size: 15px !important;
    font-weight: 600 !important;
    border-radius: var(--cp-radius-btn) !important;
    padding: 0 10px !important;
    line-height: 1.2 !important;
    box-sizing: border-box !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_start_progs button,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button {
    background: var(--cp-blue-soft) !important;
    border: 1.5px solid var(--cp-blue) !important;
    color: var(--cp-blue) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_start_progs button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button:hover:not(:disabled) {
    box-shadow: 0 2px 8px rgba(21, 101, 192, 0.2) !important;
    border-color: #0d47a1 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_stop button,
div[data-testid="stMainBlockContainer"] div.st-key-home_stop_progs button {
    background: var(--cp-stop-bg) !important;
    border: 1.5px solid var(--cp-stop-border) !important;
    color: var(--text) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_stop button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-home_stop_progs button:hover:not(:disabled) {
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.1) !important;
    border-color: var(--border2) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown button {
    background: var(--cp-red-soft) !important;
    border: 2px solid var(--cp-red) !important;
    color: var(--cp-red) !important;
    font-weight: 700 !important;
    letter-spacing: 0.5px !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown button:hover:not(:disabled) {
    box-shadow: 0 2px 10px rgba(185, 28, 28, 0.2) !important;
    background: #fee2e2 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown {
    margin-left: 6px !important;
    border-left: 1px solid var(--border2) !important;
    padding-left: 6px !important;
    box-sizing: border-box !important;
}

div[data-testid="stMainBlockContainer"] div.st-key-home_ul_code button,
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_cfg button {
    background: var(--surface2) !important;
    border: 1.5px solid var(--cp-stop-border) !important;
    color: var(--text) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_code button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_cfg button:hover:not(:disabled) {
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
    border-color: var(--border2) !important;
}

div[data-testid="stMainBlockContainer"] div.st-key-home_start_progs button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_stop button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_stop_progs button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_code button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_ul_cfg button:disabled {
    opacity: 0.45 !important;
    cursor: not-allowed !important;
    box-shadow: none !important;
}

div[data-testid="stMainBlockContainer"] .cp-svc-status {
    font-size: 14px;
    color: var(--text-dim);
    margin: 0.4rem 0 0 0;
    display: flex;
    align-items: center;
    gap: 8px;
}
div[data-testid="stMainBlockContainer"] .cp-svc-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    flex-shrink: 0;
}
div[data-testid="stMainBlockContainer"] .cp-svc-dot--idle { background: #94a3b8; }
div[data-testid="stMainBlockContainer"] .cp-svc-dot--run  { background: var(--cp-green-dot); }

div[data-testid="stMainBlockContainer"] div.st-key-home_view_logs button {
    min-height: var(--cp-btn-h) !important;
    max-height: var(--cp-btn-h) !important;
    height: var(--cp-btn-h) !important;
    padding: 0 16px !important;
    font-family: var(--sans) !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    border-radius: var(--cp-radius-btn) !important;
    line-height: 1.2 !important;
    box-sizing: border-box !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
}
div[data-testid="stMainBlockContainer"] .cp-live-status-line,
div[data-testid="stMainBlockContainer"] .cp-live-status-line *,
div[data-testid="stMainBlockContainer"] .cp-live-status-bar,
div[data-testid="stMainBlockContainer"] .cp-live-status-bar * {
    font-size: 16px !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_view_logs button:hover:not(:disabled) {
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_view_logs button:disabled {
    opacity: 0.45 !important;
    cursor: not-allowed !important;
}

div[data-testid="stMainBlockContainer"] div[data-testid="column"]:has(.st-key-home_dash_kpi) [data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stMainBlockContainer"] div[data-testid="column"]:has(.st-key-home_dash_twin) [data-testid="stVerticalBlockBorderWrapper"] {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
    padding: 0 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button,
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button {
    min-height: 72px !important;
    height: 72px !important;
    font-family: var(--sans) !important;
    white-space: nowrap !important;
    line-height: 1.25 !important;
    text-align: center !important;
    justify-content: center !important;
    align-items: center !important;
    padding: 12px 20px !important;
    border-radius: var(--cp-radius) !important;
    font-size: 16px !important;
    font-weight: 700 !important;
    color: var(--text) !important;
    background: var(--surface) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button {
    border: 1px solid var(--border) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button {
    border: 1px solid var(--border) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button:hover:not(:disabled) {
    box-shadow: 0 3px 10px rgba(15, 23, 42, 0.1) !important;
    border-color: var(--accent) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button:disabled {
    opacity: 0.45 !important;
    cursor: not-allowed !important;
}

div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"]:has(.home-other-services) {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--cp-radius) !important;
    box-shadow: var(--cp-card-shadow) !important;
    padding: 1rem 1.5rem !important;
}

div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button:disabled {
    opacity: 0.52 !important;
    cursor: not-allowed !important;
    box-shadow: none !important;
}
</style>
"""


_HOME_UI_REFRESH_CSS = """
<style>
#MainMenu, header, footer { visibility: hidden; }
.stApp { background: #f6f8fb; }
div[data-testid="stMainBlockContainer"] {
    padding-top: 1rem !important;
}
div[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlockBorderWrapper"] {
    background: #ffffff !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05) !important;
    margin-bottom: 14px !important;
}
div[data-testid="stButton"] > button {
    height: 38px !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    letter-spacing: .01em !important;
    border-radius: 7px !important;
    padding: 0 16px !important;
    width: 100% !important;
    white-space: nowrap !important;
    border: 1px solid #dee2e6 !important;
    background: #f8f9fa !important;
    color: #1f2937 !important;
    transition: all .15s !important;
}
div[data-testid="stButton"] > button:hover { background: #e9ecef !important; }
.cp-title-wrap {
    margin-bottom:20px;
    display:flex;
    align-items:baseline;
    gap:12px;
}
.cp-title-main {
    font-size:22px;
    font-weight:700;
    color:#212529;
    letter-spacing:-.3px;
}
.cp-title-sub { font-size:17px; color:#adb5bd; }
div[data-testid="stMainBlockContainer"] div.st-key-home_start_progs button,
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button {
    background: #ecfdf5 !important;
    border-color: #bbf7d0 !important;
    color: #166534 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_start button {
    background: #16a34a !important;
    border-color: #16a34a !important;
    color: #ffffff !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_btn_stop button,
div[data-testid="stMainBlockContainer"] div.st-key-home_stop_progs button {
    background: #f8fafc !important;
    border-color: #cbd5e1 !important;
    color: #172033 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_shutdown button {
    background: #fff1f2 !important;
    border-color: #fecdd3 !important;
    color: #b91c1c !important;
    font-weight: 750 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_hist_replay_toggle button,
div[data-testid="stMainBlockContainer"] div.st-key-home_hist_import_btn button {
    background: #e7f5ff !important;
    border-color: #1971c2 !important;
    color: #1864ab !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_view_logs button {
    background: transparent !important;
    border: 1px solid #dee2e6 !important;
    color: #64748b !important;
    height: 28px !important;
    font-size: 11px !important;
    font-weight: 700 !important;
    padding: 0 12px !important;
    width: auto !important;
    border-radius: 6px !important;
    white-space: nowrap !important;
    width: auto !important;
    min-width: 90px !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button {
    height: 84px !important;
    min-height: 84px !important;
    width: 100% !important;
    margin-top: -84px !important;
    margin-bottom: 0 !important;
    padding: 0 !important;
    font-size: 1px !important;
    background: transparent !important;
    border: none !important;
    color: transparent !important;
    box-shadow: none !important;
    border-radius: 10px !important;
    position: relative !important;
    z-index: 5 !important;
    cursor: pointer !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button:hover:not(:disabled) {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button:disabled {
    opacity: 0 !important;
}
div[data-testid="stMainBlockContainer"] .nav-card-hover:hover {
    background: #f0f4f8 !important;
    border-color: #c8d0da !important;
}
div[data-testid="stSelectbox"] > div > div {
    font-size: 13px !important;
    border-radius: 8px !important;
    border-color: #dee2e6 !important;
}
div[data-testid="stFileUploader"] section {
    border: 1.5px dashed #dee2e6 !important;
    border-radius: 8px !important;
    background: #fafafa !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button,
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button {
    min-height: 84px !important;
    height: 84px !important;
    width: 100% !important;
    margin-top: 0 !important;
    margin-bottom: 0 !important;
    padding: 12px 18px !important;
    font-size: 20px !important;
    line-height: 1.05 !important;
    font-weight: 700 !important;
    background: #eef2f7 !important;
    border: 1px solid #c9d2df !important;
    color: #1f2937 !important;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08) !important;
    border-radius: 10px !important;
    position: static !important;
    z-index: auto !important;
    cursor: pointer !important;
    justify-content: center !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button p,
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button p {
    font-family: var(--sans) !important;
    font-size: 20px !important;
    line-height: 1.05 !important;
    font-weight: 700 !important;
    color: #1f2937 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button:hover:not(:disabled),
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button:hover:not(:disabled) {
    background: #f0f4f8 !important;
    border-color: #c8d0da !important;
    color: #1f2937 !important;
    box-shadow: 0 3px 9px rgba(15, 23, 42, 0.12) !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_kpi button:disabled,
div[data-testid="stMainBlockContainer"] div.st-key-home_dash_twin button:disabled {
    opacity: 0.45 !important;
    cursor: not-allowed !important;
}
div[data-testid="stMainBlockContainer"] .cp-nav-tile {
    border: 1px solid #c9d2df !important;
    background: #eef2f7 !important;
    border-radius: 10px !important;
    min-height: 84px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 12px !important;
    padding: 12px 16px !important;
    box-sizing: border-box !important;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08) !important;
    transition: background .15s ease, border-color .15s ease, box-shadow .15s ease !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_nav_kpi_wrap,
div[data-testid="stMainBlockContainer"] div.st-key-home_nav_twin_wrap {
    position: relative !important;
    min-height: 84px !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_nav_kpi_wrap [data-testid="stMarkdownContainer"],
div[data-testid="stMainBlockContainer"] div.st-key-home_nav_twin_wrap [data-testid="stMarkdownContainer"] {
    pointer-events: none !important;
}
div[data-testid="stMainBlockContainer"] .cp-nav-icon {
    width: 34px !important;
    height: 34px !important;
    border-radius: 8px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    flex-shrink: 0 !important;
}
div[data-testid="stMainBlockContainer"] .cp-nav-title {
    font-size: 20px !important;
    line-height: 1.05 !important;
    font-weight: 700 !important;
    color: #1f2937 !important;
    font-family: var(--sans) !important;
    text-align: center !important;
}
div[data-testid="stMainBlockContainer"] .cp-nav-sub {
    margin-top: 3px !important;
    font-size: 14px !important;
    line-height: 1.2 !important;
    color: #6b7280 !important;
    font-family: var(--sans) !important;
}
</style>
"""


def section_title(
    text: str, color: str, right_html: str = "", accent: str = ""
) -> None:
    left = "border-left:4px solid {};".format(accent) if accent else ""
    st.markdown(
        """
<div style="display:flex;align-items:center;justify-content:space-between;
padding:10px 18px 9px;border-bottom:1px solid #f1f3f5;margin:-16px -16px 10px -16px;{left}">
  <span style="font-size:16px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:{color}">{text}</span>
  <div style="font-size:15px;color:#868e96;display:flex;align-items:center;gap:8px">{right_html}</div>
</div>
""".format(
            left=left, color=color, text=text, right_html=right_html
        ),
        unsafe_allow_html=True,
    )


def sub_label(text: str = "") -> None:
    if not text:
        return
    st.markdown(
        (
            '<p style="font-size:14px;font-weight:700;color:#adb5bd;'
            'letter-spacing:.05em;text-transform:uppercase;margin:4px 0 8px 0">{}</p>'
        ).format(text),
        unsafe_allow_html=True,
    )


def hr() -> None:
    st.markdown(
        '<hr style="border:none;border-top:1px solid #f1f3f5;margin:14px 0 12px">',
        unsafe_allow_html=True,
    )


def _replay_session_active() -> bool:
    p = st.session_state.get("replay_proc")
    if p is not None and p.poll() is None:
        return True
    kpi, _ = mqtt_backend.get_kpi_snapshot()
    return (kpi or {}).get("run_mode") == "replay"


def _validate_config_basename(basename: str) -> None:
    p = os.path.normpath(os.path.join(PROJECT_ROOT, basename))
    if not os.path.isfile(p):
        raise FileNotFoundError("Missing file: {}".format(basename))
    with open(p, encoding="utf-8") as f:
        json.load(f)


def _local_config_basename() -> str:
    cl = os.path.normpath(os.path.join(PROJECT_ROOT, "config_local.json"))
    return "config_local.json" if os.path.isfile(cl) else "config.json"


def _data_source_picker_css(ds: str | None) -> str:
    """卡片选中/未选中：与 :root token 一致（::before 勾选/空方框）。"""
    live_on = ds == "live"
    loc_on = ds == "local"
    live_bg = "var(--cp-blue-soft)" if live_on else "var(--surface)"
    live_bd = "2px solid var(--cp-blue)" if live_on else "1.5px solid var(--border)"
    loc_bg = "var(--cp-orange-soft)" if loc_on else "var(--surface)"
    loc_bd = "2px solid var(--cp-orange)" if loc_on else "1.5px solid var(--border)"

    def _before_on(accent_var: str) -> str:
        return (
            'content: "\u2713" !important;\n'
            "color: #ffffff !important;\n"
            "font-size: 9px !important;\n"
            "font-weight: 700 !important;\n"
            "line-height: 12px !important;\n"
            "text-align: center !important;\n"
            "width: 12px !important;\n"
            "height: 12px !important;\n"
            "border: none !important;\n"
            "border-radius: 2px !important;\n"
            "background: {0} !important;\n".format(accent_var)
        )

    def _before_off() -> str:
        return (
            'content: "" !important;\n'
            "width: 12px !important;\n"
            "height: 12px !important;\n"
            "border: 1.5px solid var(--border2) !important;\n"
            "border-radius: 2px !important;\n"
            "background: var(--surface) !important;\n"
        )

    live_before = _before_on("var(--cp-blue)") if live_on else _before_off()
    loc_before = _before_on("var(--cp-orange)") if loc_on else _before_off()
    live_hover = "var(--cp-blue)" if live_on else "var(--border2)"
    loc_hover = "var(--cp-orange)" if loc_on else "var(--border2)"

    return """
<style>
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button {{
  background: {lb} !important;
  border: {lbd} !important;
}}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button::before {{
  position: absolute !important;
  left: 16px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  box-sizing: border-box !important;
  {lbi}
}}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_live button:hover {{
  border-color: {lh} !important;
  box-shadow: 0 2px 6px rgba(0,0,0,0.07) !important;
}}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button {{
  background: {ob} !important;
  border: {obd} !important;
}}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button::before {{
  position: absolute !important;
  left: 16px !important;
  top: 50% !important;
  transform: translateY(-50%) !important;
  box-sizing: border-box !important;
  {obi}
}}
div[data-testid="stMainBlockContainer"] div.st-key-cp_card_local button:hover {{
  border-color: {oh} !important;
  box-shadow: 0 2px 6px rgba(0,0,0,0.07) !important;
}}
</style>
""".format(
        lb=live_bg,
        lbd=live_bd,
        lbi=live_before,
        lh=live_hover,
        ob=loc_bg,
        obd=loc_bd,
        obi=loc_before,
        oh=loc_hover,
    )


def _render_data_source_configuration() -> None:
    ds = st.session_state.get("cp_data_source")
    live_active = ds == "live"
    hist_active = ds == "local"
    chk_svg = (
        '<svg width="9" height="7" viewBox="0 0 9 7" fill="none">'
        '<path d="M1 3l2.5 2.5L8 1" stroke="#fff" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )

    def _src_card_html(
        active: bool,
        border_color: str,
        bg: str,
        chk_style: str,
        chk_inner: str,
        dot_color: str,
        name: str,
        desc: str,
    ) -> str:
        desc_html = (
            '<div style="font-size:12px;color:#868e96;margin-top:2px">{}</div>'.format(desc)
            if str(desc).strip()
            else ""
        )
        return """
<div style="border:{bw} solid {bc};background:{bg};border-radius:10px;padding:14px 16px;
display:flex;align-items:center;gap:12px;">
  <div style="width:17px;height:17px;border-radius:3px;flex-shrink:0;display:flex;
  align-items:center;justify-content:center;{cs}">{ci}</div>
  <div style="width:9px;height:9px;border-radius:50%;background:{dc};flex-shrink:0"></div>
  <div>
    <div style="font-size:18px;font-weight:700;color:#212529">{nm}</div>
    {dh}
  </div>
</div>
""".format(
            bw="2px" if active else "1px",
            bc=border_color,
            bg=bg,
            cs=chk_style,
            ci=chk_inner,
            dc=dot_color,
            nm=name,
            dh=desc_html,
        )

    section_title("Data Source", "#6c757d", accent="#6c757d")
    err = st.session_state.get("cp_config_load_error")
    if err:
        st.error("Failed to load config: **{}**".format(err))

    c1, c2 = st.columns(2, gap="small")
    with c1:
        st.markdown(
            _src_card_html(
                live_active,
                "#1971c2" if live_active else "#dee2e6",
                "#e7f5ff" if live_active else "#fff",
                "background:#1971c2;border:2px solid #1971c2"
                if live_active
                else "border:1.5px solid #ced4da",
                chk_svg if live_active else "",
                "#e03131",
                "Live Monitoring",
                "",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            " ",
            key="cp_card_live",
            disabled=live_active,
            help="config.json (lab)",
            use_container_width=True,
        ):
            if ds != "live":
                try:
                    ui_replay_panel.ensure_replay_session_state()
                    ui_replay_panel._clear_replay_child_and_temp_file()
                    mqtt_backend.clear_kpi_snapshot()
                    _validate_config_basename("config.json")
                    mqtt_backend.switch_config_file("config.json")
                    st.session_state.cp_data_source = "live"
                    st.session_state.pop("dt_resolved_session", None)
                    st.session_state.cp_config_load_error = None
                except Exception as e:
                    st.session_state.cp_config_load_error = str(e)
                st.rerun()

    with c2:
        st.markdown(
            _src_card_html(
                hist_active,
                "#e67700" if hist_active else "#dee2e6",
                "#fff9db" if hist_active else "#fff",
                "background:#e67700;border:2px solid #e67700"
                if hist_active
                else "border:1.5px solid #ced4da",
                chk_svg if hist_active else "",
                "#f59f00",
                "History Replay",
                "",
            ),
            unsafe_allow_html=True,
        )
        if st.button(
            " ",
            key="cp_card_local",
            disabled=hist_active,
            help="Prefer config_local.json",
            use_container_width=True,
        ):
            if ds != "local":
                try:
                    if ds == "live":
                        ui_replay_panel.ensure_replay_session_state()
                        ui_replay_panel._clear_replay_child_and_temp_file()
                    mqtt_backend.clear_kpi_snapshot()
                    fn = _local_config_basename()
                    _validate_config_basename(fn)
                    mqtt_backend.switch_config_file(fn)
                    st.session_state.cp_data_source = "local"
                    st.session_state.cp_config_load_error = None
                except Exception as e:
                    st.session_state.cp_config_load_error = str(e)
                st.rerun()


def render() -> None:
    """Control + deploy + entry links. Caller must have set page_config and sidebar."""
    st.markdown(_HOME_UI_REFRESH_CSS, unsafe_allow_html=True)

    if "cp_data_source" not in st.session_state:
        st.session_state.cp_data_source = None

    st.markdown(
        '<div style="display:flex;align-items:baseline;gap:12px;margin-bottom:20px">'
        '<span style="font-size:22px;font-weight:700;color:#1a1e2e;letter-spacing:-.3px">DASHBOARD</span>'
        '<span style="font-size:17px;color:#adb5bd">MOTOWN Digital Twin</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    ds = st.session_state.get("cp_data_source")
    lock_all = ds is None
    is_live = ds == "live"
    is_local = ds == "local"

    _phys_disabled = _replay_session_active()
    _bg_busy = process_control.is_control_operation_running()
    ops_disabled = lock_all or is_local or _phys_disabled
    _live_btn_disabled = ops_disabled

    if is_live and _phys_disabled:
        st.info(
            "**Replay mode** — stop replay or use **Stop System** before starting the line."
        )

    _cfg_name = mqtt_backend.active_config_name() if not lock_all else "config.json"
    _cfg_path = os.path.normpath(os.path.join(PROJECT_ROOT, _cfg_name))
    try:
        with open(_cfg_path, encoding="utf-8") as f:
            _site_cfg = json.load(f)
    except OSError:
        _site_cfg = {}
    _lcp = _site_cfg.get("local_code_paths")
    _lcf = _site_cfg.get("local_config_paths")
    _upload_code_ok = bool(_lcp)
    _upload_cfg_ok = bool(_lcf)

    # Data Source
    with st.container(border=True):
        _render_data_source_configuration()

    # Live
    prog_raw = process_control.get_programs_status()
    sys_raw = process_control.get_system_status()
    prog_label = {
        "activated": "Activated",
        "partial": "Partial",
        "deactivated": "Deactivated",
    }.get(prog_raw, "Unknown")
    prog_color = {
        "activated": "#2f9e44",
        "partial": "#e67700",
        "deactivated": "#868e96",
    }.get(prog_raw, "#868e96")
    sys_color = "#2f9e44" if sys_raw == "start" else "#868e96"
    sys_label = "Running" if sys_raw == "start" else "Stopped"

    def _dot(c: str) -> str:
        return (
            '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
            "background:{};vertical-align:middle;margin-right:4px\"></span>".format(c)
        )

    def _vbar() -> str:
        return (
            '<span style="display:inline-block;width:1px;height:14px;background:#dee2e6;'
            'vertical-align:middle;margin:0 8px"></span>'
        )

    status_html = (
        "{}Programs: <b style='color:#212529'>{}</b>{}"
        "{}System: <b style='color:#212529'>{}</b>"
    ).format(
        _dot(prog_color),
        prog_label,
        _vbar(),
        _dot(sys_color),
        sys_label,
    )

    with st.container(border=True):
        section_title("Live", "#1971c2", accent="#1971c2", right_html=status_html)

        if _bg_busy:
            st.caption("Background operation in progress — controls paused until it finishes.")
            st.markdown(
                """
<style>
div[data-testid="stMainBlockContainer"] div.st-key-home_live_ops_block {
  pointer-events: none !important;
  opacity: 0.48 !important;
  filter: grayscale(0.2);
  user-select: none;
}
div[data-testid="stMainBlockContainer"] div.st-key-home_live_ops_block button {
  cursor: not-allowed !important;
}
</style>
""".replace("motion[", "div["),
                unsafe_allow_html=True,
            )

        with st.container(key="home_live_ops_block"):
            sub_label("CONTROL")
            c1, c2, c3, c4, c5 = st.columns([1.3, 1.3, 1.2, 1.3, 1.0])
            with c1:
                if st.button(
                    "Start Programs",
                    key="home_start_progs",
                    use_container_width=True,
                    disabled=_live_btn_disabled,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    else:
                        try:
                            _enf = mqtt_backend.active_config_name()
                            if not recording.is_recording():
                                mqtt_backend.switch_config_file(_enf)
                                time.sleep(1.0)
                            process_control.run_script_background(
                                "start_programs", enforce_config=_enf
                            )
                            st.toast("Start Programs submitted. Check View Logs.")
                        except Exception as ex:
                            st.toast("Start Programs failed. Check View Logs.")
                            process_control.record_control_action(
                                "Start Programs", False, str(ex)
                            )
            with c2:
                if st.button(
                    "Start System",
                    key="home_btn_start",
                    use_container_width=True,
                    disabled=_live_btn_disabled,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    else:
                        ok, msg = physical_workflow.start_physical_line_integrated()
                        process_control.record_control_action(
                            "Start System", ok, (msg or "")[:800]
                        )
                        if ok:
                            st.toast("Start System done. See View Logs for details.")
                        else:
                            st.toast("Start System failed. See View Logs for details.")
            with c3:
                if st.button(
                    "Stop System",
                    key="home_btn_stop",
                    use_container_width=True,
                    disabled=_live_btn_disabled,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    else:
                        ok, msg = physical_workflow.stop_physical_line_integrated()
                        process_control.record_control_action(
                            "Stop System", ok, (msg or "")[:800]
                        )
                        if ok:
                            st.toast("Stop System done. See View Logs for details.")
                        else:
                            st.toast("Stop System failed. See View Logs for details.")
            with c4:
                if st.button(
                    "Stop Programs",
                    key="home_stop_progs",
                    use_container_width=True,
                    disabled=_live_btn_disabled,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    else:
                        try:
                            _enf = mqtt_backend.active_config_name()
                            if not recording.is_recording():
                                mqtt_backend.switch_config_file(_enf)
                                time.sleep(1.0)
                            process_control.run_script_background(
                                "stop_programs", enforce_config=_enf
                            )
                            st.toast("Stop Programs submitted. Check View Logs.")
                        except Exception as ex:
                            st.toast("Stop Programs failed. Check View Logs.")
                            process_control.record_control_action(
                                "Stop Programs", False, str(ex)
                            )
            with c5:
                if st.button(
                    "Shutdown",
                    key="home_shutdown",
                    use_container_width=True,
                    disabled=_live_btn_disabled,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    else:
                        try:
                            _enf = mqtt_backend.active_config_name()
                            if not recording.is_recording():
                                mqtt_backend.switch_config_file(_enf)
                                time.sleep(1.0)
                            process_control.run_script_background(
                                "shutdown", enforce_config=_enf
                            )
                            st.toast("Shutdown submitted. Check View Logs.")
                        except Exception as ex:
                            st.toast("Shutdown failed. Check View Logs.")
                            process_control.record_control_action(
                                "Shutdown", False, str(ex)
                            )

            hr()
            sub_label("DEPLOY")
            d1, d2, _ = st.columns([1.3, 1.3, 4.5])
            with d1:
                if st.button(
                    "Upload Code",
                    key="home_ul_code",
                    use_container_width=True,
                    disabled=_live_btn_disabled or not _upload_code_ok,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    elif not _lcp:
                        st.toast("Upload Code unavailable: local_code_paths empty.")
                    else:
                        _enf = mqtt_backend.active_config_name()
                        process_control.run_script_background(
                            "upload_code", enforce_config=_enf
                        )
                        st.toast("Upload Code submitted. Check View Logs.")
            with d2:
                if st.button(
                    "Upload Config",
                    key="home_ul_cfg",
                    use_container_width=True,
                    disabled=_live_btn_disabled or not _upload_cfg_ok,
                ):
                    if _bg_busy:
                        st.toast("Wait for the background operation to finish.")
                    elif not _lcf:
                        st.toast("Upload Config unavailable: local_config_paths empty.")
                    else:
                        _enf = mqtt_backend.active_config_name()
                        process_control.run_script_background(
                            "upload_config", enforce_config=_enf
                        )
                        st.toast("Upload Config submitted. Check View Logs.")

        _v1, _v2, _v3, _v4 = st.columns([1.3, 1.3, 2.5, 1.0])
        with _v4:
            if st.button("View Logs", key="home_view_logs", disabled=lock_all):
                _service_logs_unified_dialog()

        # Detailed per-host execution messages are shown in View Logs -> Control Runs.
        if recording.is_recording():
            st.warning("Recording · **{}**".format(recording.current_path() or ""))

    # History
    with st.container(border=True):
        section_title("History", "#e67700", accent="#e67700")
        _hist_disabled = lock_all or is_live
        ui_history_panel.render_history_panel(key_prefix="home_hist", disabled=_hist_disabled)

    # Navigate
    with st.container(border=True):
        section_title("Navigate", "#6c757d", accent="#6c757d")
        n1, n2 = st.columns(2, gap="small")
        with n1:
            if st.button(
                "KPI Dashboard",
                key="home_dash_kpi",
                use_container_width=True,
                disabled=lock_all,
            ):
                st.switch_page("pages/01_Realtime.py")
        with n2:
            if st.button(
                "Digital Twin",
                key="home_dash_twin",
                use_container_width=True,
                disabled=lock_all,
            ):
                st.switch_page("pages/05_Digital_Twin.py")

    # Other Services
    with st.container(border=True):
        section_title("Other Services", "#adb5bd", accent="#adb5bd")
        st.markdown(
            '<span style="font-size:16px;color:#adb5bd">Simulation — Coming Soon</span>',
            unsafe_allow_html=True,
        )
