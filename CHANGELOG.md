# 📝 更新日志 (CHANGELOG)

> 本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 规范，
> 版本号遵循 [语义化版本 (Semantic Versioning)](https://semver.org/lang/zh-CN/)。

---

## 版本格式说明

```
[MAJOR.MINOR.PATCH] - YYYY-MM-DD
```

- **MAJOR**: 不兼容的 API 改动
- **MINOR**: 向下兼容的功能性新增
- **PATCH**: 向下兼容的问题修正

### 变更类型

| 类型 | 说明 |
|------|------|
| `Added` | 新功能 |
| `Changed` | 功能变更 |
| `Deprecated` | 即将废弃 |
| `Removed` | 已移除 |
| `Fixed` | Bug 修复 |
| `Security` | 安全相关 |
| `Performance` | 性能优化 |
| `Docs` | 文档更新 |

---

## [0.2.0] - 2026-07-26

### Added
- **核心架构**
  - `config.py` — 统一配置中心（9 大类配置，dataclass 管理）
  - `db.py` — 数据库连接管理（只读模式 + 线程安全 + Schema 查询）
  - `executor.py` — SQL 安全执行器（6 层防护：关键字/语法/只读/行数/超时/权限）
  - `prompts.py` — 集中式提示词管理（Router/SQL/Retriever/Analyst 4 类 Agent）
- **多 Agent 协作**
  - `agents/specialist.py` — Agent 基类（LLM 封装 + 流式 + JSON 解析）
  - `agents/router_agent.py` — 路由 Agent（关键词快速路由 + LLM 精准路由）
  - `agents/sql_agent.py` — SQL Agent（Schema 理解 + Text-to-SQL + 执行）
  - `agents/retriever_agent.py` — 检索 Agent（向量检索 + MMR 重排）
  - `agents/analyst_agent.py` — 分析师 Agent（结构化投研报告生成）
  - `orchestrator.py` — 编排器（Router → [SQL+RAG] → Analyst，支持 SSE 流式）
- **RAG 模块**
  - `doc_loader.py` — 多格式文档加载（PDF/TXT/MD/PPTX）+ 3 种切分策略 + 对比工具
  - `vector_store.py` — FAISS 向量库管理（单例 + 持久化 + 增量更新）
- **服务层**
  - `api.py` — FastAPI 服务（健康检查/分析接口/SSE 流式/SQL 查询与校验）
  - `streamlit_app.py` — Streamlit Web 界面（聊天式交互 + 侧边栏配置 + 快速问题）
  - `cli.py` — CLI 入口（5 种模式 + 交互/单次查询 + 切分演示）
- **数据初始化**
  - `init_data.py` 扩展：支持 `--db-only` / `--docs-only` / `--vector` / `--no-vector` 等参数
  - 5 份模拟研报 + 3 份模拟公告
- **测试**
  - `tests/test_executor.py` — 15 个 SQL 安全防护测试用例（全部通过）
  - `tests/test_doc_loader.py` — 7 个文档加载/切分测试用例（全部通过）

### Docs
- CHANGELOG.md 新增 v0.2.0 记录

---

## [0.1.1] - 2026-07-26

### Docs
- README.md 补充最小 demo 一行命令
- README.md 补充硬件配置分级（小规模/中规模/大规模）
- README.md 补充高频报错速查表（6 项）
- README.md 新增长期 Roadmap（v1.0 / v1.1 / v1.2 / v2.0）
- README.md 新增已知 Bug 清单（5 项）
- docs/api/API_REFERENCE.md 补充 SSE 接口 cURL 调用示例（4 个场景）
- docs/rag/RAG_TUNING.md 补充 BM25 混合检索完整接入代码
- docs/rag/RAG_TUNING.md 补充 Rerank 重排接入示例（通义 API + 本地 BCE）
- docs/extend/EXTEND_GUIDE.md 新增爬虫扩展章节（单份研报抓取示例 + 集成代码）
- docs/extend/EXTEND_GUIDE.md 新增多行业扩展章节（新能源/医药/半导体等 6 行业）
- docs/extend/EXTEND_GUIDE.md 补充多语言扩展说明

---

## [0.1.0] - 2026-07-26

### Added
- 项目蓝图与架构设计文档
- 6 阶段实施计划 (IMPLEMENTATION_PLAN.md)
- 9 份详细技术文档 (docs/)
  - 架构设计文档 (ARCHITECTURE.md)
  - SQL 安全规范 (SECURITY.md)
  - RAG 调优指南 (RAG_TUNING.md)
  - API 接口文档 (API_REFERENCE.md)
  - Streamlit 使用手册 (STREAMLIT_GUIDE.md)
  - 部署运维指南 (DEPLOYMENT.md)
  - 扩展开发指南 (EXTEND_GUIDE.md)
  - 常见问题 FAQ (FAQ.md)
- 项目目录骨架 (agents/, data/, tests/, docs/)
- requirements.txt (带版本约束)
- .env.example (9 大类 20+ 配置项)
- 金融合规免责声明

### Docs
- README.md 包含业务边界、技术架构、安全规范、部署扩展等全量信息

---

## 模板 (复制使用)

> 下一版本发布时，复制以下模板填充内容

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- 新增功能 1
- 新增功能 2

### Changed
- 变更的功能 1

### Deprecated
- 即将废弃的功能 1

### Removed
- 已移除的功能 1

### Fixed
- 修复的 Bug 1
- 修复的 Bug 2

### Security
- 安全修复 1

### Performance
- 性能优化 1

### Docs
- 文档更新 1
```

---

## 发布流程

1. 修改代码并提交
2. 更新本文件（在顶部添加新版本）
3. 更新 README 中的版本号
4. Git 打 tag: `git tag vX.Y.Z`
5. 推送: `git push --tags`
