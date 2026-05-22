# 实施方案：事件排序、KPI 计算与 UI 开发

## 1. 当前系统概览

### 1.1 架构
```
Physical System (mt-ems-pl)
    ↓ MQTT (component_event)
    ├─→ record_events.py  →  event_log_YYMMDD_HHMMSS.csv
    └─→ main_service.py
            ↓
        event_buffer (300ms window, sorted by timestamp)
            ↓ flush_ready() every 0.3s
            ├─→ neo4j_writer  →  Neo4j Graph Database
            └─→ kpi_calculator  →  KPI snapshot (print + kpi_log.txt every 2s)
```

### 1.2 当前实现文件
- `event_buffer.py`: 时间窗口 + bisect 插入排序
- `kpi_calculator.py`: 事件驱动 KPI 计算（吞吐量、在制品、流时、利用率、状态概率）
- `main_service.py`: MQTT 订阅 → 缓冲 → Neo4j + KPI 计算
- `neo4j_writer.py`: 将事件写入 Neo4j，为同一零件创建 DF（直接跟随）边

---

## 2. 已识别的主要问题

### 2.1 MQTT 事件乱序问题

**问题：**
- MQTT 仅保证**同一客户端发往同一主题**的消息顺序
- 当前系统有**多个客户端**（工位）向同一主题 `component_event` 发送
- 网络延迟可能导致事件乱序到达
- 示例：工位 A 在 T1 发送 "TRANSFER"，工位 B 在 T2 发送 "BLOCK"，但 B 的事件先到达

**当前方案的局限：**
- 300ms 时间窗口缓冲
- 每 0.3 秒定期 flush
- 若 MQTT 延迟 > 300ms 可能丢失事件
- 无法判断缓冲事件何时可“安全”处理

**根本原因：**
- 缺乏事件驱动触发机制
- 依赖固定时间窗口，未考虑最新收到的事件时间戳

---

### 2.2 事件缓存更新机制

**问题：**
- 当前：每 0.3 秒定期 flush（`main_service.py:104` 中的 `time.sleep(0.3)`）
- 问题：未利用新收到事件的信息
- 低效：可能过早处理或等待过久

**需求：**
- 应为**事件驱动**：收到新事件时，确定哪些缓冲事件现已可确认
- 缓冲应按时间戳保持有序
- 用最新事件时间戳确定 flush 的截止点

---

### 2.3 图数据库事件排序

**当前实现（`neo4j_writer.py`）：**
- 仅在**同一零件**的连续事件间创建 DF（直接跟随）边
- 事件在图数据库中以 Set（无序）存储
- 检索事件需读取所有节点再按时间戳排序（O(n log n)）

**问题：**
- 流程挖掘关注**单一案例 ID**（单一零件）
- 本系统需跟踪**系统级事件**（多零件同时）
- 需知道**不同零件**在相同/相近时间戳下事件的顺序

**老师建议：**
- 建立全局事件排序链，而不仅是按零件
- 每个事件有 "next" 关系形成全序
- 好处：
  - 用深度优先搜索快速检索（O(n) 线性）
  - 从数据库读取后无需排序
  - 支持高效流式流程挖掘

**实现思路：**
- 全局维护 "latest_event_id" 指针
- 写入新事件到 Neo4j 时：
  1. 创建事件节点
  2. 创建到同一零件前一事件的 DF 边（现有逻辑）
  3. **从全局前一事件创建 NEXT 边**（新逻辑）
  4. 更新全局 latest_event_id

---

### 2.4 KPI 计算时机

**当前：**
- 每个事件更新 KPI（`main_service.py:76` 中的 `kpi.on_event(ev)`）
- 每 2 秒打印 KPI（`main_service.py:85-110`）

**分析：**
- 事件驱动更新是正确的
- 打印间隔适合人工阅读
- 对 UI 仪表盘，可能需要不同刷新率

**此处无关键问题**，但应考虑：
- UI 不应阻塞事件处理
- 可能需要单独线程用于 UI 更新

---

### 2.5 数据类型初始化

**Python 中的问题：**
```python
# Current code may initialize as:
wip = 0  # int
# Later used as:
wip = 0.0  # float
```

**问题：**
- Python 是动态类型
- 类型转换会创建新对象（性能开销）
- 可能导致计算中的意外行为

**解决方案：**
- 从一开始用正确类型初始化变量：
  - 浮点变量用 `0.0`
  - 整型计数用 `0`
  - 整个生命周期保持一致

**`kpi_calculator.py:29` 中的示例修复：**
```python
# Current:
self.current_wip = 0  # OK, this is intentionally int

# But ensure all time-related variables are float:
self.observation_start_ts = None  # OK, will be assigned float from timestamp()
```

**需审查：**
- 工位状态中所有累加变量
- 确保初始化时类型一致

---

### 2.6 MQTT 连接管理

**当前（`main_service.py:79-83`）：**
- 单一 MQTT 客户端，连接一次
- 优点：复用连接
- 缺失：断开时的重连逻辑

**问题：**
- 若 MQTT broker 重启，服务需手动重启
- 无连接失败处理

**未来改进：**
- 添加连接丢失回调
- 实现指数退避自动重连
- 记录连接状态变化

---

## 3. 提议的解决方案

### 3.1 事件驱动缓冲 Flush 机制

**概念：**
收到时间戳为 T_new 的新事件时：
1. 将事件加入缓冲（现有：bisect 插入）
2. 确定 cutoff = T_new - window_ms
3. Flush 所有时间戳 < cutoff 的事件
4. 这些事件是“安全”的，因为即使延迟事件到达，其时间戳也会 < cutoff - window_ms

