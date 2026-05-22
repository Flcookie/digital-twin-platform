# 第 6 周规划（会议纪要整理）

> 依据本周会议语音整理（转写有错字、顺序略乱处已按语义合并）。  
> **与代码仓库**：未特指两个新文件时，以下均为**功能/交互层面的 backlog**，落地时以现有 `streamlit_app/`、`main_service.py` 等为准。

---

## 〇、核心结论（先落地结构、再扩功能）

**老师与本阶段目标可以压成三句话：**

1. **优先级**：先把现有 **KPI + Trace + 控制**做稳；**不要**现在主攻关 simulation / 大_process mining / AI。
2. **架构**：从「功能分散在多页、控制不统一」→ **主控层（全局）+ 子页面（展示）**。
3. **产品感**：减少操作冲突（同時 real-time + replay），界面结构要像**可交付系统**而不是 demo 堆功能。

### 推荐信息架构（执行版）

**定稿交互**：**第一页（Main）只有「全局控制 + 模块入口」**（卡片 / 按钮 / 侧边导航均可）；**不承载**完整 KPI 图、整张孪生图、轨迹表等。**点击进入对应子页** 才展示具体内容。

```
Main Page（主控制层 · 入口 + 控制）
 ├── Start System / Stop System
 ├── Replay Mode（toggle 或等价）+ 文件选择（replay 时）
 ├── Mode：Real-time / Replay
 ├── 入口（仅导航，详情在子页）：KPI · Digital Twin · simulation（占位 Coming soon）
 └── 状态：Running / Idle / Replay 等

Sub Pages（功能展示层 · 点击入口后进入）
 ├── KPI Dashboard（System + Station）— 实时与历史 log 回放的指标在此页查看
 └── Digital Twin— layout、part 流转、part track、conformance check 在此页查看
```

**与会议摘要的对照（这版逻辑是否「对」）**

- **主页面**：控制（Start/Stop、Mode、Replay、文件）+ **KPI / Twin 的入口**（卡片或导航），与老师说的「总控在一页、再点进分界面」一致；**第一页不做详细展示**，避免主屏过载。  
- **KPI 子页**：写明实时与历史回放 **都在这里看指标** —— 对应老师说的 Realtime/History 内容重复、合并观感。  
- **Trace 放进 Digital Twin**：老师强调 Trace 是 **序列/路径**、Twin 是 **空间/layout**；放在同一子页内用 **分栏或 Tab（地图 | 轨迹 | Conformance）** 仍然算「一块屏看清」，与「主控 + 子页」不矛盾。后文 **§一.8「KPI 上、Trace 下」** 是备选排版；你当前是 **KPI 与 Twin 分两子页**，亦合理。  
- **Simulation 占位**：与老师「先做稳 KPI+Trace+控制、仿真后说」一致。

**原则**：控制逻辑 = **全局**；展示逻辑 = **局部**。子页尽量「一屏或一钻到底能看完」，减少无意义跳转。

### 当前痛点 vs 目标形态

| 现状问题 | 目标 |
|----------|------|
| Start / Replay 分散在不同页面 | 集中在 **Main Page** |
| KPI / Trace / State 混在一起、重复 | **拆分职责**：KPI 子页；**Trace 放在 Digital Twin 内**（与 layout 同屏或分 Tab）；Station state 不与 KPI 重复啰嗦 |
| 页面间无统一控制状态 | **单一真相**：当前 mode + running 状态驱动禁用/启用 |
| 可能同时 replay + 跑现场 | **互斥**：Running（real-time）↔ Replay；见下表 |

**控制互斥（实现时对照）**

| 状态 | 限制 |
|------|------|
| Real-time **Running** | 不得启动 **Replay**（禁用或强提示） |
| **Replay** 进行中 | 不得 **Start real-time**（或先 Stop replay） |

---

## 一、会议要点摘要

### 1. 上传代码与「考到哪里」的困惑（操作层）

- 在资源管理器里搜同名文件、看**修改时间**，确认本机目录是否为 `lego-factory` / `mt-ems-pl` 预期路径。  
- 与 **GitHub 是否联动**：本机文件夹不等于自动同步远程；上传行为以 `config.json` + `upload_code.py` 为准。  
- **建议**：在组内约定「唯一真相目录」+ 上传前 `git status` / 对比时间戳；此条偏流程，非必改代码。

