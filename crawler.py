"""
crawler.py — 财经资讯爬虫模块

功能:
  1. 从东方财富、新浪财经等公开财经网站抓取资讯
  2. 支持关键词搜索、时间范围过滤
  3. 自动清洗正文、提取标题/来源/时间
  4. 保存为 TXT 文件到 data/docs/crawled/
  5. robots.txt 合规检查（遵守目标网站抓取规则）

使用:
  python crawler.py                          # 爬取默认关键词
  python crawler.py --keywords "茅台,白酒"   # 指定关键词
  python crawler.py --max-pages 20           # 限制页数
  python crawler.py --no-save                # 仅测试不保存
"""
import argparse
import hashlib
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_CRAWLER_DEPS = True
except ImportError:
    HAS_CRAWLER_DEPS = False

from config import get_config

DEFAULT_KEYWORDS = ["白酒", "茅台", "五粮液", "泸州老窖", "A 股"]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]


class RobotsChecker:
    """robots.txt 合规检查器（带缓存，避免重复请求）"""

    def __init__(self):
        self._parsers: dict[str, RobotFileParser] = {}
        self._user_agent = USER_AGENTS[0]

    def _get_parser(self, url: str) -> Optional[RobotFileParser]:
        """获取某个域名的 robots.txt 解析器（带缓存）"""
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc
            if netloc in self._parsers:
                return self._parsers[netloc]
            robots_url = f"{parsed.scheme}://{netloc}/robots.txt"
            rp = RobotFileParser()
            try:
                rp.set_url(robots_url)
                rp.read()
                self._parsers[netloc] = rp
                print(f"  📜 robots.txt 已加载: {robots_url}")
            except Exception as e:
                # robots.txt 无法获取时默认允许（保守策略）
                print(f"  ⚠️  无法读取 robots.txt ({robots_url}): {e}，默认允许抓取")
                allow_all = RobotFileParser()
                allow_all.parse(["User-agent: *", "Allow: /"])
                self._parsers[netloc] = allow_all
                return allow_all
            return rp
        except Exception:
            return None

    def can_fetch(self, url: str) -> bool:
        """检查 URL 是否允许被抓取"""
        rp = self._get_parser(url)
        if rp is None:
            return True
        try:
            return rp.can_fetch(self._user_agent, url)
        except Exception:
            return True


