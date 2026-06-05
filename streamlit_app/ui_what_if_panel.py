"""What-if Analysis — UI shell only (no simulation model)."""
from __future__ import annotations

import html as html_module

import streamlit as st

# 与 ui_kpi_display._UI_THEME / Home Other Services 对齐
_WI_ACCENT = "#adb5bd"
_WI_TEXT = "#1e293b"
_WI_TEXT_DIM = "#64748b"
_WI_BORDER2 = "#cbd5e1"
_WI_BTN_BG = "#f8f9fa"
_WI_BTN_BORDER = "#dee2e6"
_WI_BTN_TEXT = "#1f2937"
_WI_BTN_HOVER = "#e9ecef"

_FONT_L2_PX = 22
_FONT_L3_PX = 15
_FONT_CHART_TITLE_PX = 17
_CHART_BOX_H_PX = 280
_CHART_EMPTY_PX = 14

WHAT_IF_PARAMETERS: tuple[str, ...] = (
    "Stage1 Buffer Capacity",
    "Stage2 Buffer Capacity",
    "Stage3 Buffer Capacity",
    "Stage4 Buffer Capacity",
    "Stage5 Buffer Capacity",
    "Stage6 Buffer Capacity",
    "WIP Limit",
)

_CHART_TITLES: tuple[str, ...] = (
    "WIP",
    "Completion Rate",
    "Scrap Rate",
    "Lead Time",
)

_RUN_MSG_KEY = "_what_if_run_msg"

# Parameter 35% | From/To/Step 10% each | Replications 12% | Run 10%
_CFG_COL_WEIGHTS = [35, 10, 10, 10, 12, 10]

_WHAT_IF_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;500;600;700&display=swap');
div[data-testid="stMainBlockContainer"] div.st-key-what_if_panel
[data-testid="stVerticalBlockBorderWrapper"] {
    padding: 0.85rem 1rem 3rem 1rem !important;
    box-sizing: border-box !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
}
div[data-testid="stMainBlockContainer"] .what-if-cfg-heading {
    margin: 0 0 0.55rem 0 !important;
    padding: 0 0 0 10px !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_L2_PX) + """px !important;
    font-weight: 700 !important;
    line-height: 1.25 !important;
    letter-spacing: 0.02em !important;
    color: """ + _WI_TEXT + """ !important;
    border-left: 4px solid """ + _WI_ACCENT + """ !important;
}
div[data-testid="stMainBlockContainer"] .what-if-section-divider {
    margin: 1rem 0 1.05rem 0 !important;
    border: none !important;
    border-top: 1px solid #e2e8f0 !important;
    height: 0 !important;
}
div[data-testid="stMainBlockContainer"] .what-if-cfg-label {
    margin: 0 0 0.15rem 0 !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_L3_PX) + """px !important;
    font-weight: 700 !important;
    color: """ + _WI_TEXT_DIM + """ !important;
    letter-spacing: 0.02em !important;
    white-space: nowrap !important;
}
div[data-testid="stMainBlockContainer"] .what-if-chart-title {
    margin: 0 0 10px 0 !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_CHART_TITLE_PX) + """px !important;
    font-weight: 600 !important;
    color: """ + _WI_TEXT + """ !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_parameter_wrap
[data-testid="stPopover"] > button {
    min-height: 46px !important;
    height: 46px !important;
    width: 100% !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_L3_PX) + """px !important;
    font-weight: 400 !important;
    color: """ + _WI_TEXT + """ !important;
    background: #ffffff !important;
    border: 1px solid """ + _WI_BTN_BORDER + """ !important;
    border-radius: 7px !important;
    box-shadow: none !important;
    justify-content: space-between !important;
    text-align: left !important;
    padding: 0 0.75rem !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_parameter_wrap
