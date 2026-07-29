# 🚀 本地运行指南（QUICKSTART）

> 本文档带你从零开始，一步步把金融投研助手跑起来。
> 预计耗时：10-20 分钟（取决于网络速度）

---

## 📋 环境要求

| 项目 | 要求 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | 推荐 3.11 / 3.12 |
| 内存 | ≥ 4 GB | 小规模场景够用，向量检索建议 8GB+ |
| 磁盘 | ≥ 2 GB | 数据库 + 向量索引 + 依赖 |
| 网络 | 可访问外网 | 调用通义千问 API 需要 |
| API Key | 通义千问 API Key | 免费额度即可测试 |

### 获取 API Key

1. 访问 [阿里云百炼控制台](https://dashscope.console.aliyun.com/apiKey)
2. 注册/登录阿里云账号
3. 创建 API Key 并复制
4. 新用户有免费额度，足够测试使用

---

## 🛠️ 第一步：安装依赖

### 方式 A：一键安装所有依赖（推荐）

```bash
cd fin-research-agent
pip install -r requirements.txt
```

### 方式 B：分步安装（网络不好时用）

```bash
# 1. 核心 LLM + Agent 框架
pip install langchain langchain-core langchain-community dashscope python-dotenv

# 2. RAG 相关
pip install faiss-cpu langchain-text-splitters pypdf python-pptx sqlparse tiktoken

# 3. Web 服务
pip install fastapi uvicorn streamlit pydantic sse-starlette

# 4. 可视化 + 爬虫（可选）
pip install plotly requests beautifulsoup4

# 5. 测试工具（可选）
pip install pytest pytest-asyncio pytest-cov
```

### 验证安装

```bash
python -c "import langchain; import dashscope; import faiss; print('✅ 所有核心依赖安装成功')"
```

---

## 🔑 第二步：配置 API Key

### 方式 A：环境变量（推荐，临时测试用）

**Windows PowerShell:**
```powershell
$env:DASHSCOPE_API_KEY = "sk-你的API密钥"
```

**Windows CMD:**
```cmd
set DASHSCOPE_API_KEY=sk-你的API密钥
```

**Linux / macOS:**
```bash
export DASHSCOPE_API_KEY=sk-你的API密钥
```

### 方式 B：.env 文件（长期使用推荐）

```bash
# 复制模板
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
# DASHSCOPE_API_KEY=sk-你的API密钥
```

---

## 📊 第三步：初始化数据

### 完整初始化（数据库 + 文档 + 向量索引）

```bash
python init_data.py
```

输出类似下面就成功了：
```
📊 创建数据库表结构...
📈 插入股票基础数据...
✅ 数据库初始化完成
   - 股票: 3 只
   - 年度财务数据: 18 条
   - 季度数据: 72 条
📝 模拟文档生成完成: 8 份
🔍 加载了 8 个文件，切分为 11 个片段
📊 正在构建向量索引...
✅ 向量索引构建完成
```

### 分步初始化（调试时用）

```bash
# 仅初始化数据库
python init_data.py --db-only

# 仅生成模拟文档
python init_data.py --docs-only

# 仅构建向量索引
python init_data.py --vector

# 强制重建（数据更新后）
python init_data.py --force

# 跳过向量索引（不需要 RAG 时）
python init_data.py --no-vector
```

### 验证数据

```bash
# 运行单元测试
python -m unittest discover tests -v

# 预期结果: 22 个测试全部通过
```

---

## 🧪 第四步：跑通 CLI 测试

### 1. SQL 模式（最快验证）

```bash
python cli.py --mode sql --query "茅台近5年的营收和净利润"
```

**预期输出：**
- 生成 SQL 并执行
- 返回结构化的财务分析报告
- 包含核心结论、财务分析、风险提示等

### 2. RAG 模式

```bash
python cli.py --mode rag --query "茅台中报业绩怎么样"
```

**预期输出：**
- 从研报中检索相关片段
- 生成基于文档的分析

### 3. 混合模式（完整链路）

```bash
python cli.py --mode hybrid --query "贵州茅台的投资价值分析"
```

**预期输出：**
- 同时查询 SQL 数据库和研报文档
- 生成专业的投研分析报告
- 包含财务数据 + 研报观点 + 估值分析 + 风险提示

### 4. 交互式模式

```bash
python cli.py --mode hybrid
```

进入聊天界面，输入问题即可持续对话。输入 `exit` 退出。

### 5. 切分效果演示

```bash
python cli.py --mode split-demo
```

对比三种切分策略的效果差异。

---

## 🌐 第五步：启动 Web 服务

### 方式 A：FastAPI 后端服务

```bash
python -m uvicorn api:app --host 0.0.0.0 --port 8000
```

启动后访问：
- 健康检查: http://localhost:8000/health
- 系统统计: http://localhost:8000/api/v1/stats
- API 文档: http://localhost:8000/docs
- Redoc 文档: http://localhost:8000/redoc

#### 测试 API

```bash
# 健康检查
curl http://localhost:8000/health

# 系统统计
curl http://localhost:8000/api/v1/stats

# SQL 查询
curl -X POST http://localhost:8000/api/v1/sql/query \
  -H "Content-Type: application/json" \
  -d '{"sql": "SELECT * FROM stocks"}'

# 投研分析（非流式）
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台怎么样", "mode": "hybrid"}'

# 投研分析（SSE 流式）
curl -N -X POST http://localhost:8000/api/v1/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台怎么样", "mode": "hybrid"}'
```

### 方式 B：Streamlit Web 界面

```bash
streamlit run streamlit_app.py
```

启动后浏览器自动打开（默认 http://localhost:8501 ）。

**功能特点：**
- 聊天式交互界面
- 侧边栏切换分析模式
- 快速问题一键提问
- 显示生成的 SQL 和检索来源
- 实时流式输出

### 方式 C：同时启动后端 + 前端（推荐）

```bash
# 终端 1：启动后端
python -m uvicorn api:app --port 8000

# 终端 2：启动前端
streamlit run streamlit_app.py
```

---

## 🐛 常见问题排查

### 1. API Key 配置后仍报错

**症状**: `ValueError: 请配置 DASHSCOPE_API_KEY`

**解决方法:**
```bash
# Windows PowerShell 检查
echo $env:DASHSCOPE_API_KEY

# 如果为空，重新设置
$env:DASHSCOPE_API_KEY = "sk-你的key"

# 或者用 .env 文件
# 确保 .env 文件在项目根目录，且 key 没有引号包裹
```

### 2. 端口被占用

**症状**: `Address already in use` 或 `以一种访问权限不允许的方式做了一个访问套接字的尝试`

**解决方法:**
```bash
# 换端口启动
python -m uvicorn api:app --port 8080
streamlit run streamlit_app.py --server.port 8502

# 或查找并结束占用进程
netstat -ano | findstr :8000
taskkill /PID <进程ID> /F
```

### 3. FAISS 安装失败

**症状**: `faiss-cpu` 安装报错

**解决方法:**
```bash
# 用国内镜像源
pip install faiss-cpu -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或者只装必须的依赖，跳过 FAISS（用 SQLite 全文检索替代）
pip install langchain langchain-community dashscope
```

### 4. 数据库被锁定

**症状**: `database is locked`

**解决方法:**
- 关闭其他正在访问数据库的程序
- 检查是否有多个 Python 进程在运行
- SQLite 不支持高并发写入，读取不受影响

### 5. 向量索引构建失败

**症状**: 初始化时跳过了向量索引构建

**解决方法:**
```bash
# 确认 API Key 有效
# 手动构建索引
python init_data.py --vector --force
```

### 6. 中文显示乱码（Windows）

**症状**: 控制台输出中文变成乱码

**解决方法:**
```bash
# PowerShell 中设置编码
chcp 65001
$OutputEncoding = [System.Text.Encoding]::UTF8
```

---

## 📁 数据文件说明

初始化完成后，`data/` 目录结构如下：

```
data/
├── finance.db              # SQLite 数据库（所有结构化数据）
├── faiss_index/            # FAISS 向量索引
│   ├── index.faiss         # 索引文件
│   └── index.pkl           # 元数据
└── docs/
    ├── research_pdf/       # 研报文档（5 份模拟）
    ├── announcements/      # 公告文档（3 份模拟）
    ├── roadshow_ppt/       # 路演 PPT（预留）
    └── crawled/            # 爬虫抓取（预留）
```

---

## ⏱️ 快速验证清单

从零到跑通，按这个顺序验证最快：

| 步骤 | 命令 | 通过标准 | 预计耗时 |
|------|------|---------|---------|
| 1 | `pip install -r requirements.txt` | 安装无报错 | 2-5 分钟 |
| 2 | `python -m unittest discover tests -v` | 22 个测试全过 | < 30 秒 |
| 3 | `python init_data.py --db-only` | 数据库生成成功 | < 10 秒 |
| 4 | `python cli.py --mode sql --query "茅台营收"` | 返回分析报告 | 10-30 秒 |
| 5 | `python init_data.py` | 向量索引构建成功 | 30-60 秒 |
| 6 | `python cli.py --mode hybrid --query "茅台投资价值"` | 完整报告 | 30-60 秒 |
| 7 | `python -m uvicorn api:app --port 8000` | /health 返回 ok | < 10 秒 |
| 8 | `streamlit run streamlit_app.py` | 浏览器打开界面 | < 10 秒 |

---

## 📚 进阶阅读

- 完整架构说明: [架构设计文档](./docs/architecture/ARCHITECTURE.md)
- SQL 安全防护: [安全规范](./docs/architecture/SECURITY.md)
- RAG 优化调优: [RAG 调优指南](./docs/rag/RAG_TUNING.md)
- API 接口文档: [API 参考](./docs/api/API_REFERENCE.md)
- 部署运维指南: [部署文档](./docs/deployment/DEPLOYMENT.md)
- 扩展开发指南: [扩展指南](./docs/extend/EXTEND_GUIDE.md)
- 常见问题: [FAQ](./docs/FAQ.md)

---

## ✅ 完成！

恭喜你，项目已经跑起来了 🎉

接下来你可以：
1. 试试不同的查询问题，测试效果
2. 修改提示词，优化回答质量
3. 添加更多行业数据，扩展业务范围
4. 开启新功能开发（可视化、多用户、爬虫等）