**`event_buffer.py` 中的实现变更：**

```python
class EventBuffer:
    def __init__(self, window_ms: int = 300, max_size: int | None = None):
        self.window_ms = window_ms
        self._events = []  # (ts, event) sorted by ts
        self._lock = threading.Lock()

    def add_and_flush(self, event: dict) -> list[dict]:
        """
        Add event and return events that are now safe to process.
        Event-driven: uses new event's timestamp to determine cutoff.
        """
        time_str = event.get("time")
        if not time_str:
            return []

        ts = parse_time_to_float(time_str)
        item = (ts, event)

        with self._lock:
            # Insert new event
            bisect.insort(self._events, item)

            # Determine cutoff based on latest event timestamp
            # Find the maximum timestamp in buffer (should be the last one)
            if not self._events:
                return []

            max_ts = self._events[-1][0]  # Latest event timestamp
            cutoff = max_ts - (self.window_ms / 1000.0)

            # Flush events older than cutoff
            ready = []
            while self._events and self._events[0][0] < cutoff:
                _, ev = self._events.pop(0)
                ready.append(ev)

            return ready
```

**`main_service.py` 中的变更：**

```python
# OLD:
def on_message(client, userdata, msg):
    # ...
    buffer.add(event)

# In main loop:
while True:
    time.sleep(0.3)
    _process_ready_events()

# NEW:
def on_message(client, userdata, msg):
    # ...
    ready_events = buffer.add_and_flush(event)
    for ev in ready_events:
        try:
            neo4j_writer.write_event_to_graph(ev)
        except Exception as e:
            print("[main_service] Neo4j write error:", e)
        kpi.on_event(ev)

# Main loop only handles printing:
while True:
    time.sleep(2.0)  # Only for printing, not for buffer flush
    snap = kpi.get_snapshot()
    _print_kpi_snapshot(snap, kpi_log_file)
```

**好处：**
- **事件驱动**：无任意 sleep 间隔
- **更快响应**：事件一旦安全即处理
- **更准确**：使用实际事件时间戳，而非挂钟时间
- **主循环更简单**：无需定期检查缓冲

---

### 3.2 Neo4j 中的全局事件排序

**目标：** 建立所有事件的全序，而不仅是按零件排序。

**`neo4j_writer.py` 中的实现：**

```python
# Add global state
_last_event_per_part: dict[str, str] = {}  # Existing
_last_global_event_id: str | None = None    # NEW

def write_event_to_graph(event: dict):
    """Write one event to Neo4j with both per-part and global ordering."""
    if "time" in event and "timestamp" not in event:
        event = _to_neo4j_format(event)
        if event is None:
            return

    event_id = str(uuid.uuid4())
    part_id = event["part_id"]

    with driver.session() as session:
        # Create event node
        session.execute_write(_create_event_tx, event_id, event)

        # DF edge: same part's consecutive events (existing)
        previous_part_id = _last_event_per_part.get(part_id)
        if previous_part_id is not None:
            session.execute_write(_create_df_tx, previous_part_id, event_id)

        # NEXT edge: global event ordering (NEW)
        global _last_global_event_id
        if _last_global_event_id is not None:
            session.execute_write(_create_next_tx, _last_global_event_id, event_id)

        _last_global_event_id = event_id

    _last_event_per_part[part_id] = event_id

def _create_next_tx(tx, previous_id, current_id):
    """Create NEXT edge for global event ordering."""
    query = """
    MATCH (e1:Event {id: $previous_id})
    MATCH (e2:Event {id: $current_id})
    MERGE (e1)-[:NEXT]->(e2)
    """
    tx.run(query, previous_id=previous_id, current_id=current_id)
```

**图结构：**
```
Event1 --DF--> Event2 --DF--> Event3  (same part p1)
  |              |              |
  NEXT          NEXT           NEXT
  |              |              |
  v              v              v
Event4 ------DF-----> Event5           (same part p2)
```

**按序查询所有事件：**
```cypher
// Find first event (no incoming NEXT)
MATCH (e:Event)
WHERE NOT exists((e)<-[:NEXT]-())
RETURN e
ORDER BY e.timestamp LIMIT 1

// Traverse all events via NEXT
MATCH path = (start:Event)-[:NEXT*]->(end:Event)
WHERE NOT exists((start)<-[:NEXT]-())
RETURN nodes(path)
```

**好处：**
- 线性遍历 O(n) vs 排序 O(n log n)
- 保持插入顺序（与缓冲排序一致）
- 支持高效流式查询
- 同时支持按零件（DF）和系统级（NEXT）分析

**注意：**
- 若系统重启，需处理查找最后一个全局事件
- 可添加 "Session" 节点标记不同运行

---

### 3.3 增强的 KPI 计算器初始化

**审查 `kpi_calculator.py` 的类型一致性：**

```python
# Line 23-24: OK (int counters)
self.finished_count = 0
self.scrap_count = 0

# Line 25-26: OK (None, will be assigned float)
self.observation_start_ts = None
self.last_event_ts = None

# Line 29: OK (int)
self.current_wip = 0

# Line 32: OK (list)
self.flow_times = []

# Line 49-52: NEED REVIEW
self._station_accumulated[station_id] = {
    "IDLE": 0.0,     # OK
    "LOADING": 0.0,  # OK
    "PROCESSING": 0.0,  # OK
    "UNLOADING": 0.0,   # OK
    "BLOCKED": 0.0,     # OK
    "FAILED": 0.0,      # OK
}
# Current code is correct! Already using 0.0 for float values.
```

