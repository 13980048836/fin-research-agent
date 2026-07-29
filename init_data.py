"""
init_data.py — 初始化模拟数据

生成内容:
  1. 数据库表结构 + 白酒行业模拟数据（3 家公司, 6 年财务数据）
  2. 模拟研报文档（用于 RAG 检索效果演示）

默认只在数据库不存在时初始化，加 --force 强制重建。
"""
import argparse
import os
import random
import sqlite3
from pathlib import Path

from config import get_config

random.seed(42)

# ===================== 行业基础数据 =====================

BAIJIU_STOCKS = [
    {
        "code": "600519",
        "name": "贵州茅台",
        "industry": "白酒",
        "market_cap": 21000,
        "list_date": "2001-08-27",
        "base_revenue": 1300,
        "base_roe": 0.30,
        "gross_margin": 0.91,
    },
    {
        "code": "000858",
        "name": "五粮液",
        "industry": "白酒",
        "market_cap": 6500,
        "list_date": "1998-04-27",
        "base_revenue": 800,
        "base_roe": 0.22,
        "gross_margin": 0.75,
    },
    {
        "code": "000568",
        "name": "泸州老窖",
        "industry": "白酒",
        "market_cap": 3200,
        "list_date": "1994-05-09",
        "base_revenue": 280,
        "base_roe": 0.25,
        "gross_margin": 0.86,
    },
]

YEARS = list(range(2020, 2027))

# ===================== 建表 SQL =====================

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS stocks (
    stock_code    TEXT PRIMARY KEY,
    stock_name    TEXT NOT NULL,
    industry      TEXT NOT NULL,
    market_cap    REAL,        -- 市值，单位：亿元
    list_date     TEXT,        -- 上市日期
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS financial_statements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code    TEXT NOT NULL,
    year          INTEGER NOT NULL,
    revenue       REAL,        -- 营业收入，单位：亿元
    net_profit    REAL,        -- 净利润，单位：亿元
    gross_margin  REAL,        -- 毛利率
    net_margin    REAL,        -- 净利率
    roe           REAL,        -- 净资产收益率
    roa           REAL,        -- 总资产收益率
    debt_ratio    REAL,        -- 资产负债率
    eps           REAL,        -- 每股收益，元
    per_dividend  REAL,        -- 每股分红，元
    UNIQUE(stock_code, year),
    FOREIGN KEY(stock_code) REFERENCES stocks(stock_code)
);

CREATE TABLE IF NOT EXISTS quarterly_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code    TEXT NOT NULL,
    year          INTEGER NOT NULL,
    quarter       INTEGER NOT NULL,  -- 1/2/3/4
    revenue       REAL,
    net_profit    REAL,
    UNIQUE(stock_code, year, quarter),
    FOREIGN KEY(stock_code) REFERENCES stocks(stock_code)
);

CREATE TABLE IF NOT EXISTS industry_avg (
    industry      TEXT PRIMARY KEY,
    avg_pe        REAL,
    avg_pb        REAL,
    avg_roe       REAL,
    avg_gross_margin REAL,
    company_count INTEGER
);

CREATE TABLE IF NOT EXISTS research_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    stock_code    TEXT,
    industry      TEXT,
    publish_date  TEXT,
    institution   TEXT,
    analyst       TEXT,
    rating        TEXT,        -- 买入/增持/中性/减持/卖出
    target_price  REAL,        -- 目标价
    file_path     TEXT,        -- 文档路径
    summary       TEXT,        -- 摘要
    FOREIGN KEY(stock_code) REFERENCES stocks(stock_code)
);

