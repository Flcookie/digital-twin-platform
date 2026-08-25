# Streamlit 装配线控制与数字孪生项目详细报告

本文档说明当前仓库中 Streamlit 部分的整体功能、MQTT 通信方式、Neo4j 图数据库设计、Dashboard 与 KPI 计算、Digital Twin、Part Track、Conformance，以及 What-if Analysis 仿真实验逻辑。本文基于当前代码实现编写，重点对应 `mt-ems-pl` 装配线控制包和 `streamlit_app/` 前端监控系统。

相对早期 What-if 说明（本地归档 `doc/report2.md`），本文已并入 `Config.txt` / Replications、Arena `WriteOutput` 公式语义，以及本地启动与 Neo4j 连接排错。

## 1. 项目总体定位

该项目是一个面向 MOTOWN / MT-EMS-PL 多工位装配线的 Digital Twin Platform。系统不是只有一个 Dashboard，而是由现场控制程序、事件采集服务、图数据库、KPI 计算器、Streamlit 前端和 Arena/SIMAN 离线仿真共同组成。

核心目标有四个：

1. 控制实体装配线：启动/停止控制器程序，启动/停止物理系统，上传现场代码和配置。
2. 实时监控生产状态：通过 MQTT 接收现场事件，计算 KPI，并在 Streamlit 中展示系统、阶段和工站指标。
3. 保存并追踪历史过程：把事件写入 Neo4j，支持 Session、Part Trace、Conformance、History Replay 和导出。
4. 做离线实验验证：What-if Analysis 调用 Arena/SIMAN 模型，改变 WIP 或 buffer capacity，观察 WIP、Completion Rate、Scrap Rate、Lead Time 的变化。

总体架构如下：

```text
mt-ems-pl 现场组件程序
  corner / station / splitter / driver
        |
        | MQTT: component_event/<component>/all
        v
main_service.py
  EventBuffer -> KpiCalculator -> Neo4j writer
        |
        | MQTT: kpi/main_service/all
        v
Streamlit Dashboard
  Control Panel / KPI / History / Part Trace / Conformance / Digital Twin / What-if
        |
        | Neo4j query
        v
Neo4j graph database

What-if Analysis 独立调用:
Streamlit -> whatif/siman_runner.py -> model/Input.txt + Config.txt -> siman.exe -> Output.txt -> Plotly charts
```

关键代码文件：

| 文件 | 作用 |
|---|---|
| `streamlit_app/app.py` | Streamlit 首页入口 |
| `streamlit_app/ui/home.py` | Control Panel 首页：模式选择、现场控制、部署、History、页面跳转 |
| `streamlit_app/services/mqtt_backend.py` | Streamlit 侧 MQTT 连接、KPI 订阅、控制命令发布、回放 KPI sidecar 读取 |
| `main_service.py` | MQTT 事件入口，周期打印/发布 KPI |
| `event_pipeline.py` | EventBuffer + KPI + Neo4j 的共享流水线 |
| `kpi_calculator.py` | 系统层、Stage 层、Station 层 KPI 公式和状态机 |
| `neo4j_writer.py` | Neo4j 写入模型：Session、Event、Station、Entity、Activity |
| `streamlit_app/services/neo4j_backend.py` | Streamlit 查询 Neo4j、导入导出、Part Flow、历史 KPI 重算 |
| `streamlit_app/pages/01_Realtime.py` | KPI Dashboard 页面 |
| `streamlit_app/pages/05_Digital_Twin.py` | Digital Twin 页面 |
| `streamlit_app/ui/part_trace_panel.py` | Part Trace 表格、详情、Conformance 展示 |
| `streamlit_app/twin/factory_floor_sim.py` | 根据 Neo4j 事件增量重建工厂布局状态 |
| `streamlit_app/twin/factory_floor_plotly.py` | Plotly 工厂平面图 |
| `streamlit_app/ui/what_if_panel.py` | What-if 页面控件和图表 |
| `streamlit_app/whatif/siman_runner.py` | Arena/SIMAN 参数扫描和 Output 解析 |
| `mt-ems-pl/*` | 现场控制器程序和配置 |

## 2. `mt-ems-pl` 装配线现场程序

`mt-ems-pl` 是实际上传到控制器的装配线代码包。根目录中 `config.json` / `config.example.json` 的 `local_folder_path` 指向 `mt-ems-pl`，`local_code_paths` 和 `local_config_paths` 定义了每个控制器需要上传哪些代码和配置。

现场组件包括：

| 组件类型 | 文件 | 典型组件 ID |
|---|---|---|
| corner | `corner.py` | `corner1`, `corner2` |
| driver | `driver.py` | `driver1` 到 `driver4` |
| splitter | `splitter.py` | `splitter5` |
| splitter pair | `splitter_pair.py` | `splitters12`, `splitters34`，内部产生 `splitter1` 到 `splitter4` 事件 |
| blocking station | `block_station.py` | `station11`, `station31`, `station61` |
| non-blocking station | `nonblock_station.py` | `station21`, `station22`, `station41`, `station51`, `station52`, `station71` |

现场事件由 `mt-ems-pl/common.py` 中的 `build_event()` 统一生成：

```json
{
  "time": "2026-05-09T16:45:17.123456",
  "component_id": "station41",
  "part_id": "p12",
  "activity": "PROCESS"
}
```

所有现场脚本使用同一套 MQTT topic 规则：

```python
render_topic(context, source_id, target_id)
=> context/source_id/target_id
```

典型现场事件如下：

| 组件 | 事件 activity | 含义 |
|---|---|---|
| `corner2` | `START` | Part 进入系统，一圈生产周期开始 |
| `corner1`, `corner2` | `RETURN`, `TRANSFER` | 转角输送/回流 |
| station | `LOAD` | 工件进入工站 |
| station | `PROCESS` | 工站加工 |
| station | `FAIL` | 工站失败，需要修复或返工判断 |
| station | `BLOCK` | 下游无空位，工站阻塞 |
| station | `UNLOAD` | 工件离开加工位 |
| station | `PASS` | 非阻塞/旁路逻辑中判定可通过 |
| station | `TRANSFER` | 工件转出 |
| splitter | `RETURN` | 分流器回流 |
| splitter | `FORWARD` | 分流器放行到前向路径 |
| splitter | `TRANSFER` | 分流动作完成 |
| `splitter5` | `CHECKOUT` | 出口预通知，不直接计入 FINISH/SCRAP |
| `splitter5` | `FINISH` | 合格完成 |
| `splitter5` | `SCRAP` | 报废退出 |

现场脚本同时支持 WIP / vacancy 机制：

| Topic | 方向 | 用途 |
|---|---|---|
| `system_status/master/all` | Dashboard -> all components | 发送 `START` 或 `STOP` |
| `component_wip/master/<component>` | Dashboard -> component | 系统启动前设置初始 WIP |
| `component_status/<component>/all` | component -> all | 组件自身启动/停止状态 |
| `component_vacancy/<source>/<target>` | component <-> component | 下游空位预订，`BOOK`, `PEEK`, `ACCEPT`, `SUSPEND`, `REFUSE` |
| `part_memory/master/<component>` | master -> component | 写入/格式化 RFID part memory |
| `component_event/<component>/all` | component -> backend | 生产事件日志 |

## 3. MQTT 连接与数据传输

MQTT 是物理装配线、后端服务和 Dashboard 之间的实时通信层。配置来自 `config.json` 或 `CONFIG_FILE` 指定的配置文件。关键配置字段包括：

```json
{
  "mqtt_broker_host": "server0",
  "mqtt_broker_port": 1883,
  "server_hostname": "server0",
  "server_mqtt_port": 1883,
  "component_wips": {
    "station11": 16,
    "splitters12": 0,
    "station31": 0,
    "splitters34": 0,
    "station61": 0,
    "splitter5": 0
  }
}
```

