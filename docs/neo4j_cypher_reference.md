# Neo4j Cypher reference (Streamlit / part trace)

Queries mirror `streamlit_app/neo4j_backend.py` (same intent as legacy `web_api` part flow).

## List recent sessions（UI 下拉 / 多 Run 对比）

Parameters: `$lim`.

```cypher
MATCH (s:Session)
RETURN s.id AS id, s.description AS description, s.start_time AS start_time
ORDER BY s.start_time DESC, s.id DESC
LIMIT $lim
```

## Latest session（单键取值）

与 `get_latest_session_info()` 一致：按 `start_time` 再按 `id`。

```cypher
MATCH (s:Session)
RETURN s.id AS session_id, s.description AS session_description
ORDER BY s.start_time DESC, s.id DESC
LIMIT 1
```

## Part 视角 DF 边（`neo4j_writer` 写入的相邻 Event）

用于核对「同一 Part 上 writer 连好的 directly-follows」；参数：`$session_id`, `$part_id`。

```cypher
MATCH (e1:Event)-[:IN_SESSION]->(:Session {id: $session_id})
MATCH (e1)-[:ACTS_ON]->(:Entity {sysId: $part_id})
MATCH (e1)-[:DF]->(e2:Event)
MATCH (e1)-[:OF_ACTIVITY]->(a1:Activity)
MATCH (e2)-[:OF_ACTIVITY]->(a2:Activity)
RETURN e1.timestamp AS t1, a1.name AS from_act, a2.name AS to_act, e2.timestamp AS t2
ORDER BY e1.timestamp
```

## Session 内全局交织顺序（NEXT）

仅作附录：相邻 Event 的全局序（不区分 Part）。参数：`$session_id`。

```cypher
MATCH (e1:Event)-[:IN_SESSION]->(:Session {id: $session_id})
MATCH (e1)-[:NEXT]->(e2:Event)
MATCH (e1)-[:OF_ACTIVITY]->(a1:Activity)
RETURN e1.timestamp AS t1, a1.name AS act1, e2.timestamp AS t2
ORDER BY e1.timestamp
LIMIT 200
```

## Part flow — one part (ordered steps)

Parameters: `$session_id`, `$part_id`.

```cypher
MATCH (e:Event)-[:IN_SESSION]->(sess:Session {id: $session_id})
MATCH (e)-[:OCCURRED_AT]->(s:Station)
MATCH (e)-[:ACTS_ON]->(en:Entity)
MATCH (e)-[:OF_ACTIVITY]->(a:Activity)
WHERE en.sysId = $part_id
WITH en.sysId AS part_id, s.sysId AS component_id, a.name AS activity, e.timestamp AS ts
ORDER BY ts
WITH part_id, collect({component_id: component_id, activity: activity, time: ts}) AS steps
RETURN part_id, steps
```

## Part flow — top parts by step count

Parameters: `$session_id`.

```cypher
MATCH (e:Event)-[:IN_SESSION]->(sess:Session {id: $session_id})
MATCH (e)-[:OCCURRED_AT]->(s:Station)
MATCH (e)-[:ACTS_ON]->(en:Entity)
MATCH (e)-[:OF_ACTIVITY]->(a:Activity)
WITH en.sysId AS part_id, s.sysId AS component_id, a.name AS activity, e.timestamp AS ts
ORDER BY part_id, ts
WITH part_id, collect({component_id: component_id, activity: activity, time: ts}) AS steps
RETURN part_id, steps
ORDER BY size(steps) DESC
LIMIT 50
```

## Station events (latest session)

Parameters: `$session_id`, `$sid` (station `sysId`), `$lim`.

```cypher
MATCH (e:Event)-[:IN_SESSION]->(sess:Session {id: $session_id})
MATCH (e)-[:OCCURRED_AT]->(st:Station {sysId: $sid})
MATCH (e)-[:OF_ACTIVITY]->(a:Activity)
MATCH (e)-[:ACTS_ON]->(en:Entity)
RETURN a.name AS activity, en.sysId AS part_id, e.timestamp AS ts
ORDER BY e.timestamp DESC
LIMIT $lim
```

## Clear graph (admin)

Same pattern as control topic handling; run only in trusted environments.

```cypher
MATCH (n) DETACH DELETE n
```