[data-testid="stPopover"] > button:hover:not(:disabled) {
    background: #ffffff !important;
    border-color: """ + _WI_BTN_BORDER + """ !important;
    color: """ + _WI_TEXT + """ !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_parameter_wrap
[data-testid="stPopoverBody"] [data-testid="stRadio"] label {
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_L3_PX) + """px !important;
    color: """ + _WI_TEXT + """ !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_parameter_wrap
[data-testid="stPopoverBody"] [data-testid="stRadio"] label span {
    color: """ + _WI_TEXT + """ !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_panel
[data-testid="stNumberInput"] button,
div[data-testid="stMainBlockContainer"] div.st-key-what_if_panel
[data-testid="stNumberInputStepUp"],
div[data-testid="stMainBlockContainer"] div.st-key-what_if_panel
[data-testid="stNumberInputStepDown"] {
    display: none !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_panel
[data-testid="stNumberInput"] input {
    padding-right: 0.65rem !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_cfg_row
[data-testid="stHorizontalBlock"] {
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: flex-end !important;
    width: 100% !important;
    gap: 0.4rem !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_cfg_row
[data-testid="stHorizontalBlock"] > [data-testid="column"] {
    min-width: 0 !important;
    flex-shrink: 1 !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_run_btn button {
    min-height: 46px !important;
    height: 46px !important;
    font-family: "Barlow Condensed", "Segoe UI", sans-serif !important;
    font-size: """ + str(_FONT_L3_PX) + """px !important;
    background: """ + _WI_BTN_BG + """ !important;
    color: """ + _WI_BTN_TEXT + """ !important;
    border: 1px solid """ + _WI_BTN_BORDER + """ !important;
    border-bottom: 1px solid """ + _WI_BTN_BORDER + """ !important;
    font-weight: 600 !important;
    white-space: nowrap !important;
    border-radius: 7px !important;
    box-shadow: none !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_run_btn button:hover:not(:disabled) {
    background: """ + _WI_BTN_HOVER + """ !important;
    border-color: """ + _WI_BTN_BORDER + """ !important;
    color: """ + _WI_BTN_TEXT + """ !important;
    box-shadow: none !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_charts_block {
    padding-bottom: 0.35rem !important;
}
div[data-testid="stMainBlockContainer"] div.st-key-what_if_charts_row2 {
    margin-top: 20px !important;
}
div[data-testid="stMainBlockContainer"] .what-if-chart-box {
    margin-bottom: 0 !important;
}
</style>
"""


def _block_heading(text: str) -> None:
    st.markdown(
        '<p class="what-if-cfg-heading">{}</p>'.format(html_module.escape(text)),
        unsafe_allow_html=True,
    )


def _section_divider() -> None:
    st.markdown('<hr class="what-if-section-divider">', unsafe_allow_html=True)


def _cfg_label(text: str) -> None:
    st.markdown(
        '<div class="what-if-cfg-label">{}</div>'.format(html_module.escape(text)),
        unsafe_allow_html=True,
    )


def _chart_placeholder(title: str) -> None:
    st.markdown(
        '<p class="what-if-chart-title">{}</p>'.format(html_module.escape(title)),
        unsafe_allow_html=True,
    )
    st.markdown(
        (
            "<div class='what-if-chart-box' style='min-height:{h}px;height:{h}px;"
            "display:flex;align-items:center;justify-content:center;background:#f8fafc;"
            "border:1px dashed {border};border-radius:8px;margin:0;'>"
            "<span style='color:#94a3b8;font-size:{fs}px;font-family:"
            "\"Barlow Condensed\",\"Segoe UI\",sans-serif;'>"
            "No simulation results available.</span></div>"
        ).format(h=_CHART_BOX_H_PX, border=_WI_BORDER2, fs=_CHART_EMPTY_PX),
        unsafe_allow_html=True,
    )


def render_what_if_panel() -> None:
    st.markdown(_WHAT_IF_CSS, unsafe_allow_html=True)

    with st.container(border=True, key="what_if_panel"):
        _block_heading("Configuration")
        with st.container(key="what_if_cfg_row"):
            c_param, c_from, c_to, c_step, c_rep, c_run = st.columns(
                _CFG_COL_WEIGHTS,
                gap="small",
                vertical_alignment="bottom",
            )
            with c_param:
                _cfg_label("Parameter")
                with st.container(key="what_if_parameter_wrap"):
                    _param_current = st.session_state.get(
                        "what_if_parameter",
                        WHAT_IF_PARAMETERS[0],
                    )
                    with st.popover(_param_current, use_container_width=True):
                        st.radio(
                            "Parameter",
                            WHAT_IF_PARAMETERS,
                            label_visibility="collapsed",
                            key="what_if_parameter",
                        )
            with c_from:
                _cfg_label("From")
                st.number_input(
                    "From",
                    min_value=0,
                    value=0,
                    step=1,
                    format="%d",
                    label_visibility="collapsed",
                    key="what_if_range_from",
                )
            with c_to:
                _cfg_label("To")
                st.number_input(
                    "To",
                    min_value=0,
                    value=10,
                    step=1,
                    format="%d",
                    label_visibility="collapsed",
                    key="what_if_range_to",
                )
            with c_step:
                _cfg_label("Step")
                st.number_input(
                    "Step",
                    min_value=1,
                    value=1,
                    step=1,
                    format="%d",
                    label_visibility="collapsed",
                    key="what_if_step",
                )
            with c_rep:
                _cfg_label("Replications")
                st.number_input(
                    "Replications",
                    min_value=1,
                    value=10,
                    step=1,
                    format="%d",
                    label_visibility="collapsed",
                    key="what_if_replications",
                )
            with c_run:
                _cfg_label("\u00a0")
                if st.button(
                    "Run Analysis",
                    key="what_if_run_btn",
                    use_container_width=True,
                ):
                    st.session_state[_RUN_MSG_KEY] = True

        if st.session_state.get(_RUN_MSG_KEY):
            st.info("Simulation model not connected.")

        _section_divider()
        _block_heading("Charts")

        with st.container(key="what_if_charts_block"):
            chart_row_a, chart_row_b = st.columns(2, gap="medium")
            with chart_row_a:
                _chart_placeholder(_CHART_TITLES[0])
            with chart_row_b:
                _chart_placeholder(_CHART_TITLES[1])

            with st.container(key="what_if_charts_row2"):
                chart_row_c, chart_row_d = st.columns(2, gap="medium")
                with chart_row_c:
                    _chart_placeholder(_CHART_TITLES[2])
                with chart_row_d:
                    _chart_placeholder(_CHART_TITLES[3])