CREATE INDEX IF NOT EXISTS idx_fin_stock_year ON financial_statements(stock_code, year);
CREATE INDEX IF NOT EXISTS idx_qt_stock ON quarterly_data(stock_code);
CREATE INDEX IF NOT EXISTS idx_report_stock ON research_reports(stock_code);
CREATE INDEX IF NOT EXISTS idx_stocks_industry ON stocks(industry);
"""


# ===================== 数据生成 =====================

def _gen_growth(base: float, year_idx: int, volatility: float = 0.08) -> float:
    """生成逐年增长的数据，带波动"""
    growth_rates = [0.08, 0.10, 0.15, 0.12, 0.16, 0.18, 0.20]
    rate = growth_rates[year_idx] + random.uniform(-volatility, volatility)
    return base * (1 + rate)


def generate_stock_data(stock: dict) -> tuple[list, list]:
    """为单只股票生成财务数据 + 季度数据"""
    fin_rows = []
    quarter_rows = []

    prev_revenue = stock["base_revenue"] * 0.8
    prev_net_profit = prev_revenue * stock["base_roe"]

    for yi, year in enumerate(YEARS):
        revenue = _gen_growth(prev_revenue, yi, volatility=0.05)
        net_profit = revenue * stock["base_roe"] * (1 + random.uniform(-0.05, 0.05))
        gross_margin = stock["gross_margin"] * (1 + random.uniform(-0.02, 0.02))
        net_margin = net_profit / revenue
        roe = stock["base_roe"] * (1 + random.uniform(-0.08, 0.08))
        roa = roe * 0.4
        debt_ratio = 0.25 + random.uniform(-0.05, 0.05)
        eps = round(net_profit / 12.56, 2) if stock["code"] == "600519" else round(net_profit / 38.8, 2)
        per_dividend = round(eps * 0.5, 2)

        fin_rows.append((
            stock["code"], year,
            round(revenue, 2), round(net_profit, 2),
            round(gross_margin, 4), round(net_margin, 4),
            round(roe, 4), round(roa, 4),
            round(debt_ratio, 4), eps, per_dividend,
        ))

        # 季度数据：按 30% / 25% / 25% / 20% 拆分，加点波动
        q_ratios = [0.30, 0.25, 0.25, 0.20]
        for q in range(1, 5):
            ratio = q_ratios[q - 1] * (1 + random.uniform(-0.05, 0.05))
            q_rev = revenue * ratio
            q_np = net_profit * ratio * (1 + random.uniform(-0.05, 0.05))
            quarter_rows.append((
                stock["code"], year, q,
                round(q_rev, 2), round(q_np, 2),
            ))

        prev_revenue = revenue
        prev_net_profit = net_profit

    return fin_rows, quarter_rows


def generate_industry_avg() -> tuple:
    """生成行业平均数据"""
    return ("白酒", 28.5, 7.8, 0.265, 0.85, 18)


def generate_research_reports() -> list:
    """生成模拟研报元数据"""
    reports = [
        ("贵州茅台2026年中报点评：业绩加速增长，直营化超额完成", "600519", "白酒",
         "2026-07-15", "中信证券", "薛缘", "买入", 2600, None),
        ("五粮液2025年报点评及2026年展望：千亿突破，再启新程", "000858", "白酒",
         "2026-04-25", "中金公司", "余驰", "增持", 220, None),
        ("泸州老窖2026年一季度点评：开门红，全年可期", "000568", "白酒",
         "2026-05-10", "华泰证券", "龚源月", "买入", 320, None),
        ("白酒行业2026年投资策略：高端引领，分化中寻机会", None, "白酒",
         "2026-06-01", "招商证券", "于佳琦", "中性", None, None),
        ("贵州茅台2025年报深度解析：跨越两千亿，开启新征程", "600519", "白酒",
         "2026-03-20", "海通证券", "闻宏伟", "买入", 2500, None),
    ]
    return reports


# ===================== 模拟文档生成 =====================

MOCK_REPORTS = [
    {
        "filename": "茅台2026年中报深度点评.txt",
        "subdir": "research_pdf",
        "content": """贵州茅台 2026 年中报深度点评：业绩加速增长，直营化超额完成

投资要点：
- 2026H1 实现营收 1258.6 亿元，同比+18.2%；归母净利润 685.4 亿元，同比+19.5%，业绩大超市场预期。
- 分产品看，茅台酒营收 1095.3 亿元（+17.8%），系列酒营收 162.1 亿元（+24.5%），系列酒增速持续领先。
- 分渠道看，直销渠道营收 568 亿元（+32.1%），直营化比例提升至 45%，i茅台平台贡献超380亿元。
- 毛利率 92.5%，同比提升 0.4pct；净利率 54.5%，同比提升 0.8pct，盈利能力再创新高。
- 合同负债 168.5 亿元，同比+15.2%，渠道蓄水池持续充实。

2026-2028 年盈利预测：
我们预计 2026-2028 年 EPS 分别为 78.5、92.3、108.6 元，对应 PE 分别为 22x、19x、16x。
维持"买入"评级，目标价 2600 元。

