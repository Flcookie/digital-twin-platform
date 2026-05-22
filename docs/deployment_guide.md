# LEGO Factory 部署与调试（Streamlit + main_service）

## 环境

- Python 3.10+
- 依赖：`pip install -r requirements.txt`
- Neo4j（如需 Part Trace / 写库）：`config.json` 中配置 `neo4j.uri` 等
- MQTT broker：物理现场或本地（如 `config_local.json` + HiveMQ 等）

## 形态 B（推荐）

### 终端 1 — main_service

```powershell
cd c:\Users\beira\lego-factory
.\.venv\Scripts\Activate.ps1
$env:CONFIG_FILE = "config.json"
python main_service.py
```

或在 Streamlit **06_Control** 中启动 **main_service**。

### 终端 2 — Streamlit

```powershell
cd c:\Users\beira\lego-factory
.\.venv\Scripts\Activate.ps1
$env:CONFIG_FILE = "config.json"
python -m streamlit run streamlit_app\app.py
```

浏览器：**http://localhost:8501**（勿用 `file://`）

Windows 也可双击 **`run_web.bat`**。

## 端口

- Streamlit 默认 **8501**；被占用时用 **`run_web_8001.bat`** → **8502**
- 排查：`netstat -ano | findstr ":8501"`

## 常见问题

| 现象 | 处理 |
|------|------|
| Neo4j 连接失败 | 确认数据库已启动；核对 `config` 中 uri/账号；`.env` 可覆写密码 |
| KPI 一直空 | 确认 **main_service** 在跑且能连同一 MQTT；**01_Realtime** 侧栏刷新间隔仅影响 UI |
| 回放无数据 | **02_History**：需 **main_service** 已运行；本地 broker 时在 **06_Control** 切 **config_local** 或勾选自动切换 |
| Graphviz 图不显示 | **04_Conformance** 示意流程序可选装系统 [Graphviz](https://graphviz.org/) |

## 索引

首次启动首页会尝试 `neo4j_backend.ensure_indexes()`（失败不阻塞）。亦可手工在 Neo4j Browser 执行 `改进2.md` 中的索引语句。