### 3.1 现场组件到 `main_service`

现场组件发布：

```text
component_event/<component_id>/all
```

Payload 是 JSON，例如：

```json
{"time":"2026-05-09T16:45:17.123456","component_id":"station41","part_id":"p12","activity":"PROCESS"}
```

`main_service.py` 在 `on_connect()` 中订阅：

```text
component_event/+/all
command/+/main_service
```

收到 `component_event` 后进入 `EventPipeline.ingest_event()`：

```text
MQTT message
  -> JSON deserialize
  -> EventBuffer 按时间窗口排序/缓冲
  -> KpiCalculator.on_event()
  -> neo4j_writer.write_events_batch()
```

### 3.2 `main_service` 到 Streamlit

`main_service.py` 每隔 `event_buffer.kpi_print_interval_sec` 秒计算一次 snapshot，并发布：

```text
kpi/main_service/all
```

Payload 是 KPI 快照，包含：

```json
{
  "session_id": "event_log_20260509_164517",
  "run_mode": "physical",
  "system": {...},
  "stages": {...},
  "throughput": 0.1234,
  "finished_count": 10,
  "scrap_count": 1,
  "yield_rate": 0.9091,
  "wip_instantaneous": 3,
  "wip_average": 2.417,
  "utilization": {...},
  "state_probability": {...},
  "station_live": {...}
}
```

Streamlit 在 `mqtt_backend.ensure_started()` 中创建一个 dashboard MQTT client。这个 client 同时做两件事：

1. 订阅 `kpi/main_service/all`，缓存最新 KPI 和趋势历史。
2. 发布控制命令，例如 Start/Stop System、Reset KPI、Clear Neo4j。

这样设计的原因是避免在公共 broker 上开多个 dashboard MQTT 连接导致连接互相挤掉或 `CONN_LOST`。

### 3.3 Streamlit 到现场系统的控制命令

Start System 使用 `mqtt_backend.start_physical_system()`，流程如下：

1. 等待 Dashboard MQTT client 连接成功。
2. 遍历 `component_wips`，向每个组件发送初始 WIP：

```text
component_wip/master/<component_id>
```

3. 等待 `system_start_delay`。
4. 发布：

```text
system_status/master/all = START
```

Stop System 使用：

```text
system_status/master/all = STOP
```

### 3.4 Streamlit 到 `main_service` 的命令

Streamlit 使用：

```text
command/dashboard/main_service
```

Payload 示例：

```json
{"action":"clear_neo4j"}
{"action":"reset_kpi"}
{"action":"start_new_session","description":"live"}
{"action":"finalize_session","session_id":"event_log_...","status":"completed"}
```

`event_pipeline.py` 中支持的 action 包括：

| action | 作用 |
|---|---|
| `reset_kpi` | 清空 buffer 和 KPI |
| `start_new_session` | 新建 Neo4j Session 并清空 KPI |
| `reset_all` | 新建 session 并重置全部运行状态 |
| `clear_neo4j` | 清空 Neo4j 事件图并新建 live session |
| `finalize_session` | 给 Session 写入 `end_time` |

### 3.5 History Replay 不走 MQTT 事件总线

历史 CSV / Session replay 不是重新向 MQTT 发布 component_event，而是直接运行本地子进程：

```text
replay_csv_direct.py
replay_session_direct.py
```

它们直接调用 `EventPipeline`，并把 KPI 写到项目根目录：

```text
.replay_kpi.json
```

Streamlit 在非 Live 模式下优先读取这个 sidecar 文件。这样可以避免历史回放污染现场 MQTT 总线，也避免把历史事件误发送给真实控制器。

## 4. Event Buffer 与事件顺序处理

现场 MQTT 事件可能因为网络延迟乱序到达。`event_buffer.py` 通过时间窗口解决这个问题。

核心逻辑：

1. 事件按 `time` 解析为 timestamp。
2. 用 `bisect.insort()` 插入有序列表。
3. 用当前 buffer 中最大 timestamp 作为 watermark。
4. 小于 `max_ts - window_ms` 的事件被认为已经安全，可以 flush。
5. 如果 buffer 超过 `max_size`，强制 flush 最早的一批。

配置示例：

```json
"event_buffer": {
  "window_ms": 500,
  "max_size": 500,
  "replay_window_ms": 50,
  "kpi_print_interval_sec": 3.0
}
```

为什么 replay 用更小的 `replay_window_ms`：历史 CSV 已经基本按时间排序，窗口可以更短；现场实时 MQTT 更容易乱序，所以窗口更大。

## 5. Neo4j 图数据库设计

Neo4j 用来存储生产事件和过程关系。它不是只做日志表，而是把“事件、零件、工站、活动、会话”建模成图，方便做 Part Trace、工站路径、直接跟随关系和 Conformance 查询。

### 5.1 图模型

`neo4j_writer.py` 写入的核心节点：

| Label | 关键属性 | 含义 |
|---|---|---|
| `Session` | `id`, `start_time`, `end_time` | 一次 live 或 replay/import 运行 |
| `Event` | `id`, `timestamp`, `time`, `component_id`, `part_id`, `activity`, `label` | 单条生产事件 |
| `Station` | `sysId` | 工站/分流器/角点组件 |
| `Entity` | `sysId` | Part ID |
| `EntityType` | `name` | Part 类型，默认 `part` |
| `Activity` | `name` | START/LOAD/PROCESS 等活动 |

核心关系：

| Relationship | 含义 |
|---|---|
| `(e:Event)-[:IN_SESSION]->(s:Session)` | 事件属于哪个运行会话 |
| `(e:Event)-[:OCCURRED_AT]->(st:Station)` | 事件发生在哪个组件 |
| `(e:Event)-[:ACTS_ON]->(en:Entity)` | 事件作用于哪个 Part |
| `(en:Entity)-[:OF_TYPE]->(et:EntityType)` | Part 类型 |
| `(e:Event)-[:OF_ACTIVITY]->(a:Activity)` | 事件活动类型 |
| `(e1:Event)-[:DF]->(e2:Event)` | 同一个 Part 的直接后继事件 |
| `(e1:Event)-[:DF_PROCESS]->(e2:Event)` | 同一个 Part 的工艺级直接后继，过滤掉 TRANSFER/BLOCK 等噪声 |
| `(e1:Event)-[:NEXT]->(e2:Event)` | 全局写入顺序，用于系统 timeline |
| `(s1:Station)-[:DF]->(s2:Station)` | Station 级直接跟随 |
| `(s1:Station)-[:DF_PROCESS]->(s2:Station)` | Station 级工艺直接跟随 |
| `(en1:Entity)-[:DF]->(en2:Entity)` | 全局 NEXT 派生的 Entity 跟随关系 |

### 5.2 为什么用 Neo4j

这个项目中的关键问题天然是图问题：

1. 一个 Part 会经过多个 Station，路径上存在分流、回流、返工、报废。
2. 一条 Event 同时关联 Part、Station、Activity、Session。
3. Part Trace 要问“这个 Part 按时间经过了哪些工位和活动”。
4. Conformance 要判断路径是否符合预期工艺模型。
5. Digital Twin 要知道当前 Session 下每个 Part 的最新位置。
6. Process mining 需要 Directly-Follows 关系，图数据库比普通 CSV 更直接。

因此 Neo4j 的价值不是简单存储，而是把事件流变成可查询的生产过程图。

### 5.3 索引

Streamlit 侧在 `ui_sidebar.finalize_neo4j_indexes()` 中调用 `neo4j_backend.ensure_indexes()`。创建的索引包括：