### 2. 当前闭环操作（已认可）

- **Start**：`start system` 一并带上 **main_service、record、CSV**（与 Streamlit 集成流一致）。  
- **Stop / shutdown**：停脚本与现场关机路径保留。  
- 提及 **TTI** 与**全线图**更新仍有优化空间（Performance / 全图刷新）。

### 3. 信息架构：主页面 + 子页面

- **主页面（建议）**：只放**全局控制** — Start / Stop、**Replay 总开关**、与 realtime vs replay 相关的模式切换、全局状态提示。  
- **子页面**：KPI、Part trace、Digital twin、History 等 — **钻入后再看细节**，避免单页过长、难以维护交互状态。  
- **Replay**：视为**全局模式**，与「现场已 Start」互斥时要禁点或强提示，避免一边跑线一边 replay 逻辑冲突。

### 4. Realtime / History 合并思路

- 老师认为 **Realtime 与 History 模块内容有重复**，希望**继承/合并**：例如在 Realtime 加小入口，减少割裂感。  
- **Replay**：可选文件；未选文件时 **Play 禁用**；选中后可播放，且**允许对同一文件重复播放**（类似已有 replay 行为）。  
- **配置**：Realtime 走现场 `config.json`；Replay 走 **`config_local.json`**（若存在），与现有 `process_control.start_main_service` 分支一致。

### 5. KPI 与展示（指标清单 — 可执行）

**System KPI（先稳定这些，勿堆杂项）**

- Throughput  
- Finished（完成数）  
- Scrap  
- WIP  
- Avg Flow Time  
- **Runtime**：系统运行时长（**不要用「observation time」当面向用户的名称**；若代码里仍用 observation 窗口，界面上用_runtime 或附一行说明）  

**Station KPI**

- **Utilization**（每站）  
- **Queue**（后续可加）  

其它：**Conformance / WIP 历史折线图** — 现阶段可不做（会议原话倾向先不做）。

- **Station 明细卡片**：若已表达 Idle/Loading/Processing…，与纯文字 state **去重**。  
- **KPI tick / 刷新间隔**：与 **Runtime**、观测窗口**分开写标签**，避免混为一个控件。  
- **WIP / Utilization（概念）**：WIP 非固定长度窗口；存在「不算在制」的区间，与 `kpi_calculator` 定义对齐即可。

### 6. 刷新与「跑完一轮仍像上一轮」

- **首选（与老师意图一致，实现简单）**：每次 **Start / Replay** 时，在应用侧 **清空与本轮相关的 `st.session_state`（或统一 session_id）**，并**重新订阅/拉取**数据；用户**再点一次 Start** 即等价于一次完整刷新 —— **不必先做一个复杂的全局 Reset 按钮**。  
- **备选**：若 Streamlit 仍出现脏展示，再增加**显式的「清空视图 / Rerun」**作为补救。

### 7. Part trace / 全流程展示

- **不仅选单个 part**：支持 **所有 part** 一起在列表/图上展示（与 Digital Twin 多 part 方案衔接）。  
- **表示形式**：**序列（sequence）**，不要当 **树（tree）**；允许 **loop / rework**、同一 station **多次经过**。  
- **简单版**：每 part 一行路径，例如 `Part 1: ST11 → ST21 → ST31 → ST61`。  
- **加分版**：横向 **进度条/时间轴**，标出「当前所在」工位。  
- **到过某站后淡化/清空**等视觉规则 — 与 FINISH/SCRAP 事件对齐后再定。

### 8. KPI + Trace 页面组织（减少散乱跳转）

- **方案 1（推荐）**：单一 **Dashboard** 页 — **上 KPI、下 Trace**（一屏尽量看完）。  
- **方案 2**：同一页内 **Tab** —「KPI」|「Trace」。  
- 核心原则：**尽量少页跳转**；与控制无关的内容不要堆在 Main Page。

### 9. Conformance / Workflow 分类（中长期）

- 路径分为 **Normal** vs **Scrap** vs **Rework** 等，便于展示与论文叙事。  
- 经某检查站回主线仍可能算 normal；scrap/rework 为异常类。

### 10. 仿真（Simulation）— 本阶段**忽略实现**

