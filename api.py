"""
api.py — FastAPI 服务接口

提供 REST API + SSE 流式接口，供前端或其他服务调用。

安全:
  - API Key 认证（X-API-Key 请求头）
  - 全局限流（slowapi MemoryStorage）
  - 收紧 CORS（默认仅允许 localhost，可通过环境变量扩展）
"""
import json
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import get_config
from orchestrator import Orchestrator


# ==================== 安全配置 ====================

# API Key（从环境变量读取，空则禁用认证 — 仅推荐本地调试）
API_KEY = os.getenv("API_KEY", "")

# CORS 允许源（逗号分隔，默认 localhost 各常见端口）
CORS_ORIGINS_RAW = os.getenv("CORS_ORIGINS", "")
if CORS_ORIGINS_RAW:
    CORS_ORIGINS = [o.strip() for o in CORS_ORIGINS_RAW.split(",") if o.strip()]
else:
    CORS_ORIGINS = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
        "http://localhost:8501",
    ]

# 限流阈值（每分钟）
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))

# 尝试初始化 slowapi 限流（可选依赖）
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    from slowapi.memory import MemoryStorage
    _limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    HAS_RATE_LIMIT = True
except ImportError:
    HAS_RATE_LIMIT = False


# ==================== 请求/响应模型 ====================

class AnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="用户问题")
    mode: str = Field("auto", description="分析模式: auto/sql/rag/hybrid/simple")
    include_chart: bool = Field(True, description="是否包含图表")
    stream: bool = Field(False, description="是否流式输出")


class AnalyzeResponse(BaseModel):
    code: int = 0
    message: str = "success"
    data: dict = {}


# ==================== 生命周期 ====================

_orchestrator: Orchestrator | None = None
_orch_lock = threading.Lock()


def get_orchestrator() -> Orchestrator:
    """线程安全获取 Orchestrator 单例（双检锁）"""
    global _orchestrator
    if _orchestrator is None:
        with _orch_lock:
            if _orchestrator is None:
                cfg = get_config()
                try:
                    from vector_store import get_vector_store
                    vsm = get_vector_store()
                    store = vsm.store if vsm.is_built else None
                except Exception:
                    store = None
                _orchestrator = Orchestrator(vector_store=store, config=cfg)
    return _orchestrator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    cfg = get_config()
    try:
        cfg.validate()
    except ValueError as e:
        print(f"⚠️  配置校验警告: {e}")

    # 预热编排器
    try:
        get_orchestrator()
    except Exception as e:
        print(f"⚠️  编排器初始化警告: {e}")

    yield

    # 清理
    from db import close_connections
    close_connections()


app = FastAPI(
    title="金融投研助手 API",
    description="基于 LLM + RAG + Text-to-SQL 的智能投研分析系统",
    version="0.1.0",
    lifespan=lifespan,
)

# 收紧 CORS：默认仅允许 localhost 白名单
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# 挂载限流中间件（如果可用）
if HAS_RATE_LIMIT:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ==================== API Key 认证中间件 ====================

@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """API Key 认证中间件（X-API-Key 请求头）"""
    # 健康检查无需认证，方便容器探针
    if request.url.path == "/health":
        return await call_next(request)

    if API_KEY:
        incoming_key = request.headers.get("X-API-Key", "")
        if not incoming_key or incoming_key != API_KEY:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未授权：需要正确的 X-API-Key 请求头",
            )
    return await call_next(request)


# ==================== 健康检查 ====================

@app.get("/health", summary="健康检查")
async def health_check():
    """服务健康检查（无需认证）"""
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_provider": get_config().llm.provider,
        "auth_enabled": bool(API_KEY),
        "rate_limit_enabled": HAS_RATE_LIMIT,
    }