```cypher
CREATE INDEX IF NOT EXISTS FOR (s:Session) ON (s.id)
CREATE INDEX IF NOT EXISTS FOR (s:Session) ON (s.start_time)
CREATE INDEX IF NOT EXISTS FOR (e:Event) ON (e.timestamp)
CREATE INDEX IF NOT EXISTS FOR (en:Entity) ON (en.sysId)
CREATE INDEX IF NOT EXISTS FOR (st:Station) ON (st.sysId)
CREATE INDEX IF NOT EXISTS FOR (a:Activity) ON (a.name)
```

作用：

| 索引 | 用途 |
|---|---|
| `Session.id` | 快速定位历史 session |
| `Session.start_time` | History selector 排序/筛选 |
| `Event.timestamp` | Timeline、Digital Twin 增量 cursor、Part Trace 排序 |
| `Entity.sysId` | Part ID 查询 |
| `Station.sysId` | Station 查询 |
| `Activity.name` | 活动统计和过程过滤 |

### 5.4 主要查询能力

`streamlit_app/services/neo4j_backend.py` 提供以下能力：

| 函数 | 作用 |
|---|---|
| `neo4j_ping()` | 轻量连接检测 |
| `list_sessions_enriched()` | History 页面列出 Session，包含事件数、开始/结束时间、open/completed |
| `import_csv_session()` | 把 CSV 导入为 Neo4j Session |
| `find_csv_import_duplicate_info()` | 用首条事件时间 + 行数判断重复导入 |
| `export_session_events_csv()` | 导出事件日志 CSV |
| `export_session_kpi_log_csv()` | 导出系统/Stage/Station KPI 长表 |
| `get_session_kpi_snapshot()` | 从 Neo4j 事件重算历史 KPI |
| `query_part_flow()` | 查询一个或所有 Part 的事件流 |
| `fetch_session_events_for_floor()` | 给 Digital Twin 按 cursor 拉增量事件 |
| `query_station_events()` | 查询某个 Station 的近期事件 |

## 6. Streamlit Dashboard 页面与功能

### 6.1 首页 Control Panel

入口是 `streamlit_app/app.py`。

首页实际逻辑在 `ui/home.py`（`ui.home.render()`）。

首页主要分为四块：

| 区块 | 功能 |
|---|---|
| Mode | 选择 `Live Monitoring` 或 `History Replay` |
| Live | 现场控制和部署 |
| History | 历史 Session 选择、回放、导入、导出 |
| Navigate / Other Services | 跳转 KPI Dashboard、Digital Twin、What-if Analysis |

#### Mode

`Live Monitoring`：

1. 切换到 `config.json`。
2. 清空 replay 子进程和 `.replay_kpi.json`。
3. KPI 只认 MQTT，不认历史回放 sidecar。
4. 控制面板按钮可用。

`History Replay`：

1. 优先切换到 `config_local.json`。
2. 停止或清空实时 replay 状态。
3. 控制面板现场按钮禁用。
4. History 模块可用。

#### Live 控制功能

| 按钮 | 作用 |
|---|---|
| Start Programs | 运行 `start_programs.py`，通过 SSH 启动各控制器上的程序 |
| Start System | 启动 `main_service`，等待 KPI，开始 CSV 录制，发送 WIP 和 `START` |
| Stop System | 发送 `STOP`，停止录制，关闭 Neo4j session，停止 `main_service` |
| Stop Programs | 运行 `stop_programs.py`，停止控制器程序 |
| Shutdown | 运行 `shutdown.py`，关闭控制器 |
| Upload Code | 运行 `upload_code.py`，上传 `mt-ems-pl` 代码 |
| Upload Config | 运行 `upload_config.py`，上传 `common.json` 和各组件 `specific.json` |
| View logs | 查看控制动作日志 |

`Start System` 是组合动作，核心在 `physical_workflow.start_physical_line_integrated()`：

```text
switch config.json
  -> 如果 main_service 未运行，启动 main_service.py
  -> 等待 KPI ready，确认 MQTT 与 main_service 通
  -> start_recording() 订阅 component_event 并写 CSV
  -> publish component_wip/*
  -> publish system_status/master/all = START
```

`Stop System` 流程：

```text
publish system_status/master/all = STOP
  -> 停止 recording
  -> finalize Neo4j Session，写 end_time
  -> 停止 main_service
  -> 清空 dashboard 本地 KPI cache
```

### 6.2 KPI Dashboard 页面

入口：`streamlit_app/pages/01_Realtime.py`。

页面逻辑：

1. 通过 `mqtt_backend.get_kpi_snapshot()` 获取最新 KPI。
2. 如果 MQTT 不在线且当前不是 live，则从 Neo4j 选中 session 重算 KPI。
3. 调用 `ui_kpi_display.render_kpi_dashboard()`。
4. 使用 `@st.fragment(run_every=ui_live_refresh.live_ui_refresh_delta())` 定时刷新。

展示内容：

| 模块 | 内容 |
|---|---|
| System KPI | 完成数、报废数、WIP、平均 WIP、Completion Rate、Scrap Rate、Cycle Time、Yield |
| Trend charts | WIP over time，Completion/Scrap rate over time |
| Stage KPI | Stage 1 到 Stage 6 的 WIP、Avg WIP、Departure、Throughput、Avg Flow Time |
| Station KPI | 各 station 的 utilization、BUSY/FAIL/BLOCKED/IDLE 状态概率、当前状态 |

### 6.3 History 页面/模块

`pages/02_History.py` 只是跳转提示，实际 History 模块在首页 `ui.history_panel.render_history_panel()`。

功能：

| 功能 | 说明 |
|---|---|
| Session selector | 从 Neo4j 读取最近 session，展示开始/结束时间、事件数、open/completed；过滤掉 `event_count=0` 且状态为 open 的空占位 session |
| Start Replay | 从已选 Neo4j session 读事件，运行 `replay_session_direct.py`，只回放 KPI，不重新写事件 |
| Stop Replay | 停止回放子进程并清理临时状态 |
| Speed | 1x, 2x, 5x, 10x, 20x, 50x |
| Export Event Log | 导出 `time,component_id,part_id,activity` |
| Export KPI Report | 导出 system/stage/station 长表 |
| Import to Database | 上传 CSV 导入为 Neo4j Session |
| Duplicate detection | 用首条事件时间 + 行数识别重复数据，可 Skip 或强制新 session |

### 6.4 Part Trace 页面

入口：`pages/03_Part_Trace.py`，实际逻辑在 `ui_part_trace_panel.render_part_trace_panel()`。

功能：

1. 选择 session。
2. 查询单个 Part ID 或展示所有 Part。
3. 展示 Part overview。
4. 展示当前周期、当前工站、进度、cycle time、flow/conformance。
5. 展开查看每个 Part 的详细事件。
6. 提供 7-stage matrix 和 complete trace 弹窗。

### 6.5 Conformance 页面

入口：`pages/04_Conformance.py`，实际逻辑在 `ui_conformance_panel.render_conformance_panel()`。

功能：

| 功能 | 说明 |
|---|---|
| Activity diagram | Graphviz 展示 START -> LOAD -> PROCESS -> UNLOAD -> FINISH，以及 PROCESS -> SCRAP |
| Rules | 展示 flow/conformance 分类规则 |
| Session summary | 所有 Part 的 Flow Type、Conformance、Deviation、path summary |
| Reference check | 输入 Part ID 和期望 activity 序列，做 subsequence 验证 |
| Station query | 输入 Station.sysId 查询该 station 的近期事件 |

Conformance 页面强调：Reference check 只是解释和验证工具，不驱动实际 Flow/Conformance 分类。实际分类来自 `flow_classification.py` 和 `part_track_conformance.py`。

### 6.6 Digital Twin 页面

入口：`pages/05_Digital_Twin.py`。

页面由一个同步 fragment 驱动：