- ARENA license、SimPy、离散事件、优先队列等：**留在「未来扩展」**，**现在不写进本周交付范围**。  
- **论文一句即可**：The system is designed to support simulation and further predictive analysis as future work.  
- （技术备忘仍可参考：重计算服务独立进程、占位入口 — 见下周再动。）

### 11. 物理线与背景

- 线体背景：**电动汽车马达转子类装配**抽象；各 station 对应工序。  
- **时间同步**已做；电机/送料等需细调；长跑前小步进验证，避免堆料。

---

## 附、老师手绘架构图（综合版：会议 + GPT 归纳 + 与你产品结构的对应）

> **仅作概念对齐**；**不写代码**。下列定义可直接用于 **答辩 / 面试 / 论文「系统设计」小节**。

### A. Normal / Scrap / Rework：一句话结论

**这是 Conformance Check（流程合规 / 路径质量分析）里的分类，不是 KPI。**

对象由 **Event × Station × Part** 组成：一条 **Part 的路径**即工站序列（及 SCRAP 等终止）。老师要对 **路径质量 / 与预期的关系** 打标签，属 **Process Mining 里 conformance、偏差（deviance）一类结果的通俗三分法**。

### B. 三种类型定义（建议写进论文/说明书的版本）

| 类型 | 含义 | 路径示例（示意） |
|------|------|------------------|
| **Normal Flow** | 主线一次走完：**无返工回路**、未报废 | ST11 → ST21 → ST31 → ST61 |
| **Rework Flow** | **中途回退再加工**：路径中出现 **loop**，再次进入 **先前到过的工位** | ST11 → ST21 → ST31 → ST21 → ST31 → ST61 |
| **Scrap Flow** | **未完成既定主线**即以报废/退出收束 | ST11 → ST21 → ST31 → SCRAP（或日志中等价终止） |

**实现**：第一轮可用 **事件规则**（SCRAP、重复访问某站等）归类；日后可接 **参考模型 / 更正式的 conformance 算法**。

**老师要强调的能力**：Digital Twin **不止是「看数据 / 看在哪」**，还要表达 **「相对预期是否合规、属于哪类流程结局」**。

### C. Part Track（重点；图左上角矩阵）

**Part Track = 对每个 Part 同时交代：当前在哪、走过哪、（可选）流程类型。**

| 能力 | 含义 | 示例 |
|------|------|------|
| **当前** | *Where is it now* | Part 1 → ST31 |
| **历史** | *Where has it been* | ST11 → ST21 → ST31 |
| **流程类型** | 与 §B 同源 | Normal / Rework / Scrap |

**手绘 Part × Station 小格** = **实时进度矩阵**（✔ 已过、⏳ 当前等），例如：

| Part | ST11 | ST21 | ST31 |
|------|------|------|------|
| P1 | ✔️ | ✔️ | ⏳ |
| P2 | ✔️ | ✔️ | ✔️ |

**展示方案**：**方案 A** 上表；**方案 B** 横向 **进度条 + flow**，标 **current**，如  
Part 1: [ST11] → [ST21] → [ST31] → [ST61]，下方 **↑ current**。

**产品结构（与 §〇 一致）**：Part Track **放在 Digital Twin 子页**（与 layout **同页分区或 Tab**：地图 | Part track | Conformance）；**不用树**；多 part、同一站可多次（rework）。

### D. 整幅手绘怎么读（含 GPT「系统蓝图」说法）

| 区域 | 含义 | 本周 |
|------|------|------|
| **Main Service · 控制** | Start / Stop、Replay | ✅ 首页全局控制（互斥逻辑同上） |
| **Main Service · 监控（概念）** | 图里 **KPI、DT、CC** 常画成一旁 | **概念**：同属主服务上的监控。**实现**：仍可 **KPI 独立子页** + **Twin 子页**（内聚地图、Part track、三分类型/Conformance），**不必**为了像草图而把 KPI 塞进 Twin 代码目录 —— 草图表达「能力集合」，侧栏几个入口由你产品决定。 |
| **DT 核心（理解）** | Trace、**Part Track**、**Conformance（含 Normal/Rework/Scrap）** | Twin 页内聚合；标签与 Part track **同一数据源** 即可。 |
| **Simulation / Arena / SimPy / Prediction / Deadlock / RL…** | 扩展与论文叙事 | ❌ **现在不做** |