**类型初始化无需修改。** 当前代码已正确。

---

### 3.4 MQTT 连接韧性

**在 `main_service.py` 中添加重连逻辑：**

```python
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[main_service] Connected to MQTT successfully")
        topic = common.render_topic("component_event", "+", "all")
        client.subscribe(topic, qos=2)
    else:
        print(f"[main_service] Connection failed with code {rc}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"[main_service] Unexpected disconnect (code {rc}), reconnecting...")
        # Client will auto-reconnect if configured

mqtt_client = mqtt.Client()
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect  # NEW
mqtt_client.on_message = on_message

# Enable automatic reconnection
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=120)  # NEW

mqtt_client.connect(MQTT_BROKER_HOST, port=MQTT_BROKER_PORT)
mqtt_client.loop_start()
```

---

## 4. 下一步实施步骤

### 4.1 Phase 1：修复事件缓冲机制（高优先级）

**任务：**
1. 修改 `event_buffer.py`：
   - 实现 `add_and_flush()` 方法
   - 移除或弃用单独的 `flush_ready()` 方法
   - 添加完整 docstring
   - 添加单元测试（可选但建议）

2. 更新 `main_service.py`：
   - 将 `on_message` 改为使用 `add_and_flush()`
   - 在回调中立即处理事件
   - 简化主循环，仅负责 KPI 打印
   - 为事件处理添加错误处理

3. 充分测试：
   - 用 `replay_events.py` 配合现有 CSV 日志
   - 验证事件按正确顺序处理
   - 检查 KPI 计算准确
   - 监控缓冲大小（应保持较小）

**预估工时：** 4–6 小时  
**关键：** 这是可靠事件排序的基础

---

### 4.2 Phase 2：在 Neo4j 中实现全局事件排序（中优先级）

**任务：**
1. 修改 `neo4j_writer.py`：
   - 添加 `_last_global_event_id` 变量
   - 实现 `_create_next_tx()` 函数
   - 在 `write_event_to_graph()` 中加入 NEXT 边创建
   - 处理重启场景（查询最后一个事件）

2. 测试 Neo4j 图结构：
   - 用示例事件运行系统
   - 验证 DF 和 NEXT 边均被创建
   - 编写 Cypher 查询遍历事件
   - 比较遍历与按时间戳排序的性能

3. 文档：
   - 记录图模式
   - 提供示例 Cypher 查询
   - 说明 DF 与 NEXT 的用途

**预估工时：** 3–5 小时  
**收益：** 支持高效流程挖掘查询

---

### 4.3 Phase 3：开发 FastAPI + WebSocket UI 仪表盘（高优先级）

**需求：**
- 展示实时 KPI 指标
- 显示工位状态与利用率
- 提供系统操作控制按钮
- 自动刷新且不阻塞事件处理
- 轻量级、快速开发

**推荐架构：FastAPI + WebSocket + 简单 HTML/JS**

**选择此方案的原因：**
- **开发速度快**：无需学习 Vue/React 框架
- **代码量少**：仅需 1-2 个 HTML 文件 + 少量 JS
- **调试简单**：浏览器 F12 调试，无需构建工具（npm/webpack）
- **老师关注重点**：后端逻辑（实时数据流、Neo4j、流程挖掘）更重要
- **未来可扩展**：FastAPI 后端已足够专业；前端后续可升级到 Vue/React 而不影响后端
- **独立进程**：比集成到 main_service 更易调试和重启

**文件结构：**
```
lego-factory/
├── main_service.py          # 现有：MQTT -> Buffer -> Neo4j + KPI
├── web_api.py               # 新增：FastAPI + WebSocket 服务
├── static/
│   ├── index.html           # 新增：监控主页面
│   ├── app.js               # 新增：WebSocket + Chart.js 逻辑
│   └── style.css            # 新增：可选样式
└── requirements.txt         # 添加：fastapi, uvicorn, websockets
```

**通信设计：**
```
main_service.py (MQTT 主循环)
    ↓ 发布 KPI 到 MQTT topic（如 kpi/main_service/all）
MQTT Broker
    ↓ 订阅
web_api.py (FastAPI)
    ↓ WebSocket 推送
浏览器 (HTML + Chart.js)
```

