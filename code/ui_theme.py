
import streamlit as st

STATUS_COLORS = {
    'IDLE':    '#22c55e',   # green-500
    'BUSY':    '#3b82f6',   # blue-500
    'BLOCK':   '#eab308',   # yellow-500
    'FAIL':    '#ef4444',   # red-500
}

STATUS_EMOJI = {
    'IDLE':    '✅',
    'BUSY':    '🔵',
    'BLOCK':   '⚠️',
    'FAIL':    '🔴',
}


MQTT_PILL = {
    'connected':    ('Connected',    '🟢'),
    'disconnected': ('Disconnected', '🔴'),
    'error':        ('Error',        '❗'),
}

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow+Condensed:wght@300;500;700;900&display=swap');

:root {
  --bg:        #f8fafc;
  --surface:   #ffffff;
  --surface2:  #f1f5f9;
  --border:    #e2e8f0;
  --border2:   #cbd5e1;
  --text:      #1e293b;
  --text-dim:  #64748b;
  --accent:    #0284c7;
  --green:     #22c55e;
  --orange:    #f97316;
  --red:       #ef4444;
  --blue:      #3b82f6;
  --gold:      #eab308;
  --mono:      'Share Tech Mono', monospace;
  --sans:      'Barlow Condensed', sans-serif;
}

html, body, [class*="css"] {
  font-family: var(--sans);
  background-color: var(--bg) !important;
  color: var(--text);
}

.block-container { padding-top: 2rem !important; padding-bottom: 0.8rem !important; }

/* ── HEADER ── */
.kda-header {
  display: flex; align-items: center; justify-content: space-between;
  background: linear-gradient(135deg, var(--surface) 0%, var(--surface2) 100%);
  border-radius: 10px;
  padding: 12px 24px;
  margin-top: 12px;
  margin-bottom: 14px;
  border: 1px solid var(--border);       /* ← first */
  border-top: 3px solid var(--accent);   /* ← second, overrides the top */
}
.kda-logo {
  font-size: 1.5rem; font-weight: 900; letter-spacing: 3px;
  color: var(--accent); text-transform: uppercase;
}
.kda-logo span { color: var(--text-dim); font-weight: 300; }
.kda-subtitle { font-size: 0.7rem; color: var(--text-dim); font-family: var(--mono); margin-top: 2px; }
.kda-header-right { display: flex; align-items: center; gap: 12px; }

/* ── MQTT PILL ── */
.mqtt-pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px; border-radius: 20px;
  font-size: 0.72rem; font-family: var(--mono); font-weight: 600; border: 1px solid;
}
.mqtt-connected    { background: #052010; border-color: var(--green);  color: var(--green);  }
.mqtt-disconnected { background: #1a0808; border-color: var(--red);    color: var(--red);    }
.mqtt-error        { background: #1a1008; border-color: var(--orange); color: var(--orange); }

/* ── KPI CARD ── */
.kpi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 7px 16px 6px;
  text-align: center;
  position: relative; overflow: hidden;
}
.kpi-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: var(--accent-line, var(--accent));
}
.kpi-value { font-size: 1.5rem; font-weight: 900; line-height: 1.05; }
.kpi-label { font-size: 0.65rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.5px; margin-top: 3px; }
.kpi-sub   { font-size: 0.65rem; color: var(--text-dim); margin-top: 2px; font-family: var(--mono); }

/* ── SECTION TITLE ── */
.section-title {
  font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 2px; color: var(--text-dim);
  border-bottom: 1px solid var(--border);
  padding-bottom: 5px; margin-bottom: 10px;
}

/* ── MACHINE ROW ── */
.machine-row {
  display: flex; justify-content: space-between; align-items: center;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 6px 10px; margin-bottom: 4px;
  transition: border-color 0.15s;
}
.machine-row:hover { border-color: var(--border2); }
.machine-row.selected { border-color: var(--gold) !important; }
.machine-name { font-size: 0.82rem; font-weight: 700; }
.machine-stats { font-size: 0.64rem; font-family: var(--mono); color: var(--text-dim); }

/* ── EVENT LOG ── */
.evt-log { max-height: 260px; overflow-y: auto; }
.evt-row {
  display: grid; grid-template-columns: 68px 88px 72px 1fr;
  gap: 6px; align-items: center;
  font-family: var(--mono); font-size: 0.68rem;
  border-bottom: 1px solid var(--border);
  padding: 3px 2px;
}
.evt-time { color: var(--text-dim); }
.evt-comp { color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.evt-part { color: #c9955a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── DASHBOARD CARD (hub) ── */
.dash-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 28px 22px; text-align: center;
  min-height: 180px; cursor: pointer;
  transition: border-color 0.2s, transform 0.15s;
  position: relative; overflow: hidden;
}
.dash-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.dash-card::after {
  content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0;
  transition: opacity 0.2s;
}
.dash-card:hover::after { opacity: 1; }
.dash-card.disabled { opacity: 0.45; cursor: not-allowed; }
.dash-card-icon  { font-size: 2.4rem; margin-bottom: 10px; }
.dash-card-title { font-size: 1.25rem; font-weight: 700; color: var(--text); letter-spacing: 1px; margin-bottom: 8px; }
.dash-card-desc  { font-size: 0.78rem; color: var(--text-dim); line-height: 1.5; }

/* ── LAST EVENT BAR ── */
.last-event-bar {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 7px 14px;
  font-family: var(--mono); font-size: 0.7rem;
  display: flex; gap: 20px; flex-wrap: wrap;
  margin-top: 8px;
}

/* ── BACK BUTTON ── */
.stButton > button {
  background: var(--surface) !important;
  color: var(--accent) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
  font-family: var(--sans) !important;
  font-weight: 600 !important;
  letter-spacing: 1px !important;
}
.stButton > button:hover {
  border-color: var(--accent) !important;
  background: var(--surface2) !important;
}

/* ── PLOTLY overrides ── */
.stPlotlyChart { border-radius: 8px; overflow: hidden; }
</style>
"""

def inject_theme():
    st.markdown(THEME_CSS, unsafe_allow_html=True)


def mqtt_pill_html(status: str) -> str:
    cls, label = MQTT_PILL.get(status, ('mqtt-disconnected', '● UNKNOWN'))
    return f'{label} {cls}'


def header_html(title: str, subtitle: str, mqtt_status: str, extra_right: str = "") -> str:
    pill = mqtt_pill_html(mqtt_status)
    return f"""
    <div class="kda-header">
      <div>
        <div class="kda-logo">KDA<span>-01</span> &nbsp;{title}</div>
        <div class="kda-subtitle">{subtitle}</div>
      </div>
      <div class="kda-header-right">
        {extra_right}
        {pill}
      </div>
    </div>"""


def kpi_card_html(value, label: str, sub: str = "", color: str = "var(--accent)") -> str:
    return f"""
    <div class="kpi-card" style="--accent-line:{color}">
      <div class="kpi-value" style="color:{color}">{value}</div>
      <div class="kpi-label">{label}</div>
      {"<div class='kpi-sub'>" + sub + "</div>" if sub else ""}
    </div>"""


def placeholder_card_html(label: str) -> str:
    return f"""
    <div class="kpi-card" style="--accent-line:var(--border2); opacity:0.5;">
      <div class="kpi-value" style="color:var(--border2); font-size:1.2rem;">—</div>
      <div class="kpi-label">{label}</div>
      <div class="kpi-sub">coming soon</div>
    </div>"""
