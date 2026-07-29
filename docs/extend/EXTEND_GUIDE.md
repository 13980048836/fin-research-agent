# 🔧 扩展开发指南

> 如何在现有架构基础上扩展新功能:新增数据表、文档格式、Agent、可视化图表等。

---

## 1. 扩展原则

1. **开闭原则**:对扩展开放,对修改关闭。尽量不修改核心代码。
2. **接口统一**:新增组件遵循现有接口规范,便于替换。
3. **配置驱动**:可调参数通过 `.env` 配置,不硬编码。
4. **测试覆盖**:新增功能必须附带单元测试。
5. **文档同步**:代码 + 文档同步更新。

---

## 2. 新增数据表

场景:新增 `dividends`(分红记录表)、`holdings`(持仓表)等新表。

### 2.1 步骤

**Step 1**:在 `init_data.py` 中添加建表语句和模拟数据

```python
def init_dividends_table(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS dividends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            dividend_per_share REAL,
            payout_ratio REAL,
            record_date TEXT,
            ex_dividend_date TEXT
        )
    ''')
    # 插入模拟数据...
    conn.commit()
```

**Step 2**:更新 `db_client.py` 中的 schema 缓存(如适用)

```python
# 如果有 schema 描述缓存,需要更新
SCHEMA_DESCRIPTIONS = {
    "stocks": "...",
    "financial_statements": "...",
    "dividends": "分红记录表,包含每股分红、股息率、分红日期等",
}
```

**Step 3**:更新 `prompts.py` 中 SQL Agent 的提示词

在 schema 说明中添加新表的描述和 few-shot 示例:

```python
SQL_AGENT_PROMPT = """
...
可用表:
- stocks: 股票基本信息
- financial_statements: 财务报表
- dividends: 分红记录表 (字段: stock_code, year, dividend_per_share, payout_ratio)

示例:
用户: 茅台近5年每股分红是多少?
SQL: SELECT year, dividend_per_share FROM dividends WHERE stock_code = '600519' ORDER BY year
...
"""
```

**Step 4**:添加索引(可选,但推荐)

```python
CREATE INDEX idx_dividends_stock ON dividends(stock_code);
CREATE INDEX idx_dividends_year ON dividends(year);
```

**Step 5**:编写测试

```python
# tests/test_sql_agent.py
def test_dividend_query():
    result = sql_agent.invoke("茅台每股分红")
    assert "dividends" in result["sql"].lower()
```

### 2.2 注意事项
- 表名和字段名用英文,加中文注释
- 考虑与现有表的关联关系(外键)
- 补充 few-shot 示例能大幅提升 SQL 生成准确率

---

## 3. 新增文档格式

场景:新增 Word(.docx)、Excel(.xlsx)、Markdown(.md)、HTML 等格式支持。

### 3.1 步骤

**Step 1**:在 `doc_loader.py` 中添加新的加载器

```python
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    UnstructuredWordDocumentLoader,   # 新增
    UnstructuredExcelLoader,          # 新增
    UnstructuredMarkdownLoader,       # 新增
)

# 扩展名 → 加载器类 的映射
LOADER_MAP = {
    ".pdf": PyPDFLoader,
    ".txt": TextLoader,
    ".pptx": UnstructuredPowerPointLoader,
    ".docx": UnstructuredWordDocumentLoader,   # 新增
    ".xlsx": UnstructuredExcelLoader,          # 新增
    ".md": UnstructuredMarkdownLoader,         # 新增
}

def get_loader(file_path: str):
    """根据文件扩展名获取对应加载器"""
    ext = os.path.splitext(file_path)[1].lower()
    loader_cls = LOADER_MAP.get(ext)
    if loader_cls is None:
        raise ValueError(f"不支持的文件格式: {ext}")
    return loader_cls(file_path)
```

**Step 2**:安装对应依赖

```bash
# Word
pip install python-docx

# Excel
pip install openpyxl

# 或者用 unstructured 全家桶
pip install unstructured[all-docs]
```

**Step 3**:在 `data/docs/` 下新增对应目录(可选)

