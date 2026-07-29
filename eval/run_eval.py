"""
eval/run_eval.py — 一键评估入口

运行 RAG + SQL 全套评估，输出指标表格 + 保存结果到 eval/results.json

使用:
  python -m eval.run_eval              # 跑全套
  python -m eval.run_eval --rag-only   # 只跑 RAG
  python -m eval.run_eval --sql-only   # 只跑 SQL
  python -m eval.run_eval --top-k 5    # 指定 RAG top-k
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main():
    parser = argparse.ArgumentParser(description="金融投研助手 - 评估体系")
    parser.add_argument("--rag-only", action="store_true", help="只跑 RAG 评估")
    parser.add_argument("--sql-only", action="store_true", help="只跑 SQL 评估")
    parser.add_argument("--top-k", type=int, default=5, help="RAG top-k 值")
    parser.add_argument("--save", action="store_true", default=True, help="保存结果到 results.json")
    args = parser.parse_args()

    run_rag = not args.sql_only
    run_sql = not args.rag_only

    results = {
        "timestamp": datetime.now().isoformat(),
        "top_k": args.top_k,
    }

    if run_rag:
        from eval import eval_rag
        print()
        results["rag"] = eval_rag.run(top_k=args.top_k)

    if run_sql:
        from eval import eval_sql
        print()
        results["sql"] = asyncio.run(eval_sql.run())

    # 汇总
    print()
    print("=" * 70)
    print("📋 评估汇总")
    print("=" * 70)
    if "rag" in results and results["rag"]:
        rag = results["rag"]
        if "混合检索" in rag:
            h = rag["混合检索"]
            print(f"RAG (混合检索, top-{args.top_k}):")
            print(f"  Recall@{args.top_k}    = {h['recall']:.2%}")
            print(f"  Precision@{args.top_k} = {h['precision']:.2%}")
            print(f"  MRR         = {h['mrr']:.4f}")
            print(f"  Hit@{args.top_k}       = {h['hit_rate']:.2%}")
    if "sql" in results and results["sql"]:
        sql = results["sql"]
        print(f"SQL:")
        print(f"  执行成功率 = {sql['exec_success_rate']:.2%}")
        print(f"  结果匹配率 = {sql['result_match_rate']:.2%}")
        print(f"  表命中率   = {sql['table_hit_rate']:.2%}")
    print()

    # 保存
    if args.save and (results.get("rag") or results.get("sql")):
        out_path = Path(__file__).parent / "results.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f"💾 结果已保存: {out_path}")


if __name__ == "__main__":
    main()
