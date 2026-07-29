# 🚀 部署运维指南

> 从本地开发到生产部署的完整指南,包含 Docker 化、数据库迁移、向量库扩展、性能优化。

---

## 1. 部署方式总览

| 部署方式 | 适用场景 | 难度 | 并发能力 |
|---------|---------|------|---------|
| 本地直接运行 | 开发、演示 | ★☆☆ | 单用户 |
| Docker 单容器 | 单服务器测试 | ★★☆ | 10-50 QPS |
| Docker Compose | 小团队生产 | ★★☆ | 50-200 QPS |
| Kubernetes | 大规模生产 | ★★★ | 无限扩展 |

---

## 2. Docker 部署

### 2.1 Dockerfile

```dockerfile
# ===== 基础镜像 =====
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建数据目录
RUN mkdir -p data/faiss_index data/docs/research_pdf data/docs/announcement_txt data/docs/roadshow_ppt

# 初始化数据(构建时执行一次)
RUN python init_data.py

# 暴露端口
EXPOSE 8000 8501

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动 FastAPI(可通过 command 覆盖)
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2.2 构建与运行

```bash
# 构建镜像
docker build -t fin-research-agent:latest .

# 运行 FastAPI
docker run -d \
  --name fin-api \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  fin-research-agent:latest

# 运行 Streamlit
docker run -d \
  --name fin-streamlit \
  -p 8501:8501 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  --entrypoint streamlit \
  fin-research-agent:latest \
  run app.py --server.port 8501 --server.address 0.0.0.0

# 查看日志
docker logs -f fin-api

# 停止
docker stop fin-api fin-streamlit
```

### 2.3 Docker Compose

`docker-compose.yml`:

```yaml
version: '3.8'

services:
  api:
    build: .
    container_name: fin-api
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
    env_file:
      - .env
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  streamlit:
    build: .
    container_name: fin-streamlit
    ports:
      - "8501:8501"
    volumes:
      - ./data:/app/data
    env_file:
      - .env
    entrypoint: streamlit
    command: run app.py --server.port 8501 --server.address 0.0.0.0
    depends_on:
      api:
        condition: service_healthy
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: fin-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

**启动**:
```bash
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f api
docker-compose logs -f streamlit

# 停止
docker-compose down
```

---

## 3. 数据库迁移

SQLite 适合开发和小规模使用。数据量超过 10GB 或需要高并发时,建议迁移到 PostgreSQL 或 MySQL。

### 3.1 迁移到 PostgreSQL

#### 步骤 1:安装依赖

```bash
pip install psycopg2-binary sqlalchemy
```

#### 步骤 2:修改配置

`.env` 中添加:
```bash
# ===== 数据库配置(PostgreSQL) =====
DB_TYPE=postgresql
DB_HOST=localhost
DB_PORT=5432
DB_NAME=fin_research
DB_USER=fin_user
DB_PASSWORD=your_password
```

#### 步骤 3:修改 db_client.py

将 SQLite 连接替换为 SQLAlchemy + psycopg2:

```python
from sqlalchemy import create_engine, text

class DBClient:
    def __init__(self):
        if CONFIG.db_type == "postgresql":
            self.engine = create_engine(
                f"postgresql+psycopg2://{CONFIG.db_user}:{CONFIG.db_password}"
                f"@{CONFIG.db_host}:{CONFIG.db_port}/{CONFIG.db_name}",
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20
            )
        else:
            # SQLite 模式
            ...
    
    def execute_query(self, sql: str, params=None):
        with self.engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            return result.fetchall()
```

#### 步骤 4:数据迁移

```bash
# 导出 SQLite 数据
sqlite3 data/finance.db .dump > finance_dump.sql

# 在 PostgreSQL 中创建表并导入
# (需要手动调整 SQL 语法,SQLite 和 PG 有差异)
psql -U fin_user -d fin_research -f finance_dump.sql
```

### 3.2 迁移到 MySQL

类似 PostgreSQL,使用 `pymysql` 驱动:

```python
self.engine = create_engine(
    f"mysql+pymysql://{CONFIG.db_user}:{CONFIG.db_password}"
    f"@{CONFIG.db_host}:{CONFIG.db_port}/{CONFIG.db_name}"
)
```

### 3.3 迁移注意事项

| 注意点 | SQLite | PostgreSQL | MySQL |
|--------|--------|------------|-------|
| 自增主键 | `INTEGER PRIMARY KEY` | `SERIAL` / `BIGSERIAL` | `AUTO_INCREMENT` |
| 字符串类型 | `TEXT` | `TEXT` / `VARCHAR` | `TEXT` / `VARCHAR` |
| 浮点类型 | `REAL` | `FLOAT` / `NUMERIC` | `FLOAT` / `DECIMAL` |
| 日期函数 | `strftime('%Y', date)` | `EXTRACT(YEAR FROM date)` | `YEAR(date)` |
| 分页 | `LIMIT offset, count` | `LIMIT count OFFSET offset` | `LIMIT offset, count` |
| 字符串拼接 | `\|\|` | `\|\|` 或 `CONCAT` | `CONCAT` |

---

## 4. 向量库扩展

FAISS 本地索引适合 100 万向量以内。文档量更大或需要多机部署时,迁移到分布式向量数据库。

### 4.1 迁移到 Milvus

Milvus 是云原生向量数据库,支持亿级向量检索。

#### Docker 部署 Milvus

```bash
# 下载 docker-compose
wget https://github.com/milvus-io/milvus/releases/download/v2.3.0/milvus-standalone-docker-compose.yml -O docker-compose.milvus.yml

# 启动
docker-compose -f docker-compose.milvus.yml up -d
```

#### 修改 vector_store.py

```python
from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType

class VectorStore:
    def __init__(self):
        if CONFIG.vector_db_type == "milvus":
            connections.connect(
                alias="default",
                host=CONFIG.milvus_host,
                port=CONFIG.milvus_port
            )
            self.collection = Collection(CONFIG.milvus_collection)
        else:
            # FAISS 模式
            ...
```

### 4.2 迁移到 Qdrant

Qdrant 是 Rust 写的高性能向量数据库,部署简单。

```bash
# Docker 启动 Qdrant
docker run -d -p 6333:6333 qdrant/qdrant
```

### 4.3 向量库选型对比

| 维度 | FAISS | Milvus | Qdrant | Weaviate |
|------|-------|--------|--------|----------|
| 部署难度 | 零(库) | 中(Docker集群) | 易(单Docker) | 中 |
| 单机最大向量数 | 100-1000万 | 亿级 | 千万级 | 千万级 |
| 分布式 | ❌ | ✅ | ✅ | ✅ |
| 过滤能力 | 弱 | 强 | 强 | 强 |
| 多租户 | ❌ | ✅ | ✅ | ✅ |
| 运维复杂度 | 低 | 高 | 中 | 中 |
| 适用规模 | 小型 | 大型企业 | 中小型 | 中小型 |

---

## 5. 性能优化

### 5.1 数据库优化

| 优化点 | 方案 | 预计提升 |
|--------|------|---------|
| 索引优化 | 给 `stock_code`, `year`, `date`, `industry` 建索引 | 查询 5-10 倍 |
| 连接池 | 使用 SQLAlchemy 连接池 | 高并发 3-5 倍 |
| 读写分离 | 主从复制,读请求走从库 | 读性能线性扩展 |
| 缓存 | Redis 缓存热门查询结果 | 重复查询 10-100 倍 |
| 分区表 | 按日期分区 `daily_quotes` 表 | 大表查询 5-10 倍 |

**索引示例**:
```sql
CREATE INDEX idx_stock_code ON financial_statements(stock_code);
CREATE INDEX idx_year ON financial_statements(year);
CREATE INDEX idx_industry ON stocks(industry);
CREATE INDEX idx_date ON daily_quotes(date);
CREATE INDEX idx_stock_date ON daily_quotes(stock_code, date);
```

### 5.2 向量检索优化