**`web_api.py` - FastAPI 服务（约 100 行）：**
```python
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import asyncio
import json
import paho.mqtt.client as mqtt
from neo4j import GraphDatabase
import common

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# 配置
CONFIG = common.load_json("config.json")
NEO4J_URI = CONFIG["neo4j"]["uri"]
NEO4J_USER = CONFIG["neo4j"]["username"]
NEO4J_PASSWORD = CONFIG["neo4j"]["password"]
MQTT_BROKER_HOST = CONFIG["mqtt_broker_host"]
MQTT_BROKER_PORT = CONFIG["mqtt_broker_port"]

neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# 全局 KPI 状态（由 MQTT 回调更新）
_latest_kpi = {}

# MQTT 客户端订阅 KPI 更新
def on_connect_kpi(client, userdata, flags, rc):
    print("[web_api] 已连接到 MQTT 获取 KPI (rc={})".format(rc))
    topic = common.render_topic("kpi", "main_service", "all")
    client.subscribe(topic, qos=0)

def on_message_kpi(client, userdata, msg):
    global _latest_kpi
    try:
        _latest_kpi = common.deserialize_object(msg.payload.decode("utf-8"))
    except Exception as e:
        print("[web_api] 解析 KPI 错误: {}".format(e))

mqtt_kpi_client = mqtt.Client()
mqtt_kpi_client.on_connect = on_connect_kpi
mqtt_kpi_client.on_message = on_message_kpi
mqtt_kpi_client.connect(MQTT_BROKER_HOST, port=MQTT_BROKER_PORT)
mqtt_kpi_client.loop_start()

@app.get("/")
def index():
    """返回主仪表盘 HTML"""
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/kpi")
async def websocket_kpi(websocket: WebSocket):
    """通过 WebSocket 向浏览器推送 KPI 更新"""
    await websocket.accept()
    try:
        while True:
            if _latest_kpi:
                await websocket.send_json(_latest_kpi)
            await asyncio.sleep(2)  # 每 2 秒推送
    except Exception as e:
        print(f"[web_api] WebSocket 错误: {e}")

@app.get("/api/graph")
def get_process_graph():
    """从 Neo4j 返回流程图数据（活动到活动的 DF 边）"""
    with neo4j_driver.session() as session:
        result = session.run("""
            MATCH (e1:Event)-[:DF]->(e2:Event)
            MATCH (e1)-[:OF_ACTIVITY]->(a1:Activity)
            MATCH (e2)-[:OF_ACTIVITY]->(a2:Activity)
            RETURN a1.name AS from_activity, a2.name AS to_activity, count(*) AS count
            ORDER BY count DESC
            LIMIT 50
        """)
        edges = [{"from": r["from_activity"], "to": r["to_activity"], "count": r["count"]}
                 for r in result]
    return {"edges": edges}

@app.on_event("shutdown")
def shutdown():
    """清理连接"""
    mqtt_kpi_client.loop_stop()
    mqtt_kpi_client.disconnect()
    neo4j_driver.close()
```

**`static/index.html` - 仪表盘 UI（约 60 行）：**
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LEGO 工厂监控</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <header>
        <h1>LEGO 工厂实时监控仪表盘</h1>
    </header>

    <main>
        <section class="kpi-cards">
            <div class="card">
                <h3>吞吐量</h3>
                <p id="throughput">0.0000 parts/s</p>
            </div>
            <div class="card">
                <h3>完成</h3>
                <p id="finished">0</p>
            </div>
            <div class="card">
                <h3>废品</h3>
                <p id="scrap">0</p>
            </div>
            <div class="card">
                <h3>在制品</h3>
                <p id="wip">0</p>
            </div>
            <div class="card">
                <h3>平均流时</h3>
                <p id="flow_time">0.00 s</p>
            </div>
        </section>

        <section class="charts">
            <div class="chart-container">
                <canvas id="throughputChart"></canvas>
            </div>
            <div class="chart-container">
                <canvas id="wipChart"></canvas>
            </div>
        </section>

        <section class="stations" id="stations">
            <!-- 工位状态将动态填充 -->
        </section>
    </main>

    <script src="/static/app.js"></script>
</body>
</html>
```

**`static/app.js` - WebSocket + Chart.js 逻辑（约 100 行）：**
```javascript
// WebSocket 连接
const ws = new WebSocket('ws://localhost:8000/ws/kpi');

// 图表数据
const throughputData = { labels: [], values: [] };
const wipData = { labels: [], values: [] };
const MAX_POINTS = 50;

// 初始化 Chart.js 图表
const throughputChart = new Chart(
    document.getElementById('throughputChart'),
    {
        type: 'line',
        data: {
            labels: throughputData.labels,
            datasets: [{
                label: '吞吐量 (parts/s)',
                data: throughputData.values,
                borderColor: 'rgb(75, 192, 192)',
                tension: 0.1
            }]
        },
        options: { animation: false, responsive: true }
    }
);

const wipChart = new Chart(
    document.getElementById('wipChart'),
    {
        type: 'line',
        data: {
            labels: wipData.labels,
            datasets: [{
                label: '在制品 WIP',
                data: wipData.values,
                borderColor: 'rgb(255, 99, 132)',
                tension: 0.1
            }]
        },
        options: { animation: false, responsive: true }
    }
);

// WebSocket 消息处理
ws.onmessage = function(event) {
    const kpi = JSON.parse(event.data);

    // 更新 KPI 卡片
    document.getElementById('throughput').textContent =
        kpi.throughput.toFixed(4) + ' parts/s';
    document.getElementById('finished').textContent = kpi.finished_count;
    document.getElementById('scrap').textContent = kpi.scrap_count;
    document.getElementById('wip').textContent = kpi.wip;
    document.getElementById('flow_time').textContent =
        kpi.avg_flow_time_sec.toFixed(2) + ' s';

    // 更新图表
    const now = new Date().toLocaleTimeString();

    throughputData.labels.push(now);
    throughputData.values.push(kpi.throughput);
    if (throughputData.labels.length > MAX_POINTS) {
        throughputData.labels.shift();
        throughputData.values.shift();
    }
    throughputChart.update();

    wipData.labels.push(now);
    wipData.values.push(kpi.wip);
    if (wipData.labels.length > MAX_POINTS) {
        wipData.labels.shift();
        wipData.values.shift();
    }
    wipChart.update();

    // 更新工位状态
    updateStations(kpi.utilization, kpi.state_probability);
};

