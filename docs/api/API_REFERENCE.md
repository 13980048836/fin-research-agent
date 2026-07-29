# 📡 API 接口文档

> FastAPI 接口完整说明,包含入参、出参、示例和错误码。

---

## 1. 接口总览

| 接口 | 方法 | 路径 | 说明 | 是否需要 API Key |
|------|------|------|------|-----------------|
| 健康检查 | GET | `/health` | 服务状态检查 | 否 |
| 投研分析(同步) | POST | `/analyze` | 完整投研分析 | 是(服务端) |
| 投研分析(流式) | POST | `/analyze/stream` | SSE 流式输出 | 是(服务端) |
| SQL 查询 | POST | `/sql` | 单跑 Text-to-SQL 链路 | 是 |
| RAG 检索 | POST | `/rag` | 单跑 RAG 检索链路 | 是 |
| Schema 查询 | GET | `/schema` | 查看数据库表结构 | 否 |
| 文档库列表 | GET | `/docs` | 查看已索引文档列表 | 否 |
| 配置信息 | GET | `/config` | 查看当前配置(脱敏) | 否 |

**Base URL**: `http://localhost:8000`

**文档地址**:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## 2. 通用约定

### 2.1 请求头

```
Content-Type: application/json
```

### 2.2 响应格式

所有接口返回统一的 JSON 格式:

```json
{
  "code": 0,
  "message": "success",
  "data": { ... }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 状态码,0 表示成功,非 0 表示错误 |
| `message` | string | 描述信息 |
| `data` | object | 响应数据,错误时可能为 null |

### 2.3 错误码

| code | HTTP 状态 | 说明 |
|------|----------|------|
| 0 | 200 | 成功 |
| 1001 | 400 | 参数错误 |
| 1002 | 401 | 未授权(预留) |
| 1003 | 429 | 请求频率超限 |
| 2001 | 500 | LLM 调用失败 |
| 2002 | 500 | 数据库查询失败 |
| 2003 | 500 | 向量库操作失败 |
| 2004 | 500 | SQL 生成失败 |
| 3001 | 500 | 内部服务器错误 |

---

## 3. 接口详情

### 3.1 健康检查

**GET** `/health`

检查服务是否正常运行。

**响应示例**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "healthy",
    "version": "0.1.0",
    "llm_connected": true,
    "db_connected": true,
    "vector_store_loaded": true,
    "doc_count": 13,
    "table_count": 4
  }
}
```

---

### 3.2 投研分析(同步)

**POST** `/analyze`

输入自然语言查询,返回完整投研报告。适用于非实时场景。

**请求体**:
```json
{
  "query": "分析茅台2023年财报,对比行业平均,引用最新研报给出投资建议",
  "mode": "auto",
  "include_chart": true,
  "stream": false
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `query` | string | ✅ | - | 用户查询的自然语言 |
| `mode` | string | - | `auto` | 分析模式:`sql` / `rag` / `hybrid` / `auto`(自动路由) |
| `include_chart` | boolean | - | `true` | 是否包含可视化图表 |
| `top_k` | int | - | 5 | RAG 召回数量(覆盖配置) |

**成功响应**(200):
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "分析茅台2023年财报,对比行业平均,引用最新研报给出投资建议",
    "mode": "hybrid",
    "sql_result": {
      "sql": "SELECT year, revenue, net_profit, roe, ...",
      "columns": ["year", "revenue", "net_profit", "roe", "debt_ratio"],
      "rows": [
        [2023, 1505.6, 751.3, 0.302, 0.185],
        [2022, 1275.5, 627.2, 0.285, 0.198]
      ],
      "row_count": 5
    },
    "rag_results": [
      {
        "content": "预计 2024 年茅台营收同比增长 15%...",
        "source": "research_pdf/中信证券-茅台2024深度报告.pdf",
        "page": 3,
        "score": 0.91
      }
    ],
    "report_markdown": "# 贵州茅台(600519)投研分析报告\n\n...",
    "chart": {
      "type": "bar",
      "title": "茅台 vs 行业平均 ROE 对比",
      "plotly_json": { ... }
    },
    "usage": {
      "total_tokens": 3200,
      "prompt_tokens": 2800,
      "completion_tokens": 400,
      "latency_ms": 5200
    }
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `mode` | string | 实际使用的分析模式 |
| `sql_result` | object \| null | SQL 查询结果(sql-only/hybrid 模式有值) |
| `rag_results` | array \| null | RAG 召回结果(rag-only/hybrid 模式有值) |
| `report_markdown` | string | 投研报告(Markdown 格式) |
| `chart` | object \| null | 可视化图表数据 |
| `usage` | object | Token 消耗和耗时统计 |

**错误响应**(500):
```json
{
  "code": 2001,
  "message": "LLM 调用失败: 超时,已重试 3 次",
  "data": null
}
```

---

### 3.3 投研分析(流式 SSE)

**POST** `/analyze/stream`

SSE (Server-Sent Events) 流式输出,实时返回生成进度。

**请求体**:同 `/analyze`

**响应类型**:`text/event-stream`

**事件流格式**:
```
event: router
data: {"mode": "hybrid", "confidence": 0.85}