```text
resolve session
  -> get KPI
  -> sync_factory_floor_sim()
  -> resolve_twin_part_trace()
  -> build_factory_floor_figure()
  -> render embedded Part Trace
```

关键特点：

1. Factory Layout 和 Part Trace 在同一个 fragment 中刷新。
2. 两者使用同一个 Neo4j session。
3. replay 模式下根据 KPI 的 `chart_time_unix` 截断事件，地图和表格显示同一回放时刻。
4. live 模式下使用 cursor 增量读取 Neo4j 新事件，避免全量重算。

### 6.7 What-if Analysis 页面

入口：`pages/what-if-analysis.py`，实际逻辑在 `ui/what_if_panel.py` 和 `whatif/siman_runner.py`。

功能：

1. 选择 Work Folder，默认 `model/`。
2. 选择一个参数：
   - WIP Limit
   - Stage1 Buffer Capacity
   - Stage2 Buffer Capacity
   - Stage3 Buffer Capacity
   - Stage4 Buffer Capacity
   - Stage5 Buffer Capacity
   - Stage6 Buffer Capacity
3. 输入 From / To / Step / Replications。
4. 点击 Run Analysis。
5. 后台调用 Arena/SIMAN 对参数做 sweep。
6. 输出四张 Plotly 图：
   - WIP
   - Completion Rate
   - Scrap Rate
   - Lead Time

## 7. KPI 分层与公式

KPI 由 `kpi_calculator.py` 以事件流方式计算。它不是事后 SQL 聚合，而是每来一条事件就更新一次内部状态。

### 7.1 时间定义

`observation_time_sec`：

```text
obs_time = end_ts - observation_start_ts
```

其中：

| 模式 | end_ts |
|---|---|
| `replay` | 最后一条事件时间 |
| `realtime` | 如果最近 30 秒仍有事件，用当前 wall clock；如果超过 30 秒无事件，用最后事件时间 |

这样可以避免现场停线后 observation time 一直增长，把 throughput 稀释到 0。

### 7.2 System KPI

系统层 WIP 定义为“打开的生产 lap 数”，不是物理托盘数量。

WIP 变化规则：

| 事件 | 规则 |
|---|---|
| `corner2 START` | 如果该 part 没有 open lap，则 WIP +1 |
| 重复 `corner2 START` | 如果同一 part 尚未 FINISH/SCRAP，不增加 WIP，`duplicate_start_count +1` |
| `splitter5 FINISH` | 如果 part 有 open lap，则 WIP -1，`num_completions +1` |
| `splitter5 SCRAP` | 如果 part 有 open lap，则 WIP -1，`num_scraps +1` |
| `splitter5 CHECKOUT` | 忽略，不计入完成/报废 |

系统层公式：

| KPI | 公式 |
|---|---|
| `num_completions` | `splitter5 FINISH` 且 part 有 open lap 的计数 |
| `num_scraps` | `splitter5 SCRAP` 且 part 有 open lap 的计数 |
| `wip_instantaneous` | 当前 open lap 数 |
| `wip_average` | 时间加权平均 WIP |
| `complete_rate` / `throughput` | `num_completions / observation_time_sec` |
| `scrap_rate` | `num_scraps / (num_completions + num_scraps)` |
| UI 中 scrap/min | `num_scraps / observation_time_sec * 60` |
| `yield_rate` | `num_completions / (num_completions + num_scraps)` |
| `avg_cycle_time_fin` | 所有完成 lap 的 `(FINISH time - START time)` 平均 |
| `avg_cycle_time_all` | 完成 lap 和报废 lap 的 cycle time 平均 |

平均 WIP 的公式是时间加权平均：

```text
AvgWIP = sum(WIP_i * duration_i) / observation_time_sec
```

其中每次 WIP 变化都会记录 `(timestamp, wip)`，最后一个 WIP 状态会延伸到 `end_ts`。

### 7.3 Stage KPI

系统把装配线抽象成 6 个 Stage：

| Stage | 入口 anchor | 说明 |
|---|---|---|
| Stage 1 | `station11 LOAD` | M1-1 |
| Stage 2 | `station21 LOAD`, `station22 LOAD` | M2-1/M2-2，looping stage |
| Stage 3 | `station31 LOAD` | M3-1 |
| Stage 4 | `station41 LOAD`, `station51 LOAD`, `station52 LOAD` | M4/M5 区域，looping stage |
| Stage 5 | `station61 LOAD` | M6-1 |
| Stage 6 | `station71 LOAD` | M7/QC，looping stage |

Stage 出口规则：

| Stage | 出口事件 |
|---|---|
| Stage 1 | `station11 TRANSFER` |
| Stage 2 | `splitter1 FORWARD` 后的 `splitter1 TRANSFER` |
| Stage 3 | `station31 TRANSFER` |
| Stage 4 | `splitter3` 或 `splitter4` 的 `FORWARD` 后 `TRANSFER`，且每个 `station41 LOAD` 只计一次 exit |
| Stage 5 | `station61 TRANSFER` |
| Stage 6 | `corner1 TRANSFER` |

Stage WIP 设计重点：

1. 一个 open lap 同一时刻只归属一个 Stage。
2. 如果已离开上一 Stage 但还没进入下一 anchor，则放在 `_part_transit_stage`。
3. `sum(stage_i.wip_instantaneous) == system.wip_instantaneous`。
4. 如果缺少正式 exit 事件，但 part 直接出现在下一 stage，系统会做 forced reconciliation，只调整 WIP，不增加 departure。

Stage 层公式：

| KPI | 公式 |
|---|---|
| `wip_instantaneous` | 当前归属该 Stage 的 open lap 数 |
| `wip_average` | 该 Stage WIP 的时间加权平均 |
| `num_departures` | 该 Stage 正式 exit 次数 |
| `throughput` | `num_departures / observation_time_sec` |
| `avg_flow_time` | 该 Stage 所有正式 entry 到 exit 的时间差平均 |

### 7.4 Station KPI

Station KPI 覆盖 9 个加工工站：

```text
station11, station21, station22, station31, station41,
station51, station52, station61, station71
```

每个工站是一个状态机：

```text
IDLE -> BUSY -> FAIL -> BLOCKED -> IDLE
```

状态转移：

| 事件 | 状态变化 |
|---|---|
| `LOAD` | 进入 `BUSY`，记录当前 part |
| `FAIL` | 如果当前是 `BUSY`，进入 `FAIL` |
| `UNLOAD` | 如果当前是 `BUSY` 或 `FAIL`，进入 `BLOCKED` |
| `BLOCK` | 如果当前是 `BUSY` 或 `FAIL`，进入 `BLOCKED` |
| `TRANSFER` | 如果当前是 `BLOCKED`，进入 `IDLE`，清空当前 part |
| `PASS` | 记录当前 part，但不强制改成 BUSY |

Station KPI 公式：

| KPI | 公式 |
|---|---|
| `P_busy` | `busy_time / station_observed_time` |
| `P_fail` | `fail_time / station_observed_time` |
| `P_blocked` | `blocked_time / station_observed_time` |
| `P_idle` | `idle_time / station_observed_time` |
| `utilization` | `P_busy + P_fail` |
| `current_state` | 当前状态 |
| `current_part_id` | 当前工站记录的 part |

注意：FAIL 被算作占用时间，所以 utilization = busy + fail；BLOCKED 不算 utilization。

### 7.5 Trend KPI

趋势图使用最近历史点：

| 趋势 | 数据 |
|---|---|
| WIP trend | `trend_sys_wip_history`，最多 200 个点 |
| Completion/Scrap rate trend | `trend_throughput_rates` |
| Yield/Scrap percentage trend | `trend_rate_history`，基于最近 20 个 departure rolling window |
| Finished cycle time trend | `trend_finished_cycle_times`，最多 1000 个完成样本 |