function updateStations(utilization, stateProb) {
    const container = document.getElementById('stations');
    container.innerHTML = '<h2>工位状态</h2>';

    for (const [stationId, util] of Object.entries(utilization)) {
        const stationDiv = document.createElement('div');
        stationDiv.className = 'station';
        stationDiv.innerHTML = `
            <h3>${stationId.toUpperCase()}</h3>
            <p>利用率: ${(util * 100).toFixed(1)}%</p>
        `;
        container.appendChild(stationDiv);
    }
}

ws.onerror = function(error) {
    console.error('WebSocket 错误:', error);
};
```

**对 `main_service.py` 的修改 - 发布 KPI 到 MQTT：**
```python
# 在主循环中，获取 KPI 快照后：
while True:
    time.sleep(KPI_PRINT_INTERVAL)
    snap = kpi.get_snapshot()
    _print_kpi_snapshot(snap, kpi_log_file)
    _flush_since_last_print = 0

    # 新增：将 KPI 发布到 MQTT 供 Web 仪表盘使用
    try:
        topic = common.render_topic("kpi", "main_service", "all")
        mqtt_client.publish(topic, common.serialize_object(snap), qos=0)
    except Exception as e:
        print("[main_service] KPI 发布错误: {}".format(e))
```

**运行系统：**
```bash
# 终端 1：主服务（MQTT + Neo4j + KPI）
python main_service.py

# 终端 2：FastAPI Web 服务器
uvicorn web_api:app --reload --port 8000

# 浏览器打开：http://localhost:8000
```

**优势：**
- **快速开发**：2-3 天即可完成基础监控 UI
- **无框架负担**：无需 Vue/React 学习曲线
- **专业后端**：FastAPI 可用于生产环境，可扩展
- **面向未来**：易于升级前端到 Vue.js 用于流程挖掘（Phase 3B）
- **独立部署**：web_api 可运行在不同机器/端口
- **实时性**：WebSocket 提供即时更新，无需轮询

**预估工时：** 4–6 小时（相比 Streamlit 的 6-8 小时）
**优先级：** 高（用于演示和易用性）

---

### 4.4 Phase 4：优化 MQTT 连接（低优先级）

**任务：**
1. 添加 `on_disconnect` 回调
2. 配置自动重连
3. 在 UI 中添加连接状态指示
4. 记录所有连接事件

**预估工时：** 2–3 小时  
**优先级：** 低（无此功能系统仍可运行，但可提升稳健性）

---

## 5. 测试策略

### 5.1 事件排序测试
**目标：** 验证事件驱动缓冲正确排序事件

**测试设置：**
1. 用 `replay_events.py` 配合已知 CSV 日志
2. 人为打乱事件（模拟乱序）
3. 验证输出顺序与时间戳顺序一致

**预期结果：**
- 所有事件按时间戳顺序处理
- 无事件丢失
- 缓冲大小在限定范围内

---

### 5.2 KPI 准确性测试
**目标：** 验证 KPI 计算正确

**测试用例：**
1. **吞吐量：** 在 T 秒内发送 N 个 FINISH 事件，验证 throughput ≈ N/T
2. **在制品：** 跟踪 LOAD/FINISH/SCRAP 事件，验证 WIP 计数与预期一致
3. **流时：** 对已知零件，验证 avg_flow_time 与手工计算一致
4. **利用率：** 对已知工位状态序列，验证利用率正确

**测试数据：**
- 使用小型、手工构造的事件序列
- 手工计算预期 KPI
- 与系统输出对比

---

### 5.3 Neo4j 图结构测试
**目标：** 验证图正确表示事件与排序

**测试查询：**
```cypher
// Count events
MATCH (e:Event) RETURN count(e)

// Verify all events have NEXT edge (except last)
MATCH (e:Event)
WHERE NOT exists((e)-[:NEXT]->())
RETURN count(e)  // Should be 1 (only last event)

// Verify DF edges for a specific part
MATCH path = (e:Event)-[:DF*]->(end:Event)
WHERE e.part_id = 'p1' AND NOT exists((e)<-[:DF]-())
RETURN length(path)

// Check for orphaned events
MATCH (e:Event)
WHERE NOT exists((e)-[:OCCURRED_AT]->())
   OR NOT exists((e)-[:ACTS_ON]->())
   OR NOT exists((e)-[:OF_ACTIVITY]->())