风险提示：
宏观经济下行风险；行业政策风险；食品安全风险；市场竞争加剧风险。
""",
    },
    {
        "filename": "五粮液2025年报及2026展望.txt",
        "subdir": "research_pdf",
        "content": """五粮液 2025 年报点评及 2026 年展望

核心观点：
2025 年公司营收首次突破 1000 亿元大关，达 1018.5 亿元（+16.5%），归母净利润 385.2 亿元（+18.2%），
创历史新高。2026 年受益于产品升级和渠道优化，有望继续保持两位数增长。

投资亮点：
1. 品牌价值突破：五粮液品牌市值突破 5000 亿元，品牌护城河更加稳固。
2. 产品矩阵优化：第八代五粮液完成全国铺货，经典五粮液增长强劲，千元价格带份额持续提升。
3. 渠道改革深化：数字化渠道占比提升至 28%，经销商体系优化成效显著。
4. 分红回报提升：2025 年分红比例提升至 65%，股息率约 3.5%。

财务分析：
- 2025 年营收 1018.5 亿元（+16.5%），净利 385.2 亿元（+18.2%）。
- 毛利率 76.8%（+1.3pct），净利率 37.8%（+0.5pct），盈利能力持续改善。
- ROE 25.8%（+1.2pct），运营效率提升。
- 2026 年展望：预计营收增长 15-18%，净利增长 16-20%。

投资评级：
维持"增持"评级，目标价 220 元，对应 2026 年 22x PE。
""",
    },
    {
        "filename": "白酒行业2026年投资策略.txt",
        "subdir": "research_pdf",
        "content": """白酒行业 2026 年投资策略报告

行业景气度：
2026 年白酒行业整体呈现"高端引领、次高端分化、大众酒升级"的格局。
行业营收同比增长 9.8%，净利润增长 11.5%，增速较 2025 年略有加快。

高端白酒：茅台、五粮液、泸州老窖
- 茅台：直营化比例突破 45%，i茅台用户突破 8000 万，数字化转型成效显著。飞天批价稳定在 2800 元以上。
- 五粮液：经典五粮液完成品牌重塑，千年酒文化 IP 打造取得阶段性成果。
- 泸州老窖：国窖 1573 批价突破 1200 元，特曲系列全国化加速。

次高端白酒：
- 整体承压，库存偏高，动销缓慢。部分区域型酒企通过产品升级和渠道下沉实现突围。
- 山西汾酒青花系列、洋河梦之蓝系列仍是次高端标杆。

大众白酒：
- 升级趋势明显，80-200 元价格带增长最快。
- 古井贡酒、今世缘、口子窖等区域龙头表现亮眼。

投资建议：
超配高端白酒龙头（茅台、五粮液），标配优质次高端（汾酒、老窖），低配大众酒。

估值水平：
- 高端酒平均 PE 25x，次高端 22x，大众酒 18x。
- 行业整体估值处于历史中位数水平，安全边际充足。
""",
    },
    {
        "filename": "泸州老窖2026年一季度点评.txt",
        "subdir": "research_pdf",
        "content": """泸州老窖 2026 年一季度业绩点评：开门红，全年可期

事件：
公司发布 2026 年一季报，实现营收 105.8 亿元，同比+22.5%；
归母净利润 42.3 亿元，同比+25.8%，超出市场预期。

业绩点评：
1. 国窖 1573：一季度营收增长 20%，批价稳定在 1250 元，渠道库存健康。
2. 特曲系列：营收增长 32%，中档酒战略推进顺利，成为第二增长引擎。
3. 窖龄酒：营收增长 28%，高端中档酒定位清晰，增长潜力大。
4. 毛利率：一季度毛利率 87.2%（+0.8pct），产品结构持续优化。
5. 费用率：销售费用率下降 0.5pct，投放效率提升。

全年展望：
公司预计 2026 年实现营收 380-400 亿元，同比增长 18-22%；
归母净利润 160-170 亿元，同比增长 20-25%。

投资逻辑：
- 品牌战略清晰：国窖做高度，特曲做腰部，窖龄做潜力。
- 管理层执行力强：公司治理结构持续改善。
- 估值合理：当前 PE 20 倍，低于历史中枢。

投资评级：
维持"买入"评级，目标价 320 元。
""",
    },
    {
        "filename": "茅台2025年报深度解析.txt",
        "subdir": "research_pdf",
        "content": """贵州茅台 2025 年报深度解析：跨越两千亿，开启新征程

