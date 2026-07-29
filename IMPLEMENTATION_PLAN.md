# 📋 实施计划 (Implementation Plan)

> 分 **6 个阶段**推进,每阶段**独立可验证**,完成后即可运行测试。
> 总计约 **2200 行代码**,预计开发周期 **6-8 天**(每天 1 个阶段 + 优化缓冲)。

---

## 🗓️ 开发周期总览

| 阶段 | 主题 | 预计时间 | 代码量 | 核心产出 | 验证方式 | 难度 |
|------|------|---------|--------|---------|---------|------|
| **Phase 1** | 基础设施搭建 | 0.5-1 天 | ~300 行 | 配置中心 + 数据库 + 示例数据 | `python init_data.py` 建库成功 | ★☆☆ |
| **Phase 2** | Text-to-SQL 链路 | 1-1.5 天 | ~400 行 | Schema/SQL Agent + Executor | CLI 查询出 SQL 结果 | ★★☆ |
| **Phase 3** | RAG 链路 | 1-1.5 天 | ~400 行 | DocLoader + VectorStore + Retriever | 文档检索召回 top-k | ★★☆ |
| **Phase 4** | 多 Agent 编排 | 1 天 | ~400 行 | Orchestrator + Analyst + Render | 端到端投研报告 | ★★★ |
| **Phase 5** | 双形态接口 | 1 天 | ~400 行 | FastAPI + Streamlit + Visualizer | Web 看板可交互 | ★★☆ |
| **Phase 6** | 工程化收尾 | 1 天 | ~300 行 | 测试 + 爬虫 + 文档 + 优化 | 测试全绿 + 文档完整 | ★★☆ |
| **合计** | - | **6-8 天** | **~2200 行** | - | - | - |

---

## Phase 1: 基础设施搭建 ⚙️

**阶段目标**:搭好配置中心和数据库底座,造好示例金融数据,为后续 Agent 提供稳定数据源。

### 关键产出
| 文件 | 说明 |
|------|------|
| `config.py` | 配置中心(LLM / DB / Embedding / 向量库 / 限流 / 重试),单例模式 |
| `db_client.py` | SQLite 连接管理(单例 + 连接池 + 只读模式) |
| `init_data.py` | 示例数据生成器(4 张表 + 模拟文档) |
| `requirements.txt` | 依赖清单(带版本约束) |
| `.env.example` | 环境变量模板(20+ 配置项) |

### 数据库表设计
- **`stocks`** — 股票基本信息:stock_code, name, industry, list_date, market_cap
- **`daily_quotes`** — 日线行情:id, stock_code, date, open, high, low, close, volume, amount, pct_change
- **`financial_statements`** — 财务报表:id, stock_code, year, quarter, revenue, net_profit, roe, debt_ratio, eps, pe, pb
- **`industries`** — 行业指标:industry, avg_pe, avg_pb, avg_roe, avg_debt_ratio, company_count

> 示例数据规模:10 只股票 × 4 个行业 × 5 年财报 ≈ 200+ 条记录;日线行情约 2000+ 条。

### 任务清单
- [ ] 编写 `config.py`,支持从 `.env` 读取所有配置
- [ ] 编写 `db_client.py`,实现单例 + get_schema + execute_query
- [ ] 编写 `init_data.py`,造 4 张表 + 插入模拟数据
- [ ] 完善 `requirements.txt`,补充版本约束
- [ ] 完善 `.env.example`,列出全部配置项
- [ ] 编写 `agents/__init__.py`

### 验证命令
```bash
python init_data.py
# 预期输出:
# ✅ 数据库初始化完成: 4 张表, 256 条记录

sqlite3 data/finance.db ".tables"
# 输出: stocks  daily_quotes  financial_statements  industries

sqlite3 data/finance.db "SELECT COUNT(*) FROM stocks;"
# 输出: 10
```

### 学习重点
- 复用旅行项目的 config 单例模式
- SQLite 数据库设计与索引优化
- 金融数据建模(股票、行情、财报的关系)
- python-dotenv 环境变量管理

---

## Phase 2: Text-to-SQL 链路 📊

**阶段目标**:实现自然语言→SQL→执行→结果的完整链路,带 6 层安全防护。

### 关键产出
| 文件 | 说明 |
|------|------|
| `prompts.py` | SQL Agent / Schema Agent 系统提示词(含 few-shot 示例) |
| `agents/specialist.py` | 通用领域 Agent 基类(LangGraph create_agent 封装) |
| `agents/schema_agent.py` | Schema 理解 Agent(读表结构,生成 schema 描述) |
| `agents/sql_agent.py` | Text-to-SQL Agent(自然语言 → SQL) |
| `executor.py` | SQL 安全执行器(6 层防护 + 只读隔离 + 超时) |
| `cli.py` | CLI 入口(支持 `--mode sql` 单跑 SQL 链路) |

