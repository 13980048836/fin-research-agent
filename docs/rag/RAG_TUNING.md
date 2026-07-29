# 🔍 RAG 调优指南

> 详细说明 RAG 全流程的可调参数、切分策略对比、召回优化方法与效果评估。

---

## 1. RAG 全流程概览

```
原始文档 → 文档加载 → 文档切分 → 向量化 → 存入向量库 → 查询向量化 → 相似度检索 → 重排 → 上下文组装 → LLM 生成
  ↑         ↑          ↑          ↑          ↑            ↑            ↑          ↑           ↑
  ①格式     ②加载器    ③切分策略   ④Embedding  ⑤索引类型    ⑥TopK       ⑦重排算法   ⑧组装方式    ⑨Prompt
```

每个环节都有可调参数,最终影响召回精度和生成质量。

---

## 2. 文档加载

### 2.1 支持的格式

| 格式 | 加载器 | 适用场景 | 注意事项 |
|------|--------|---------|---------|
| **PDF** | `PyPDFLoader` | 券商研报、白皮书 | 扫描版 PDF 需先 OCR |
| **TXT** | `TextLoader` | 公司公告、新闻 | 编码需为 UTF-8 |
| **PPTX** | `UnstructuredPowerPointLoader` | 路演资料、演讲 | 仅提取文字,丢失图表 |

### 2.2 加载注意事项

1. **编码问题**:TXT 文件确保 UTF-8 编码,否则中文乱码
2. **PDF 质量**:扫描版 PDF 需用 OCR(如 PaddleOCR)预处理
3. **表格处理**:PDF 中的表格可能被打散,影响语义完整性
4. **页眉页脚**:重复的页眉页脚会增加噪声,建议预处理去除

---

## 3. 切分策略详解

### 3.1 三种切分策略对比

| 策略 | 原理 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| **固定大小切分** (CharacterTextSplitter) | 按固定字符数切分,可选重叠 | 实现简单,速度快 | 容易切断语义,上下文断裂 | 简单文本、性能要求高 |
| **递归字符切分** (RecursiveCharacterTextSplitter) | 按分隔符优先级递归切分,尽量保持语义单元 | 语义完整性好,中文友好 | 参数需调优,略慢 | **通用场景(推荐)** |
| **Markdown 标题切分** (MarkdownHeaderTextSplitter) | 按 Markdown 标题层级切分 | 语义单元最清晰,天然分段 | 仅支持 Markdown 格式 | 结构化 Markdown 文档 |

### 3.2 递归切分分隔符优先级

默认分隔符列表(按优先级从高到低):
```
\n\n    段落分隔
\n      换行
。！？   中文句号/感叹/问号
.!?     英文句号/感叹/问号
，、    中文逗号/顿号
,;      英文逗号/分号
        空格
```

切分逻辑:从第一个分隔符开始尝试,如果切完后 chunk 仍大于 `chunk_size`,就用下一级分隔符继续切。

### 3.3 关键参数调优

| 参数 | 默认值 | 影响 | 调优建议 |
|------|-------|------|---------|
| `CHUNK_SIZE` | 500 字符 | 越大上下文越完整,但粒度粗召回准度下降 | 中文文档建议 300-800 |
| `CHUNK_OVERLAP` | 50 字符 | 越大上下文连贯性越好,但冗余增加存储 | 通常为 chunk_size 的 10-20% |
| 分隔符列表 | 见上 | 分隔符越丰富,切分越智能 | 中文文档确保包含中文标点 |

### 3.4 切分效果评估指标

| 指标 | 说明 | 计算方式 | 理想值 |
|------|------|---------|--------|
| **Chunk 数量** | 切分后总块数 | 直接计数 | 越少越好(但粒度要够) |
| **平均 Chunk 大小** | 平均字符数 | 总字符数 / chunk 数 | 接近目标 chunk_size |
| **Chunk 大小方差** | 大小均匀程度 | 标准差 / 平均值 | 越小越均匀 |
| **语义完整性** | 切断句子的比例 | 人工抽样评估 | < 5% |
| **重叠率** | 重叠字符占比 | overlap / chunk_size | 10-20% |

