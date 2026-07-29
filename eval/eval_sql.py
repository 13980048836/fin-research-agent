"""
eval/eval_sql.py — SQL 生成准确率评估

指标:
  - 执行成功率:   生成的 SQL 能否成功执行
  - 结果匹配率:   执行结果是否与 ground truth SQL 结果一致
  - 表命中率:     是否用对了表

对比方式:
  - LLM 生成 SQL → 执行 → 与 ground truth SQL 结果对比

使用:
  python -m eval.eval_sql
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_config


def load_benchmark(path: Path = None) -> list:
    """加载 SQL 类 benchmark"""
    if path is None:
        path = Path(__file__).parent / "benchmark.jsonl"
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return [it for it in items if it["type"] == "sql"]


def execute_ground_truth_sql(sql: str, db_path: str) -> tuple:
    """执行 ground truth SQL，返回 (成功, 结果)"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return True, rows
    except Exception as e:
        return False, str(e)


def _normalize_rows(rows) -> list:
    """将查询结果统一转为 tuple 列表（处理 dict/tuple/Row 等格式）"""
    normalized = []
    for row in rows:
        if isinstance(row, dict):
            values = list(row.values())
        elif isinstance(row, (list, tuple)):
            values = list(row)
        else:
            values = [row]
        # float 精度统一到 2 位（兼容 ROUND 函数差异）
        clean = []
        for v in values:
            if isinstance(v, (float, int)):
                clean.append(round(float(v), 2))
            elif isinstance(v, str):
                # 尝试把数字字符串也转一下
                try:
                    clean.append(round(float(v), 2))
                except ValueError:
                    clean.append(v.strip())
            else:
                clean.append(v)
        normalized.append(tuple(clean))
    return normalized


def results_match(generated_rows: list, truth_rows: list) -> bool:
    """比较两份查询结果是否一致（忽略行顺序，float 容差 2 位小数）"""
    if not isinstance(generated_rows, list) or not isinstance(truth_rows, list):
        return False
    if len(generated_rows) != len(truth_rows):
        return False

    gen_set = set(_normalize_rows(generated_rows))
    truth_set = set(_normalize_rows(truth_rows))
    return gen_set == truth_set


async def run() -> dict:
    """运行 SQL 评估"""
    print("=" * 70)
    print("📊 SQL 生成准确率评估")
    print("=" * 70)

    queries = load_benchmark()
    print(f"📝 加载 benchmark: {len(queries)} 条 SQL 问题")
    print()

    cfg = get_config()
    db_path = str(BASE_DIR / cfg.database.path) if not Path(cfg.database.path).is_absolute() else cfg.database.path

    # 先执行所有 ground truth SQL，确保 benchmark 有效
    print("  预检: 执行 ground truth SQL...")
    valid_queries = []
    for q in queries:
        ok, rows = execute_ground_truth_sql(q["expected_result_sql"], db_path)
        if ok:
            q["_truth_rows"] = rows
            valid_queries.append(q)
        else:
            print(f"    ⚠️  {q['id']} ground truth SQL 失败: {rows}")
    print(f"  有效 benchmark: {len(valid_queries)}/{len(queries)}")
    print()

    if not valid_queries:
        print("❌ 无有效 benchmark")
        return {}

    # 初始化 SQL Agent
    from agents.sql_agent import SQLAgent
    agent = SQLAgent(config=cfg)

    total = len(valid_queries)
    exec_success = 0      # 执行成功
    result_match = 0      # 结果匹配
    table_hit = 0         # 表命中

    print(f"{'ID':<6} {'问题':<30} {'执行':>6} {'匹配':>6} {'表命中':>6}")
    print("-" * 70)

    for q in valid_queries:
        query_text = q["query"]
        short_q = query_text[:28] + ".." if len(query_text) > 28 else query_text

        # LLM 生成 SQL 并执行
        try:
            result = await agent.run(query=query_text)
            generated_sql = result.metadata.get("sql", "") if result.success else ""
            gen_rows = result.metadata.get("raw_rows", []) if result.success else []

            # 检查执行成功
            exec_ok = result.success and bool(generated_sql)
            if exec_ok:
                exec_success += 1

            # 检查结果匹配
            match_ok = False
            if exec_ok and gen_rows:
                match_ok = results_match(gen_rows, q["_truth_rows"])
                if match_ok:
                    result_match += 1

            # 检查表命中
            table_ok = False
            if generated_sql:
                table_ok = any(t.lower() in generated_sql.lower() for t in q["expected_tables"])
                if table_ok:
                    table_hit += 1

            status_exec = "✅" if exec_ok else "❌"
            status_match = "✅" if match_ok else "❌"
            status_table = "✅" if table_ok else "❌"
            print(f"{q['id']:<6} {short_q:<30} {status_exec:>6} {status_match:>6} {status_table:>6}")

        except Exception as e:
            print(f"{q['id']:<6} {short_q:<30} {'ERR':>6} {'-':>6} {'-':>6}  {e}")

    print()
    print("-" * 70)
    print(f"{'指标':<20} {'值':>10} {'比例':>10}")
    print("-" * 70)
    print(f"{'执行成功率':<20} {exec_success:>10} {exec_success/total:>10.2%}")
    print(f"{'结果匹配率':<20} {result_match:>10} {result_match/total:>10.2%}")
    print(f"{'表命中率':<20} {table_hit:>10} {table_hit/total:>10.2%}")
    print(f"{'总数':<20} {total:>10}")

    metrics = {
        "exec_success_rate": exec_success / total,
        "result_match_rate": result_match / total,
        "table_hit_rate": table_hit / total,
        "count": total,
    }
    print()
    return metrics


if __name__ == "__main__":
    asyncio.run(run())