### SQL 安全执行器 6 层防护
1. **关键字过滤** — 正则匹配 DROP/DELETE/UPDATE/INSERT 等禁用词
2. **语法校验** — sqlparse 解析 AST,确认语句类型为 SELECT
3. **只读事务** — SQLite 连接开启只读模式
4. **行数限制** — 自动追加 LIMIT 1000
5. **超时控制** — 30 秒超时中断
6. **权限隔离** — 数据库文件仅 SELECT 权限

### 任务清单
- [ ] 编写 `prompts.py`,设计 Schema Agent + SQL Agent 提示词
- [ ] 编写 `agents/specialist.py`,封装 LangGraph Agent 基类
- [ ] 编写 `agents/schema_agent.py`,生成 schema 描述供 SQL Agent 使用
- [ ] 编写 `agents/sql_agent.py`,实现 Text-to-SQL 生成
- [ ] 编写 `executor.py`,实现 6 层安全防护
- [ ] 扩展 `cli.py`,支持 `--mode sql` 流式查询
- [ ] 编写 `tests/test_executor.py`,SQL 注入防护测试用例

### 验证命令
```bash
python cli.py --mode sql
> 茅台近5年营收复合增长率

# 预期输出:
# 📝 Schema Agent: 加载表结构...
# 🔧 SQL Agent: 生成 SQL 中...
# 📋 生成 SQL:
#    SELECT year, revenue FROM financial_statements
#    WHERE stock_code = '600519' ORDER BY year
# 🛡️ Executor: 通过 6 层安全检查
# 📊 执行结果:
#    年份    营收(亿)
#    2019    888.54
#    ...
# 💡 复合增长率: 14.32%
```

### 学习重点
- Text-to-SQL 提示词工程(schema 提示 + few-shot 示例)
- SQL 注入防护的多层工程实现
- LangGraph create_agent 用法
- 流式输出 + 工具事件监听

---

## Phase 3: RAG 链路 📄

**阶段目标**:实现多格式文档加载、切分、向量化、检索全流程,并可视化切分效果。

### 关键产出
| 文件 | 说明 |
|------|------|
| `doc_loader.py` | 多格式文档加载器 + 3 种切分策略对比 |
| `vector_store.py` | FAISS 向量库管理(单例 + 持久化 + 增量更新) |
| `agents/retriever_agent.py` | RAG 检索 Agent(向量检索 + MMR 重排 + 上下文组装) |
| `init_data.py` 扩展 | 生成模拟研报/公告/路演文档 + 构建向量索引 |
| `cli.py` 扩展 | 支持 `--mode rag` 和 `--mode split-demo` |

### 切分策略对比
| 策略 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **CharacterTextSplitter** | 简单文本 | 实现简单 | 容易切断语义 |
| **RecursiveCharacterTextSplitter** | 通用文档(推荐) | 尽量保持语义完整 | 参数需调优 |
| **MarkdownHeaderTextSplitter** | Markdown 文档 | 按标题切分,语义清晰 | 仅支持 Markdown |

### 任务清单
- [ ] 编写 `doc_loader.py`,支持 PDF/TXT/PPTX 三种格式加载
- [ ] 实现 3 种切分策略 + 效果对比工具
- [ ] 编写 `vector_store.py`,FAISS 向量库单例管理
- [ ] 编写 `agents/retriever_agent.py`,实现向量检索 + 上下文组装
- [ ] 扩展 `init_data.py`,生成 5 份研报 + 5 份公告 + 3 份路演 PPT
- [ ] 扩展 `cli.py`,支持 RAG 模式和切分效果演示
- [ ] 编写 `tests/test_retriever_agent.py`

### 验证命令
```bash
# 切分效果对比演示
python cli.py --mode split-demo
# 输出: 同一份研报用 3 种策略切分的 chunk 数量、平均大小、重叠率对比

# RAG 检索测试
python cli.py --mode rag
> 茅台 2024 年业绩展望

# 预期输出:
# 📄 Retriever Agent: 检索中...
# 🔍 找到 5 个相关片段 (top-5):
#   [1] research_pdf/中信证券-茅台2024深度报告.pdf (score: 0.91)
#        "预计 2024 年茅台营收同比增长 15%..."
#   [2] ...
```

### 学习重点
- LangChain 文档加载器统一接口(Document / Loader / Splitter)
- RecursiveCharacterTextSplitter 切分原理与参数调优
- FAISS 向量检索工程实践(similarity_search / MMR / save_local)
- Embedding 模型选型与维度配置
- 切分效果评估方法

---

## Phase 4: 多 Agent 编排 🎯