RETURN count(e)  // Should be 0
```

---

### 5.4 UI 响应性测试
**目标：** 确保 UI 不阻塞事件处理

**测试：**
1. 在高事件率下运行系统
2. 监控 main_service 处理时间
3. 验证 UI 更新不造成延迟
4. 检查 CPU 使用

**预期：**
- 单事件处理 <10ms
- UI 刷新不阻塞 MQTT 线程
- 更新流畅无卡顿

---

## 6. 文档更新

### 6.1 更新 README.md
- 添加事件排序机制说明
- 记录 UI 仪表盘用法
- 更新执行步骤以包含 UI

### 6.2 创建技术文档（英文）
**文件：** `TECHNICAL_ARCHITECTURE.md`

**章节：**
1. 系统概览
2. 事件处理流水线
3. KPI 计算逻辑
4. Neo4j 图模式
5. 缓冲机制设计
6. MQTT 通信协议
7. 性能考量

### 6.3 更新 WEEKLY_REPORT.md
- 记录新的事件驱动缓冲设计
- 说明全局事件排序
- 包含 UI 仪表盘截图
- 更新架构图

**所有文档按老师要求使用英文。**

---

## 7. 时间线与优先级

- [x] 审查当前实现
- [x] 识别问题（本文档）
- [ ] Phase 1：实现事件驱动缓冲（高优先级）
- [ ] 用 replay_events.py 测试


- [ ] Phase 2：Neo4j 全局事件排序（中优先级）
- [ ] Phase 3：启动 FastAPI + WebSocket UI 仪表盘（高优先级）
- [ ] 基础 UI 与 KPI 展示


- [x] Phase 3 续：UI 控制按钮、流程图
- [x] 将 UI 与主服务集成（MQTT KPI 发布）
- [x] Phase 4：MQTT 连接韧性（低优先级）
- [x] 第 16 节：Upload Code/Config、配置切换、PID 单例、事件驱动改进、安全修复、Stop Replay 与 Stop main_service 区分、UI 更新

- [ ] 测试与验证
- [ ] 文档更新（全部英文）
- [ ] 性能优化
- [ ] 准备演示

---

## 8. 风险缓解

### 8.1 事件丢失
**风险：** 若回调中发生异常，事件驱动缓冲可能丢失事件

**缓解：**
- 用 try-except 包裹事件处理
- 记录所有错误及事件详情
- 为失败事件实现死信队列
- 添加已处理/失败事件指标

### 8.2 Neo4j 性能
**风险：** 创建 NEXT 边可能降低写入速度

**缓解：**
- 必要时批量写入
- 为 Event.id 和 Event.timestamp 建索引
- 监控写入延迟
- 考虑异步写入（但保持顺序）

### 8.3 UI 阻塞
**风险：** WebSocket 或 MQTT 订阅可能阻塞 FastAPI 事件循环

**缓解：**
- MQTT 使用 `loop_start()` 在独立线程；FastAPI 运行异步
- 保持 KPI 快照轻量（无重计算）
- WebSocket 每 2 秒推送一次，非阻塞
- web_api 与 main_service 独立进程

### 8.4 MQTT 消息丢失
**风险：** QoS 2 可能有性能开销

**缓解：**
- 对 QoS 0、1、2 做基准测试
- 若可接受，考虑 QoS 1（至少一次投递）
- 必要时添加消息 ID 与去重

### 8.5 线程安全（MQTT 回调）
**风险：** `on_message` 在 MQTT 线程中运行；`kpi.on_event()` 与 Neo4j 写入可能存在竞态

**缓解：**
- 详见第 15.1 节
- 使用 `queue.Queue` 将事件传给主线程，或在 KPI 计算器中加锁
- 确认 Neo4j 驱动用法为线程安全

---

## 9. 未来增强（当前范围外）

### 9.1 流程挖掘集成
- 将图数据导入 ProM/Disco
- 发现流程模型
- 一致性检查
- 瓶颈分析

### 9.2 高级分析
- 基于当前状态预测流时
- 检测工位行为异常
- 基于 KPI 优化调度

### 9.3 多会话支持
- 分别跟踪不同生产运行
- 跨会话比较 KPI
- 历史趋势分析

### 9.4 分布式部署
- 分离服务（MQTT、Neo4j、KPI、UI）
- 容器化（Docker）
- 高吞吐水平扩展

---

## 10. 关键设计决策摘要

| 决策 | 理由 |
|----------|-----------|
| 事件驱动缓冲 flush | 比定期轮询更准确、响应更快 |
| Neo4j 全局 NEXT 边 | 实现 O(n) 事件检索 vs O(n log n) 排序 |
| MQTT 发布 KPI | 将 Web UI 与 main_service 进程解耦 |
| 使用 FastAPI + WebSocket 做 UI | 实时推送，生产可用，可扩展 |
| MQTT QoS 2 | 保证恰好一次投递（无重复/丢失） |
| 按零件 DF + 全局 NEXT | 同时支持案例级与系统级分析 |

---

## 11. 需与老师澄清的问题

1. **事件排序：**
   - 是否应为不同零件类型也创建 NEXT 边？
   - 如何处理时间戳完全相同的事件？

2. **KPI 计算：**
   - 是否支持运行中重置 KPI？
   - KPI 应按会话还是累计跟踪？

3. **UI 需求：**
   - 需要哪些控制操作（启动/停止/重置）？
   - UI 应支持查看历史数据还是仅实时？

4. **Neo4j 会话管理：**
   - 每次运行前是否清空数据库？
   - 还是用 session_id 标记事件并保留历史？

5. **性能：**
   - 预期事件率（事件/秒）？
   - KPI 更新可接受延迟？

---

## 12. 结论

本实施方案针对当前系统的主要问题：
1. **事件排序**：通过事件驱动缓冲 flush 机制
2. **图结构**：全局 NEXT 边实现高效检索
3. **UI 仪表盘**：使用 FastAPI + WebSocket 做实时监控与控制
4. **稳健性**：更好的错误处理与 MQTT 重连

**近期步骤：**
1. 实现事件驱动缓冲（Phase 1）——最高优先级
2. 用 replay_events.py 充分测试
3. 启动 FastAPI + WebSocket UI 开发（Phase 3）

所有后续文档将按老师要求使用**英文**。

---

## 13. 真实事件日志数据分析（event_log_260312_180229.csv）

### 13.1 数据概览

**数据集特征：**
- **总事件数：** 911
- **时间范围：** 2026-03-12 18:02:42 至 18:15:42
- **时长：** 约 13 分钟（782 秒）
- **平均事件率：** 约 1.16 事件/秒
- **组件：** station11-71, corner1-2, splitter1-5
- **跟踪零件：** p2, p3, p6, p7, p9, p11, p12, p16

### 13.2 事件排序 - 主要发现

**未检测到乱序事件**

911 个事件均按时间戳严格时间先后顺序。

**关键洞察：** 该 CSV 表示 record_events.py 的**到达顺序**。若 MQTT 乱序投递但每条消息带有正确的生成时间戳，CSV 会按到达顺序显示有序时间戳——从而掩盖乱序！

### 13.3 时间间隔统计

| 指标 | 值 | 解读 |
|--------|-------|----------------|
| **最小间隔** | 0.12 ms | 几乎同时发生 |
| **中位数间隔** | 550.76 ms | 典型间距 |
| **95 分位** | 2530.55 ms | 约 2.5 秒 |
| **最大间隔** | 11163.92 ms | 约 11 秒 |
| **间隔 < 50ms** | 76 (8.4%) | 高并发 |
| **间隔 < 300ms** | 262 (29%) | **当前窗口仅覆盖 29%！** |
| **间隔 < 2000ms** | 836 (92%) | 推荐窗口覆盖 |

**主要发现：** 71% 的事件间隔 > 300ms（当前缓冲窗口）。

### 13.4 老师讨论中的观察

1. **MQTT 延迟：** 实践中观察到“数秒”级延迟
2. **事件驱动设计：** 用最新事件时间戳做截止，而非挂钟时间
3. **全局排序：** 需要 NEXT 边做系统级分析
4. **窗口担忧：** 鉴于观察到的延迟，质疑 300ms 是否足够

### 13.5 窗口大小建议

**当前：300ms** → 仅覆盖 29% 的事件到达

**建议：2000ms（2 秒）**
- 理由：
  - 95 分位间隔 = 2.5s
  - 老师观察到“数秒”级延迟
  - 覆盖 92% 典型场景
  - 为网络问题留安全余量

**配置：**
```json
{
  "event_buffer": {
    "window_ms": 2000,
    "max_size": 500
  }
}
```

### 13.6 事件驱动设计（老师核心洞察）

**当前做法（有问题）：**
```python
while True:
    time.sleep(0.3)  # Arbitrary wait
    flush_ready(now())  # Uses wall clock