```bash
mkdir data/docs/word_docx
mkdir data/docs/excel_xlsx
mkdir data/docs/markdown
```

**Step 4**:在 `vector_store.py` 中更新索引构建逻辑(如果按目录分类)

### 3.2 注意事项
- 不同格式的加载质量差异大,建议先做抽样测试
- Excel 表格转纯文本可能丢失结构,复杂表格考虑先转 CSV
- Markdown 格式可以用 MarkdownHeaderTextSplitter 获得更好的切分效果

---

## 4. 新增 Agent

场景:新增风险评估 Agent、估值计算 Agent、新闻摘要 Agent 等。

### 4.1 步骤(以 RiskAgent 为例)

**Step 1**:在 `agents/` 下新建文件 `risk_agent.py`

```python
"""
风险评估 Agent — 分析投资风险。

输入: 公司财务数据 + 行业信息
输出: 风险等级 + 风险点分析
"""
from agents.specialist import SpecialistAgent

RISK_AGENT_PROMPT = """你是风险评估专家...
[完整的系统提示词,包含输出格式要求]
"""

class RiskAgent(SpecialistAgent):
    def __init__(self, llm):
        super().__init__(
            llm=llm,
            name="RiskAgent",
            system_prompt=RISK_AGENT_PROMPT,
            tools=[]  # 如果需要调用工具,在这里注册
        )

    async def analyze(self, stock_code: str, financial_data: str) -> str:
        """分析指定股票的投资风险"""
        query = f"分析股票 {stock_code} 的投资风险,财务数据如下:\n{financial_data}"
        return await self.invoke(query)
```

**Step 2**:在 `prompts.py` 中添加对应提示词(或放在 agent 文件顶部)

**Step 3**:在 `orchestrator.py` 中注册为 Tool

```python
from agents.risk_agent import RiskAgent

class Orchestrator:
    async def build(self):
        # ... 现有代码 ...
        
        self._risk_agent = RiskAgent(self.llm)
        await self._risk_agent.build()
        
        @tool
        async def analyze_risk(stock_code: str) -> str:
            """分析股票投资风险。输入股票代码,返回风险评估。"""
            financial_data = await self._get_financial_data(stock_code)
            return await self._risk_agent.analyze(stock_code, financial_data)
        
        # 将新 tool 加入 tools 列表
        all_tools = [..., analyze_risk]
```

**Step 4**:更新 `orchestrator.py` 的系统提示词,说明新 tool 的用途

**Step 5**:编写测试

```python
# tests/test_risk_agent.py
import pytest
from agents.risk_agent import RiskAgent

@pytest.mark.asyncio
async def test_risk_analysis():
    agent = RiskAgent(llm)
    await agent.build()
    result = await agent.analyze("600519", "ROE 30%, 资产负债率 18%")
    assert "风险" in result
```

### 4.2 注意事项
- 继承 `SpecialistAgent` 基类,复用 build/invoke/stream 逻辑
- 新 Agent 的输入输出格式最好结构化,方便总控解析
- 如果 Agent 需要调用外部工具,在 `__init__` 中传入 tools 列表

---

## 5. 自定义可视化图表

场景:新增散点图、热力图、雷达图、K线图等。

### 5.1 步骤

**Step 1**:在 `visualizer.py` 中添加新图表类型

```python
def _detect_chart_type(df: pd.DataFrame) -> str:
    """根据数据结构自动选择图表类型"""
    cols = df.columns.tolist()
    
    # 散点图: 两个数值列,无时间字段
    if len(cols) == 2 and _is_numeric(df[cols[0]]) and _is_numeric(df[cols[1]]):
        return "scatter"
    
    # 热力图: 矩阵结构
    if _is_matrix(df):
        return "heatmap"
    
    # ... 现有逻辑 (bar/line/pie)
    
    return "bar"  # 默认柱状图


def _generate_scatter(df: pd.DataFrame, title: str) -> dict:
    """生成散点图"""
    import plotly.express as px
    x_col = df.columns[0]
    y_col = df.columns[1]
    fig = px.scatter(df, x=x_col, y=y_col, title=title)
    return json.loads(fig.to_json())


def _generate_heatmap(df: pd.DataFrame, title: str) -> dict:
    """生成热力图"""
    import plotly.figure_factory as ff
    fig = ff.create_annotated_heatmap(
        z=df.values,
        x=list(df.columns),
        y=list(df.index),
        annotation_text=df.values.round(2).astype(str),
    )
    fig.update_layout(title=title)
    return json.loads(fig.to_json())
```