核心结论：
茅台 2025 年实现营收 2489.6 亿元，同比+18.7%；归母净利润 768.5 亿元，同比+26.0%。
营收首次突破 2000 亿元大关，公司发展迈入新阶段。

一、收入分析
- 茅台酒：营收 2150.8 亿元，同比+17.5%。其中飞天茅台占比约 72%，生肖酒等非标酒占比提升至 15%。
- 系列酒：营收 328.5 亿元，同比+28.2%。茅台 1935 成为千元以下大单品，营收突破 120 亿元。
- 直销渠道：营收 965.3 亿元，同比+35.8%，占比提升至 39%。
- i 茅台：线上平台营收超 480 亿元，用户数突破 6500 万。

二、盈利能力
- 毛利率 92.1%，同比提升 0.3pct。
- 净利率 53.2%，同比提升 0.7pct。
- ROE 33.5%，同比提升 1.0pct，盈利能力为 A 股之最。

三、资产负债表
- 货币资金 2200 亿元，占总资产 68%。
- 合同负债 145.6 亿元，同比+18.5%。
- 有息负债为 0，财务极其稳健。

四、2026 年展望
- 基酒产能突破 6 万吨，为未来 3-5 年增长奠定基础。
- 直营化比例目标 50%，渠道利润空间进一步释放。
- 系列酒目标突破 400 亿元，第二增长曲线确立。

投资建议：
维持"买入"评级，目标价 2500 元，对应 2026 年 32 倍 PE。
""",
    },
]

MOCK_ANNOUNCEMENTS = [
    {
        "filename": "茅台2025年报公告.txt",
        "subdir": "announcements",
        "content": """贵州茅台酒股份有限公司 2025 年年度报告摘要

一、主要财务数据（单位：亿元）
| 项目 | 2025 年 | 2024 年 | 同比增减 |
|------|---------|---------|---------|
| 营业收入 | 2489.60 | 2097.80 | +18.68% |
| 归属于上市公司股东的净利润 | 768.50 | 609.95 | +25.99% |
| 归属于上市公司股东的扣除非经常性损益的净利润 | 765.30 | 607.20 | +26.04% |
| 经营活动产生的现金流量净额 | 620.80 | 495.60 | +25.26% |
| 基本每股收益（元/股） | 61.20 | 48.57 | +26.00% |
| 加权平均净资产收益率 | 33.50% | 32.20% | +1.30pct |

二、主营业务分析
报告期内，公司紧紧围绕"十四五"规划目标，坚持高质量发展，
统筹推进生产经营各项工作，直销化比例提升至 39%，i茅台用户突破 6500 万，
市场发展态势良好，主要经营指标创历史新高。

三、利润分配预案
公司拟以 12.56 亿股为基数，向全体股东每 10 股派发现金红利 300.00 元（含税），
合计派发现金红利 376.80 亿元，占归母净利润比例为 49.03%。

四、风险提示
宏观经济波动风险、行业政策风险、食品安全风险、市场竞争加剧风险。
""",
    },
    {
        "filename": "五粮液2025年报及分红公告.txt",
        "subdir": "announcements",
        "content": """宜宾五粮液股份有限公司 2025 年度利润分配实施公告

一、通过利润分配方案的股东大会届次和日期
公司 2025 年度利润分配方案已经 2026 年 4 月 18 日召开的
2025 年度股东大会审议通过。

二、利润分配方案
1. 发放年度：2025 年度
2. 发放范围：截至 2026 年 5 月 10 日下午深圳证券交易所收市后，
   在中国证券登记结算有限责任公司深圳分公司登记在册的本公司全体 A 股股东。
3. 分配方案：以公司现有总股本 38.82 亿股为基数，
   向全体股东每 10 股派发现金红利 65.80 元（含税），
   合计派发现金红利 255.44 亿元，占 2025 年度归母净利润比例为 66.31%。

三、股权登记日、除权（息）日、现金红利发放日
- 股权登记日：2026 年 5 月 10 日
- 除权（息）日：2026 年 5 月 11 日
- 现金红利发放日：2026 年 5 月 18 日

四、2025 年度业绩
公司 2025 年实现营业收入 1018.5 亿元，同比+16.5%；
归母净利润 385.2 亿元，同比+18.2%。
营收首次突破千亿大关，创历史新高。
""",
    },
    {
        "filename": "泸州老窖2026年股权激励方案公告.txt",
        "subdir": "announcements",
        "content": """泸州老窖股份有限公司 2026 年限制性股票激励计划（草案）摘要