| 优化点 | 方案 | 预计提升 |
|--------|------|---------|
| 索引类型 | Flat → IVF → HNSW | 检索 10-100 倍 |
| 批量向量化 | 并发 + 批处理 Embedding 调用 | 构建 3-5 倍 |
| 量化 | PCA 降维 / 产品量化 | 内存减少 50-75% |
| 缓存 | 热门查询向量缓存 | 重复查询 10 倍+ |

**FAISS IVF 索引示例**:
```python
import faiss

dimension = 1536
nlist = 100  # 聚类中心数

quantizer = faiss.IndexFlatL2(dimension)
index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
index.train(vectors)  # 训练聚类中心
index.add(vectors)   # 添加向量
index.nprobe = 10    # 搜索时探查的聚类数
```

### 5.3 LLM 调用优化

| 优化点 | 方案 | 预计提升 |
|--------|------|---------|
| 流式输出 | SSE 逐 token 返回 | 体感提升 50%+ |
| 结果缓存 | 相同问题直接返回缓存结果 | 重复查询几乎零延迟 |
| 并发调用 | SQL 和 RAG 并行执行 | 端到端时间减少 30% |
| 提示词压缩 | 精简 schema 描述和上下文 | 速度提升 20-30% |
| 模型分级 | 简单问题用 turbo,复杂用 plus | 成本降低 50% |

### 5.4 RAG 优化

| 优化点 | 方案 | 预计提升 |
|--------|------|---------|
| 混合检索 | BM25 + 向量融合 | 召回 +15-30% |
| Rerank | 重排模型精排 | Top-k 精度 +20-40% |
| 查询重写 | LLM 改写查询后再检索 | 模糊查询 +20% |
| 父子文档 | 小 chunk 检索,大 chunk 返回 | 答案完整性 +30% |
| 增量索引 | 新文档只向量化一次 | 构建速度大幅提升 |

---

## 6. 监控与运维

### 6.1 关键监控指标

| 指标 | 说明 | 告警阈值 |
|------|------|---------|
| API 响应时间 | p50 / p95 / p99 | p95 > 30s 告警 |
| 错误率 | 5xx / 总请求 | > 5% 告警 |
| LLM 调用次数 | 每日 token 消耗量 | 超过预算 80% 告警 |
| 数据库连接数 | 活跃连接数 / 池大小 | > 80% 告警 |
| 向量库查询时间 | 单次检索耗时 | > 500ms 告警 |
| 内存使用率 | 进程内存占用 | > 80% 告警 |
| 磁盘使用率 | 数据目录磁盘空间 | > 80% 告警 |

### 6.2 日志规范

```python
import logging

logger = logging.getLogger("fin-research")

# 日志级别
# DEBUG: 详细调试信息(开发环境)
# INFO: 正常流程信息(生产环境)
# WARNING: 警告信息(降级、重试)
# ERROR: 错误信息(调用失败)
# CRITICAL: 严重错误(服务不可用)
```

### 6.3 备份策略

| 数据 | 备份频率 | 保留时长 | 方式 |
|------|---------|---------|------|
| SQLite 数据库 | 每日 | 30 天 | 定时复制 + 压缩 |
| FAISS 索引 | 每周 | 30 天 | 文件快照 |
| 文档源文件 | 每月 | 永久 | 对象存储 |
| 配置文件 | 每次变更 | 永久 | Git 版本控制 |

---

## 7. 安全加固

### 7.1 网络安全
- 服务不直接暴露公网,前置 Nginx 反向代理
- 启用 HTTPS(Let's Encrypt)
- 配置 IP 白名单或 API Key 鉴权

### 7.2 数据安全
- 数据库定期备份
- 敏感配置(API Key)通过环境变量注入,不写死代码
- 日志中脱敏处理(不记录完整 API Key)

### 7.3 API 安全
- 限流:防止滥用
- 鉴权:生产环境增加 API Key 校验
- 输入校验:所有输入参数做长度和格式校验

---

## 8. 相关文件

| 文件 | 说明 |
|------|------|
| `config.py` | 所有可配置项 |
| `db_client.py` | 数据库连接(需修改以支持 PG/MySQL) |
| `vector_store.py` | 向量库管理(需修改以支持 Milvus/Qdrant) |
| `requirements.txt` | 依赖清单 |