event: sql_start
data: {"message": "正在查询数据库..."}

event: sql_end
data: {"row_count": 5, "sql": "SELECT ..."}

event: rag_start
data: {"message": "正在检索文档..."}

event: rag_end
data: {"chunk_count": 5}

event: report_token
data: {"token": "#"}

event: report_token
data: {"token": "贵州茅台"}

event: chart
data: {"type": "bar", "plotly_json": {...}}

event: done
data: {"total_tokens": 3200, "latency_ms": 5200}
```

**事件类型**:

| event | 说明 | data 内容 |
|-------|------|-----------|
| `router` | 路由决策完成 | `{ mode, confidence }` |
| `sql_start` | SQL 查询开始 | `{ message }` |
| `sql_end` | SQL 查询完成 | `{ row_count, sql }` |
| `rag_start` | RAG 检索开始 | `{ message }` |
| `rag_end` | RAG 检索完成 | `{ chunk_count }` |
| `report_token` | 报告生成 token | `{ token }` |
| `chart` | 图表生成完成 | `{ type, plotly_json }` |
| `done` | 全部完成 | `{ total_tokens, latency_ms }` |
| `error` | 发生错误 | `{ code, message }` |

**前端调用示例**(JavaScript):
```javascript
const eventSource = new EventSource('/analyze/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: '茅台怎么样' })
});

eventSource.addEventListener('report_token', (e) => {
  const data = JSON.parse(e.data);
  reportElement.innerHTML += data.token;
});

eventSource.addEventListener('done', (e) => {
  console.log('完成', JSON.parse(e.data));
  eventSource.close();
});
```

**cURL 调用示例**（实时流式输出）:

```bash
# 最简调用
curl -N -X POST http://localhost:8000/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台近5年营收复合增长率"}'

# 指定 SQL 模式
curl -N -X POST http://localhost:8000/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "白酒行业平均ROE", "mode": "sql"}'

# 不包含图表
curl -N -X POST http://localhost:8000/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "分析茅台财报", "include_chart": false}'

# 保存到文件（同时观看输出）
curl -N -X POST http://localhost:8000/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台怎么样"}' 2>&1 | tee sse_output.txt
```

> `curl -N` 参数用于禁用缓冲，确保实时收到 SSE 事件流。

---

### 3.4 SQL 查询

**POST** `/sql`

单独调用 Text-to-SQL 链路,用于调试或单独使用。

**请求体**:
```json
{
  "query": "近5年白酒行业平均ROE是多少",
  "raw_sql": null,
  "include_explain": true
}
```

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | string | ✅ | 自然语言查询 |
| `raw_sql` | string | - | 直接执行 SQL(调试用,绕过 LLM 生成) |
| `include_explain` | boolean | - | 是否包含 EXPLAIN 查询计划 |

**成功响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "近5年白酒行业平均ROE是多少",
    "generated_sql": "SELECT year, AVG(roe) as avg_roe FROM financial_statements WHERE industry = '白酒' AND year >= 2019 GROUP BY year ORDER BY year",
    "result": {
      "columns": ["year", "avg_roe"],
      "rows": [
        [2019, 0.195],
        [2020, 0.210],
        [2021, 0.228],
        [2022, 0.225],
        [2023, 0.225]
      ],
      "row_count": 5
    },
    "explain": "SCAN financial_statements\nFILTER industry = '白酒'\nUSE INDEX idx_stock_code",
    "execution_time_ms": 12
  }
}
```

