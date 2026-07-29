import json
import subprocess
import sys
from pathlib import Path

try:
    import matplotlib
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "matplotlib"])
    import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

BASE_DIR = Path(__file__).resolve().parent
EVAL_DIR = BASE_DIR

STRATEGY_NAME_MAP = {
    "vector_only": ["vector_only", "纯向量", "纯向量检索"],
    "bm25_only": ["bm25_only", "纯BM25", "纯bm25", "纯 BM25"],
    "hybrid_rrf": ["hybrid_rrf", "混合(RRF)", "混合检索", "混合RRF"],
    "hybrid_mmr": ["hybrid_mmr", "混合+MMR", "混合(MMR)", "混合MMR"],
}

STRATEGY_ORDER = ["vector_only", "bm25_only", "hybrid_rrf", "hybrid_mmr"]

BAR_COLORS = {
    "hybrid_rrf": "#6C5CE7",
    "vector_only": "#00CEC9",
    "bm25_only": "#FF7675",
    "hybrid_mmr": "#FDCB6E",
}

BG_COLOR = "#0f1117"


def _find_candidate(data: dict, candidates: list):
    for key in candidates:
        if key in data:
            return data[key]
    k_lower = {k.lower(): v for k, v in data.items()}
    for key in candidates:
        if key.lower() in k_lower:
            return k_lower[key.lower()]
    return None


def load_results() -> dict:
    strategy_metrics = {s: {"recall": None, "precision": None, "mrr": None} for s in STRATEGY_ORDER}

    jsonl_files = sorted(EVAL_DIR.glob("results_*.jsonl"))
    json_file = EVAL_DIR / "results.json"

    all_data = {}

    for jf in jsonl_files:
        with open(jf, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        obj = json.loads(line)
                        if "rag" in obj:
                            all_data.update(obj["rag"])
                        else:
                            all_data.update(obj)
                    except json.JSONDecodeError:
                        pass

    if json_file.exists():
        with open(json_file, "r", encoding="utf-8") as f:
            obj = json.load(f)
            if "rag" in obj:
                all_data.update(obj["rag"])
            else:
                all_data.update(obj)

    if not all_data:
        return {}

    for std_name, aliases in STRATEGY_NAME_MAP.items():
        found = _find_candidate(all_data, aliases)
        if found:
            strategy_metrics[std_name]["recall"] = found.get("recall")
            strategy_metrics[std_name]["precision"] = found.get("precision")
            strategy_metrics[std_name]["mrr"] = found.get("mrr")

    return {k: v for k, v in strategy_metrics.items() if any(v.values())}


def save_summary(metrics: dict, out_path: Path):
    summary = {}
    for s in STRATEGY_ORDER:
        if s in metrics:
            for m in ["recall", "precision", "mrr"]:
                val = metrics[s].get(m)
                if val is not None:
                    summary[f"{s}_{m}"] = val
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def _setup_font():
    available = {f.name for f in font_manager.fontManager.ttflist}
    if "Arial" in available:
        plt.rcParams["font.family"] = "Arial"
    elif "Microsoft YaHei" in available:
        plt.rcParams["font.family"] = "Microsoft YaHei"
    elif "SimHei" in available:
        plt.rcParams["font.family"] = "SimHei"


def plot_bar(metrics: dict, metric_key: str, title: str, ylabel: str, out_path: Path, is_percent: bool = True):
    _setup_font()

    names = []
    values = []
    colors = []
    for s in STRATEGY_ORDER:
        if s in metrics and metrics[s].get(metric_key) is not None:
            names.append(s)
            val = metrics[s][metric_key]
            values.append(val * 100 if is_percent else val)
            colors.append(BAR_COLORS[s])

    if not names:
        return

    fig, ax = plt.subplots(figsize=(8, 5.5))
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    bars = ax.bar(names, values, color=colors, edgecolor="none", width=0.6)

    for bar, val in zip(bars, values):
        height = bar.get_height()
        if is_percent:
            label = f"{val:.1f}%"
        else:
            label = f"{val:.3f}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + (max(values) * 0.015 if max(values) > 0 else 0.5),
            label,
            ha="center",
            va="bottom",
            color="white",
            fontsize=11,
            fontweight="bold",
        )

    ax.set_title(title, color="white", fontsize=14, fontweight="bold", pad=18)
    ax.set_ylabel(ylabel, color="white", fontsize=12)
    ax.tick_params(axis="x", colors="white", labelsize=11)
    ax.tick_params(axis="y", colors="white", labelsize=11)

    if is_percent:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))

    for spine in ax.spines.values():
        spine.set_color("#3a3f4b")
    ax.grid(axis="y", linestyle="--", alpha=0.25, color="#555")
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, facecolor=BG_COLOR, bbox_inches="tight")
    plt.close(fig)


def main():
    metrics = load_results()
    if not metrics:
        print("No metrics found. Run eval first.")
        return

    summary_path = EVAL_DIR / "metrics_summary.json"
    save_summary(metrics, summary_path)
    print(f"Summary saved: {summary_path}")

    plot_bar(
        metrics,
        "recall",
        "Recall@5 — RAG Strategy Ablation",
        "Recall@5 (%)",
        EVAL_DIR / "ablation_recall.png",
        is_percent=True,
    )
    print(f"Saved: {EVAL_DIR / 'ablation_recall.png'}")

    plot_bar(
        metrics,
        "precision",
        "Precision@5 — RAG Strategy Ablation",
        "Precision@5 (%)",
        EVAL_DIR / "ablation_precision.png",
        is_percent=True,
    )
    print(f"Saved: {EVAL_DIR / 'ablation_precision.png'}")

    plot_bar(
        metrics,
        "mrr",
        "MRR — RAG Strategy Ablation",
        "MRR",
        EVAL_DIR / "ablation_mrr.png",
        is_percent=False,
    )
    print(f"Saved: {EVAL_DIR / 'ablation_mrr.png'}")


if __name__ == "__main__":
    main()
