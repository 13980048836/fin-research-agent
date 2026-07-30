# ==================== 构建阶段 ====================
FROM python:3.11-slim AS builder

# 编译依赖（faiss-cpu / sentence-transformers 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 单独拷贝 requirements，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ==================== 运行阶段 ====================
FROM python:3.11-slim AS runtime

# 运行时只需 libgomp（faiss 依赖 OpenMP）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 拷贝构建阶段安装的依赖
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HUB_OFFLINE=0

WORKDIR /app

# 拷贝源码
COPY . .

# 数据目录（运行时挂载卷覆盖）
RUN mkdir -p /app/data /app/faiss_index /app/docs

# 健康检查（FastAPI /health 端点）
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# 默认启动 API；web 服务在 compose 里 override
EXPOSE 8000 8501
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
