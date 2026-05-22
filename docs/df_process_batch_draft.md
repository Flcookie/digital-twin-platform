# DF_PROCESS 批处理草稿（week5 · A5 加分项）

> **未接入 `neo4j_writer`**：仅供论文/答辩演示「工艺链 vs 原始 DF」思路。执行前请在不重要库上试验。

## 思路

在已有 **DF**（同 Part 相邻 Event）上，按 **Activity.name** 白名单滤掉传送/等待类噪声，再合并为 **`DF_PROCESS`**。白名单需与老师工艺流（LOAD / PROCESS / UNLOAD…）对齐。

## 示例 Cypher（一次性批处理）

参数：`$session_id`；活动列表按现场改。

```cypher
MATCH (e1:Event)-[:IN_SESSION]->(:Session {id: $session_id})
MATCH (e1)-[:DF]->(e2:Event)
MATCH (e1)-[:OF_ACTIVITY]->(a1:Activity)
MATCH (e2)-[:OF_ACTIVITY]->(a2:Activity)
MATCH (e1)-[:ACTS_ON]->(p:Entity)
MATCH (e2)-[:ACTS_ON]->(p)
WHERE a1.name IN ['START','LOAD','PROCESS','UNLOAD','FINISH']
  AND a2.name IN ['START','LOAD','PROCESS','UNLOAD','FINISH']
MERGE (e1)-[r:DF_PROCESS]->(e2)
RETURN count(r) AS merged_edges
```

**注意**：重复运行可能重复计数 `merged_edges`；生产环境宜加 **唯一性约束** 或用 `apoc` 去重后再 MERGE。
