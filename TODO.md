# 项目待办清单

> 创建日期：2026-07-29
> 优先级说明：🔴 P0 紧急 / 🟠 P1 高 / 🟡 P2 中 / 🟢 P3 低

---

## 🔴 P0 紧急（必须尽快完成）

| # | 事项 | 说明 / 预期 | 关联文件 / 参考 | 状态 |
|---|------|------------|----------------|------|
| 1 | **重置 DashScope API Key** | 已泄露在对话上下文，即使有 `.gitignore` 也必须**去阿里云百炼控制台作废**原 `sk-ws-H.EDLMIHI...` 并重建。本地 `.env` 同步替换新 Key。 | [.env#L6](.env#L6) | ⬜ 待办（你自己操作）|
| 2 | **Git 初始化 + 推送到 GitHub** | ✅ commit `fe56b48`（45 个文件，11741 行），已推送。仓库地址：https://github.com/13980048836/fin-research-agent | [.gitignore](.gitignore) | ✅ 完成 |

---

## 🟠 P1 高优先级（上线 / 简历发布前完成）

| # | 事项 | 说明 / 预期 | 关联文件 / 参考 | 状态 |
|---|------|------------|----------------|------|
| 3 | **生产环境误删保护验证** | 设置 `ENVIRONMENT=production` 后执行 `python init_data.py --force`，应直接退出（返回码 1），**禁止**执行删除/重建。 | [init_data.py#L597-L618](init_data.py#L597-L618) | ⬜ 待办 |
| 4 | **Streamlit UI 全量回归测试** | 逐项验证：6 条快速问题是否正常出结果 / 上传 PDF 大小限制+路径穿越防御 / SQL 面板复制按钮 / 导出对话 / 清空对话 / 免责声明高亮 / 分析模式下拉框功能说明。 | [streamlit_app.py](streamlit_app.py) | ⬜ 待办 |
| 5 | **补装全套依赖 + 剩余 3 条测试排查** | `pip install -r requirements.txt` 完整安装；排查 `tests/test_doc_loader.py` 中 `test_chunk_size_config`、`test_compare_split_strategies`、`test_load_txt_file` 失败根因（`DocumentLoader` 返回 dict vs LangChain Document 的结构差异）。 | [requirements.txt](requirements.txt) / [tests/test_doc_loader.py](tests/test_doc_loader.py) | ⬜ 待办 |
| 6 | **创建 GitHub 公开仓库 + 推送** | ① 新建 GitHub 仓库（建议名 `fin-research-agent`，不要加真实 Key）；② 补 `LICENSE`（推荐 MIT 或 Apache-2.0）；③ README 顶部加一行项目副标题 + 指标速览卡片（把 Recall@5=100% / SQL 100% 直接放显眼位置）。 | [README.md](README.md) | ⬜ 待办 |

---

## 🟡 P2 中优先级（简历加分项）

| # | 事项 | 说明 / 预期 | 关联文件 / 参考 | 状态 |
|---|------|------------|----------------|------|
| 7 | **评估跑一次 + 终端输出截图保存** | 运行 `python -m eval.run_eval`，把完整输出截图保存为 `docs/assets/eval_result.png`（简历 PDF 可以贴图，面试时直接展示，比文字更有说服力）。 | [eval/run_eval.py](eval/run_eval.py) | ⬜ 待办 |
| 8 | **扩充 benchmark 到 50+ 题** | 当前 30 题偏少（18 RAG + 12 SQL）。建议新增：<br>• SQL 对比类（五粮液 vs 泸州老窖毛利率、市值排序）<br>• SQL 聚合类（行业平均毛利率、3 家总市值）<br>• RAG 公告类（分红公告、股权激励）<br>• RAG 行业类（2026 白酒投资策略） | [eval/benchmark.jsonl](eval/benchmark.jsonl) | ⬜ 待办 |
| 9 | **CrossEncoder 重排真实对比（需联网一次）** | 临时设 `HF_HUB_OFFLINE=0` + 网络通畅，加载 `BAAI/bge-reranker-base`（≈400MB），跑完 RAG 评估对比 `混合(RRF)` vs `混合(完整)` 的 MRR 差值，**只要能提升 3~5% 就非常有说服力**。跑完再改回离线模式。 | [hybrid_retriever.py#L205-L259](hybrid_retriever.py#L205-L259) | ⬜ 待办 |
| 10 | **消融实验柱状图** | 5 种策略 Recall@5 + Precision@5 + MRR 做 3 张柱状图（`matplotlib`/`plotly` 导出 PNG），贴到 README 评估指标章节下。可视化远胜于表格。 | [README.md#L107-L139](README.md#L107-L139) | ⬜ 待办 |

---

## 🟢 P3 低优先级（锦上添花）

| # | 事项 | 说明 / 预期 | 状态 |
|---|------|------------|------|
| 11 | **多轮对话上下文测试** | 设计多轮问答：① "茅台2025年营收多少" ② "那毛利率呢？"（应承接前一题上下文）③ "和五粮液对比呢？" 评估当前多轮关联是否稳定。 | ⬜ 待办 |
| 12 | **PDF 智能处理端到端复现 + 录屏** | 构造原生 PDF / 扫描 PDF / 含表格 PDF 4 页测试文件，跑 `pdf_processor.py` 验证路由，录 60 秒屏贴 README（比文字直观）。 | ⬜ 待办 |
| 13 | **爬虫模块实抓一次** | `python crawler.py --keywords "茅台,白酒" --max-pages 10`，验证：`robots.txt` 合规检查生效 / 抓取后 `data/docs/crawled/` 是否产出 / 正文清洗 OK。 | ⬜ 待办 |
| 14 | **SQL 注入压力测试集** | 写 20 条注入 payload（`' OR 1=1 --`、`UNION SELECT`、`; DROP TABLE`、注释注入、编码绕过等）跑一遍 `SQLExecutor.validate_only`，确认 100% 拦截。 | ⬜ 待办 |
| 15 | **30 秒交互演示 GIF/视频** | 录屏：输入"茅台近 5 年营收和净利润" → SQL 面板出数据 → 自动生成折线图 → 研报引用 + 免责声明。README 最顶部放 GIF，10 秒抓住注意力。 | ⬜ 待办 |

---

## 💡 下次来直接问我（快捷提示）

任选下面一条复制粘贴，不用重新描述：

```
帮我做 P0 第 2 步：初始化 Git + 首次 commit（我已经重置了 API Key）
帮我做 P1 第 3-5 步：生产误删保护验证 + UI 全测 + 依赖补装
帮我做 P1 第 6 步：创建 GitHub 仓库 + 推代码 + 加 LICENSE
帮我做 P2 第 7-10 步：评估截图 / benchmark 扩充 / 重排对比 / 消融作图
帮我做 P3 第 12 步：PDF 智能处理端到端测试 + 录屏
P2 第 9 步，我这边网络通了，帮我真正加载 CrossEncoder 跑一次重排对比
帮我跑 P3 第 14 步：SQL 注入压力测试
```

---

## ✅ 已完成（归档）

| 完成日期 | 事项 | 结果 |
|---------|------|------|
| 2026-07-29 | 评估体系搭建（RAG+SQL） | Recall@5=100% / SQL 三项 100% |
| 2026-07-29 | 修复 RRF 融合 `id(doc)` 去重失效 bug | 改为内容 hash 标识 |
| 2026-07-29 | 重建 BM25 索引（剔除项目文档干扰） | BM25 Recall@5 从 0% → 94.44% |
| 2026-07-29 | 上线安全加固 | `.env` 密钥注入、Orchestrator 双检锁单例、API Key+CORS+限流、robots.txt 合规、`--force` 环境保护、文件上传 4 层安全防护 |
