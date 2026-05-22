# 批处理：按 config 重建 Event 上 DF_PROCESS，并在「全库」模式下顺带重建
# Station–Station / Entity–Entity 上的派生 DF（与 main_service 写入规则一致）。
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import neo4j_writer


def main():
    n = neo4j_writer.rebuild_df_process_graph()
    print("DF_PROCESS MERGE 次数（拆图后按轨迹重连）: {}".format(n))
    neo4j_writer.close()


if __name__ == "__main__":
    main()