**论文可用一句（英文）**：  
*The system is designed to support simulation-based analysis and optimization as future extensions.*

### E. 与 §一.5–§一.9 的边界

- **KPI**（吞吐、WIP、utilization…）≠ **三分类型**；后者属 **Conformance / DT 展示**。  
- **Conformance 折线图**可后做；**三类标签** 与折线图 **不是一回事**，标签可 **先做轻量版**。  
- **可再确认老师**：检查站后回主线是否一律算 **Normal**（会议提过），**规则定稿** 时写死一版。

---

## 二、可执行 backlog（与「〇」对齐的步骤）

| Step | 优先级 | 内容 |
|------|--------|------|
| **1** | P0 | **Main Page**：Start / Stop、Mode（Real-time / Replay）、Replay 开关 + 文件选择、状态展示；**互斥逻辑**表实现到控件层。 |
| **2** | P0 | **KPI 页**：拆 **System KPI** + **Station KPI**；指标以 §一.5 清单为第一版；Conformance 折线不做。 |
| **3** | P1 | **Trace 页**：多 part、**序列**展示；先做简单路径行，再加进度条式 UI。 |
| **4** | P1 | **Dashboard 组织**：KPI + Trace **同页（上/下）或 Tab**；History/Realtime 入口与主页模式联动、减少重复。 |
| **5** | P1 | **刷新**：Start/Replay 路径上 **清 session + 重拉数据**；必要时再加显式清空。 |
| — | 远期 | Simulation / SimPy / 重服务 — **不排进当前 sprint**。 |

（与旧表对应：P0 主导航 + 互斥 = Step 1；KPI 文案 = Step 2；Trace = Step 3；合并 History = Step 4 的一部分。）

---

## 三、与你此前任务的对照

- **Digital Twin 全 part**：对应 §一.7 + `twin_layout` / Neo4j `get_session_parts_latest_locations`。  
- **主页面控制 Replay**：对应 §〇、`process_control` 模式分支。  
- **「两个文件」**：会议未明确文件名；若指 `week5.md` + `week6.md` 或上传目标，以老师邮件/群里为准。

---

## 四、待与老师一句确认

- History 与 Realtime **合并到什么程度**（仅导航 vs 单页双栏）。  
- **System KPI / Station KPI**：两个子页 vs **同一 Dashboard 内上下两块**（§一.8 方案 1 vs 2）。  
- **Runtime** 的精确定义（墙钟从 Start 起算 vs 与 `session_id` 对齐）是否在论文里要写一句。

---

## 五、向老师汇报（英文一句，可选用）

> I'm restructuring the app into a **main control page** plus modular sub-pages (KPI and trace). The main page owns start/stop/replay and mode, with mutual exclusion between real-time and replay; sub-pages focus on visualization. This sprint I will **stabilize System/Station KPIs and sequence-based trace**, and treat **simulation as future extension**.

---

## 六、接下来要做的步骤（与仓库对齐的实现顺序）

> 现状：`app.py` / `main.py` 直接 `switch_page` 到 `pages/01_Realtime.py`，**控制与 KPI 都堆在 01**。目标：**首页仅入口 + 全局控制**，KPI / Twin 各在子页。

### 阶段 A — 首页壳 + 控制下沉（P0，先做）

1. **改入口**  
   - `streamlit_app/app.py`、`main.py`：不再直达 `01_Realtime`；改为渲染 **Home**（同一文件内写 Home，或新建 `pages/00_Home.py` 并把入口 `switch_page` 改到 Home —— 以 Streamlit 多页规范为准，保证侧栏里 **Home 在第一项**）。  
2. **把 `01_Realtime.py` 顶部整块 Control（Start/Stop、programs、Replay 相关）迁到 Home**  
   - 子页 **不再**放「会改全局进程」的按钮（避免两处都能 Start）。  
3. **用 `st.session_state` 统一「单一真相」**（建议键名一次性定好）  
   - `mode`: `realtime` | `replay`；与现有 `process_control` / `mqtt_backend.switch_config_file` 对齐。  
   - `replay_file`、可选 `replay_running` / `line_running`（或复用 `recording.is_recording()` + main_service 探活，以你现有 API 为准）。  