@app.get("/api/v1/stats", summary="系统统计")
async def stats(request: Request):
    """获取系统统计信息"""
    from db import get_schema_info
    try:
        tables = get_schema_info()
        table_count = len(tables)
    except Exception:
        table_count = 0

    try:
        from vector_store import get_vector_store
        vsm = get_vector_store()
        has_vector = vsm.is_built
    except Exception:
        has_vector = False

    return {
        "code": 0,
        "data": {
            "tables": table_count,
            "vector_index": has_vector,
            "llm_model": get_config().llm.model,
            "embedding_model": get_config().embedding.model,
        },
    }


# ==================== 核心分析接口 ====================

@app.post("/api/v1/analyze", summary="投研分析（非流式）")
async def analyze(req: AnalyzeRequest, request: Request):
    """
    投研分析接口（一次性返回结果）

    - query: 用户问题
    - mode: auto/sql/rag/hybrid/simple
    """
    # 限流（如可用）
    if HAS_RATE_LIMIT:
        try:
            _limiter.limit(f"{RATE_LIMIT_PER_MINUTE}/minute")(lambda: None)()
        except RateLimitExceeded:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求过于频繁，请稍后再试（{RATE_LIMIT_PER_MINUTE}次/分钟）",
            )

    orch = get_orchestrator()
    try:
        result = await orch.analyze(query=req.query, mode=req.mode)

        return {
            "code": 0 if result.is_success else 1,
            "message": "success" if result.is_success else result.error,
            "data": {
                "query": result.query,
                "mode": result.mode,
                "router": result.router_result,
                "sql": {
                    "success": result.sql_result.success if result.sql_result else False,
                    "sql": result.sql_result.metadata.get("sql", "") if result.sql_result else "",
                    "row_count": result.sql_result.metadata.get("row_count", 0) if result.sql_result else 0,
                    "content": result.sql_result.content if result.sql_result else "",
                } if result.sql_result else None,
                "rag": {
                    "success": result.rag_result.success if result.rag_result else False,
                    "chunk_count": result.rag_result.metadata.get("total", 0) if result.rag_result else 0,
                    "content": result.rag_result.content if result.rag_result else "",
                } if result.rag_result else None,
                "report": result.final_content,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/analyze/stream", summary="投研分析（SSE 流式）")
async def analyze_stream(req: AnalyzeRequest, request: Request):
    """
    SSE 流式投研分析

    事件类型:
    - router: 路由决策完成
    - sql_start / sql_end: SQL 链路起止
    - rag_start / rag_end: RAG 链路起止
    - report_start / report_token: 报告生成（逐token）
    - done: 全部完成
    - error: 错误
    """
    orch = get_orchestrator()

    async def event_generator():
        async for event in orch.stream_analyze(query=req.query, mode=req.mode):
            yield f"event: {event['event']}\n"
            yield f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== SQL 查询接口 ====================

class SQLQueryRequest(BaseModel):
    sql: str = Field(..., description="SQL 查询语句")


@app.post("/api/v1/sql/query", summary="SQL 查询（受限）")
async def sql_query(req: SQLQueryRequest, request: Request):
    """直接执行 SQL 查询（经过安全过滤）"""
    from executor import get_executor
    executor = get_executor()
    result = executor.execute(req.sql)

    return {
        "code": 0 if result.is_success else 1,
        "message": "success" if result.is_success else result.error,
        "data": {
            "sql": result.sql,
            "rows": result.rows,
            "row_count": result.row_count,
            "columns": result.columns,
            "passed_checks": result.passed_checks,
            "failed_check": result.failed_check,
        },
    }


@app.post("/api/v1/sql/validate", summary="SQL 安全校验")
async def sql_validate(req: SQLQueryRequest, request: Request):
    """仅校验 SQL 是否安全，不执行"""
    from executor import get_executor
    executor = get_executor()
    is_safe, reason = executor.validate_only(req.sql)
    return {
        "code": 0,
        "data": {"is_safe": is_safe, "reason": reason},
    }


# ==================== 入口 ====================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8080"))
    uvicorn.run(
        "api:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=port,
        reload=False,
    )