### 3.5 切分效果对比演示

运行以下命令查看同一份文档用 3 种策略切分的对比:

```bash
python cli.py --mode split-demo
```

输出示例:
```
📊 切分效果对比 (文档: 中信证券-茅台2024深度报告.pdf, 约 8000 字)

┌────────────────────┬──────────┬──────────┬──────────┬──────────┐
│ 策略               │ Chunk数  │ 平均大小  │ 最大/最小 │ 切断句数  │
├────────────────────┼──────────┼──────────┼──────────┼──────────┤
│ 固定大小切分        │ 18       │ 445      │ 500/120  │ 7        │
│ 递归字符切分(推荐)  │ 16       │ 500      │ 520/380  │ 2        │
│ 标题切分           │ 9        │ 889      │ 1200/200 │ 0        │
└────────────────────┴──────────┴──────────┴──────────┴──────────┘

💡 建议:递归字符切分在语义完整性和粒度控制之间平衡最好
```

---

## 4. Embedding 选型

### 4.1 可用 Embedding 模型

| 模型 | 维度 | 中文效果 | 速度 | 费用 | 适用场景 |
|------|------|---------|------|------|---------|
| **通义 text-embedding-v2** | 1536 | ⭐⭐⭐⭐ | 快 | 低 | 通用中文场景(默认) |
| BAAI/bge-large-zh-v1.5 | 1024 | ⭐⭐⭐⭐⭐ | 中 | 免费(本地) | 对中文精度要求高 |
| text2vec-large-chinese | 1024 | ⭐⭐⭐⭐ | 中 | 免费(本地) | 轻量级场景 |

### 4.2 Embedding 质量影响因素

1. **模型与文档领域匹配度**:通用 Embedding 在金融专业文档上效果可能下降
2. **向量维度**:维度越高表达能力越强,但存储和计算成本越高
3. **批处理大小**:批量向量化比单条快,但受 API 限流限制

---

## 5. 向量检索

### 5.1 FAISS 索引类型

| 索引类型 | 查询速度 | 内存占用 | 精度 | 适用场景 |
|---------|---------|---------|------|---------|
| **Flat** (默认) | 慢(O(n)) | 高(全量) | 100% 精确 | 文档 < 1 万条 |
| **IVF** | 快(对数级) | 中 | 近似 | 文档 1 万 - 100 万 |
| **HNSW** | 极快 | 高(比 Flat 高 50%) | 近似 | 文档 > 100 万,低延迟要求 |

切换索引类型的配置:
```python
# 在 vector_store.py 中修改
index = faiss.IndexIVFFlat(dimension, nlist)
```

### 5.2 TopK 调优

| TopK 值 | 召回率 | 精度 | LLM 上下文占用 | 适用场景 |
|---------|-------|------|---------------|---------|
| 3 | 低 | 高 | 少 | 简单查询,答案明确 |
| **5**(默认) | 中 | 中 | 中 | **通用场景** |
| 10 | 高 | 低(噪声多) | 多 | 复杂查询,需要全面信息 |

调优建议:
- 先从 5 开始,根据效果调整
- 如果召回的文档相关性都很高,可以增加 TopK
- 如果召回的文档很多不相关,减少 TopK 或优化切分

### 5.3 MMR 多样性重排

MMR (Maximal Marginal Relevance) 在相关性和多样性之间做平衡:

```
MMR = λ × 相关性 - (1-λ) × 与已选文档的最大相似度
```

| λ 值 | 效果 | 适用场景 |
|------|------|---------|
| 1.0 | 完全按相似度排序(默认行为) | 精确查询 |
| 0.7 | 相关性为主,兼顾多样性 | 通用场景(推荐) |
| 0.5 | 平衡 | 探索性查询 |
| 0.3 | 多样性为主 | 需要多角度信息 |

配置方式:
```bash
FAISS_MMR_ENABLED=true
FAISS_MMR_LAMBDA=0.7
```

---

## 6. 高级优化策略

### 6.1 混合检索(BM25 + 向量)