4. **互斥**  
   - 线体 / realtime 已跑：禁用 Replay 启动；Replay 模式：禁用 **Start system**（或弹出说明）。在 Home 的 `st.button`/`widget` 上 `disabled=` 体现。  
5. **入口区**（仅占位 + `st.page_link` / 导航）  
   - **KPI Dashboard** → 指向合并后的 KPI 子页（可先仍链到 `01_Realtime` 改完名再调）。  
   - **Digital Twin** → `pages/05_Digital_Twin.py`。  
   - **Simulation** → `disabled` 或文案 Coming soon。  

### 阶段 B — KPI 子页定型（P0）

6. **将原 01 的展示部分拆成「System KPI + Station KPI」**（`ui_kpi_display.py` 已基本可复用；补 **Runtime** 文案，去掉含糊的 observation 用语）。  
7. **与 Replay 共用数据源**  
   - Home 选好 mode + 文件后，KPI 子页读同一 `session_state`（realtime → MQTT/现有快照；replay → 与 `02_History` 一致的 log/session 逻辑）。  
8. **`02_History.py`**  
   - 回放 **控制**迁走后，若只剩选文件 + 图表，与 KPI **合并或删重复**（保留一条回放数据通路即可）。

### 阶段 C — Digital Twin 打包 Trace + Conformance（P1）

9. **`05_Digital_Twin.py`** 内用 **Tab 或上下分栏**：Layout | Part trace（序列）| Conformance（先简版）。  
10. **`03_Part_Trace.py` / `04_Conformance.py`**  
   - 逻辑迁入 Twin 后：侧栏隐藏或页面内 `st.switch_page` 重定向到 Twin，避免用户迷路。  
11. **Trace**：多 part、序列字符串或进度条（先字符串后美化）。

### 阶段 D — 刷新与收尾（P1）

12. **每次 Home 上成功 Start / 开始 Replay**：清除与上一轮相关的 `session_state`（KPI 缓存键、session_id 等），必要时 `st.rerun()`。  
13. **侧栏**：已去掉顶部横向 `ui_quick_nav`，改用 Streamlit 默认左侧多页导航；`ui_sidebar.py` 仍负责 MQTT/Neo4j 提示。  

### 阶段 E（不做）

- Simulation 实现；Conformance 大图表；Arena/SimPy。

**建议本周 closure**：完成 **阶段 A + B 的大半**（能演示：首页控制 + 进 KPI 看实时指标）；Twin 内 Trace 合并可跟下周或并行。

---

## 七、Week 6 完成记录（2026-04-01）

### 已落地（代码）

| 项 | 说明 |
|----|------|
| **Main · Control 首页** | `app.py` / `main.py` 直接渲染 `ui_home.render()`，不再 `switch_page` 进 01。 |
| **`ui_home.py`** | 全局 Control + Deploy；`start_programs` 状态；**Dashboard 入口**（KPI / Twin / History）；**Simulation** 占位按钮。 |
| **互斥（首版）** | `run_mode == replay` 或 `replay_proc` 存活时：Home 上 **Start system / programs / Stop programs / Upload / Shutdown** 等禁用，并提示先停 replay。 |
| **KPI 子页** | `01_Realtime.py` 改为 **KPI Dashboard**，去掉控制区；**replay 时也展示 KPI**（仅警告 + History 链接）；保留 WIP 告警。 |
| **History** | **正在 physical recording 时禁止 Start replay**，与 Home 互斥一致。 |
| **导航** | 顶部横向菜单已移除；依赖左侧栏切换页面（`app.py` / `main.py` 入口不变）。 |
| **Digital Twin** | **三 Tab**：Layout & map | Part track | Conformance；后两 Tab 暂为说明 + 链到 03 / 04（后续可内嵌）。 |

### 仍属后续迭代（未声称本周 closure）

- **阶段 B**：`ui_kpi_display` 中 **Runtime** 文案与 observation 彻底分离（可再改一轮）。  
- **阶段 C**：Part track **矩阵 / 多 Part** 迁入 Twin Tab；03 / 04 **逻辑合并**进 05。  
- **阶段 D**：Start / Replay 成功后的 **session 清理**策略可再加强。  
- **CSV 回放控制台**：仍主要在 **History**；未整页迁入 Home（减轻本次 diff）。

### 如何运行

```bash
python -m streamlit run streamlit_app/app.py
```

（或 `main.py` 入口。）