```

**老师建议：**
```python
def on_message(msg):
    event = parse(msg)
    buffer.add(event)

    # Key: Use event timestamp!
    cutoff = event['timestamp'] - window_ms
    ready_events = buffer.flush_before(cutoff)

    for e in ready_events:
        process(e)
```

**为何更优：**
- 无任意 sleep
- 使用实际事件时间
- 事件一到即处理
- 尊重因果

**数学保证：**
```
If:
  - MQTT max delay = D ms
  - Window = W ms (W > D)
  - Receive event E with timestamp T

Then:
  Any event with timestamp < T - W
  was generated ≥W ms ago
  and should have arrived already
  → Safe to process!
```

### 13.7 摘要：数据驱动结论

| 发现 | 含义 |
|---------|-------------|
| CSV 中 0 乱序 | 不能证明无 MQTT 乱序（仅显示生成顺序） |
| 95 分位 = 2.5s | 印证老师“数秒”观察 |
| 71% 间隔 > 300ms | **当前窗口过小** |
| 8.4% 间隔 < 50ms | 高并发需要高效缓冲 |

**建议置信度：**
- ✓✓✓ 高：将窗口增至 2000ms
- ✓✓✓ 高：使用事件驱动 flush
- ✓✓ 中：需要到达时间戳以测量真实乱序
- ✓ 低：仅靠 CSV 不足以验证当前方案

**变更后预期：**
- KPI 更稳定
- 无事件遗漏（若 MQTT 延迟 < 2s）
- 比定期轮询响应更快
- 更好的并发事件处理

---

## 14. 与老师设想的一致性

数据分析印证了老师的直觉：

1. ✓ “MQTT 延迟数秒” → 95 分位 = 2.5s
2. ✓ “300ms 可能太小” → 仅覆盖 29% 事件
3. ✓ “用事件时间戳做截止” → 当前使用挂钟时间（错误）
4. ✓ “事件驱动更好” → 有统计支持

**立即行动：** 以数据支持的窗口大小 **2000ms** 实施 Phase 1。

---

## 15. 实现注意事项与补充

*本节在审查中识别的实现细节上对方案进行补充。*

### 15.1 回调中事件处理的线程安全

**背景：** 在 `on_message` 回调中处理事件时，paho-mqtt 在其**自有线程**中调用回调。`neo4j_writer.write_event_to_graph()` 和 `kpi.on_event()` 都会在该线程中运行。

**考量：**
- **Neo4j 驱动：** 官方 Python 驱动在 session/transaction 使用上通常为线程安全。确保每次写入使用一个 session 或正确使用连接池。
- **KPI 计算器：** 审查 `kpi_calculator.py` 的线程安全。若 `on_event()` 在无锁情况下修改共享状态（计数器、列表、字典），应添加 `threading.Lock()` 保护，或使用 `queue.Queue` 将事件传给主线程处理。

**若 KPI 非线程安全时的推荐做法：**
```python
# In main_service.py: use a queue, process in main loop
import queue
event_queue = queue.Queue()

def on_message(client, userdata, msg):
    # ... parse event ...
    ready_events = buffer.add_and_flush(event)
    for ev in ready_events:
        event_queue.put(ev)