滚动窗口不是 lifetime cumulative。这样最近连续 scrap 时，曲线能迅速反映质量下降，而不是被早期大量良品稀释。

### 7.6 三套 WIP / Scrap 定义对照

答辩和读图时容易把三套指标混为一谈。对照如下：

| 场景 | WIP 含义 | Scrap / Scrap Rate 含义 |
|---|---|---|
| Live System KPI（§7.2） | open production lap 数 | `num_scraps / (num_completions + num_scraps)`，**比例** |
| Digital Twin | 地图上托盘位置与工站占用状态 | FINISH/SCRAP 事件计数，不是速率公式 |
| What-if Arena（§11） | `DAVG(Average WIP)` 仿真平均 WIP | `1/TAVG(ScrapDepartTime)*24*3600`，**报废产出速率** |

因此：What-if 图上 Scrap Rate 抖动大，并不等于“Live 报废比例突然变差”；它反映仿真中 scrap 间隔的随机性。Live 的 scrap rate 更接近质量合格率视角。

## 8. 日志格式

系统中有几类日志，作用不同。

### 8.1 Event CSV 日志

`recording.py` 或 `record_events.py` 订阅：

```text
component_event/+/all
```

写入 `event-logs/event_log_YYMMDD_HHMMSS.csv`。

默认列：

```csv
time,component_id,part_id,activity
2026-05-09T16:45:17.123456,corner2,p1,START
2026-05-09T16:45:20.222222,station11,p1,LOAD
2026-05-09T16:45:24.333333,station11,p1,PROCESS
2026-05-09T16:45:31.444444,station11,p1,UNLOAD
2026-05-09T16:45:33.555555,station11,p1,TRANSFER
```

这是 History Import、Replay、Neo4j 写入和 KPI 重算的标准事件格式。

### 8.2 KPI 文本日志

`main_service.py` 启动后写入：

```text
event-logs/kpi_log_YYMMDD_HHMMSS.txt
```

典型内容：

```text
[main_service] Started. Buffer + Neo4j + KPI. Ctrl+C to stop.
[main_service] KPI log: event-logs/kpi_log_260509_164517.txt
[main_service] App log: event-logs/main_service_260509_164517.log
[Session] event_log_20260509_164517
[KPI system] NumCompletions=10 NumScraps=1 WIP=3 AvgWIP=2.417 CompleteRate=0.0321/s ScrapRate=0.091 AvgCycleFin=45.6s AvgCycleAll=47.2s obs_time=311.4s
[KPI stage 1] WIP=1 AvgWIP=0.800 NumDepartures=14 Throughput=0.0450/s AvgFlow=8.2s
[KPI stage 2] WIP=0 AvgWIP=0.600 NumDepartures=13 Throughput=0.0418/s AvgFlow=12.7s
[Buffer] size=4, flush_last=2, flush_2s=17, total=380
  station41
    Utilization (P_busy): 0.72
    P_busy: 0.62  P_fail: 0.10  P_blocked: 0.08  P_idle: 0.20
```

其中 system/stage/station 三层 KPI 都会打印。

### 8.3 main_service app log

路径：

```text
event-logs/main_service_YYMMDD_HHMMSS.log
```

格式来自 `common.setup_logger()`：

```text
2026-05-09 16:45:17 - main_service - INFO - Connected to MQTT
2026-05-09 16:45:17 - main_service - INFO - Neo4j init OK, session: event_log_20260509_164517
2026-05-09 16:45:19 - main_service - INFO - [KPI system] ...
2026-05-09 16:45:21 - main_service - WARNING - Unexpected disconnect (rc=7), will auto-reconnect
```

### 8.4 控制动作日志

Streamlit 控制面板记录：

```text
.last_control_action.json
.control_action_history.jsonl
event-logs/deployment_actions.log
start_programs_progress.json
```

`.last_control_action.json` 示例：

```json
{
  "cmd": "Start System",
  "success": true,
  "time": "16:45:20",
  "time_full": "2026-05-09 16:45:20",
  "message": "main_service (realtime) up; physical line START sent..."
}
```

`.control_action_history.jsonl` 是一行一个 JSON，用于 View logs 弹窗。

`deployment_actions.log` 记录后台脚本 stdout/stderr，例如 `upload_code.py`、`upload_config.py`、`start_programs.py` 的输出。

### 8.5 Replay KPI sidecar

历史回放写：

```text
.replay_kpi.json
```

格式：

```json
{
  "t": 1715260000.123,
  "data": {
    "session_id": "event_log_20260509_164517",
    "run_mode": "replay",
    "system": {...},
    "stages": {...},
    "chart_time_unix": 1715260000.000
  },
  "completed": false
}
```

Streamlit 在非 Live 模式下优先读取它。`completed=true` 后，即使文件不再刷新，也仍然可用。

### 8.6 What-if Output 日志

Arena/SIMAN 输出 `Output.txt`，示例：

```text
1,11.725674,2240.605803,616.176533,468.782139,308.479312
2,11.764366,2280.629861,327.790016,489.173898,315.793353
3,11.808712,2323.010966,380.572043,478.659350,310.005546
```

字段含义（与 Arena `WriteOutput` 模块一致）：

| 列 | Arena 表达式 | 页面用途 |
|---|---|---|
| 1 | `NREP` | replication index |
| 2 | `DAVG(Average WIP)` | WIP 图 |
| 3 | `1/TAVG(ProducedDepartTime)*24*3600` | Completion Rate 图 |
| 4 | `1/TAVG(ScrapDepartTime)*24*3600` | Scrap Rate 图 |
| 5 | `TAVG(ProducedLeadTime)` | Lead Time 图 |
| 6 | `TAVG(ScrapLeadTime)` | 目前页面未画 |

说明：第 3、4 列是**单位时间内的产出速率**（由平均间隔时间的倒数换算），不是 Live Dashboard 里的报废比例。详见 §11.8。

`siman_runner.parse_output_file()` 对第 2 到第 5 列取中位数，作为当前 sweep point 的结果。

## 9. Digital Twin 功能

当前 Digital Twin 页面使用 Plotly 工厂布局图，主要代码是：

```text
twin/factory_floor_sim.py
twin/factory_floor_plotly.py
twin/digital_twin_cache.py
pages/05_Digital_Twin.py
```

### 9.1 Session 对齐

Digital Twin 首先调用：

```python
mqtt_backend.resolve_digital_twin_neo4j_session_id()
```

解析优先级：

| 模式 | Session 来源 |
|---|---|
| Live | KPI payload 中 `run_mode=physical` 的 `session_id` |
| Replay | `.replay_kpi.json` 的 `session_id` |
| History selection | `st.session_state["dt_resolved_session"]` |
| MQTT 不在线 | 从 Neo4j latest/selected session 重算 |

这样可以保证 KPI、Factory Layout、Part Trace 看到的是同一个 session。

### 9.2 Factory Layout 如何更新

`factory_floor_sim.sync_factory_floor_sim()` 根据 Neo4j 事件构建 sim state。

状态结构：

```python
{
  "queues": {},
  "part_locs": {},
  "part_states": {},
  "machines": {"station11": "IDLE", ...},
  "machine_parts": {},
  "kpi": {
    "fail_events": {},
    "block_events": {},
    "completed": 0,
    "scrapped": 0,
    "total_checkouts": 0
  }
}
```

事件处理逻辑：

| 事件 | Digital Twin 状态变化 |
|---|---|
| 任意有 SEQ_MAP 坐标的事件 | 更新 Part 所在队列/节点 |
| `LOAD` | 工站机器状态 `BUSY`，记录 part |
| `PROCESS`, `UNLOAD` | 如果当前 part 匹配，机器保持 `BUSY` |
| `BLOCK` | 机器状态 `BLOCK`，block count +1 |
| `FAIL` | 机器状态 `FAIL`，fail count +1 |
| `TRANSFER` | 如果机器处于 BLOCKED/占用，释放为 `IDLE` |
| `splitter5 FINISH` | Part 标记为完成，completed +1 |
| `splitter5 SCRAP` | Part 标记为报废，scrapped +1 |