---

### 3.5 RAG 检索

**POST** `/rag`

单独调用 RAG 检索链路。

**请求体**:
```json
{
  "query": "茅台 2024 业绩预测",
  "top_k": 5,
  "min_score": 0.6,
  "include_raw": false
}
```

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `query` | string | ✅ | - | 查询文本 |
| `top_k` | int | - | 5 | 返回数量 |
| `min_score` | float | - | 0.6 | 最低相似度阈值 |
| `include_raw` | boolean | - | false | 是否返回原始 chunk 对象 |

**成功响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "query": "茅台 2024 业绩预测",
    "results": [
      {
        "content": "预计 2024 年茅台营收同比增长 15%,净利润增长 12-15%...",
        "source": "research_pdf/中信证券-茅台2024深度报告.pdf",
        "page": 3,
        "score": 0.91,
        "category": "research_pdf"
      }
    ],
    "total_count": 5,
    "avg_score": 0.82,
    "search_time_ms": 45
  }
}
```

---

### 3.6 Schema 查询

**GET** `/schema`

获取数据库表结构,用于调试或前端展示。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `table` | string | - | 指定表名,不传则返回所有表 |

**成功响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "tables": [
      {
        "name": "stocks",
        "description": "股票基本信息表",
        "columns": [
          { "name": "stock_code", "type": "TEXT", "primary_key": true, "description": "股票代码" },
          { "name": "name", "type": "TEXT", "description": "股票名称" },
          { "name": "industry", "type": "TEXT", "description": "所属行业" }
        ],
        "row_count": 10
      }
    ]
  }
}
```

---

### 3.7 文档库列表

**GET** `/docs`

获取已索引的文档列表。

**查询参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `category` | string | - | 按分类过滤: `research_pdf` / `announcement_txt` / `roadshow_ppt` |

**成功响应**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "total_docs": 13,
    "total_chunks": 287,
    "docs": [
      {
        "filename": "中信证券-茅台2024深度报告.pdf",
        "category": "research_pdf",
        "size_bytes": 524288,
        "chunk_count": 18,
        "indexed_at": "2026-07-26T10:00:00Z"
      }
    ]
  }
}
```

---

## 4. cURL 示例

### 健康检查
```bash
curl http://localhost:8000/health
```

### 同步投研分析
```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "query": "茅台近5年营收复合增长率",
    "mode": "sql"
  }'
```

### 流式投研分析
```bash
curl -N -X POST http://localhost:8000/analyze/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台怎么样"}'
```

### SQL 查询
```bash
curl -X POST http://localhost:8000/sql \
  -H "Content-Type: application/json" \
  -d '{"query": "白酒行业平均ROE"}'
```

### RAG 检索
```bash
curl -X POST http://localhost:8000/rag \
  -H "Content-Type: application/json" \
  -d '{"query": "茅台 2024 预测", "top_k": 3}'
```

---

## 5. Python SDK 示例

```python
import requests

BASE_URL = "http://localhost:8000"

def analyze(query: str, mode: str = "auto") -> dict:
    """同步投研分析"""
    resp = requests.post(
        f"{BASE_URL}/analyze",
        json={"query": query, "mode": mode}
    )
    resp.raise_for_status()
    return resp.json()["data"]

def analyze_stream(query: str, on_token=None):
    """流式投研分析"""
    import json
    resp = requests.post(
        f"{BASE_URL}/analyze/stream",
        json={"query": query},
        stream=True
    )
    for line in resp.iter_lines():
        if line.startswith(b"data: "):
            data = json.loads(line[6:])
            if on_token:
                on_token(data)

# 使用
result = analyze("茅台近5年营收")
print(result["report_markdown"])
```

---

## 6. 相关文件

| 文件 | 说明 |
|------|------|
| `api.py` | FastAPI 服务实现 |
| `docs/api/STREAMLIT_GUIDE.md` | Streamlit 看板使用手册 |
| `config.py` | API 相关配置 |
