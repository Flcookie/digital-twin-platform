# 第四周汇报：方案2 实施进展

## 一、老师提出的问题

根据方案2文档，老师主要关注以下问题：

1. **MQTT 事件乱序**：多客户端向同一主题发送，网络延迟导致事件乱序到达；当前 300ms 窗口 + 定期 flush 可能丢失事件。
2. **事件缓存机制**：当前用固定 0.3 秒轮询 flush，未利用新事件时间戳，效率低。
3. **图数据库事件排序**：仅按零件建 DF 边，缺少全局事件链；老师建议建立 NEXT 边形成全序，便于 O(n) 检索。
4. **MQTT 连接管理**：无断线重连，broker 重启需手动重启服务。
5. **UI 仪表盘**：需实时 KPI、工位状态、控制按钮，且不阻塞事件处理。

---

## 二、解决思路与实现

### 2.1 事件驱动缓冲（Phase 1）✓

- **思路**：收到新事件时，用其时间戳确定 cutoff = T_new - window_ms，flush 所有 ts < cutoff 的事件。
- **实现**：`event_buffer.py` 实现 `add_and_flush()`，`main_service.py` 在 `on_message` 中直接处理返回的 ready 事件；窗口可配置（建议 2000ms）。
- **效果**：事件驱动、响应更快、不依赖挂钟。

### 2.2 Neo4j 全局事件链（Phase 2）✓

- **思路**：维护 `last_global_event_id`，写入新事件时创建 `(prev)-[:NEXT]->(current)` 边。
- **实现**：`neo4j_writer.py` 在批量写入时创建 DF 边（同零件）和 NEXT 边（全局顺序）。
- **效果**：支持按 NEXT 链 O(n) 遍历，无需排序。

### 2.3 FastAPI + WebSocket UI（Phase 3）✓

- **思路**：main_service 独立进程，通过 MQTT 发布 KPI；web_api 订阅并转发给 WebSocket 客户端。
- **实现**：`web_api.py` + `static/index.html`，KPI、工位状态、Part Flow、图表；控制按钮：Deploy Code/Config、Start main_service、Upload & Replay、Stop 等。
- **效果**：UI 与事件处理解耦，实时更新。

### 2.4 MQTT 连接韧性（Phase 4）✓

- **思路**：配置连接、重连逻辑；UI 显示连接状态。
- **实现**：配置切换时 MQTT 重连；WebSocket 推送 status（含 MQTT 状态）；诊断接口 `GET /api/diagnostics`。

### 2.5 方案外增强（第 16 节）

- **Upload Code/Config**：通过 SSH+SFTP 部署代码和配置到远程控制器。
- **配置自动切换**：Upload & Replay 用 `config_local.json` (broker.hivemq.com)；Start main_service 用 `config.json`（物理系统）。
- **进程管理**：main_service 单例（PID 文件）；统一检测与清理逻辑。
- **安全修复**：命令注入改为 `subprocess.run`；RuntimeError 补 `raise`；KPI 除零防护。
- **Stop 行为区分**：Stop Replay 保留数据；Stop main_service 清空数据；图表在两者均停时冻结。

---

## 三、完成情况

| 任务 | 状态 | 说明 |
|------|------|------|
| Phase 1：事件驱动缓冲 | ✓ 已完成 | `add_and_flush` 已实现并接入 main_service |
| Phase 2：Neo4j NEXT 边 | ✓ 已完成 | 全局事件链已写入 neo4j_writer |
| Phase 3：UI 仪表盘 | ✓ 已完成 | FastAPI + WebSocket，KPI、图表、控制按钮 |
| Phase 4：MQTT 韧性 | ✓ 已完成 | 配置切换重连、状态推送、诊断接口 |
| 第 16 节增强 | ✓ 已完成 | Deploy、配置切换、PID 单例、安全修复等 |

**老师提出的核心任务已全部完成。** 后续可做：测试与验证、文档完善、性能优化、演示准备。

---

## 四、测试与验证报告

### 4.1 测试范围

按方案2 第 5 节测试策略，执行了以下测试：

| 测试类型 | 对应方案 | 测试文件 | 结果 |
|----------|----------|----------|------|
| 事件排序 | 5.1 Event Ordering | `test_event_buffer.py` | ✓ 通过 |
| KPI 准确性 | 5.2 KPI Accuracy | `test_kpi_calculator.py` | ✓ 通过 |
| API 接口 | Phase 3 UI | `test_web_api.py` | ✓ 通过 |