**Step 2**:在 `generate_chart` 函数中注册新类型

```python
CHART_GENERATORS = {
    "bar": _generate_bar,
    "line": _generate_line,
    "pie": _generate_pie,
    "scatter": _generate_scatter,    # 新增
    "heatmap": _generate_heatmap,    # 新增
}
```

**Step 3**:添加自动检测逻辑(如果希望自动选新图)

在 `_detect_chart_type` 中添加对应判断。

**Step 4**:在 Streamlit 中添加图表类型切换选项(可选)

### 5.2 Plotly 图库速查

| 图表类型 | Plotly 函数 | 适用场景 |
|---------|------------|---------|
| 柱状图 | `px.bar` | 分类对比 |
| 折线图 | `px.line` | 时间趋势 |
| 饼图 | `px.pie` | 占比结构 |
| 散点图 | `px.scatter` | 两变量相关性 |
| 气泡图 | `px.scatter(size=...)` | 三变量关系 |
| 热力图 | `ff.create_annotated_heatmap` | 矩阵数据 |
| 雷达图 | `px.line_polar` | 多维对比 |
| K线图 | `plotly.graph_objects.Candlestick` | 股票行情 |
| 箱线图 | `px.box` | 分布统计 |
| 直方图 | `px.histogram` | 频率分布 |

---

## 6. 切换 LLM

场景:从通义千问切换到 DeepSeek、GPT-4、Claude 等。

### 6.1 步骤

**Step 1**:安装对应 SDK

```bash
# DeepSeek
pip install langchain-deepseek

# OpenAI
pip install langchain-openai
```

**Step 2**:修改 `config.py`,添加 LLM 工厂

```python
from dataclasses import dataclass
from langchain_community.chat_models.tongyi import ChatTongyi
# from langchain_deepseek import ChatDeepSeek  # 如果用 DeepSeek
# from langchain_openai import ChatOpenAI      # 如果用 OpenAI

@dataclass
class Config:
    llm_provider: str = "tongyi"  # tongyi / deepseek / openai
    llm_model_name: str = "qwen-plus"
    llm_api_key: str = ""
    llm_base_url: str = ""
    # ...
    
    def create_llm(self):
        if self.llm_provider == "tongyi":
            return ChatTongyi(
                model=self.llm_model_name,
                api_key=self.llm_api_key,
                streaming=True,
            )
        elif self.llm_provider == "deepseek":
            from langchain_deepseek import ChatDeepSeek
            return ChatDeepSeek(
                model=self.llm_model_name,
                api_key=self.llm_api_key,
                streaming=True,
            )
        elif self.llm_provider == "openai":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.llm_model_name,
                api_key=self.llm_api_key,
                base_url=self.llm_base_url,
                streaming=True,
            )
        else:
            raise ValueError(f"不支持的 LLM provider: {self.llm_provider}")
```

**Step 3**:在 `.env` 中添加配置

```bash
LLM_PROVIDER=deepseek
LLM_MODEL_NAME=deepseek-chat
LLM_API_KEY=sk-xxxx
```

### 6.2 注意事项
- 不同模型的 prompt 格式和能力有差异,切换后可能需要调整提示词
- 模型最大 token 数不同,注意上下文窗口限制
- Embedding 模型也要相应切换(见 RAG 调优指南)
- 价格差异很大,注意成本控制

---

## 7. 接入 MCP 工具

场景:接入搜索 MCP、计算器 MCP、天气 MCP 等外部工具。

### 7.1 步骤

**Step 1**:在 `config.py` 中添加 MCP 配置

