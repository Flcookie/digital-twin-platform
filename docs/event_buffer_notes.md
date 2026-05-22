# event_buffer：时间窗与 flush（答辩 / 论文备用）

## `window_ms` 在做什么

`EventBuffer`（`event_buffer.py`）在内存里按时间戳维护有序事件。每次 `add_and_flush(event)` 时，在**已知最新事件时间**的前提下，把「时间戳足够旧、不可能再与窗口内新事件乱序合并」的事件**安全 flush** 出去，交给 `neo4j_writer` 等下游批量写库。

- **通俗说**：短暂保留一个小窗口，吸收**秒级时钟偏差或网络到达顺序**带来的「假乱序」；窗口太窄可能过早写出、仍然乱序；太宽则延迟增大。
- **实现语义（见代码）**：以当前缓冲中最大时间戳 `max_ts` 为参考，`cutoff = max_ts - window_ms/1000`；时间戳 `< cutoff` 的事件视为已稳定，可输出（并与 KPI 计算等链路对齐）。

## 与 KPI / Neo4j

Flush 出的批次顺序在设计上与缓冲内时间序一致；`neo4j_writer` 在同一 Session 下还会维护 **DF / NEXT** 等关系。若现场调试「少事件 / 序错乱」，应同时核对：**MQTT 时间戳来源、`window_ms`、站点时钟**是否与论文叙述一致。
