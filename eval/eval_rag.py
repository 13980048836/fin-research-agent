"""
eval/eval_rag.py — RAG 检索质量评估

指标:
  - Recall@k:    top-k 中命中期望文档的比例
  - Precision@k: top-k 中相关文档比例
  - MRR:         第一个命中文档的倒数排名均值
  - Hit@k:       至少命中一个的比例

对比三种检索策略:
  1. 纯向量检索 (FAISS only)
  2. 纯 BM25 检索
  3. 混合检索 (BM25 + 向量 + RRF + 重排)

使用:
  python -m eval.eval_rag          # 跑全部
  python -m eval.eval_rag --top-k 5  # 指定 k
"""
import argparse
import json
import sys
from pathlib import Path

# 项目根目录加入 path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_config


def load_benchmark(path: Path = None) -> list:
    """加载 benchmark 数据集"""
    if path is None:
        path = Path(__file__).parent / "benchmark.jsonl"
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return [it for it in items if it["type"] == "rag"]


def _doc_source(doc) -> str:
    """从 LangChain Document 提取文件名（basename）"""
    if hasattr(doc, "metadata") and "source" in doc.metadata:
        return Path(doc.metadata["source"]).name
    return ""


def _doc_text(doc) -> str:
    """提取文档文本"""
    if hasattr(doc, "page_content"):
        return doc.page_content
    return str(doc)


def eval_vector_only(queries, vsm, top_k: int) -> list:
    """纯向量检索"""
    results = []
    store = vsm.store if vsm.is_built else None
    if store is None:
        return [None] * len(queries)
    for q in queries:
        try:
            docs = store.similarity_search(q["query"], k=top_k)
            results.append([_doc_source(d) for d in docs])
        except Exception:
            results.append([])
    return results


def eval_bm25_only(queries, hr, top_k: int) -> list:
    """纯 BM25 检索"""
    results = []
    for q in queries:
        try:
            bm25_res = hr._bm25_search(q["query"], top_k)
            results.append([_doc_source(item["doc"]) for item in bm25_res])
        except Exception:
            results.append([])
    return results


def eval_hybrid(queries, hr, top_k: int, use_mmr: bool = False, use_rerank: bool = False) -> list:
    """混合检索 (BM25 + 向量 + RRF，可选重排/MMR)"""
    results = []
    for q in queries:
        try:
            search_results = hr.search(
                q["query"], top_k=top_k,
                use_mmr=use_mmr, use_rerank=use_rerank,
            )
            results.append([_doc_source(item["doc"]) for item in search_results])
        except Exception:
            results.append([])
    return results


def compute_metrics(predictions: list, ground_truth: list, top_k: int) -> dict:
    """
    计算检索指标

    Args:
        predictions: 每个问题的 top-k 文件名列表
        ground_truth: 每个问题的期望文件名列表
        top_k: k 值

    Returns:
        dict: recall, precision, mrr, hit_rate
    """
    total = len(ground_truth)
    if total == 0:
        return {"recall": 0, "precision": 0, "mrr": 0, "hit_rate": 0, "count": 0}

    recall_sum = 0
    precision_sum = 0
    mrr_sum = 0
    hit_count = 0

    for preds, expected in zip(predictions, ground_truth):
        if preds is None:
            preds = []
        expected_set = set(expected)
        preds_set = set(preds[:top_k])

        hits = expected_set & preds_set
        recall_sum += len(hits) / len(expected_set) if expected_set else 0
        precision_sum += len(hits) / min(top_k, len(preds)) if preds else 0

        # MRR: 第一个命中文档的倒数排名
        for rank, p in enumerate(preds[:top_k], 1):
            if p in expected_set:
                mrr_sum += 1.0 / rank
                break

        # Hit@k
        if hits:
            hit_count += 1

    return {
        "recall": recall_sum / total,
        "precision": precision_sum / total,
        "mrr": mrr_sum / total,
        "hit_rate": hit_count / total,
        "count": total,
    }


def run(top_k: int = 5) -> dict:
    """运行 RAG 评估"""
    print("=" * 70)
    print("📊 RAG 检索质量评估")
    print("=" * 70)

    # 加载 benchmark
    queries = load_benchmark()
    print(f"📝 加载 benchmark: {len(queries)} 条 RAG 问题")

    ground_truth = [q["expected_sources"] for q in queries]

    # 初始化检索器
    from vector_store import get_vector_store
    from hybrid_retriever import HybridRetriever

    cfg = get_config()
    vsm = get_vector_store()
    if not vsm.is_built:
        print("❌ 向量索引未构建，请先运行: python init_data.py")
        return {}

    hr = HybridRetriever(vector_store=vsm, config=cfg)
    print(f"🔧 向量库: {vsm.is_built} | BM25: {hr._bm25 is not None}")
    print(f"🎯 评估 top_k = {top_k}")
    print()

    # 五种策略
    strategies = {}

    print("  [1/5] 纯向量检索 (FAISS only)...")
    strategies["纯向量"] = eval_vector_only(queries, vsm, top_k)

    print("  [2/5] 纯 BM25 检索...")
    strategies["纯BM25"] = eval_bm25_only(queries, hr, top_k)

    print("  [3/5] 混合检索 (RRF 融合，无重排/MMR)...")
    strategies["混合(RRF)"] = eval_hybrid(queries, hr, top_k, use_mmr=False, use_rerank=False)

    print("  [4/5] 混合检索 (RRF + MMR 去重)...")
    strategies["混合+MMR"] = eval_hybrid(queries, hr, top_k, use_mmr=True, use_rerank=False)

    print("  [5/5] 混合检索 (RRF + 重排 + MMR，完整链路)...")
    strategies["混合(完整)"] = eval_hybrid(queries, hr, top_k, use_mmr=True, use_rerank=True)

    # 计算指标
    print()
    print(f"{'策略':<16} {'Recall@%d' % top_k:>10} {'Precision@%d' % top_k:>14} {'MRR':>8} {'Hit@%d' % top_k:>10}" % ())
    print("-" * 74)

    results = {}
    for name, preds in strategies.items():
        m = compute_metrics(preds, ground_truth, top_k)
        results[name] = m
        print(f"{name:<16} {m['recall']:>10.2%} {m['precision']:>14.2%} {m['mrr']:>8.4f} {m['hit_rate']:>10.2%}")

    # 提升对比
    print()
    if "纯向量" in results and "混合(RRF)" in results:
        vec_recall = results["纯向量"]["recall"]
        hybrid_recall = results["混合(RRF)"]["recall"]
        if vec_recall > 0:
            uplift = (hybrid_recall - vec_recall) / vec_recall * 100
            print(f"📈 混合(RRF) vs 纯向量: Recall@%d 提升 %+.1f%% (%.2f%% → %.2f%%)" % (
                top_k, uplift, vec_recall * 100, hybrid_recall * 100
            ))

    print()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 检索质量评估")
    parser.add_argument("--top-k", type=int, default=5, help="top-k 值 (默认 5)")
    args = parser.parse_args()
    run(top_k=args.top_k)