`factory_floor_plotly.py` 定义了工厂几何布局：

| 元素 | 内容 |
|---|---|
| `machines_conf` | M1-1 到 M7-1 的 x 坐标和 station id |
| `draw_mergers` | Merger 1 到 Merger 5 |
| `draw_splitters` | Splitter 1 到 Splitter 5 |
| `SEQ_MAP` | `(component_id, activity) -> (x, y, direction)` |
| `build_factory_floor_figure()` | 画轨道、工站、分流器、托盘/Part 标记 |

如果多个 Part 在同一个位置，会聚合显示为 `+N`，避免地图文字重叠。

### 9.3 Live 与 Replay 的不同

Live：

```text
用 Neo4j cursor_ts + cursor_id 增量拉取新事件
```

Replay：

```text
用 KPI 的 chart_time_unix 作为回放时刻
只显示 timestamp <= chart_time_unix 的事件
```

所以 replay 时地图像“播放实验录像”，每次 KPI sidecar 更新时间，地图跟着推进。

### 9.4 Digital Twin 里的 Part Trace

Digital Twin 页面下半部分嵌入 Part Trace：

```python
ui_part_trace_panel.render_part_trace_panel(
  use_coordinated_twin_session=True,
  coordinated_twin_session_id=sess,
  kpi_for_replay=kpi,
  twin_preloaded_parts=...,
  twin_preloaded_rows=...
)
```

这意味着：

1. Part Trace 不会自己随便选 latest session。
2. 它和 Factory Layout 使用同一个 `sess`。
3. replay 模式下会按 `chart_time_unix` 截断 Part steps。
4. `digital_twin_cache.py` 会缓存 Neo4j 查询结果，减少刷新时重复查询。

## 10. Track / Part Trace 如何做

Part Track 的数据源是 Neo4j：

```cypher
MATCH (e:Event)-[:IN_SESSION]->(sess:Session {id: $session_id})
MATCH (e)-[:OCCURRED_AT]->(s:Station)
MATCH (e)-[:ACTS_ON]->(en:Entity)
MATCH (e)-[:OF_ACTIVITY]->(a:Activity)
RETURN en.sysId AS part_id, s.sysId AS component_id, a.name AS activity, e.timestamp AS ts
ORDER BY part_id, ts
```

`neo4j_backend.query_part_flow()` 返回：

```json
{
  "session_id": "event_log_...",
  "parts": [
    {
      "part_id": "p1",
      "steps": [
        {"component_id":"corner2","activity":"START","time":"16:45:17","timestamp":...},
        {"component_id":"station11","activity":"LOAD","time":"16:45:20","timestamp":...}
      ],
      "flow": "[16:45:17] corner2@START -> ..."
    }
  ]
}
```

### 10.1 Cycle 切分

Part Trace 以 `FINISH` 切分生产周期：

```text
Cycle = 从 corner2 START 到 splitter5 FINISH 的一段
SCRAP 会关闭 scrap lap
FAIL 不关闭周期
RETURN / TRANSFER 不关闭周期
```

如果 FINISH 之后又出现后续事件，则会形成新的 cycle。

### 10.2 物理路径 vs 工艺路径

系统明确区分：

| 路径 | 用途 |
|---|---|
| Physical path | 原始 component_id 序列，包含 splitter、corner、return belt |
| Process path | 只看 station 的 PROCESS/PASS 推导出的主线 Stage 序列 |

`twin_layout.PROCESS_STAGE_ORDER` 定义主线 7 个工艺格：

```text
ST11 -> ST21/22 -> ST31 -> ST41 -> ST51 -> ST61 -> ST71
```

其中：

| 组件 | 工艺格 |
|---|---|
| `station11` | `ST11` |
| `station21`, `station22` | `ST21/22` |
| `station31` | `ST31` |
| `station41` | `ST41` |
| `station51`, `station52` | `ST51` |
| `station61` | `ST61` |
| `station71` | `ST71` |

重要判断：

```text
物理回流 != 工艺返工
```

例如 splitter/corner/return belt 造成的物流环路，不一定是 Rework。只有工艺 Stage 出现 rollback，或者 FAIL 后继续加工/最终 FINISH，才归入 Rework。

### 10.3 Flow Type 分类

`flow_classification.classify_flow_from_steps()` 输出：

| outcome | UI label | 含义 |
|---|---|---|
| `normal` | Normal | 已 FINISH，无 FAIL，无 stage rollback |
| `rework` | Rework | FAIL 后修复/FINISH，或主线 stage rollback |
| `scrap` | Scrap | 路径包含 SCRAP |
| `open` | In progress | 未 FINISH，无 FAIL，无 rollback |
| `fail_open` | FAIL | 有 FAIL，尚未 FINISH，且没有后续 PROCESS/PASS 恢复 |

分类顺序：

```text
SCRAP
  -> last event == FINISH ? Normal/Rework
  -> has FAIL but not FINISH ? FAIL/Rework
  -> stage rollback ? Rework
  -> Open
```

### 10.4 Conformance 显示

`part_track_model.conformance_label_en()` 把 Flow 映射成 Conformance：

| Flow | Conformance |
|---|---|
| Normal | Conformant |
| Rework | Deviated (allowed) |
| Scrap | Deviated |
| In progress | Incomplete |
| FAIL | Incomplete (error) |

### 10.5 Matrix 和 Complete Trace

Part Track 提供两种矩阵：

1. 7-stage matrix：ST11 到 ST71，适合概览。
2. 9-step flow grid：来自 `flow_conformance_engine.py`，把 M4/M5 的 first pass 和 second pass 分开：

```text
S11
S21/S22
S31
S41 (1st)
S51/S52 (1st)
S41 (2nd)
S51/S52 (2nd)
S61
S71
```

Complete Trace 弹窗会显示每个 lap 的事件明细，并按 activity 着色：

| Activity | 显示语义 |
|---|---|
| LOAD / UNLOAD | 主要工位动作 |
| PROCESS | 加工 |
| FAIL | 失败 |
| FINISH / SCRAP | 结束结果 |
| PASS / RETURN / TRANSFER / CHECKOUT | 路由事件，视觉降权 |

## 11. What-if Analysis 仿真模拟

What-if Analysis 是一个离线实验验证模块。它不控制真实装配线，也不读取 MQTT/Neo4j 实时数据，而是调用 Arena/SIMAN 模型做参数扫描。

可以理解为：

```text
我提出一个实验假设：
如果 WIP Limit 或某个 Stage Buffer Capacity 改变，
系统的 WIP、Completion Rate、Scrap Rate、Lead Time 会怎样？

然后页面自动批量跑 Arena 模型，
把每组参数的仿真结果画出来。
```

所以它很适合答辩中说成“实验验证 / sensitivity analysis / scenario validation”。

### 11.1 输入文件

默认 Work Folder 是：

```text
model/
```

必须包含：

```text
model.p
Input.txt
Config.txt
```

当前 `model/Input.txt` 示例：

```text
16
6
10
4
10
4
6
```

对应参数：

| 行 | 页面参数 | 含义 |
|---|---|---|
| 1 | WIP Limit | 系统托盘/WIP 限制 |
| 2 | Stage1 Buffer Capacity | Stage 1 buffer capacity |
| 3 | Stage2 Buffer Capacity | Stage 2 buffer capacity |
| 4 | Stage3 Buffer Capacity | Stage 3 buffer capacity |
| 5 | Stage4 Buffer Capacity | Stage 4 buffer capacity |
| 6 | Stage5 Buffer Capacity | Stage 5 buffer capacity |
| 7 | Stage6 Buffer Capacity | Stage 6 buffer capacity |

