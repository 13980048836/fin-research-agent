"""
cli.py — CLI 入口

交互式命令行投研助手，支持多种模式:
  - sql:      仅 SQL 链路
  - rag:      仅 RAG 链路
  - hybrid:   混合模式（SQL + RAG）
  - auto:     自动路由（默认）
  - split-demo: 切分效果演示
"""
import argparse
import asyncio
import sys
from pathlib import Path

# 确保当前目录在 path 中
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_config


BANNER = """
╔══════════════════════════════════════════════╗
║       📊 金融投研助手  FinResearch Agent      ║
║  基于 LLM + RAG + Text-to-SQL 的智能分析系统  ║
╚══════════════════════════════════════════════╝
"""

DISCLAIMER = """
⚠️  免责声明
本系统输出内容仅为 AI 分析示例，不构成任何投资建议。
投资有风险，入市需谨慎。数据为模拟数据，仅供学习研究使用。
"""


def print_separator(title: str = ""):
    if title:
        print(f"\n{'─' * 10} {title} {'─' * 40}")
    else:
        print(f"\n{'─' * 60}")


def run_sql_mode(cfg) -> None:
    """SQL 模式演示"""
    from agents.sql_agent import SQLAgent

    print_separator("SQL 模式")
    print("🔧 正在初始化 SQL Agent...")

    agent = SQLAgent(config=cfg)

    test_queries = [
        "茅台近5年的营收和净利润",
        "白酒行业的平均ROE是多少",
        "五粮液和泸州老窖的毛利率对比",
    ]

    print("\n📝 测试查询示例:")
    for i, q in enumerate(test_queries, 1):
        print(f"   {i}. {q}")

    print("\n💡 输入你的问题（输入 exit 退出）:")

    while True:
        try:
            query = input("\n❓ 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if query.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break
        if not query:
            continue

        async def run():
            print("\n🤖 Agent: 正在生成 SQL...")
            result = await agent.run(query=query)
            if result.success:
                print(f"\n📋 生成的 SQL:\n   {result.metadata.get('sql', 'N/A')}")
                print(f"\n✅ 通过 {len(result.metadata.get('passed_checks', []))} 层安全检查")
                print(f"\n📊 查询结果 ({result.metadata.get('row_count', 0)} 行):")
                print(result.content)
            else:
                print(f"❌ 失败: {result.error}")

        asyncio.run(run())


def run_rag_mode(cfg) -> None:
    """RAG 模式演示"""
    from agents.retriever_agent import RetrieverAgent
    from vector_store import get_vector_store

    print_separator("RAG 模式")
    print("📚 正在初始化 RAG 检索器...")

    try:
        vsm = get_vector_store()
        if not vsm.is_built:
            print("⚠️  向量索引未构建，请先运行: python init_data.py")
            print("   或者仅构建向量索引: python init_data.py --vector")
            return
        store = vsm.store
    except Exception as e:
        print(f"❌ 向量库初始化失败: {e}")
        return

    agent = RetrieverAgent(vector_store=store, config=cfg)

    test_queries = [
        "茅台2024中报业绩",
        "五粮液深度报告观点",
        "白酒行业三季报综述",
    ]

    print("\n📝 测试查询示例:")
    for i, q in enumerate(test_queries, 1):
        print(f"   {i}. {q}")

    print("\n💡 输入你的问题（输入 exit 退出）:")

    while True:
        try:
            query = input("\n❓ 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if query.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break
        if not query:
            continue

        async def run():
            print("\n🔍 正在检索...")
            result = await agent.run(query=query)
            if result.success:
                chunks = result.metadata.get("chunks", [])
                print(f"\n✅ 找到 {len(chunks)} 个相关片段:")
                for c in chunks:
                    source = c.get("source", "未知")
                    page = c.get("page", "-")
                    preview = c["content"][:80].replace("\n", " ")
                    print(f"\n   [{c['index']}] {Path(source).name} (p{page})")
                    print(f"       {preview}...")
            else:
                print(f"❌ 失败: {result.error}")

        asyncio.run(run())


def run_hybrid_mode(cfg) -> None:
    """混合模式（完整链路）"""
    from orchestrator import Orchestrator
    from vector_store import get_vector_store

    print_separator("混合模式 (Hybrid)")
    print("🚀 正在初始化多 Agent 编排器...")

    try:
        vsm = get_vector_store()
        store = vsm.store if vsm.is_built else None
        if store is None:
            print("⚠️  向量索引未构建，将仅使用 SQL 链路")
    except Exception:
        store = None

    orch = Orchestrator(vector_store=store, config=cfg)

    test_queries = [
        "贵州茅台的投资价值分析",
        "对比一下五粮液和泸州老窖",
        "白酒行业未来趋势怎么看",
    ]

    print("\n📝 测试查询示例:")
    for i, q in enumerate(test_queries, 1):
        print(f"   {i}. {q}")

    print("\n💡 输入你的问题（输入 exit 退出）:")

    while True:
        try:
            query = input("\n❓ 你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 再见！")
            break

        if query.lower() in ("exit", "quit", "q"):
            print("👋 再见！")
            break
        if not query:
            continue

        async def run_stream():
            print()
            async for event in orch.stream_analyze(query=query, mode="hybrid"):
                evt = event["event"]
                data = event["data"]

                if evt == "router":
                    print(f"🧭 路由决策: {data['mode']} (置信度: {data.get('confidence', 0):.0%})")
                elif evt == "sql_start":
                    print("📊 查询数据库中...", end=" ", flush=True)
                elif evt == "sql_end":
                    if data.get("success"):
                        print(f"✅ ({data.get('row_count', 0)} 行)")
                    else:
                        print("❌ 失败")
                elif evt == "rag_start":
                    print("📚 检索研报中...", end=" ", flush=True)
                elif evt == "rag_end":
                    if data.get("success"):
                        print(f"✅ ({data.get('chunk_count', 0)} 个片段)")
                    else:
                        print("❌ 失败")
                elif evt == "report_start":
                    print("\n📝 分析报告:\n")
                elif evt == "report_token":
                    print(data.get("token", ""), end="", flush=True)
                elif evt == "done":
                    print(f"\n\n✅ 完成！模式: {data.get('mode', '')}")
                elif evt == "error":
                    print(f"\n❌ 错误: {data.get('message', '')}")

            print()

        asyncio.run(run_stream())


def run_split_demo(cfg) -> None:
    """切分效果演示"""
    from doc_loader import DocumentLoader

    print_separator("切分效果演示")
    print("🔍 加载默认文档并对比切分策略...")

    docs_dir = cfg.docs_dir / "research_pdf"
    if not docs_dir.exists():
        print(f"❌ 文档目录不存在: {docs_dir}")
        print("   请先运行: python init_data.py --docs-only")
        return

    # 找第一个 txt 文件
    txt_files = list(docs_dir.glob("*.txt"))
    if not txt_files:
        print("❌ 没有找到测试文档")
        return

    test_file = txt_files[0]
    print(f"📄 测试文件: {test_file.name}")

    loader = DocumentLoader(cfg)
    results = loader.compare_split_strategies(test_file)

    print(f"\n{'策略':<12} {'片段数':>8} {'平均大小':>10} {'最大':>8} {'最小':>8}")
    print("─" * 55)
    for strategy, info in results.items():
        print(f"{strategy:<12} {info['chunks']:>8} {info['avg_size']:>10.0f} {info['max_size']:>8} {info['min_size']:>8}")

    print(f"\n💡 推荐策略: recursive（通用场景效果最好）")
    print(f"   当前配置: {cfg.splitter.strategy} / chunk_size={cfg.splitter.chunk_size} / overlap={cfg.splitter.chunk_overlap}")


def main():
    parser = argparse.ArgumentParser(
        description="金融投研助手 - 交互式 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=DISCLAIMER,
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["auto", "sql", "rag", "hybrid", "simple", "split-demo"],
        default="hybrid",
        help="运行模式 (默认: hybrid)",
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="单次查询（非交互模式）",
    )
    args = parser.parse_args()

    print(BANNER)
    print(DISCLAIMER)

    # 加载配置
    try:
        cfg = get_config()
        cfg.ensure_dirs()
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        sys.exit(1)

    # 单次查询模式
    if args.query:
        from orchestrator import Orchestrator
        from vector_store import get_vector_store

        try:
            vsm = get_vector_store()
            store = vsm.store if vsm.is_built else None
        except Exception:
            store = None

        orch = Orchestrator(vector_store=store, config=cfg)

        async def run_single():
            print(f"\n❓ 问题: {args.query}")
            print(f"🎯 模式: {args.mode}")
            print()
            async for event in orch.stream_analyze(query=args.query, mode=args.mode):
                evt = event["event"]
                data = event["data"]
                if evt == "report_token":
                    print(data.get("token", ""), end="", flush=True)
                elif evt == "done":
                    print(f"\n\n✅ 完成")
            print()

        asyncio.run(run_single())
        return

    # 交互模式
    mode_handlers = {
        "sql": run_sql_mode,
        "rag": run_rag_mode,
        "hybrid": run_hybrid_mode,
        "auto": run_hybrid_mode,
        "simple": run_hybrid_mode,
        "split-demo": run_split_demo,
    }

    handler = mode_handlers.get(args.mode, run_hybrid_mode)
    handler(cfg)


if __name__ == "__main__":
    main()