```python
@dataclass
class Config:
    # ... 现有配置 ...
    mcp_servers: dict = field(default_factory=lambda: {
        "search": {
            "transport": "http",
            "url": "https://api.example.com/mcp/search",
            "api_key_env": "SEARCH_API_KEY",
        }
    })
```

**Step 2**:新建 `mcp_client.py`(参考旅行项目)

```python
"""MCP 客户端管理器 — 管理外部 MCP 服务连接。"""
from langchain_mcp_adapters.client import MultiServerMCPClient

class McpClientManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._client = None
        self._tools_cache = {}
        self._initialized = True
    
    async def get_tools(self, server_name: str = None):
        # ... 参考旅行项目实现 ...
```

**Step 3**:在对应 Agent 中注册 MCP 工具

```python
# 在 orchestrator.py 中
async def build(self):
    mcp = McpClientManager()
    mcp_tools = await mcp.get_tools("search")
    all_tools = [..., *mcp_tools]
```

### 7.2 注意事项
- MCP 工具调用有网络延迟,注意超时设置
- 外部工具有限流,需要做缓存和降级
- 安全考虑:不要把敏感数据传给不可信的 MCP 服务

---

## 8. 爬虫扩展：抓取研报与公告

> ⚠️ **合规声明**：爬虫功能仅用于技术学习，启用前请：
> 1. 阅读目标网站 `robots.txt`，遵守爬取规则
> 2. 设置合理的请求间隔（建议 >= 2 秒）
> 3. 仅用于个人学习，不得传播、分发或商用抓取到的内容
> 4. 尊重版权，真实研报和公告版权归原发布方所有

### 8.1 单份研报抓取示例

以下示例从公开页面抓取 PDF 研报并保存到本地：

```python
"""
单份研报抓取示例（以东方财富研报页面为例）
⚠️ 仅供学习，实际使用请遵守目标网站规定
"""
import os
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

def download_pdf(pdf_url: str, save_path: str, delay: float = 2.0) -> bool:
    """
    下载单份 PDF 研报。

    Args:
        pdf_url: PDF 文件的直接链接
        save_path: 保存路径
        delay: 请求前等待秒数（礼貌爬取）

    Returns:
        是否下载成功
    """
    time.sleep(delay)  # 礼貌爬取：每次请求前等待

    try:
        resp = requests.get(pdf_url, headers=HEADERS, timeout=30, stream=True)
        resp.raise_for_status()

        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        print(f"✅ 下载完成: {save_path} ({os.path.getsize(save_path)//1024} KB)")
        return True

    except Exception as e:
        print(f"❌ 下载失败 {pdf_url}: {e}")
        return False


def extract_pdf_links_from_page(page_url: str) -> list[str]:
    """
    从列表页提取所有 PDF 链接。

    Args:
        page_url: 研报列表页 URL

    Returns:
        PDF 链接列表
    """
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        pdf_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.lower().endswith(".pdf"):
                full_url = urljoin(page_url, href)
                pdf_links.append(full_url)

        return list(set(pdf_links))  # 去重

    except Exception as e:
        print(f"❌ 解析页面失败 {page_url}: {e}")
        return []


# ====== 使用示例 ======
if __name__ == "__main__":
    # 示例：从某研报列表页提取并下载前 3 份 PDF
    # list_url = "https://example.com/research/list"  # 替换为实际地址
    # pdf_urls = extract_pdf_links_from_page(list_url)

    # 单份直接下载
    sample_pdf_url = "https://example.com/research/maotai_2024.pdf"  # 替换为实际地址
    save_path = "data/docs/research_pdf/示例-茅台2024深度报告.pdf"

    download_pdf(sample_pdf_url, save_path, delay=2.0)
```

### 8.2 集成到项目中

在 `crawler.py` 中封装爬虫管理器：