`model/Config.txt` 示例：

```text
5
1800
10800
```

对应：

| 行 | 参数 |
|---|---|
| 1 | ReplicasNum |
| 2 | WarmUp |
| 3 | SimLength |

页面上的 `Replications` 会写入 Config.txt 第一行，WarmUp 和 SimLength 保持原值。

### 11.1.1 Arena 模型读写模块

当前编译模型 `model.p` 在仿真开始时用 ReadWrite 模块读入配置与输入，在每次 replication 结束时按条件写出 KPI：

```text
Create
  -> ReadConfig   （读 Config.txt）
  -> ReadInput    （读 Input.txt）
  -> Terminate    （结束 setup entity；不是整次仿真卡死）
  -> … 主仿真逻辑 …
  -> WriteOutput? （是否写出本 replication）
  -> WriteOutput  （写 Output.txt）
  -> Dispose
```

| 模块 | Arena File | 赋给的变量（顺序） |
|---|---|---|
| `ReadConfig` | `Config` → `Config.txt` | `ReplicasNum`, `WarmUp`, `SimLength` |
| `ReadInput` | `Input` → `Input.txt` | `PalletsNum`, `CapS_1_3_6(1)`, `Loop2Cap`, `CapS_1_3_6(2)`, `Loop45Cap`, `CapS_1_3_6(3)`, `Loop7Cap` |
| `WriteOutput` | `Output` → `Output.txt` | 见 §8.6 / §11.6；格式串 `"%i,%f,%f,%f,%f,%f\n"` |

扫参工作目录若缺少 `Config.txt`，SIMAN 会直接失败（连接被拒绝式的文件读错误），因此 `siman_runner` 每次 run 都会写入完整 Config。

关于复制次数：Arena Project 参数里的 Number of Replications 可能仍显示较大（例如日志中的 `Replication n of 50`），但模型逻辑用 `ReplicasNum` 控制有效写出。页面 `Replications` 改的是 Config 第一行，对应 `Output.txt` 中有意义的行数，而不是改 Project 对话框本身。

### 11.2 页面逻辑

用户操作：

1. 选择 Work Folder。
2. 选择 Parameter。
3. 输入 From / To / Step。
4. 输入 Replications。
5. 点击 Run Analysis。

校验规则：

| 校验 | 规则 |
|---|---|
| Work Folder | 必须存在 |
| 文件 | 必须包含 `model.p`, `Input.txt`, `Config.txt` |
| From/To | `To >= From` |
| Step | `Step > 0` |
| Replications | `>= 1` |
| 点数 | 最多 15 个 sweep points |

点数计算：

```text
N = floor((To - From) / Step) + 1
```

### 11.3 运行逻辑

`run_parameter_sweep()` 的流程：

```text
读取 Input.txt 得到 base values
读取 Config.txt 得到 [ReplicasNum, WarmUp, SimLength]
如果页面指定 replications，则替换 Config 第一行
生成参数值序列 x
为每个 x 建立 run payload
并行运行每个 point
读取各 point 的 Output.txt
按 x 排序
返回 SweepResult
```

每个点会建立独立目录：

```text
model/runs/pt_<Parameter>_<x>/
```

里面包含：

```text
model.p
model.dsn
MOTOWN_7Stations_Arena.csv
Input.txt
Config.txt
Output.txt
```

这样做的原因是避免多个 SIMAN 进程同时读写同一个 `Output.txt`。

### 11.4 调用 SIMAN

默认 SIMAN 路径：

```text
C:\Program Files\Rockwell Software\Arena\siman.exe
```

也可以通过环境变量覆盖：

```text
ARENA_SIMAN_EXE
```

实际命令：

```text
siman.exe -B -Q model.p
```

含义：

| 参数 | 作用 |
|---|---|
| `-B` | batch mode |
| `-Q` | quiet mode |

### 11.5 并行方式

What-if 使用 `ProcessPoolExecutor`：

```python
workers = max(1, min(os.cpu_count() or 1, len(values_x)))
```

也就是说：

```text
worker 数 = min(本机逻辑核心数, sweep 点数)
```

如果只有 1 个点，则串行运行，不额外开进程池。

### 11.6 输出结果

SIMAN 的 `Output.txt` 每行代表一个 replication，格式与 Arena `WriteOutput` 一致：

```text
NREP, DAVG(Average WIP), 1/TAVG(ProducedDepartTime)*24*3600, 1/TAVG(ScrapDepartTime)*24*3600, TAVG(ProducedLeadTime), TAVG(ScrapLeadTime)
```

页面当前使用第 2 到第 5 列：

| 图 | 来源列 | Arena 含义（简要） |
|---|---|---|
| WIP | 第 2 列 | 平均在制品 |
| Completion Rate | 第 3 列 | 合格件产出速率（间隔时间倒数换算） |
| Scrap Rate | 第 4 列 | 报废件产出速率（同上，**不是报废比例**） |
| Lead Time | 第 5 列 | 合格件平均提前期 |

如果有多个 replication，代码对每个指标取中位数：

```text
point.WIP = median(all replication WIP)
point.Completion Rate = median(all replication completion rate)
point.Scrap Rate = median(all replication scrap rate)
point.Lead Time = median(all replication lead time)
```

中位数比均值更抗离群复制；但当 scrap 间隔方差很大时，5 次复制的中位数曲线仍可能锯齿明显。

最终写入 Streamlit session state 的结构：

```json
{
  "x": [12, 13, 14, 15],
  "WIP": [10.8, 11.1, 11.5, 11.7],
  "Completion Rate": [2100.0, 2200.0, 2300.0, 2280.0],
  "Scrap Rate": [400.0, 380.0, 360.0, 390.0],
  "Lead Time": [510.0, 495.0, 480.0, 489.0]
}
```

页面用四张 Plotly 折线图显示，即：

```text
横轴 = 被扫描参数值
纵轴 = 对应仿真 KPI
```

### 11.7 What-if 的实验意义

What-if Analysis 可以作为“仿真实验验证”：

1. 控制变量：一次只改变一个参数。
2. 重复实验：用 Replications 多次重复，取中位数降低随机波动。
3. 输出指标：观察 WIP、产出速率、报废产出速率、Lead Time 的 trade-off。
4. 参数敏感性：判断哪个 buffer 或 WIP limit 对产线表现最敏感。

它和真实线 Dashboard 的关系：

| 模块 | 数据来源 | 目的 |
|---|---|---|
| Live KPI | MQTT + main_service | 实时监控真实生产 |
| History / Replay | Neo4j / CSV | 回放和复盘真实或导入事件 |
| Digital Twin | Neo4j event stream | 可视化当前或历史事件状态 |
| What-if | Arena/SIMAN | 离线做方案实验，不影响真实产线 |

因此 What-if 更像实验室中的 scenario testing，而不是现场控制指令。

### 11.8 与 Live KPI 的指标语义差异

What-if 图名与 Dashboard 相似，但定义不同（参见 §7.6）：

| 名称 | Live Dashboard | What-if Arena |
|---|---|---|
| WIP | open lap 数（事件状态机） | 仿真平均 WIP |
| Completion / throughput | `num_completions / obs_time` | `1/TAVG(ProducedDepartTime)*24*3600` |
| Scrap Rate | 报废**比例** | 报废**产出速率** |
| Lead / Cycle Time | 完成 lap 的 `(FINISH−START)` 平均等 | `TAVG(ProducedLeadTime)` |