# Main loop (runs in main thread):
while True:
    try:
        while True:
            ev = event_queue.get_nowait()
            neo4j_writer.write_event_to_graph(ev)
            kpi.on_event(ev)
    except queue.Empty:
        pass
    time.sleep(2.0)
    # ... print KPI ...
```

**备选：** 若可接受修改，在 `kpi_calculator.py` 内加锁。

---

### 15.2 UI 与 main_service 进程分离（KPI 共享）

**背景：** 方案使用**独立进程**：`main_service.py` 与 `web_api.py`（FastAPI）。KPI 数据需跨进程共享。

**跨进程 KPI 共享方案：**

| 方案 | 优点 | 缺点 |
|--------|------|------|
| **A. MQTT 发布** | 实时，复用现有 broker | 需 main_service 发布 |
| **B. JSON 文件** | 简单，无额外依赖 | 文件 I/O，轮询延迟 |
| **C. Redis/Socket** | 实时，可扩展 | 额外依赖/基础设施 |

**Phase 3 推荐：** 使用 **MQTT 发布**（主方案）：
- `main_service.py` 每 2 秒发布 KPI 到 topic `kpi/main_service/all`
- `web_api.py` 订阅并转发给 WebSocket 客户端

**备选（最简单）：** 使用 **JSON 文件**——若不想用 MQTT，main_service 写文件，web_api 定时读取并推送。

---

### 15.3 WebSocket 推送间隔

**说明：** WebSocket 每 2 秒推送一次（`asyncio.sleep(2)`），与 main_service 的 KPI 打印间隔一致。若需更高频率，可同时缩短两处间隔；确保 main_service 发布频率不超过计算频率。

---

### 15.4 建议的周度范围

| 周 | 重点 | 备注 |
|------|-------|-------|
| **第 1 周** | 仅 Phase 1 | 事件驱动缓冲 + 2000ms 窗口；用 replay 验证 |
| **第 2 周** | Phase 2 + Phase 3 起步 | Neo4j NEXT 边；基础 FastAPI + WebSocket UI |
| **第 3 周** | Phase 3 完成 + Phase 4 | UI 控制、MQTT 韧性、测试 |

Phase 1 是基础；若时间允许，Phase 2 和 3 可并行。

---

## 16. 已实现增强（方案后实施）

*本节记录在原方案基础上新增的增强功能。*

### 16.1 Upload Code / Upload Config

- **API：** `POST /api/control/upload_code`、`POST /api/control/upload_config`
- **用途：** 通过 SSH+SFTP 将本地 Python 代码和配置文件部署到远程控制器（树莓派/EV3）
- **配置：** 使用 `config.json` 的 `local_code_paths` 和 `local_config_paths`；路径预配置，非文件选择器
- **仪表盘：** 实时控制区 Step 0 的 Deploy Code、Deploy Config 按钮

### 16.2 配置自动切换

- **行为：** 仪表盘根据用户操作自动切换配置：
  - **Upload & Replay** → `config_local.json`（broker.hivemq.com，本地 MQTT）
  - **Start main_service** → `config.json`（物理系统）
- **MQTT：** 切换时重连；web_api 与 main_service 保持同一 broker
- **回放流程：** 回放前校验 main_service 已运行；配置切换后等待 MQTT 就绪，避免「上传后无数据」
- **UI：** 顶部显示「Config: physical」或「Config: local」徽章

### 16.3 进程管理（PID 文件 + 统一检测）

- **main_service：** 通过 PID 文件实现单例；若已有实例则退出
- **web_api：** 统一从 PID 文件获取 `_get_main_service_pid()` 和 `_is_main_service_running()`
- **进程结束：** Windows 使用 `taskkill /F /T`；最多等待 10 秒；验证进程已结束
- **启动：** 启动前强制清理；等待 main_service 就绪；验证 PID 文件
- **psutil：** 必需依赖（无可选降级）

### 16.4 事件驱动改进

- **WebSocket：** 随 KPI 推送状态（recording、replay、main_service、MQTT）；减少前端轮询
- **前端：** 仅轮询 `part_flow`（5 秒）；状态由 WebSocket 提供
- **common.sleep：** `mt-ems-pl`、`g2-2s-pl` 使用 `threading.Event.wait()` 替代忙轮询；MQTT 收到 system_status 时调用 `notify_status_changed()`
- **event_buffer：** 使用切片批量 pop，替代逐项 `pop(0)`

### 16.5 安全修复

- **命令注入：** 将 `os.system("sudo date -s " + payload)` 改为 `subprocess.run(["sudo", "date", "-s", payload])` 并校验
- **RuntimeError：** 在 `mt-ems-pl/common.py`、`g2-2s-pl/common.py` 中为 `RuntimeError("No more spare blocks")` 补上 `raise`
- **KPI 除零：** `kpi_calculator.py` 中 `obs_time = max(0.001, ...)`

### 16.6 Stop Replay 与 Stop main_service 区分

- **Stop Replay：** 停止回放和 main_service；**保留** KPI、图表、工位数据
- **Stop main_service：** 清空所有数据（KPI、图表、Part Flow）
- **前端：** 两者均停止时图表冻结，不再追加新点

### 16.7 UI / 仪表盘

- **Config 徽章：** 顶部显示 physical / local
- **Deploy 标签：** Deploy Code / Deploy Config（非文件上传）
- **Start main_service：** 30 秒就绪超时，带进度反馈
- **诊断：** `GET /api/diagnostics` 用于排查问题
- **语言：** 界面仅英文