向量检索擅长语义匹配，但对精确关键词(如股票代码、专业术语)召回可能不足。混合检索结合两者优势:

```
查询
  ├── 向量检索 → top-20 候选
  ├── BM25 关键词检索 → top-20 候选
  └── 融合重排 → top-5 最终结果
```

**预计提升**:召回率提升 15-30%，尤其对专业术语类查询

**接入代码示例**:

```python
# 安装依赖
# pip install rank_bm25 langchain

from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

def build_hybrid_retriever(vector_store, documents, top_k: int = 5):
    """构建 BM25 + 向量混合检索器"""

    # 1. BM25 关键词检索器
    bm25_retriever = BM25Retriever.from_documents(documents)
    bm25_retriever.k = 20  # BM25 初筛 top-20

    # 2. FAISS 向量检索器
    vector_retriever = vector_store.as_retriever(
        search_type="similarity",
        search_kwargs={"k": 20}  # 向量初筛 top-20
    )

    # 3. 融合检索器
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, vector_retriever],
        weights=[0.4, 0.6],  # BM25 权重 0.4, 向量权重 0.6
    )

    return ensemble_retriever


# 使用方式
retriever = build_hybrid_retriever(vector_store, all_docs, top_k=5)
results = retriever.get_relevant_documents("茅台 2024 营收预测")
# 返回前已做融合 + 去重 + 截取 top-k
```

**调优建议**:
- 权重 `[0.3, 0.7]` 到 `[0.5, 0.5]` 之间微调
- 中文场景 BM25 需先分词（接入 jieba 等中文分词器）
- 初筛数量建议为最终 top-k 的 3-5 倍

---

### 6.2 Rerank 重排

用专门的重排模型对初筛结果做精细排序，精度比单纯向量检索高很多：

```
向量检索 → top-20 → Rerank 模型重排 → top-5
```

**常用重排模型**:
- BCE Embedding Reranker（开源，中文效果好，本地部署）
- 通义千问 Rerank API（云端 API，零部署）
- Cohere Rerank（海外模型，中文一般）

**预计提升**:Top-k 精度提升 20-40%

**接入代码示例（通义千问 Rerank API）**:

```python
import dashscope
from dashscope import TextReRank

def rerank_with_tongyi(query: str, documents: list[str], top_n: int = 5) -> list[int]:
    """
    用通义千问 Rerank API 重排文档。

    Args:
        query: 查询文本
        documents: 文档文本列表
        top_n: 返回前 N 个

    Returns:
        重排后的文档索引列表（按相关性从高到低）
    """
    resp = TextReRank.call(
        model='gte-rerank',
        query=query,
        documents=documents,
        top_n=top_n,
        return_documents=False,
    )

    if resp.status_code == 200:
        results = resp.output.results
        return [r.index for r in results]
    else:
        print(f"Rerank 失败: {resp.code} - {resp.message}")
        return list(range(min(top_n, len(documents))))  # 降级：按原顺序


# 集成到检索流程
def search_with_rerank(vector_store, query: str, k: int = 5, rerank_top_n: int = 20):
    """向量初筛 + Rerank 精排"""
    # 1. 向量检索粗筛
    docs = vector_store.similarity_search(query, k=rerank_top_n)

    # 2. Rerank 精排
    doc_texts = [d.page_content for d in docs]
    reranked_indices = rerank_with_tongyi(query, doc_texts, top_n=k)

    # 3. 按重排顺序返回
    return [docs[i] for i in reranked_indices]
```

**接入代码示例（本地 BCE Reranker）**:

```python
# pip install modelscope transformers torch
from modelscope.models import Model
from modelscope.pipelines import pipeline

_reranker = None

def get_local_reranker():
    """懒加载本地重排模型（首次加载较慢）"""
    global _reranker
    if _reranker is None:
        model_id = "damo/nlp_gte_sentence-embedding_chinese-base"
        _reranker = pipeline(
            task="text-ranking",
            model=model_id,
        )
    return _reranker


def rerank_local(query: str, documents: list[str], top_n: int = 5) -> list[int]:
    """本地重排，无需调用 API"""
    reranker = get_local_reranker()
    result = reranker({
        "query": query,
        "documents": documents,
    })
    # 返回 top_n 索引
    return [r["index"] for r in result["scores"][:top_n]]
```

