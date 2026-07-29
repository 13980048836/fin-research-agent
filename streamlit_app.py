"""
streamlit_app.py — Streamlit Web 界面

功能:
  1. 交互式投研问答（流式输出）
  2. SQL 查询结果可视化（自动图表）
  3. SQL 面板（复制 / 参数修改 / 重新执行）
  4. 快速问题分组分类
  5. 研报上传交互
  6. 对话导出 / 清空
  7. 数据可视化图表
"""
import asyncio
import sys
import json
from pathlib import Path

import streamlit as st

# 确保项目根目录在 path 中
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import get_config


# ==================== 页面配置 ====================

st.set_page_config(
    page_title="金融投研助手",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==================== 自定义样式 ====================

st.markdown("""
<style>
/* ========== 全局微调 ========== */
section[data-testid="stSidebar"] .block-container {
    padding-top: 1rem;
    padding-bottom: 1rem;
}

/* ========== 免责声明（降饱和 + 融入）========== */
.disclaimer-box {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-left: 3px solid #94a3b8;
    padding: 10px 14px;
    border-radius: 8px;
    margin: 10px 0 6px 0;
    font-size: 0.82rem;
    line-height: 1.65;
}
.disclaimer-box .title {
    font-weight: 600;
    color: #475569;
    margin-bottom: 4px;
    font-size: 0.85rem;
}
.disclaimer-box .body {
    color: #64748b;
}

/* 合规提示 */
.compliance-banner {
    background: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 7px 12px;
    font-size: 0.78rem;
    color: #64748b;
    margin: 4px 0;
    line-height: 1.55;
}

/* ========== 底部技术标签（低权重 + 大留白）========== */
.feature-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 20px 18px 18px 18px;
    text-align: left;
    height: 100%;
    transition: border-color 0.2s;
}
.feature-card:hover {
    border-color: #cbd5e1;
}
.feature-icon {
    font-size: 1.6rem;
    margin-bottom: 8px;
    opacity: 0.9;
}
.feature-title {
    font-weight: 600;
    color: #334155;
    margin-bottom: 6px;
    font-size: 0.95rem;
    line-height: 1.3;
}
.feature-desc {
    font-size: 0.8rem;
    color: #6b7280;
    line-height: 1.6;
}

/* ========== 工具栏 ========== */
.toolbar-btn {
    margin-right: 8px;
}
</style>
""", unsafe_allow_html=True)


st.title("📊 金融投研助手")
st.caption("基于 LLM + RAG + Text-to-SQL 的智能投研分析系统")


# ==================== 常量定义 ====================

# 分析模式（带功能说明）
MODE_OPTIONS = {
    "auto": "🤖 自动路由 — 智能判断最佳查询方式",
    "sql": "📊 数据库查询 — 仅查询结构化财务数据",
    "rag": "📄 研报检索 — 仅检索研报文档内容",
    "hybrid": "🔄 混合模式 — 同时查询数据库和研报",
    "simple": "💬 简单对话 — 直接回答常见问题",
}

MODE_DESCRIPTIONS = {
    "auto": "系统根据问题类型自动选择 SQL、RAG 或混合模式，适合大多数场景",
    "sql": "将问题转为 SQL 查询数据库，适合查询营收、利润、ROE 等数值型问题",
    "rag": "从研报文档中检索相关段落，适合查询研报观点、公告内容、行业分析",
    "hybrid": "同时查询数据库和研报，适合需要数据+观点的综合分析",
    "simple": "不走检索链路，直接用 LLM 回答，适合寒暄和常识问题",
}

# 快速问题分组
QUESTION_GROUPS = {
    "📊 财务数据查询": [
        "茅台近5年营收和净利润",
        "白酒行业平均ROE是多少",
        "五粮液的毛利率变化趋势",
    ],
    "📚 研报观点分析": [
        "茅台研报怎么看",
        "泸州老窖的投资价值分析",
    ],
    "🔄 综合对比分析": [
        "三家白酒公司的对比",
    ],
}

# 底部技术标签
FEATURES = [
    {
        "icon": "🛡️",
        "title": "6 层 SQL 安全防护",
        "desc": "关键字过滤 → 语法校验 → 只读事务 → 行数限制 → 超时控制 → 权限隔离",
    },
    {
        "icon": "📄",
        "title": "RAG 文档检索",
        "desc": "支持 PDF/TXT/PPTX，BM25+向量混合检索，Cross-Encoder 重排，MMR 去重",
    },
    {
        "icon": "🤖",
        "title": "多 Agent 协作",
        "desc": "Router 路由 → SQL 生成 → Retriever 检索 → Analyst 分析，四智能体协同",
    },
    {
        "icon": "🔍",
        "title": "智能 PDF 处理",
        "desc": "原生 PDF 直接抽取 → 扫描件 OCR 识别 → 表格图表视觉理解，三路自动路由",
    },
]


# ==================== 辅助函数 ====================

def render_chart(columns, rows, key_suffix=""):
    """根据 SQL 结果自动渲染图表（左表右图）"""
    if not rows or not columns:
        st.caption("暂无数据可可视化")
        return

    if len(rows) < 2:
        st.caption(f"仅 {len(rows)} 行数据，图表至少需要 2 行")
        st.dataframe(rows, use_container_width=True)
        return

    try:
        import pandas as pd

        df = pd.DataFrame(rows, columns=columns)

        # 左表右图布局（列数足够时）
        use_split = len(columns) <= 5

        if use_split:
            tab_col, chart_col = st.columns([5, 7])
            with tab_col:
                st.markdown(
                    '<div style="font-size: 0.85rem; font-weight: 600; color: #374151; margin-bottom: 4px;">'
                    '📋 数据表</div>',
                    unsafe_allow_html=True,
                )
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.markdown(
                '<div style="font-size: 0.85rem; font-weight: 600; color: #374151; margin-bottom: 4px;">'
                '📋 数据表</div>',
                unsafe_allow_html=True,
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

        # 用 pandas 类型推断找数值列
        numeric_cols = df.select_dtypes(include=["number", "float", "int"]).columns.tolist()
        if not numeric_cols:
            st.caption("未检测到数值列，无法生成图表")
            return

        # 找类别列（第一个非数值列）
        non_numeric = [c for c in columns if c not in numeric_cols]
        if non_numeric:
            category_col = non_numeric[0]
            chart_df = df.set_index(category_col)

            cat_val = str(df[category_col].iloc[0])
            is_time_series = (
                "year" in category_col.lower()
                or "年" in cat_val
                or "date" in category_col.lower()
                or "日期" in category_col
            )

            chart_title = "📈 趋势图" if is_time_series else "📊 对比图"

            if use_split:
                target = chart_col
            else:
                target = st.container()

            with target:
                st.markdown(
                    f'<div style="font-size: 0.85rem; font-weight: 600; color: #374151; '
                    f'margin-bottom: 4px;">{chart_title}</div>',
                    unsafe_allow_html=True,
                )
                if is_time_series:
                    st.line_chart(chart_df[numeric_cols], use_container_width=True)
                else:
                    st.bar_chart(chart_df[numeric_cols], use_container_width=True)
        else:
            # 所有列都是数值
            target = chart_col if use_split else st.container()
            with target:
                st.markdown(
                    '<div style="font-size: 0.85rem; font-weight: 600; color: #374151; '
                    'margin-bottom: 4px;">📈 趋势图</div>',
                    unsafe_allow_html=True,
                )
                st.line_chart(df[numeric_cols], use_container_width=True)
    except Exception as e:
        st.caption(f"图表渲染失败: {e}")
        try:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        except Exception:
            pass


def export_messages() -> str:
    """将对话历史导出为 Markdown"""
    lines = ["# 金融投研助手 — 对话记录\n"]
    for msg in st.session_state.messages:
        role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        lines.append(f"## {role}\n")
        lines.append(f"{msg['content']}\n")
        if msg.get("sql"):
            lines.append(f"```sql\n{msg['sql']}\n```\n")
        if msg.get("sources"):
            lines.append("**检索来源:**\n")
            for s in msg["sources"]:
                lines.append(f"- {s}")
            lines.append("")
    return "\n".join(lines)


def save_uploaded_file(uploaded_file):
    """保存上传的研报文件到 docs 目录（带安全校验）"""
    docs_dir = BASE_DIR / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    # 安全修复 1：防止路径穿越，仅保留纯文件名
    filename = Path(uploaded_file.name).name
    # 安全修复 2：文件大小限制（5MB）
    MAX_SIZE = 5 * 1024 * 1024
    if uploaded_file.size > MAX_SIZE:
        raise ValueError(f"文件大小超过 5MB 限制（当前: {uploaded_file.size / 1024 / 1024:.1f}MB）")
    # 安全修复 3：白名单扩展名
    ALLOWED_EXT = {".pdf", ".txt", ".md"}
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"不支持的文件类型: {ext}，仅允许 {', '.join(sorted(ALLOWED_EXT))}")
    save_path = docs_dir / filename
    # 安全修复 4：确保最终路径在 docs_dir 内（双重防护）
    save_path_resolved = save_path.resolve()
    docs_dir_resolved = docs_dir.resolve()
    if docs_dir_resolved not in save_path_resolved.parents and save_path_resolved != docs_dir_resolved:
        raise ValueError("非法文件路径")
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return save_path


# ==================== 侧边栏 ====================

with st.sidebar:
    st.header("⚙️ 设置")

    # 分析模式（带功能说明）
    mode = st.selectbox(
        "分析模式",
        list(MODE_OPTIONS.keys()),
        format_func=lambda x: MODE_OPTIONS[x],
        index=0,
        help="选择查询方式，auto 模式推荐日常使用",
    )

    # 模式说明
    st.caption(f"💡 {MODE_DESCRIPTIONS[mode]}")

    show_sql = st.checkbox("显示生成的 SQL", value=True)
    show_rag_sources = st.checkbox("显示检索来源", value=True)
    show_chart = st.checkbox("显示数据图表", value=True)

    st.divider()

    # 快速问题分组
    st.subheader("📈 快速问题")

    for gi, (group_name, questions) in enumerate(QUESTION_GROUPS.items()):
        if gi > 0:
            st.markdown('<div style="height: 8px;"></div>', unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size: 0.8rem; font-weight: 600; color: #475569; '
            f'margin-bottom: 6px; padding-left: 2px;">{group_name}</div>',
            unsafe_allow_html=True,
        )
        for q in questions:
            if st.button(q, use_container_width=True, key=f"q_{q}"):
                st.session_state.current_question = q
                st.rerun()
        if gi < len(QUESTION_GROUPS) - 1:
            st.markdown('<div style="border-bottom: 1px solid #eef2f7; margin: 4px 0 4px 0;"></div>', unsafe_allow_html=True)

    st.divider()

    # 上传研报
    st.subheader("📤 上传研报")
    uploaded_file = st.file_uploader(
        "上传 PDF / TXT / MD 研报文件",
        type=["pdf", "txt", "md"],
        help="上传后将保存到 docs 目录，需重建索引后生效",
    )
    if uploaded_file is not None:
        try:
            save_path = save_uploaded_file(uploaded_file)
            st.success(f"✅ 已保存: {uploaded_file.name}")
            st.info("💡 提示：运行 `python init_data.py` 重建索引后生效")
        except Exception as e:
            st.error(f"保存失败: {e}")

    st.divider()

    # 免责声明（高亮突出）
    st.markdown("""
    <div class="disclaimer-box">
      <div class="title">⚠️ 免责声明</div>
      <div class="body">
        本工具内容仅供学习研究使用，不构成任何投资建议。<br>
        数据来源为模拟数据，不代表真实市场情况。<br>
        投资有风险，入市需谨慎。
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="compliance-banner">
      🔒 合规提示：本系统生成的分析报告由 AI 模型产出，<br>
      可能存在偏差，请以官方披露信息为准。
    </div>
    """, unsafe_allow_html=True)


# ==================== 主内容区 ====================

# Session state 初始化
if "messages" not in st.session_state:
    st.session_state.messages = []

if "current_question" not in st.session_state:
    st.session_state.current_question = ""

# 顶部工具栏（导出 / 清空）
if st.session_state.messages:
    toolbar_col1, toolbar_col2, toolbar_col3 = st.columns([6, 1, 1])
    with toolbar_col2:
        st.download_button(
            "📥 导出",
            data=export_messages(),
            file_name="投研对话记录.md",
            mime="text/markdown",
            use_container_width=True,
        )
    with toolbar_col3:
        if st.button("🗑️ 清空", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


# 显示历史消息
for msg_idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            if msg.get("sql"):
                with st.expander("🔍 生成的 SQL", expanded=show_sql):
                    st.code(msg["sql"], language="sql")
            if msg.get("rows") and msg.get("columns") and show_chart:
                with st.expander("📊 数据可视化", expanded=False):
                    render_chart(msg["columns"], msg["rows"], key_suffix=f"hist_{msg_idx}")
            if msg.get("sources"):
                with st.expander(f"📚 检索来源 ({len(msg['sources'])} 个)", expanded=show_rag_sources):
                    for s in msg["sources"]:
                        st.markdown(f"- {s}")
        st.markdown(msg["content"])


# 输入框
prompt = st.chat_input("请输入你的投研问题，例如：茅台近5年营收复合增长率是多少？")
if st.session_state.current_question and not prompt:
    prompt = st.session_state.current_question
    st.session_state.current_question = ""

if prompt:
    # 显示用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 生成回复
    def generate_response():
        sql_text = ""
        sql_rows = []
        sql_columns = []
        sources = []
        status_lines = []
        rag_chunk_count = 0
        actual_route_mode = mode

        try:
            cfg = get_config()

            from orchestrator import get_orchestrator_cached
            from vector_store import get_vector_store

            # 优化：使用 session_state 缓存 Orchestrator 和向量库，避免每次重建
            if "_orch_cache" not in st.session_state:
                try:
                    vsm = get_vector_store()
                    store = vsm.store if vsm.is_built else None
                except Exception:
                    store = None
                st.session_state._orch_cache = get_orchestrator_cached(
                    vector_store=store, config=cfg
                )
                st.session_state._orch_store_ready = store is not None
            orch = st.session_state._orch_cache

            with st.chat_message("assistant"):
                ph_status = st.empty()

                import queue
                import threading

                event_queue = queue.Queue()

                def _run_async():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                    async def _collect():
                        async for event in orch.stream_analyze(query=prompt, mode=mode):
                            event_queue.put(event)
                        event_queue.put(None)

                    loop.run_until_complete(_collect())
                    loop.close()

                thread = threading.Thread(target=_run_async, daemon=True)
                thread.start()

                def token_gen():
                    nonlocal sql_text, sql_rows, sql_columns, sources, status_lines, rag_chunk_count, actual_route_mode
                    while True:
                        event = event_queue.get()
                        if event is None:
                            break
                        evt = event["event"]
                        data = event["data"]

                        if evt == "router":
                            actual_route_mode = data["mode"]
                            status_lines.append(f"🧭 路由决策: {data['mode']} (置信度: {data['confidence']:.0%})")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "sql_start":
                            status_lines.append("📊 正在查询数据库...")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "sql_end":
                            if data.get("sql"):
                                sql_text = data["sql"]
                            sql_rows = data.get("rows", [])
                            sql_columns = data.get("columns", [])
                            status_lines.append(f"✅ SQL 执行完成，返回 {data.get('row_count', 0)} 行")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "rag_start":
                            status_lines.append("📚 正在检索研报...")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "rag_end":
                            rag_chunk_count = data.get("chunk_count", 0)
                            sources = data.get("sources", [])
                            status_lines.append(f"✅ 检索完成，找到 {rag_chunk_count} 个相关片段")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "report_start":
                            status_lines.append("✍️ 正在生成分析报告...")
                            ph_status.caption("\n\n".join(status_lines))
                        elif evt == "report_token":
                            yield data.get("token", "")
                        elif evt == "error":
                            status_lines.append(f"❌ 错误: {data.get('message', '')}")
                            ph_status.caption("\n\n".join(status_lines))

                final_text = "".join(st.write_stream(token_gen()))

                # SQL 面板（复制 + 参数修改）
                if sql_text and show_sql:
                    with st.expander("🔍 生成的 SQL（可复制 / 可编辑重跑）", expanded=False):
                        st.code(sql_text, language="sql")

                        st.caption("📝 修改参数后点击执行：")
                        edited_sql = st.text_area(
                            "编辑 SQL",
                            value=sql_text,
                            height=140,
                            key=f"sql_edit_{len(st.session_state.messages)}",
                            label_visibility="collapsed",
                        )
                        edit_col1, edit_col2, edit_col3 = st.columns([1.2, 1, 2])
                        with edit_col1:
                            if st.button("▶️ 执行修改后的 SQL", key=f"run_sql_{len(st.session_state.messages)}", use_container_width=True):
                                try:
                                    from executor import get_executor
                                    exec_result = get_executor().execute(edited_sql)
                                    if exec_result.is_success and exec_result.rows:
                                        st.dataframe(exec_result.rows, use_container_width=True)
                                        render_chart(exec_result.columns, exec_result.rows, key_suffix=f"edit_{len(st.session_state.messages)}")
                                    elif exec_result.error:
                                        st.error(f"执行失败: {exec_result.error}")
                                    else:
                                        st.info("查询返回 0 行")
                                except Exception as ex:
                                    st.error(f"执行异常: {ex}")
                        with edit_col2:
                            if st.button("📋 复制原始 SQL", key=f"copy_sql_{len(st.session_state.messages)}", use_container_width=True):
                                st.info("SQL 已显示在上方代码框，可点击代码框右上角按钮复制")
                        st.markdown('<div style="height: 4px;"></div>', unsafe_allow_html=True)

                # 数据可视化图表
                if sql_rows and sql_columns and show_chart:
                    with st.expander("📊 数据可视化", expanded=True):
                        st.markdown('<div style="height: 4px;"></div>', unsafe_allow_html=True)
                        render_chart(sql_columns, sql_rows, key_suffix=f"new_{len(st.session_state.messages)}")
                        st.markdown('<div style="height: 6px;"></div>', unsafe_allow_html=True)

                # 检索来源
                if sources and show_rag_sources:
                    with st.expander(f"📚 检索来源 ({len(sources)} 个)", expanded=False):
                        for s in sources:
                            st.markdown(f"- {s}")

                # 研报无数据时提示上传（仅当实际路由到 RAG/Hybrid 时才提示）
                if rag_chunk_count == 0 and actual_route_mode in ("rag", "hybrid"):
                    st.warning("⚠️ 未检索到相关研报文档。你可以在侧边栏上传研报文件，或切换为 SQL 模式查询财务数据。")

                msg_data = {
                    "role": "assistant",
                    "content": final_text,
                }
                if sql_text:
                    msg_data["sql"] = sql_text
                if sql_rows and sql_columns:
                    msg_data["rows"] = sql_rows
                    msg_data["columns"] = sql_columns
                if sources:
                    msg_data["sources"] = sources
                st.session_state.messages.append(msg_data)

        except ImportError as e:
            error_msg = f"⚠️ 依赖未安装: {e}\n\n请先安装依赖: `pip install -r requirements.txt`"
            with st.chat_message("assistant"):
                st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})
        except Exception as e:
            error_msg = f"❌ 出错了: {type(e).__name__}: {e}"
            with st.chat_message("assistant"):
                st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})

    generate_response()


# ==================== 底部技术标签 ====================

st.divider()
st.markdown(
    '<div style="font-size: 1rem; font-weight: 600; color: #374151; margin-bottom: 14px;">🛠️ 技术架构</div>',
    unsafe_allow_html=True,
)

cols = st.columns(len(FEATURES))
for col, feat in zip(cols, FEATURES):
    with col:
        st.markdown(f"""
        <div class="feature-card">
          <div class="feature-icon">{feat['icon']}</div>
          <div class="feature-title">{feat['title']}</div>
          <div class="feature-desc">{feat['desc']}</div>
        </div>
        """, unsafe_allow_html=True)

st.markdown(
    '<div style="height: 12px;"></div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div style="text-align: center; color: #9ca3af; font-size: 0.78rem; padding: 8px 0;">'
    '金融投研助手 v1.0 · 基于 LLM + RAG + Text-to-SQL · 仅供学习研究'
    '</div>',
    unsafe_allow_html=True,
)