### 4.2 事件缓冲单元测试（test_event_buffer.py）

- **test_add_and_flush**：验证用事件时间戳做 cutoff，非挂钟；单事件不 flush，2s 窗口内多事件按序 flush。
- **test_out_of_order**：乱序到达（t=2, t=0, t=1）时，缓冲内按时间戳排序，收到 t=4.2 后一次性按 A→B→C 顺序输出。
- **test_max_size**：超过 max_size 时强制 flush 最旧事件，保证缓冲不溢出。

**结果：** 3/3 通过

### 4.3 KPI 计算单元测试（test_kpi_calculator.py）

- **test_throughput**：1 个 FINISH 在 10s 内 → throughput ≈ 0.1 parts/s（replay 模式）。
- **test_wip**：LOAD +1、FINISH -1、SCRAP -1，WIP 正确增减。
- **test_flow_time**：LOAD→FINISH 间隔 5s → avg_flow_time = 5s。
- **test_divide_by_zero**：空 KPI 时 obs_time 使用 max(0.001,...)，无除零崩溃。
- **test_reset**：reset 后计数归零。

**结果：** 5/5 通过

### 4.4 Web API 接口测试（test_web_api.py）

使用 FastAPI TestClient 验证：

- **GET /api/health**：返回 `{ok: true}`
- **GET /api/diagnostics**：返回 main_service、mqtt、neo4j、recording、replay_running
- **GET /api/main_service/status**：返回 running、pid
- **GET /api/dashboard_status**：返回 config_mode、recording 等
- **GET /**：返回 HTML 仪表盘页面

**结果：** 5/5 通过

### 4.5 运行方式

```powershell
cd c:\Users\beira\lego-factory
.venv\Scripts\activate
python run_tests.py
```

或分别运行：`python test_event_buffer.py`、`python test_kpi_calculator.py`、`python test_web_api.py`。

### 4.6 集成测试（手动）

- **Replay 回放**：按《运行指南》启动 `run_web.bat`，选择 CSV、Upload & Replay，观察 KPI/图表更新。需 MQTT（broker.hivemq.com）和 Neo4j。
- **Neo4j 图结构**：回放后可用 Cypher 验证 NEXT 边：`MATCH (e:Event) WHERE NOT exists((e)-[:NEXT]->()) RETURN count(e)` 应为 1（仅最后事件无出边）。

### 4.7 总结

| 项目 | 通过 | 失败 |
|------|------|------|
| 事件缓冲 | 3 | 0 |
| KPI 计算 | 5 | 0 |
| Web API | 5 | 0 |
| **合计** | **13** | **0** |

**所有自动化测试通过。** 事件驱动缓冲、KPI 计算、API 接口均符合方案2 预期。

---

## 五、口头汇报参考

*以下为向老师口头汇报时可参考的说法，可按实际情况精简或展开。*

---

**开场：**

老师好，我汇报一下这周做的工作。您上次提的几个问题，基本都解决了，也做了测试验证。

---

**问题与解决（简要版）：**

第一个是 **MQTT 事件乱序**。改成了事件驱动：收到新事件时，用它的时间戳算 cutoff，把超过窗口的旧事件 flush 出去，不再用固定 0.3 秒轮询。窗口也调成 3000ms，因为我在看log发现92%的事件，3000ms可靠性更高，代价可接受。

第二个是 **Neo4j 全局排序**。加了 NEXT 边，每个事件连到前一个，形成一条全局链，检索时按链走就行，不用再排序。

第三个是 **UI 仪表盘**。用 FastAPI + WebSocket，main_service 发 KPI 到 MQTT，web_api 转给前端，实时显示。控制按钮也都有了，比如 Deploy Code、Start main_service、Upload & Replay 这些。

另外还做了一些增强：配置自动切换（本地测试用 broker.hivemq.com，物理系统用 config.json）、main_service 单例、安全修复（命令注入、除零这些），以及 Stop Replay 和 Stop main_service 的行为区分。

---

**测试：**

写了单元测试和 API 测试，一共 13 个用例，全部通过。包括事件缓冲的乱序、窗口、max_size，KPI 的吞吐量、WIP、流时、除零，还有 Web API 的 health、diagnostics、status 等接口。集成测试可以按运行指南手动跑 Replay 验证。