一、股权激励计划的目的
为进一步建立、健全公司长效激励机制，吸引和留住优秀人才，
充分调动公司核心骨干员工的积极性，有效地将股东利益、公司利益和员工个人利益结合在一起，
使各方共同关注公司的长远发展。

二、激励计划拟授予的权益数量及占比
本激励计划拟授予限制性股票数量不超过 2000 万股，
约占本激励计划草案公告时公司股本总额 14.72 亿股的 1.36%。

三、激励对象范围
本激励计划涉及的激励对象共计 280 人，包括：
1. 公司董事、高级管理人员
2. 公司中层管理人员
3. 公司核心技术（业务）人员
4. 年度优秀员工代表

四、授予价格
限制性股票的授予价格为每股 180.00 元，
为公告前 20 个交易日公司股票均价的 50%。

五、业绩考核要求
| 解除限售期 | 业绩考核目标 |
|-----------|-------------|
| 第一个解除限售期 | 2026 年净利润增长率不低于 18% |
| 第二个解除限售期 | 2027 年净利润增长率不低于 18% |
| 第三个解除限售期 | 2028 年净利润增长率不低于 18% |

六、对公司的影响
本激励计划将进一步完善公司治理结构，提升公司核心竞争力，
促进公司持续、健康发展。预计三年摊销费用约 2.8 亿元。
""",
    },
]


def write_mock_docs(docs_dir: Path) -> int:
    """写入模拟文档，返回写入的文档数"""
    all_docs = MOCK_REPORTS + MOCK_ANNOUNCEMENTS
    count = 0

    for doc in all_docs:
        file_path = docs_dir / doc["subdir"] / doc["filename"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(doc["content"], encoding="utf-8")
        count += 1

    return count


# ===================== 主函数 =====================

def init_db(force: bool = False) -> None:
    """初始化数据库"""
    cfg = get_config().database
    db_path = Path(cfg.path)

    if db_path.exists() and not force:
        print(f"✅ 数据库已存在: {db_path}")
        print("   如需重建，请运行: python init_data.py --force")
        return

    if force and db_path.exists():
        db_path.unlink()
        print(f"🗑️  已删除旧数据库")

    print("📊 创建数据库表结构...")
    conn = sqlite3.connect(str(db_path))
    conn.executescript(CREATE_TABLES_SQL)
    conn.commit()

    print("📈 插入股票基础数据...")
    for stock in BAIJIU_STOCKS:
        conn.execute(
            "INSERT INTO stocks (stock_code, stock_name, industry, market_cap, list_date) VALUES (?,?,?,?,?)",
            (stock["code"], stock["name"], stock["industry"], stock["market_cap"], stock["list_date"]),
        )

    print("📊 生成财务数据...")
    all_fin = []
    all_quarter = []
    for stock in BAIJIU_STOCKS:
        fin_rows, q_rows = generate_stock_data(stock)
        all_fin.extend(fin_rows)
        all_quarter.extend(q_rows)

    conn.executemany(
        "INSERT INTO financial_statements (stock_code, year, revenue, net_profit, "
        "gross_margin, net_margin, roe, roa, debt_ratio, eps, per_dividend) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        all_fin,
    )
    conn.executemany(
        "INSERT INTO quarterly_data (stock_code, year, quarter, revenue, net_profit) VALUES (?,?,?,?,?)",
        all_quarter,
    )

    print("🏭 生成行业平均数据...")
    industry_data = generate_industry_avg()
    conn.execute(
        "INSERT INTO industry_avg (industry, avg_pe, avg_pb, avg_roe, avg_gross_margin, company_count) "
        "VALUES (?,?,?,?,?,?)",
        industry_data,
    )

    print("📑 生成研报元数据...")
    reports = generate_research_reports()
    conn.executemany(
        "INSERT INTO research_reports (title, stock_code, industry, publish_date, "
        "institution, analyst, rating, target_price, summary) VALUES (?,?,?,?,?,?,?,?,?)",
        [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[0][:50]) for r in reports],
    )

    conn.commit()
    conn.close()

    print(f"✅ 数据库初始化完成: {db_path}")
    print(f"   - 股票: {len(BAIJIU_STOCKS)} 只")
    print(f"   - 年度财务数据: {len(all_fin)} 条")
    print(f"   - 季度数据: {len(all_quarter)} 条")
    print(f"   - 研报元数据: {len(reports)} 条")


def init_docs() -> None:
    """初始化模拟文档"""
    cfg = get_config()
    docs_dir = cfg.docs_dir
    count = write_mock_docs(docs_dir)
    print(f"📝 模拟文档生成完成: {count} 份")
    print(f"   目录: {docs_dir}")


def init_vector_store(force: bool = False) -> None:
    """初始化向量索引"""
    cfg = get_config()
    docs_dir = cfg.docs_dir
    index_path = Path(cfg.faiss.index_path)

    if index_path.exists() and (index_path / "index.faiss").exists() and not force:
        print(f"✅ 向量索引已存在: {index_path}")
        return

    try:
        from vector_store import VectorStoreManager
        from doc_loader import DocumentLoader
    except ImportError as e:
        print(f"⚠️  缺少依赖，跳过向量索引构建: {e}")
        print("   安装命令: pip install faiss-cpu langchain-community dashscope")
        return

    try:
        loader = DocumentLoader(cfg)
        result = loader.load_directory(docs_dir)

        if not result.documents:
            print("⚠️  没有找到可索引的文档，跳过向量索引构建")
            return

        print(f"🔍 加载了 {result.total_files} 个文件，切分为 {result.total_chunks} 个片段")
        if result.failed_files:
            print(f"⚠️  失败文件 {len(result.failed_files)} 个")

        vsm = VectorStoreManager(cfg)
        if force and index_path.exists():
            vsm.clear()

        vsm.build_from_documents(result.documents)

        # 构建混合检索 BM25 索引
        try:
            from hybrid_retriever import HybridRetriever
            hr = HybridRetriever(vector_store=vsm, config=cfg)
            hr.build_index(result.documents)
            print("✅ 混合检索索引构建完成 (BM25 + 向量)")
        except Exception as e:
            print(f"⚠️  混合检索索引构建失败（不影响基本功能）: {e}")

    except Exception as e:
        print(f"⚠️  向量索引构建失败: {e}")
        print("   不影响主功能使用，后续可运行: python init_data.py --vector")


def main():
    parser = argparse.ArgumentParser(description="初始化金融投研助手数据")
    parser.add_argument("--force", action="store_true", help="强制重建数据库+向量索引（生产环境禁用）")
    parser.add_argument("--db-only", action="store_true", help="仅初始化数据库")
    parser.add_argument("--docs-only", action="store_true", help="仅生成模拟文档")
    parser.add_argument("--vector", action="store_true", help="仅构建向量索引")
    parser.add_argument("--no-vector", action="store_true", help="跳过向量索引构建")
    args = parser.parse_args()

    # ==================== 环境保护：生产环境禁止 --force ====================
    ENV = os.getenv("ENVIRONMENT", "").strip().lower()
    PROD_TOKENS = {"prod", "production", "online", "生产"}
    is_prod = any(t in ENV for t in PROD_TOKENS)

    if args.force and is_prod:
        print("❌ 生产环境检测到 ENVIRONMENT={ENV}，禁止使用 --force 参数！")
        print("   生产环境如需初始化，请先手动备份数据库后再执行：")
        print("   1. 备份 data/finance.db 和 data/faiss_index/")
        print("   2. 临时设置 ENVIRONMENT=dev 后再执行 --force")
        import sys
        sys.exit(1)

    if args.force and not is_prod:
        # 二次确认（交互式环境）
        import sys
        if sys.stdin.isatty():
            print("⚠️  警告：--force 将删除并重建现有数据库和向量索引！")
            confirm = input("   请输入 YES 确认继续: ").strip()
            if confirm != "YES":
                print("已取消。")
                sys.exit(0)

    get_config().ensure_dirs()

    if args.vector:
        init_vector_store(force=args.force)
        return

    if not args.docs_only:
        init_db(force=args.force)

    if not args.db_only:
        init_docs()

    if not args.no_vector and not args.db_only:
        init_vector_store(force=args.force)

    print("\n🎉 数据初始化全部完成！")
    print("   下一步: python cli.py --mode sql 测试 SQL 链路")
    print("         python cli.py --mode rag 测试 RAG 链路")
    print("         python cli.py --mode hybrid 测试完整链路")


if __name__ == "__main__":
    main()