**注意事项**:
- Rerank 会增加一次调用延迟（约 0.5-2 秒）
- 本地模型需 GPU 才能跑快，CPU 上较慢
- 生产环境建议缓存高频查询的 Rerank 结果

### 6.3 查询重写(Query Rewrite)

用 LLM 把用户的自然语言查询重写成更适合检索的形式:

```
原始查询: "茅台怎么样"
重写后: "贵州茅台 600519 投资价值分析 业绩预测 风险评估"
```

**适用场景**:用户输入模糊、简短、口语化

### 6.4 父子文档(Parent-Child Chunking)

检索用小 chunk(精度高),返回时返回父文档(上下文完整):

```
大文档 → 切分为大 chunk(父, 2000字) → 每个父 chunk 再切小 chunk(子, 200字)
                                                         ↓
                                                  子 chunk 做向量索引
                                                         ↓
检索时用子 chunk 匹配 → 找到后返回对应的父 chunk 给 LLM
```

**优点**:检索粒度细,生成时上下文完整
**成本**:索引存储翻倍

---

## 7. 效果评估方法

### 7.1 评估指标

| 指标 | 说明 | 计算方式 |
|------|------|---------|
| **Recall@K** | 前 K 个结果中相关文档占所有相关文档的比例 | 相关且在前K / 总相关数 |
| **Precision@K** | 前 K 个结果中相关文档的比例 | 相关且在前K / K |
| **MRR** | 第一个相关文档的排名倒数的平均值 | 1/rank 的平均 |
| **NDCG@K** | 考虑排名位置的归一化折损累计增益 | 加权排名 |

### 7.2 评估数据集

建议构建 50-100 条标注数据:
- 查询(query)
- 相关文档列表(ground truth,人工标注)
- 不相关文档列表

### 7.3 评估流程

```bash
# 1. 准备评估数据集 (tests/fixtures/rag_benchmark.json)

# 2. 运行评估
python -m scripts.evaluate_rag

# 3. 查看报告
# Recall@5: 0.72
# Precision@5: 0.68
# MRR: 0.81
```

---

## 8. 常见问题调优指南

| 问题 | 可能原因 | 调优方案 |
|------|---------|---------|
| **召回的文档都不相关** | Embedding 模型不匹配 / 切分太粗 | 换金融领域 Embedding / 减小 chunk_size |
| **召回了很多但都是重复内容** | 切分重叠太大 / 缺乏多样性 | 减小 overlap / 开启 MMR |
| **LLM 回答找不到依据** | 召回的文档不含答案 / TopK 太小 | 增加 TopK / 优化查询重写 |
| **回答有依据但不准确** | 切分把答案切断了 / 上下文不够 | 减小 chunk_size / 增加 overlap / 用父子文档 |
| **检索速度慢** | 文档太多 / 用了 Flat 索引 | 切换到 IVF / HNSW 索引 |
| **长文档效果差** | 关键信息分散在多个 chunk | 用父子文档 / 增加 chunk_size |

---

## 9. 调优最佳实践

1. **从默认值开始**:先用默认参数跑通,再逐步调优
2. **固定变量**:一次只调一个参数,观察效果变化
3. **量化评估**:用评估数据集量化效果,不要靠感觉
4. **记录实验**:每次调优记录参数和效果,便于回溯
5. **关注瓶颈**:找到效果最差的环节,针对性优化
6. **平衡精度和成本**:不是越复杂越好,根据场景选择合适方案

---

## 10. 相关文件

| 文件 | 说明 |
|------|------|
| `doc_loader.py` | 文档加载 + 切分 + 效果对比工具 |
| `vector_store.py` | FAISS 向量库管理 |
| `agents/retriever_agent.py` | RAG 检索 Agent |
| `config.py` | RAG 相关配置 |
| `tests/test_retriever_agent.py` | RAG 测试用例 |