```python
"""
crawler.py — 金融数据爬虫管理器（默认关闭，需主动启用）
"""
import os
import time
import requests
from dataclasses import dataclass

@dataclass
class CrawlerConfig:
    enabled: bool = False
    delay: float = 2.0          # 请求间隔（秒）
    max_pages: int = 50         # 单次最大抓取页数
    user_agent: str = "FinResearchBot/1.0 (Learning)"
    save_dir: str = "data/docs/crawled"  # 抓取数据单独存放

class ResearchCrawler:
    def __init__(self, config: CrawlerConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
        self._visited = set()  # 去重

    def check_robots(self, base_url: str) -> bool:
        """检查 robots.txt 是否允许爬取"""
        # 实际使用时实现 robots.txt 解析
        return True  # 占位：请自行检查

    def crawl_report(self, url: str, filename: str = None) -> str | None:
        """抓取单份研报并保存，返回保存路径"""
        if not self.config.enabled:
            print("⚠️ 爬虫未启用，跳过抓取")
            return None

        if url in self._visited:
            return None
        self._visited.add(url)

        if not self.check_robots(url):
            print(f"⚠️ robots.txt 禁止抓取: {url}")
            return None

        # 生成文件名
        if filename is None:
            filename = url.split("/")[-1] or "report.pdf"
        save_path = os.path.join(self.config.save_dir, filename)

        time.sleep(self.config.delay)

        try:
            resp = self.session.get(url, timeout=30, stream=True)
            resp.raise_for_status()
            os.makedirs(self.config.save_dir, exist_ok=True)
            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            return save_path
        except Exception as e:
            print(f"抓取失败: {e}")
            return None
```

### 8.3 最佳实践

1. **默认关闭**：`CRAWLER_ENABLED=false`，用户明确启用才工作
2. **数据隔离**：抓取的数据存 `data/docs/crawled/`，与模拟数据分开
3. **增量抓取**：用 `_visited` 集合 + 本地文件存在性判断，避免重复下载
4. **错误重试**：网络失败重试 2-3 次，指数退避
5. **日志记录**：记录每次抓取的 URL、时间、大小、状态

---

## 9. 多行业扩展：新能源/医药/TMT 等

当前默认只有白酒行业数据。扩展到其他行业非常简单，只需：新增数据 → 更新提示词 → 完成。

### 9.1 支持的行业清单（可扩展）

| 行业 | 行业代码 | 代表公司 | 核心指标 |
|------|---------|---------|---------|
| 白酒 | `baijiu` | 贵州茅台、五粮液、泸州老窖 | 营收增速、毛利率、ROE |
| 新能源 | `new_energy` | 宁德时代、比亚迪、隆基绿能 | 装机量、毛利率、研发占比 |
| 医药 | `pharmaceutical` | 恒瑞医药、药明康德、迈瑞医疗 | 研发投入、管线数量、毛利率 |
| 互联网 | `internet` | 腾讯、阿里、美团 | 用户数、ARPU、毛利率 |
| 银行 | `bank` | 招商银行、宁波银行 | 净息差、不良率、拨备覆盖率 |
| 半导体 | `semiconductor` | 中芯国际、韦尔股份 | 制程、营收增速、研发占比 |

### 9.2 扩展步骤

**Step 1**：在 `init_data.py` 中添加新行业数据

```python
# init_data.py
INDUSTRIES_DATA = {
    "白酒": {
        "stocks": [
            ("600519", "贵州茅台", "白酒", ...),
            ("000858", "五粮液", "白酒", ...),
        ],
        "industry_avg": {"avg_pe": 25, "avg_pb": 6, "avg_roe": 0.225},
    },
    # 新增新能源行业
    "新能源": {
        "stocks": [
            ("300750", "宁德时代", "新能源", 12000, "2018-06-11"),
            ("002594", "比亚迪", "新能源", 8000, "2011-06-30"),
            ("601012", "隆基绿能", "新能源", 2000, "2012-04-11"),
        ],
        "industry_avg": {"avg_pe": 30, "avg_pb": 4.5, "avg_roe": 0.15},
    },
    # 新增医药行业
    "医药": {
        "stocks": [
            ("600276", "恒瑞医药", "医药", 3000, "2000-10-18"),
            ("603259", "药明康德", "医药", 2000, "2018-05-08"),
            ("300760", "迈瑞医疗", "医药", 3500, "2018-10-16"),
        ],
        "industry_avg": {"avg_pe": 40, "avg_pb": 6, "avg_roe": 0.18},
    },
}
```