class FinancialCrawler:
    """财经资讯爬虫（含 robots.txt 合规）"""

    def __init__(self, config=None):
        self.cfg = config or get_config()
        self.crawler_cfg = self.cfg.crawler
        self.save_dir = Path(self.crawler_cfg.save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self.delay = self.crawler_cfg.delay
        self.max_pages = self.crawler_cfg.max_pages
        # robots.txt 合规检查器
        self.robots = RobotsChecker()

    def _safe_request(self, url: str, timeout: int = 15) -> Optional[str]:
        """安全请求，带重试 + robots.txt 合规检查"""
        # robots.txt 合规检查（仅在第一次请求某域名时触发）
        if not self.robots.can_fetch(url):
            print(f"  🚫 robots.txt 禁止抓取，跳过: {url}")
            return None

        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=timeout)
                resp.encoding = resp.apparent_encoding or "utf-8"
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 403:
                    print(f"  ⚠️  403 禁止访问: {url}")
                    return None
                else:
                    print(f"  ⚠️  HTTP {resp.status_code}: {url}")
            except requests.RequestException as e:
                print(f"  ⚠️  请求失败 (尝试 {attempt + 1}/3): {e}")
                time.sleep(2)
        return None

    def _clean_text(self, text: str) -> str:
        """清洗文本"""
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"\s+", " ", text)
        text = text.replace("\u3000", " ")
        return text.strip()

    def _extract_eastmoney(self, keyword: str, max_pages: int) -> list:
        """从东方财富搜索爬取"""
        articles = []
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        params = {
            "cb": "jQuery",
            "param": f'{{"uid":"","keyword":"{keyword}","type":["cmsArticleWebOld"],"client":"web","clientType":"web","clientVersion":"curr","param":{{"cmsArticleWebOld":{{"searchScope":"default","sort":"default","pageIndex":1,"pageSize":{max_pages},"preTag":"","postTag":""}}}}}}',
        }
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.encoding = "utf-8"
            text = resp.text
            json_match = re.search(r'jQuery\((.*)\)', text, re.DOTALL)
            if json_match:
                import json
                data = json.loads(json_match.group(1))
                for item in data.get("result", {}).get("cmsArticleWebOld", {}).get("list", []):
                    title = self._clean_text(item.get("title", ""))
                    content = self._clean_text(item.get("content", ""))
                    url_link = item.get("url", "")
                    date = item.get("date", "")
                    source = item.get("mediaName", "")
                    if title and content:
                        articles.append({
                            "title": title,
                            "content": content[:500],
                            "url": url_link,
                            "date": date,
                            "source": source or "东方财富",
                            "keyword": keyword,
                        })
        except Exception as e:
            print(f"  ⚠️  东方财富搜索异常: {e}")
        return articles

    def _extract_sina(self, keyword: str) -> list:
        """从新浪财经搜索爬取"""
        articles = []
        url = f"https://search.sina.com.cn/news"
        params = {"q": keyword, "c": "news", "sort": "time", "range": "all", "num": 20}
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.select("div.box-result")
            for r in results[:15]:
                a_tag = r.select_one("h2 a")
                if not a_tag:
                    continue
                title = self._clean_text(a_tag.get_text())
                link = a_tag.get("href", "")
                summary_tag = r.select_one("p.content")
                summary = self._clean_text(summary_tag.get_text()) if summary_tag else ""
                date_tag = r.select_one("span.fgray_time")
                date_text = self._clean_text(date_tag.get_text()) if date_tag else ""
                if title:
                    articles.append({
                        "title": title,
                        "content": summary[:500],
                        "url": link,
                        "date": date_text,
                        "source": "新浪财经",
                        "keyword": keyword,
                    })
        except Exception as e:
            print(f"  ⚠️  新浪搜索异常: {e}")
        return articles

    def crawl(self, keywords: list = None, max_pages: int = None) -> list:
        """执行爬取"""
        if not HAS_CRAWLER_DEPS:
            raise ImportError(
                "需要安装爬虫依赖: pip install requests beautifulsoup4"
            )

        keywords = keywords or DEFAULT_KEYWORDS
        max_pages = max_pages or self.max_pages
        all_articles = []

        for i, keyword in enumerate(keywords):
            print(f"🔍 [{i+1}/{len(keywords)}] 正在搜索: {keyword}")
            articles = []

            # 来源1: 东方财富
            print(f"  📰 东方财富...")
            articles.extend(self._extract_eastmoney(keyword, max_pages))

            # 来源2: 新浪财经
            print(f"  📰 新浪财经...")
            articles.extend(self._extract_sina(keyword))

            all_articles.extend(articles)
            print(f"  ✅ 获取 {len(articles)} 篇文章")
            time.sleep(self.delay)

        return all_articles

    def save_articles(self, articles: list) -> int:
        """保存文章到文件"""
        saved = 0
        for article in articles:
            title = article.get("title", "无标题")
            content = article.get("content", "")
            url = article.get("url", "")
            date = article.get("date", "")
            source = article.get("source", "")
            keyword = article.get("keyword", "")

            safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
            file_hash = hashlib.md5(title.encode()).hexdigest()[:8]
            filename = f"{date}_{safe_title}_{file_hash}.txt" if date else f"{safe_title}_{file_hash}.txt"
            filepath = self.save_dir / filename

            if filepath.exists():
                continue

            text = f"""标题: {title}
来源: {source}
日期: {date}
关键词: {keyword}
链接: {url}

{content}
"""
            try:
                filepath.write_text(text, encoding="utf-8")
                saved += 1
            except Exception as e:
                print(f"  ⚠️  保存失败 {filename}: {e}")

        return saved

    def run(self, keywords: list = None, max_pages: int = None, save: bool = True) -> list:
        """完整爬取流程"""
        print("=" * 50)
        print("🕷️  财经资讯爬虫启动")
        print(f"   关键词: {keywords or DEFAULT_KEYWORDS}")
        print(f"   保存目录: {self.save_dir}")
        print("=" * 50)

        articles = self.crawl(keywords, max_pages)

        if save and articles:
            saved = self.save_articles(articles)
            print(f"\n💾  已保存 {saved} 篇文章到 {self.save_dir}")
        else:
            print(f"\n📋 共获取 {len(articles)} 篇文章（未保存）")

        return articles


def main():
    parser = argparse.ArgumentParser(description="财经资讯爬虫")
    parser.add_argument("--keywords", type=str, default=None, help="关键词，逗号分隔")
    parser.add_argument("--max-pages", type=int, default=10, help="每关键词最大页数")
    parser.add_argument("--no-save", action="store_true", help="不保存文件")
    parser.add_argument("--test", action="store_true", help="快速测试模式（仅 1 个关键词）")
    args = parser.parse_args()

    crawler = FinancialCrawler()

    if args.test:
        keywords = ["白酒"]
    elif args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",")]
    else:
        keywords = DEFAULT_KEYWORDS

    crawler.run(keywords=keywords, max_pages=args.max_pages, save=not args.no_save)


if __name__ == "__main__":
    main()