**阶段目标**:实现 Router 智能路由 + 总控编排 + 投研分析,端到端生成完整投研报告。

### 关键产出
| 文件 | 说明 |
|------|------|
| `prompts.py` 扩展 | Router / Analyst 系统提示词 |
| `agents/orchestrator.py` | 总控编排 Agent(Router + 状态机 + 流式输出) |
| `agents/analyst_agent.py` | 投研分析师 Agent(综合分析 + 投资建议 + 风险提示) |
| `render.py` | Markdown 投研报告渲染器 |
| `cli.py` 扩展 | 默认 `--mode full` 跑完整链路 |

### 路由决策逻辑
```
用户输入
  ↓
Router Agent 判断意图
  ├── 仅涉及数据查询 → SQL-only 模式
  ├── 仅涉及文档检索 → RAG-only 模式
  ├── 混合查询(既有数据又有文档) → Full 模式
  └── 无法判断 → 降级为 Full 模式(宁可多查不可漏查)
```

### 任务清单
- [ ] 扩展 `prompts.py`,添加 Router + Analyst 提示词
- [ ] 编写 `agents/orchestrator.py`,总控编排 + 工具化子 Agent
- [ ] 编写 `agents/analyst_agent.py`,投研分析 Agent
- [ ] 编写 `render.py`,Markdown 报告渲染
- [ ] 扩展 `cli.py`,full 模式端到端输出
- [ ] 完善流式输出(工具调用状态、进度显示)
- [ ] 编写 `tests/test_integration.py`

### 验证命令
```bash
python cli.py --mode full
> 分析茅台2023年财报,对比行业平均,引用最新研报给出投资建议

# 预期输出:
# 🔀 Router: 混合查询(SQL + RAG)
# 📊 SQL Agent: 查询中...
# 📄 Retriever Agent: 检索中...
# 📝 Analyst Agent: 综合分析中...
# ════════════════════════════════════
# 📌 贵州茅台(600519)投研分析报告
# ════════════════════════════════════
# 一、财务表现速览
#   ...
# 二、行业对比
#   ...
# 三、研究观点汇总
#   ...
# 四、投资建议
#   评级: 买入
#   ...
```

### 学习重点
- 多 Agent 编排模式(Router + Orchestrator + Tool-based)
- LangGraph 状态管理与事件流
- `astream_events` 流式输出 + 工具状态可视化
- Analyst 提示词工程(结构化输出 + 证据引用)
- Markdown 报告渲染设计

---

## Phase 5: 双形态接口 🌐

**阶段目标**:封装 FastAPI 后端 + Streamlit 前端,支持 Web 交互和程序化调用。

### 关键产出
| 文件 | 说明 |
|------|------|
| `api.py` | FastAPI 服务(REST + SSE 流式 + Swagger 文档) |
| `visualizer.py` | Plotly 图表生成(智能选图 + JSON 输出) |
| `app.py` | Streamlit Web 看板(多页面 + 交互) |

### FastAPI 接口清单
| 接口 | 方法 | 说明 |
|------|------|------|
| `/analyze` | POST | 投研分析(同步 + 流式 SSE 两种模式) |
| `/sql` | POST | 单跑 SQL 链路 |
| `/rag` | POST | 单跑 RAG 链路 |
| `/schema` | GET | 查看数据库 schema |
| `/docs` | GET | 文档库列表 |
| `/health` | GET | 健康检查 |

### Streamlit 看板页面
1. **投研分析**(主页)— 输入问题 → 生成报告 + 图表
2. **SQL 实验室** — 直接执行 SQL,查看结果 + 可视化
3. **文档检索** — 单测 RAG 检索,查看召回片段 + 相似度
4. **切分效果对比** — 上传文档,对比 3 种切分策略效果
5. **Schema 浏览** — 查看数据库表结构

### 任务清单
- [ ] 编写 `api.py`,FastAPI 服务 + SSE 流式响应
- [ ] 编写 `visualizer.py`,Plotly 智能选图(柱状/折线/饼图)
- [ ] 编写 `app.py`,Streamlit 多页面看板
- [ ] 完善错误处理 + 异常响应格式
- [ ] 编写 API 文档(Postman Collection / Swagger 示例)
- [ ] 编写 Streamlit 使用手册

### 验证命令
```bash
# 启动 FastAPI
uvicorn api:app --reload --host 0.0.0.0 --port 8000
# 浏览器打开: http://localhost:8000/docs (Swagger UI)

# 启动 Streamlit
streamlit run app.py --server.port 8501
# 浏览器打开: http://localhost:8501
```