**Step 2**：添加对应行业的财务数据生成逻辑

```python
def generate_financial_data_for_industry(industry: str, stocks: list):
    """为指定行业生成 5 年财务数据"""
    base_roe = {
        "白酒": 0.25,
        "新能源": 0.18,
        "医药": 0.16,
        "银行": 0.14,
        "半导体": 0.10,
        "互联网": 0.20,
    }.get(industry, 0.15)

    for stock in stocks:
        for year in range(2019, 2025):
            # 生成逐年变化的财务数据...
            roe = base_roe * (1 + random.uniform(-0.1, 0.15))
            revenue = random.uniform(50, 500)  # 亿元
            net_profit = revenue * roe
            # 插入数据库...
```

**Step 3**：更新 SQL Agent 提示词中的行业说明

```python
# prompts.py 中 SQL_AGENT_PROMPT 添加
"""
可用行业分类:
- 白酒: 贵州茅台(600519)、五粮液(000858)、泸州老窖(000568)...
- 新能源: 宁德时代(300750)、比亚迪(002594)、隆基绿能(601012)...
- 医药: 恒瑞医药(600276)、药明康德(603259)、迈瑞医疗(300760)...
- 银行: 招商银行(600036)、宁波银行(002142)...
"""
```

**Step 4**：（可选）添加行业专属分析指标

不同行业有不同的核心指标，在 Analyst Agent 中增加行业专属分析逻辑：

```python
def get_industry_specific_metrics(industry: str) -> list[str]:
    """返回行业专属分析维度"""
    return {
        "白酒": ["毛利率趋势", "渠道库存", "批价走势", "吨价变化"],
        "新能源": ["装机量", "市占率", "技术路线", "产能扩张"],
        "医药": ["研发管线", "专利到期", "集采影响", "出海进度"],
        "银行": ["净息差", "不良贷款率", "拨备覆盖率", "资本充足率"],
        "半导体": ["制程进度", "产能利用率", "研发投入", "下游需求"],
    }.get(industry, ["营收", "利润", "ROE"])
```

**Step 5**：重新初始化数据

```bash
python init_data.py --force
```

### 9.3 多语言扩展（可选）

当前仅支持中文查询。要支持英文/日文等：

```python
# config.py 中添加
MULTILINGUAL = {
    "zh": "中文查询",
    "en": "English query",
}

# prompts.py 中准备多语言版本的系统提示词
ANALYST_PROMPT = {
    "zh": "你是中文投研分析师...",
    "en": "You are a financial research analyst...",
}
```

---

## 10. 代码风格与规范

### 10.1 命名规范
- 文件名:小写 + 下划线 (`snake_case`)
- 类名:大驼峰 (`PascalCase`)
- 函数/方法名:小写 + 下划线 (`snake_case`)
- 常量:全大写 + 下划线 (`UPPER_SNAKE_CASE`)

### 10.2 类型提示
所有函数必须加类型标注:
```python
def query_sql(query: str, limit: int = 100) -> list[dict]:
    """执行 SQL 查询并返回结果列表。"""
    ...
```

### 10.3 注释规范
- 模块顶部 docstring:说明模块用途
- 类 docstring:说明类职责和用法
- 函数 docstring:说明参数、返回值、异常
- 关键逻辑加行内注释

### 10.4 提交规范
使用 [Conventional Commits](https://www.conventionalcommits.org/):
```
feat: 新增功能
fix: 修复 bug
docs: 文档更新
refactor: 重构
test: 测试相关
perf: 性能优化
chore: 构建/工具链相关
```

---

## 11. 相关文件

| 文件 | 说明 |
|------|------|
| `agents/specialist.py` | Agent 基类,新增 Agent 继承此基类 |
| `doc_loader.py` | 文档加载器,新增格式在此扩展 |
| `visualizer.py` | 可视化生成器,新增图表在此扩展 |
| `config.py` | 配置中心,新增配置项在此添加 |