读 What-if 图时应注意：Scrap 曲线上下跳动，通常表示随机报废到达间隔波动大，不能直接解读为“合格率恶化”。若需要更平滑的敏感性曲线，应增大 Replications（例如 10–20），或另行计算 `scrap/(completion+scrap)` 比例指标（当前页面未画）。

### 11.9 实测示例：WIP Limit 扫参（12→20）

在默认 `Config.txt`（ReplicasNum=5, WarmUp=1800, SimLength=10800）下，对 WIP Limit 从 12 扫到 20（Step=1）时，四张图的典型形态为：

| 图 | 趋势 | 是否合理 |
|---|---|---|
| WIP | 近似随 Limit 线性上升（约 9→14），且低于 Limit | 合理：放宽托盘上限后平均 WIP 上升，但仍受工位/buffer 约束 |
| Completion Rate | 整体上升，小幅波动 | 合理：更多在制品通常带来更高吞吐，直至趋近瓶颈 |
| Scrap Rate | 锯齿明显、无单调趋势 | 可解释：速率型指标 + 仅 5 次复制取中位，方差大 |
| Lead Time | 近似线性上升（约 400→550） | 合理：符合 Little’s Law 方向（WIP↑ 且吞吐未同比例↑ 时 LT↑） |

该示例说明 What-if 模块能跑通完整链路，且主趋势符合制造系统直觉；Scrap 图“看起来不合理”时，应先核对指标定义与复制次数，而不是先怀疑画图错误。

### 11.10 What-if 实现边界

1. 扫参在 Streamlit 请求内同步执行，长时间 Run 会占用该页会话。
2. `workers = min(逻辑核数, 点数)`，全核并行可能与本机 Dashboard / `main_service` 抢 CPU。
3. 点数上限 15，避免一次实验过长。
4. 只扫 `Input.txt` 七个参数之一；WarmUp / SimLength 需改 `Config.txt` 基准文件。
5. 与早期 What-if 说明（本地 `doc/report2.md`）相比，当前实现已接入 `Config.txt` 与页面 Replications；以本文 §11 为准。

## 12. 数据流总结

### 12.1 Live Monitoring 数据流

```text
组件脚本发布 component_event
  -> main_service 订阅 MQTT
  -> EventBuffer 排序
  -> KpiCalculator 更新 KPI
  -> Neo4j writer 写图数据库
  -> main_service 发布 kpi/main_service/all
  -> Streamlit KPI Dashboard 展示
  -> Digital Twin 从 Neo4j 增量查询事件，更新地图和 Part Trace
```

### 12.2 History Replay 数据流

```text
选择 Neo4j Session
  -> replay_session_direct.py 读取该 Session 的事件
  -> EventPipeline 只重算 KPI，不重复写 Neo4j
  -> .replay_kpi.json 更新
  -> Streamlit 读取 sidecar
  -> KPI / Digital Twin / Part Trace 按 chart_time_unix 同步推进
```

### 12.3 CSV Import 数据流

```text
上传 CSV
  -> 校验列 time/component_id/part_id/activity
  -> 检查重复：first event time + event_count
  -> neo4j_backend.import_csv_session()
  -> neo4j_writer 写 Session/Event/关系
  -> History selector 中出现新 session
```

### 12.4 What-if 数据流

```text
页面输入参数范围
  -> siman_runner 复制 model 到 runs/pt_*
  -> 修改 Input.txt 和 Config.txt
  -> 调用 siman.exe
  -> 读取 Output.txt
  -> 取中位数
  -> Plotly 画 WIP / Completion / Scrap / Lead Time
```

## 13. 当前实现的边界与注意点

1. Streamlit 不替代 `main_service`。实时事件处理、Neo4j 写入和 MQTT KPI 发布仍由独立 `main_service.py` 完成。
2. Live Monitoring 模式下 KPI 只认 MQTT，不使用 `.replay_kpi.json`。
3. History Replay 不通过 MQTT event bus，避免历史数据影响真实控制器。
4. Neo4j Session 节点当前只保留 `id/start_time/end_time`，description/status 等旧字段会在写入时移除。
5. What-if 不读取 live KPI，也不写 Neo4j；它是 Arena/SIMAN 离线实验。
6. Digital Twin 当前页面实际使用 Plotly 工厂图；`twin_layout.py` 仍提供 SVG 布局和工艺 Stage 映射规则。
7. Live WIP 是“open production lap”概念，不是简单托盘实物数；重复 START 会被忽略，避免同一 part 未闭环时重复计 WIP。
8. Rework 不是任意物理回流，而是工艺主线 Stage 回退或 FAIL 后修复/完成。
9. Live 与 What-if 的 Scrap Rate **不同义**（比例 vs 速率），见 §7.6、§11.8。
10. What-if 工作目录必须同时有 `model.p`、`Input.txt`、`Config.txt`；缺 Config 时 SIMAN 无法启动。
11. Neo4j 索引检查曾会把首次连接失败结果缓存住；当前实现在失败后会于下次刷新重试（`ui_sidebar.finalize_neo4j_indexes`）。
12. History 的 session `selectbox` 绑定 `session_state` key 后，同一次脚本运行中不得再写入该 key（Streamlit 限制）；归一化逻辑须放在控件创建之前。

## 14. 本地启动与常见问题

### 14.1 推荐启动方式

在项目根目录（含 `config.json`）下：

| 角色 | 方式 | 说明 |
|---|---|---|
| 后端 | `run_main.bat` 或 `python main_service.py` | 订阅现场事件、写 Neo4j、发 KPI |
| 前端 | `run_streamlit.bat` / `run_web.bat` | `streamlit run streamlit_app/app.py` |
| 环境 | `CONFIG_FILE=config.json` | 与 `main_service`、Dashboard 共用 broker / Neo4j |

What-if 不依赖 `main_service` 与 MQTT，但依赖本机已安装的 Arena `siman.exe`。

### 14.2 Neo4j：`WinError 10061` / indexes not fully ready

典型报错：

```text
Couldn't connect to localhost:7687 ... [WinError 10061] 由于目标计算机积极拒绝，无法连接
```

含义：当时 Bolt 端口无人监听，不是“图数据库密码一定错了”。

常见原因与处理：

| 现象 | 处理 |
|---|---|
| Neo4j Desktop 已打开，但 DBMS 未 Start | 在 Desktop 中启动实例，确认 `7687` Listening |
| 先打开 Streamlit、后启动 Neo4j | 刷新页面；索引失败会重试，必要时 Clear cache |
| `config.json` 的 `neo4j.uri` 指向 `bolt://localhost:7687` | 与 Desktop 默认本地实例一致；远程库需改 URI |

注意：Desktop UI 显示“已连接项目”≠ Bolt 服务已就绪。应用侧以 `neo4j_backend.neo4j_ping()` / 索引创建成功为准。

### 14.3 `main_service`：Already running

若日志出现 `Already running (PID …)`，表示已有实例在跑，新进程会退出。这是单实例保护，不是崩溃。需要重启时先结束旧 PID 再启动。

### 14.4 Streamlit 端口

若 `8501` 已被占用，Streamlit 可能改用 `8502`、`8503` 等。以终端打印的 Local URL 为准。

## 15. 一句话总结

这个项目的 Streamlit 部分是一个装配线数字孪生控制台：Live 模式通过 MQTT 控制和监控 `mt-ems-pl` 真实装配线，`main_service` 把事件转成 KPI 和 Neo4j 图数据；Dashboard 用这些数据展示 KPI、历史回放、Part Trace、Conformance 和 Digital Twin；What-if Analysis 则独立调用 Arena/SIMAN（`Config.txt` + `Input.txt` → `Output.txt`）做参数敏感性实验，用来验证不同 WIP/buffer 策略对产线性能的影响。阅读仿真结果时，须区分 Live 比例型报废率与 Arena 速率型 Scrap 指标。