### 学习重点
- FastAPI 接口设计(Pydantic 模型 + 依赖注入 + 异常处理)
- SSE (Server-Sent Events) 流式响应实现
- Streamlit 多页面 + 状态管理 + 组件化
- Plotly 图表集成 + JSON 序列化
- 前后端数据契约设计

---

## Phase 6: 工程化收尾 🏁

**阶段目标**:补全测试、爬虫、性能优化、文档,达到企业级交付标准。

### 关键产出
| 文件 | 说明 |
|------|------|
| `tests/test_sql_agent.py` | SQL 生成准确性测试(25+ 用例) |
| `tests/test_executor.py` | SQL 安全执行测试(15+ 注入用例) |
| `tests/test_retriever_agent.py` | RAG 召回效果测试(10+ 用例) |
| `tests/test_integration.py` | 端到端集成测试(8+ 用例) |
| `crawler.py` | 金融数据爬虫(默认关闭,需主动启用) |
| `docs/` 全部文档 | 架构/安全/RAG/API/部署/扩展/FAQ |
| 性能优化 | 数据库索引 + FAISS IVF + 批量化 |

### 爬虫设计原则
- **默认关闭**:CRAWLER_ENABLED=false,不主动抓取
- **合规检查**:启动时检查目标网站 robots.txt
- **礼貌爬取**:可配置延迟(默认 2 秒),限速
- **增量更新**:记录已抓取 URL,避免重复
- **数据隔离**:爬虫数据与模拟数据分目录存储

### 任务清单
- [ ] 补全所有测试文件,覆盖率 > 70%
- [ ] 编写 `crawler.py`,支持研报/公告抓取
- [ ] 数据库索引优化(stock_code, year, date 等字段)
- [ ] 容错机制完善(重试 + 降级 + 限流)
- [ ] 编写 Dockerfile + docker-compose.yml
- [ ] 补全 docs/ 下 8 份独立文档
- [ ] 性能基准测试 + 优化报告
- [ ] 最终联调 + README 最终完善

### 验证命令
```bash
# 全量测试
pytest tests/ -v --cov=. --cov-report=html
# 预期: 全部测试通过,覆盖率 > 70%

# 性能基准
python cli.py --benchmark
# 输出: SQL 平均耗时、RAG 平均耗时、端到端平均耗时

# Docker 构建
docker build -t fin-research-agent .
docker run -p 8000:8000 -p 8501:8501 fin-research-agent
```

### 学习重点
- 测试驱动开发(TDD)方法论
- 企业级容错(重试、降级、限流)工程实现
- 爬虫合规设计与工程实践
- Docker 容器化部署
- 性能优化方法论(数据库索引、向量索引、批量化)
- 技术文档写作规范

---

## 📊 阶段性学习成果检查清单

| 阶段完成 | 你将能独立完成 | 自检 ✓ |
|---------|--------------|--------|
| **Phase 1** | 设计金融数据库 schema,用 Python 操作 SQLite | ☐ |
| **Phase 2** | 实现 Text-to-SQL,带多层安全防护 | ☐ |
| **Phase 3** | 实现 RAG 全流程,对比评估切分策略效果 | ☐ |
| **Phase 4** | 设计多 Agent 协作架构,Router 自动路由 | ☐ |
| **Phase 5** | 提供 FastAPI + Streamlit 双形态产品级接口 | ☐ |
| **Phase 6** | 写出企业级质量的测试、文档和部署方案 | ☐ |

---

## ⏱️ 节奏建议

### 推荐学习节奏
- **每天 1 个 Phase**,6 天完成 MVP
- **第 7 天** 回顾优化 + 写简历项目描述
- **遇到卡点** 优先跳过,标记 TODO,后续回头补

### 每阶段产出标准
每完成一个 Phase,请:
1. ✅ 跑一遍验证命令,确保功能可用
2. ✅ 运行该阶段相关测试,全部通过
3. ✅ Git commit 一次,message 用 `feat(phase-x): ...`
4. ✅ 在本文件勾选已完成项
5. ✅ 简短记录学到的 1-2 个核心知识点

### 建议提交格式
每次阶段完成 commit 后,在项目根目录记录:
```
docs/progress.md
  Phase 1 ✅ - 2026-07-27
    学到: SQLite 索引设计、单例模式线程安全
    卡点: 日期字段的 SQL 聚合(已解决,用 strftime)
```

---

## 🎓 完成标准

当以下全部达成时,项目视为完成:

- [ ] 6 个 Phase 全部完成
- [ ] 所有测试通过 (`pytest tests/ -v` 全绿)
- [ ] CLI / FastAPI / Streamlit 三端均可正常使用
- [ ] docs/ 下 8 份文档全部编写完成
- [ ] README.md 最终版确认
- [ ] Docker 镜像可构建并运行
- [ ] 简历项目描述定稿
